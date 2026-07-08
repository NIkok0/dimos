# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Thin wrapper around ``dax_skill_sdk.atomic_skill_executor_helper.execute_atomic_skill``.

DimOS orchestrates task steps; this module only transports one atomic call at a
time to the external Action Server (subprocess on dax-agent uv venv, or
in-process when ROS + SDK are importable).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dimos.agents.skill_result import SkillResult

DaxAtomicSkillError = Literal[
    "DAX_ATOMIC_SDK_UNAVAILABLE",
    "DAX_ATOMIC_SERVER_NOT_READY",
    "DAX_ATOMIC_GOAL_REJECTED",
    "DAX_ATOMIC_NO_RESULT",
    "DAX_ATOMIC_SKILL_FAILED",
    "DAX_ATOMIC_EXECUTION_TIMEOUT",
    "DAX_ATOMIC_INVALID_RESPONSE",
]

RC_OK = 0
RC_SERVER_NOT_READY = 2
RC_GOAL_REJECTED = 3
RC_NO_RESULT = 4
RC_REMOTE_FAILED = 5


@dataclass(frozen=True)
class AtomicSkillStep:
    """One orchestrated atomic skill invocation."""

    name: str
    skill: str
    params: dict[str, Any]


ExecuteAtomicFn = Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]]
SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


def map_atomic_rc(rc: int, result: dict[str, Any]) -> SkillResult[DaxAtomicSkillError]:
    """Map SDK ``execute_atomic_skill`` return codes to DimOS ``SkillResult``."""
    message = str(result.get("message") or "")
    data = result.get("data")
    metadata: dict[str, Any] = {
        "rc": rc,
        "atomic_success": bool(result.get("success")),
        "atomic_data": data if isinstance(data, dict) else {},
    }
    if rc == RC_OK and result.get("success"):
        return SkillResult(
            success=True,
            message=message or "Atomic skill completed successfully.",
            metadata=metadata,
        )
    if rc == RC_SERVER_NOT_READY:
        return SkillResult(
            success=False,
            error_code="DAX_ATOMIC_SERVER_NOT_READY",
            message=message or "Action Server 未就绪，请确认 atomic_skill_executor_server 已启动。",
            metadata=metadata,
        )
    if rc == RC_GOAL_REJECTED:
        return SkillResult(
            success=False,
            error_code="DAX_ATOMIC_GOAL_REJECTED",
            message=message or "Atomic skill goal was rejected.",
            metadata=metadata,
        )
    if rc == RC_NO_RESULT:
        return SkillResult(
            success=False,
            error_code="DAX_ATOMIC_NO_RESULT",
            message=message or "Atomic skill returned no result.",
            metadata=metadata,
        )
    return SkillResult(
        success=False,
        error_code="DAX_ATOMIC_SKILL_FAILED",
        message=message or "Atomic skill failed.",
        metadata=metadata,
    )


class DaxAtomicSkillClient:
    """Call ``execute_atomic_skill`` with subprocess or in-process execution."""

    def __init__(
        self,
        *,
        executor: str = "subprocess",
        sdk_ws: str = "",
        ros_setup: str = "/opt/ros/humble/setup.bash",
        invoke_script: str = "",
        timeout_s: float = 120.0,
        dry_run: bool = False,
        execute_fn: ExecuteAtomicFn | None = None,
        subprocess_runner: SubprocessRunner | None = None,
    ) -> None:
        self._executor = executor.strip().lower()
        self._sdk_ws = sdk_ws
        self._ros_setup = ros_setup
        self._invoke_script = invoke_script
        self._timeout_s = timeout_s
        self._dry_run = dry_run
        self._execute_fn = execute_fn
        self._subprocess_runner = subprocess_runner or subprocess.run
        self._execution_lock = threading.Lock()

    @classmethod
    def from_config(cls, config: Any) -> DaxAtomicSkillClient:
        """Build a client from DimOS GlobalConfig-like fields."""
        dry_run = bool(config.dax_atomic_skill_dry_run or config.dax_skill_dry_run)
        return cls(
            executor=config.dax_atomic_skill_executor,
            sdk_ws=config.dax_atomic_skill_ws or config.dax_skill_sdk_ws,
            ros_setup=config.dax_atomic_skill_ros_setup or config.dax_skill_ros_setup,
            invoke_script=config.dax_atomic_skill_invoke_script,
            timeout_s=config.dax_atomic_skill_timeout_s,
            dry_run=dry_run,
        )

    def execute(
        self,
        skill_name: str,
        params: dict[str, Any],
        *,
        request_id: str,
        step_name: str = "",
    ) -> SkillResult[DaxAtomicSkillError]:
        """Run one atomic skill and return a DimOS ``SkillResult``."""
        base_metadata = {
            "request_id": request_id,
            "sdk": "dax_atomic_skill",
            "atomic_skill": skill_name,
            "atomic_step": step_name or skill_name,
            "atomic_params": params,
            "dry_run": self._dry_run,
        }
        if self._dry_run:
            return SkillResult.ok(
                "Atomic skill dry-run succeeded.",
                **base_metadata,
            )

        started = time.monotonic()
        with self._execution_lock:
            try:
                rc, result = self._invoke(skill_name, params)
            except subprocess.TimeoutExpired:
                duration_ms = _elapsed_ms(started)
                return SkillResult(
                    success=False,
                    error_code="DAX_ATOMIC_EXECUTION_TIMEOUT",
                    message=f"Atomic skill exceeded timeout {self._timeout_s:.3f}s.",
                    duration_ms=duration_ms,
                    metadata={**base_metadata, "duration_ms": duration_ms},
                )
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                duration_ms = _elapsed_ms(started)
                return SkillResult(
                    success=False,
                    error_code="DAX_ATOMIC_SDK_UNAVAILABLE",
                    message=f"Atomic skill invocation failed: {exc}",
                    duration_ms=duration_ms,
                    metadata={**base_metadata, "duration_ms": duration_ms},
                )

        duration_ms = _elapsed_ms(started)
        mapped = map_atomic_rc(rc, result)
        mapped.duration_ms = duration_ms
        mapped.metadata = {**base_metadata, **mapped.metadata, "duration_ms": duration_ms}
        return mapped

    def execute_sequence(
        self,
        steps: list[AtomicSkillStep],
        *,
        request_id: str,
    ) -> SkillResult[DaxAtomicSkillError]:
        """Run steps in order; stop on the first failure."""
        results: list[dict[str, Any]] = []
        for index, step in enumerate(steps, start=1):
            result = self.execute(
                step.skill,
                step.params,
                request_id=request_id,
                step_name=step.name,
            )
            results.append(
                {
                    "index": index,
                    "step": step.name,
                    "skill": step.skill,
                    "success": result.success,
                    "message": result.message,
                    "error_code": result.error_code,
                }
            )
            if not result.success:
                result.metadata["atomic_results"] = results
                result.metadata["failed_step"] = step.name
                return result
        return SkillResult.ok(
            "Atomic skill sequence completed successfully.",
            request_id=request_id,
            sdk="dax_atomic_skill",
            atomic_results=results,
            step_count=len(steps),
        )

    def _invoke(self, skill_name: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if self._execute_fn is not None:
            return self._execute_fn(skill_name, params)
        if self._executor == "inprocess":
            return self._invoke_inprocess(skill_name, params)
        return self._invoke_subprocess(skill_name, params)

    def _invoke_inprocess(self, skill_name: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self._ensure_sdk_path()
        from dax_skill_sdk.atomic_skill_executor_helper import execute_atomic_skill

        rc, result = execute_atomic_skill(skill_name, params)
        if not isinstance(result, dict):
            raise TypeError(f"execute_atomic_skill result must be dict, got {type(result)!r}")
        return int(rc), result

    def _invoke_subprocess(self, skill_name: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        script = self._resolve_invoke_script()
        env = self._subprocess_env()
        proc = self._subprocess_runner(
            ["bash", str(script), skill_name, json.dumps(params, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=self._timeout_s,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise OSError(detail or f"atomic invoke script exited {proc.returncode}")
        payload = json.loads(proc.stdout)
        return int(payload["rc"]), dict(payload["result"])

    def _resolve_invoke_script(self) -> Path:
        if self._invoke_script.strip():
            path = Path(self._invoke_script)
        else:
            path = Path(__file__).resolve().parents[2] / "deploy/run_atomic_skill_invoke.sh"
        if not path.is_file():
            raise FileNotFoundError(f"Atomic skill invoke script not found: {path}")
        return path

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self._sdk_ws.strip():
            env["DAX_ATOMIC_SKILL_WS"] = self._sdk_ws
        if self._ros_setup.strip():
            env["DAX_ATOMIC_SKILL_ROS_SETUP"] = self._ros_setup
        return env

    def _ensure_sdk_path(self) -> None:
        sdk_root = Path(self._sdk_ws)
        for rel in ("src/dax_skill_sdk", "src/dax_planner_executor"):
            path = sdk_root / rel
            path_str = str(path)
            if path.is_dir() and path_str not in sys.path:
                sys.path.insert(0, path_str)


def _elapsed_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000.0


__all__ = [
    "AtomicSkillStep",
    "DaxAtomicSkillClient",
    "DaxAtomicSkillError",
    "map_atomic_rc",
]
