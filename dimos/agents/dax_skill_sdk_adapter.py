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

"""Dax SDK 内部适配层。

本模块把 fetch/drop 链路中的 ``vla_drop_sku`` 接到 Dax composite skill，
但不把 Dax atomic skill 暴露给 MCP/LLM。DimOS 仍使用统一 ActionPlan；
这里负责加载 YAML、准备 RuntimeContext、串行执行 run_plan，并把 Dax 结果
转换为 ``SkillResult``。任务语义到 YAML inputs 的绑定由上层 resolver 完成，
本文件只接受严格符合 README 第 5 节 inputs contract 的参数。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import inspect
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Literal, Protocol

from dimos.agents.skill_result import SkillResult
from dimos.agents.task_action_plan import VlaActionClient
from dimos.agents.vla_pick_output_receiver import VlaPickRequest, VlaReceiverResult

DaxSkillError = Literal[
    "DAX_SDK_UNAVAILABLE",
    "DAX_RUNTIME_NOT_READY",
    "DAX_PLAN_LOAD_FAILED",
    "DAX_INPUT_INVALID",
    "DAX_SKILL_FAILED",
    "DAX_EXECUTION_TIMEOUT",
]

DEFAULT_DAX_SDK_WS = "/home/miaoli/Projects/dax_planner_ws-main"
DEFAULT_DAX_COMPOSITE_DIR = (
    "/home/miaoli/Projects/dax_planner_ws-main/"
    "src/dax_skill_sdk/dax_skill_sdk/composite_skill"
)


class _DaxPlan(Protocol):
    """Dax Plan 的最小接口，避免 DimOS 在 import 时依赖真实 SDK。"""

    name: str
    inputs: dict[str, Any]


class _DaxRuntime(Protocol):
    """Dax RuntimeContext 的最小接口，用于真实运行和测试替身。"""

    def setup(self) -> None: ...


class _DaxResult(Protocol):
    """Dax SkillResult 的最小接口，用于统一转换执行结果。"""

    success: bool
    message: str
    data: dict[str, Any]


class DaxSkillSdkAdapter:
    """封装 Dax composite skill 的加载、运行时生命周期和结果转换。"""

    def __init__(
        self,
        *,
        sdk_ws: str = DEFAULT_DAX_SDK_WS,
        composite_dir: str = DEFAULT_DAX_COMPOSITE_DIR,
        runtime_config: str = "DaxBot_X7Pro.yaml",
        default_arm_name: str = "left",
        default_grasp_type: str = "Default",
        dry_run: bool = True,
        step_confirm: bool = False,
        timeout_s: float = 30.0,
        executor: str = "inprocess",
        ros_setup: str = "/opt/ros/humble/setup.bash",
        ros_executor_script: str = "",
        load_plan_fn: Callable[[str], _DaxPlan] | None = None,
        run_plan_fn: Callable[..., Sequence[_DaxResult]] | None = None,
        runtime_factory: Callable[[str], _DaxRuntime] | None = None,
        subprocess_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._sdk_ws = sdk_ws
        self._composite_dir = composite_dir
        self._runtime_config = runtime_config
        self._default_arm_name = default_arm_name
        self._default_grasp_type = default_grasp_type
        self._dry_run = dry_run
        self._step_confirm = step_confirm
        self._timeout_s = timeout_s
        self._executor = executor.strip().lower()
        self._ros_setup = ros_setup
        self._ros_executor_script = ros_executor_script
        self._load_plan_fn = load_plan_fn
        self._run_plan_fn = run_plan_fn
        self._runtime_factory = runtime_factory
        self._subprocess_runner = subprocess_runner or subprocess.run
        self._runtime: _DaxRuntime | None = None
        self._runtime_lock = threading.Lock()
        self._execution_lock = threading.Lock()

    @classmethod
    def from_config(cls, config: Any) -> DaxSkillSdkAdapter:
        """Build an adapter from DimOS GlobalConfig-like fields."""
        return cls(
            sdk_ws=config.dax_skill_sdk_ws,
            composite_dir=config.dax_skill_composite_dir,
            runtime_config=config.dax_skill_runtime_config,
            default_arm_name=config.dax_skill_default_arm_name,
            default_grasp_type=config.dax_skill_default_grasp_type,
            dry_run=config.dax_skill_dry_run,
            step_confirm=config.dax_skill_step_confirm,
            timeout_s=config.dax_skill_timeout_s,
            executor=config.dax_skill_executor,
            ros_setup=config.dax_skill_ros_setup,
            ros_executor_script=config.dax_skill_ros_executor_script,
        )

    def place(
        self,
        *,
        request_id: str,
        arm_name: str,
        grasp_type: str,
        target_name: str,
    ) -> SkillResult[DaxSkillError]:
        """Run ``place.yaml`` with already-resolved Dax YAML inputs."""
        inputs = {
            "arm_name": arm_name,
            "grasp_type": grasp_type,
            "target_name": target_name,
        }
        return self.run_composite_skill(
            yaml_name="place.yaml",
            inputs=inputs,
            request_id=request_id,
        )

    def go_home(self, *, request_id: str) -> SkillResult[DaxSkillError]:
        """Run ``go_home.yaml`` to return the Dax-controlled body to home pose."""
        return self.run_composite_skill(
            yaml_name="go_home.yaml",
            inputs={},
            request_id=request_id,
        )

    def run_composite_skill(
        self,
        *,
        yaml_name: str,
        inputs: dict[str, Any],
        request_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SkillResult[DaxSkillError]:
        """Load and execute one Dax composite skill as a DimOS SkillResult."""
        plan_result = self._load_plan(yaml_name)
        if not plan_result.success:
            return plan_result
        plan = plan_result.metadata["plan"]

        normalized = self._normalize_inputs(plan, inputs)
        if not normalized.success:
            return SkillResult(
                success=False,
                error_code="DAX_INPUT_INVALID",
                message=normalized.message,
                metadata={
                    "request_id": request_id,
                    "composite_skill": yaml_name,
                    "inputs": inputs,
                },
            )
        normalized_inputs = normalized.metadata["inputs"]

        base_metadata = {
            "request_id": request_id,
            "sdk": "dax_skill_sdk",
            "composite_skill": yaml_name,
            "plan_name": getattr(plan, "name", ""),
            "inputs": normalized_inputs,
            "dry_run": self._dry_run,
            "step_confirm": self._step_confirm,
            "timeout_s": self._timeout_s,
            "executor": self._executor,
            "phase": "dax_dry_run" if self._dry_run else "dax_run_plan",
            "failed_step": None,
            **(metadata or {}),
        }

        if self._dry_run:
            return SkillResult.ok(
                "Dax composite skill dry-run succeeded.",
                **base_metadata,
                dax_results=[],
            )

        started = time.monotonic()
        with self._execution_lock:
            if self._executor == "subprocess":
                return self._run_composite_subprocess(
                    yaml_path=self._resolve_yaml_path(yaml_name),
                    normalized_inputs=normalized_inputs,
                    base_metadata=base_metadata,
                    started=started,
                )

            runtime_result = self._ensure_runtime()
            if not runtime_result.success:
                runtime_result.metadata.update(base_metadata)
                return runtime_result
            runtime = runtime_result.metadata["runtime"]
            try:
                run_plan = self._run_plan_fn or self._import_run_plan()
                dax_results = list(
                    _call_run_plan(
                        run_plan,
                        plan,
                        runtime,
                        normalized_inputs,
                        step_confirm=self._step_confirm,
                    )
                )
            except Exception as exc:
                duration_ms = _elapsed_ms(started)
                return SkillResult(
                    success=False,
                    error_code="DAX_SKILL_FAILED",
                    message=f"Dax run_plan failed: {exc}",
                    duration_ms=duration_ms,
                    metadata={**base_metadata, "duration_ms": duration_ms},
                )
        duration_ms = _elapsed_ms(started)

        result_dicts = [_dax_result_to_dict(result) for result in dax_results]
        result_metadata = {
            **base_metadata,
            "duration_ms": duration_ms,
            "dax_results": result_dicts,
        }
        if duration_ms > self._timeout_s * 1000.0:
            return SkillResult(
                success=False,
                error_code="DAX_EXECUTION_TIMEOUT",
                message=f"Dax composite skill exceeded timeout {self._timeout_s:.3f}s.",
                duration_ms=duration_ms,
                metadata=result_metadata,
            )
        if any(not result["success"] for result in result_dicts):
            result_metadata["failed_step"] = _first_failure_step(result_dicts)
            return SkillResult(
                success=False,
                error_code="DAX_SKILL_FAILED",
                message=_first_failure_message(result_dicts) or "Dax composite skill failed.",
                duration_ms=duration_ms,
                metadata=result_metadata,
            )
        return SkillResult(
            success=True,
            message="Dax composite skill completed successfully.",
            duration_ms=duration_ms,
            metadata=result_metadata,
        )

    def check_runtime_ready(self, *, request_id: str) -> SkillResult[DaxSkillError]:
        """Check whether Dax RuntimeContext can be setup before real robot execution."""
        started = time.monotonic()
        if self._executor == "subprocess":
            result = self._check_subprocess_runtime()
        else:
            result = self._ensure_runtime()
        duration_ms = _elapsed_ms(started)
        metadata = {
            "request_id": request_id,
            "sdk": "dax_skill_sdk",
            "phase": "runtime_ready" if result.success else "runtime_not_ready",
            "runtime_config": self._runtime_config,
            "duration_ms": duration_ms,
        }
        if result.success:
            return SkillResult(
                success=True,
                message="Dax runtime is ready.",
                duration_ms=duration_ms,
                metadata=metadata,
            )
        result.metadata.update(metadata)
        result.duration_ms = duration_ms
        return result

    def _resolve_ros_executor_script(self) -> Path:
        """Return the bash wrapper that sources ROS and runs ros2 skill_executor."""
        if self._ros_executor_script:
            path = Path(self._ros_executor_script)
        else:
            path = Path(__file__).resolve().parents[2] / "deploy/run_ros2_skill_executor.sh"
        if not path.is_file():
            raise FileNotFoundError(f"Dax ROS executor script not found: {path}")
        return path

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["DAX_SKILL_SDK_WS"] = self._sdk_ws
        env["DAX_SKILL_ROS_SETUP"] = self._ros_setup
        return env

    def _build_subprocess_cmd(
        self,
        yaml_path: Path,
        inputs: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> list[str]:
        script = self._resolve_ros_executor_script()
        cmd = ["bash", str(script), str(yaml_path)]
        if dry_run:
            cmd.append("--dry-run")
        else:
            cmd.append("--no-confirm")
            if self._step_confirm:
                cmd.append("--step-confirm")
        for key, value in sorted(inputs.items()):
            cmd.extend(["--input", f"{key}={value}"])
        return cmd

    def _check_subprocess_runtime(self) -> SkillResult[DaxSkillError]:
        """Verify ros2 skill_executor --dry-run works in the ROS subprocess wrapper."""
        yaml_path = self._resolve_yaml_path("go_home.yaml")
        if not yaml_path.is_file():
            return SkillResult(
                success=False,
                error_code="DAX_PLAN_LOAD_FAILED",
                message=f"Dax composite YAML not found: {yaml_path}",
                metadata={"yaml_path": str(yaml_path)},
            )
        try:
            cmd = self._build_subprocess_cmd(yaml_path, {}, dry_run=True)
        except FileNotFoundError as exc:
            return SkillResult(
                success=False,
                error_code="DAX_SDK_UNAVAILABLE",
                message=str(exc),
            )
        try:
            proc = self._subprocess_runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=min(30.0, self._timeout_s),
                env=self._subprocess_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SkillResult(
                success=False,
                error_code="DAX_EXECUTION_TIMEOUT",
                message="Dax subprocess runtime check timed out.",
            )
        except OSError as exc:
            return SkillResult(
                success=False,
                error_code="DAX_SDK_UNAVAILABLE",
                message=f"Dax subprocess runtime check failed: {exc}",
            )
        if proc.returncode == 0:
            return SkillResult.ok("Dax subprocess runtime is ready.")
        detail = (proc.stderr or proc.stdout or "").strip()
        return SkillResult(
            success=False,
            error_code="DAX_SDK_UNAVAILABLE" if proc.returncode == 127 else "DAX_RUNTIME_NOT_READY",
            message=detail or f"Dax subprocess dry-run failed (exit {proc.returncode}).",
            metadata={"subprocess_exit_code": proc.returncode},
        )

    def _run_composite_subprocess(
        self,
        *,
        yaml_path: Path,
        normalized_inputs: dict[str, Any],
        base_metadata: dict[str, Any],
        started: float,
    ) -> SkillResult[DaxSkillError]:
        try:
            cmd = self._build_subprocess_cmd(yaml_path, normalized_inputs)
        except FileNotFoundError as exc:
            return SkillResult(
                success=False,
                error_code="DAX_SDK_UNAVAILABLE",
                message=str(exc),
                metadata={**base_metadata, "executor": "subprocess"},
            )
        try:
            proc = self._subprocess_runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                env=self._subprocess_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            duration_ms = _elapsed_ms(started)
            return SkillResult(
                success=False,
                error_code="DAX_EXECUTION_TIMEOUT",
                message=f"Dax composite skill exceeded timeout {self._timeout_s:.3f}s.",
                duration_ms=duration_ms,
                metadata={
                    **base_metadata,
                    "executor": "subprocess",
                    "duration_ms": duration_ms,
                    "dax_results": [],
                },
            )
        except OSError as exc:
            duration_ms = _elapsed_ms(started)
            return SkillResult(
                success=False,
                error_code="DAX_SDK_UNAVAILABLE",
                message=f"Dax subprocess execution failed: {exc}",
                duration_ms=duration_ms,
                metadata={**base_metadata, "executor": "subprocess", "duration_ms": duration_ms},
            )

        duration_ms = _elapsed_ms(started)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        result_metadata = {
            **base_metadata,
            "executor": "subprocess",
            "duration_ms": duration_ms,
            "subprocess_exit_code": proc.returncode,
            "subprocess_stdout_tail": stdout[-4000:],
            "subprocess_stderr_tail": stderr[-4000:],
            "dax_results": [],
        }
        if duration_ms > self._timeout_s * 1000.0:
            return SkillResult(
                success=False,
                error_code="DAX_EXECUTION_TIMEOUT",
                message=f"Dax composite skill exceeded timeout {self._timeout_s:.3f}s.",
                duration_ms=duration_ms,
                metadata=result_metadata,
            )
        if proc.returncode == 0:
            return SkillResult(
                success=True,
                message="Dax composite skill completed successfully (subprocess).",
                duration_ms=duration_ms,
                metadata=result_metadata,
            )
        detail = stderr.strip() or stdout.strip()
        error_code: DaxSkillError = (
            "DAX_SDK_UNAVAILABLE" if proc.returncode == 127 else "DAX_SKILL_FAILED"
        )
        return SkillResult(
            success=False,
            error_code=error_code,
            message=detail or f"Dax subprocess failed (exit {proc.returncode}).",
            duration_ms=duration_ms,
            metadata=result_metadata,
        )

    def _load_plan(self, yaml_name: str) -> SkillResult[DaxSkillError]:
        """Resolve and load a Dax YAML plan without importing SDK at module load time."""
        yaml_path = self._resolve_yaml_path(yaml_name)
        if not yaml_path.is_file():
            return SkillResult(
                success=False,
                error_code="DAX_PLAN_LOAD_FAILED",
                message=f"Dax composite YAML not found: {yaml_path}",
                metadata={"composite_skill": yaml_name, "yaml_path": str(yaml_path)},
            )
        try:
            load_plan = self._load_plan_fn or self._import_load_plan()
            plan = load_plan(str(yaml_path))
        except ImportError as exc:
            return SkillResult(
                success=False,
                error_code="DAX_SDK_UNAVAILABLE",
                message=f"Dax SDK import failed: {exc}",
                metadata={"composite_skill": yaml_name, "yaml_path": str(yaml_path)},
            )
        except Exception as exc:
            return SkillResult(
                success=False,
                error_code="DAX_PLAN_LOAD_FAILED",
                message=f"Dax plan load failed: {exc}",
                metadata={"composite_skill": yaml_name, "yaml_path": str(yaml_path)},
            )
        return SkillResult.ok("Dax plan loaded.", plan=plan)

    def _ensure_runtime(self) -> SkillResult[DaxSkillError]:
        """Create and setup RuntimeContext once, guarded from concurrent callers."""
        with self._runtime_lock:
            if self._runtime is not None:
                return SkillResult.ok("Dax runtime ready.", runtime=self._runtime)
            try:
                runtime = self._make_runtime()
                # RuntimeContext.setup() touches ROS/daxplanner, so it is never called in dry-run.
                runtime.setup()
            except ImportError as exc:
                return SkillResult(
                    success=False,
                    error_code="DAX_SDK_UNAVAILABLE",
                    message=f"Dax runtime import failed: {exc}",
                )
            except Exception as exc:
                return SkillResult(
                    success=False,
                    error_code="DAX_RUNTIME_NOT_READY",
                    message=f"Dax runtime setup failed: {exc}",
                )
            self._runtime = runtime
            return SkillResult.ok("Dax runtime ready.", runtime=runtime)

    def _make_runtime(self) -> _DaxRuntime:
        """Instantiate RuntimeContext through an injectable factory."""
        if self._runtime_factory is not None:
            return self._runtime_factory(self._runtime_config)
        RuntimeContext = self._import_runtime_context()
        return RuntimeContext(config=self._runtime_config)

    def _resolve_yaml_path(self, yaml_name: str) -> Path:
        """Resolve a composite YAML name under the configured composite directory."""
        return Path(self._composite_dir) / yaml_name

    def _normalize_inputs(self, plan: _DaxPlan, inputs: dict[str, Any]) -> SkillResult[DaxSkillError]:
        """Validate, default, and coerce inputs according to the Dax YAML contract."""
        input_specs = getattr(plan, "inputs", {}) or {}
        if not isinstance(input_specs, dict):
            return SkillResult(
                success=False,
                error_code="DAX_INPUT_INVALID",
                message="Dax plan inputs declaration must be a mapping.",
            )

        extras = sorted(set(inputs) - set(input_specs))
        if extras:
            return SkillResult(
                success=False,
                error_code="DAX_INPUT_INVALID",
                message=f"Dax inputs were not declared by YAML: {', '.join(extras)}.",
            )

        normalized: dict[str, Any] = {}
        for key, raw_spec in input_specs.items():
            if not isinstance(raw_spec, dict):
                return SkillResult(
                    success=False,
                    error_code="DAX_INPUT_INVALID",
                    message=f"Dax input spec {key!r} must be a mapping.",
                )

            has_value = key in inputs and inputs[key] not in (None, "")
            if has_value:
                value = inputs[key]
            elif "default" in raw_spec:
                value = raw_spec["default"]
            elif raw_spec.get("required"):
                return SkillResult(
                    success=False,
                    error_code="DAX_INPUT_INVALID",
                    message=f"Dax input {key!r} is required.",
                )
            else:
                continue

            try:
                normalized[key] = _coerce_input_value(key, value, raw_spec.get("type"))
            except ValueError as exc:
                return SkillResult(
                    success=False,
                    error_code="DAX_INPUT_INVALID",
                    message=str(exc),
                )

        return SkillResult.ok("Dax inputs normalized.", inputs=normalized)

    def _ensure_sdk_path(self) -> None:
        """Add Dax source roots to sys.path so local SDK imports work without install."""
        sdk_root = Path(self._sdk_ws)
        for path in (
            sdk_root / "src/dax_skill_sdk",
            sdk_root / "src/dax_planner_executor",
        ):
            path_str = str(path)
            if path.is_dir() and path_str not in sys.path:
                sys.path.insert(0, path_str)

    def _import_load_plan(self) -> Callable[[str], _DaxPlan]:
        """Import Dax load_plan lazily at the SDK boundary."""
        self._ensure_sdk_path()
        from dax_skill_sdk.executor.yaml_loader import load_plan

        return load_plan

    def _import_run_plan(self) -> Callable[..., Sequence[_DaxResult]]:
        """Import Dax run_plan lazily at the SDK boundary."""
        self._ensure_sdk_path()
        from dax_skill_sdk.executor.skill_executor import run_plan

        return run_plan

    def _import_runtime_context(self) -> type[_DaxRuntime]:
        """Import Dax RuntimeContext lazily so tests and dry-run remain lightweight."""
        self._ensure_sdk_path()
        from dax_skill_sdk.runtime import RuntimeContext

        return RuntimeContext


class DaxDropVlaActionClient:
    """VLA client wrapper that delegates pick to VLA and routes drop to Dax SDK."""

    def __init__(self, *, base_client: VlaActionClient, dax_adapter: Any) -> None:
        self._base_client = base_client
        self._dax_adapter = dax_adapter

    def pick_sku(self, request: VlaPickRequest) -> VlaReceiverResult:
        """Delegate pick_sku to the existing VLA client."""
        return self._base_client.pick_sku(request)

    def execute_pick_task(self, request: VlaPickRequest) -> VlaReceiverResult:
        """Delegate execute_pick_task to the existing VLA client."""
        return self._base_client.execute_pick_task(request)

    def execute_action_list(
        self,
        actions: list[dict[str, Any]],
        *,
        request: VlaPickRequest,
    ) -> VlaReceiverResult:
        """Handle vla_drop_sku by running Dax place instead of VLA/ROS forwarding."""
        if not actions:
            return SkillResult(
                success=False,
                error_code="DAX_INPUT_INVALID",
                message="vla_drop_sku requires at least one action payload.",
            )

        action = actions[0]
        if action.get("action") != "drop_sku":
            return self._base_client.execute_action_list(actions, request=request)

        place_error = action.get("dax_place_error")
        if isinstance(place_error, dict):
            return SkillResult(
                success=False,
                error_code=str(place_error.get("error_code") or "DAX_INPUT_INVALID"),
                message=str(place_error.get("message") or "Dax place inputs could not be resolved."),
                metadata=dict(place_error.get("metadata") or {}),
            )

        place_inputs = action.get("dax_place_inputs")
        if not isinstance(place_inputs, dict):
            return SkillResult(
                success=False,
                error_code="DAX_INPUT_INVALID",
                message="vla_drop_sku requires resolved Dax place.yaml inputs.",
                metadata={"action": action},
            )

        result = self._dax_adapter.place(
            request_id=request.request_id,
            arm_name=str(place_inputs.get("arm_name", "")),
            grasp_type=str(place_inputs.get("grasp_type", "")),
            target_name=str(place_inputs.get("target_name", "")),
        )
        if not result.success:
            return result

        # Do not attach validated_payload here: drop is already executed by Dax,
        # and the ActionPlanOrchestrator only forwards to ROS when that key exists.
        return SkillResult.ok(
            result.message or "Dax drop completed successfully.",
            **result.metadata,
            dax_result=_skill_result_to_dict(result),
        )


def _dax_result_to_dict(result: _DaxResult) -> dict[str, Any]:
    """Convert a Dax SDK result object into JSON-friendly metadata."""
    return {
        "success": bool(getattr(result, "success", False)),
        "message": str(getattr(result, "message", "")),
        "data": dict(getattr(result, "data", {}) or {}),
    }


def _call_run_plan(
    run_plan: Callable[..., Sequence[_DaxResult]],
    plan: _DaxPlan,
    runtime: _DaxRuntime,
    inputs: dict[str, Any],
    *,
    step_confirm: bool,
) -> Sequence[_DaxResult]:
    """Call Dax run_plan with step_confirm when the SDK/test double supports it."""
    try:
        signature = inspect.signature(run_plan)
    except (TypeError, ValueError):
        return run_plan(plan, runtime, inputs, step_confirm=step_confirm)
    if "step_confirm" in signature.parameters:
        return run_plan(plan, runtime, inputs, step_confirm=step_confirm)
    return run_plan(plan, runtime, inputs)


def _coerce_input_value(key: str, value: Any, declared_type: Any) -> Any:
    """Coerce one Dax YAML input value using README-supported primitive types."""
    if declared_type in (None, ""):
        return value
    if declared_type == "str":
        return str(value)
    if declared_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Dax input {key!r} must be int.") from exc
    if declared_type == "float":
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Dax input {key!r} must be float.") from exc
    if declared_type == "bool":
        return _coerce_bool(key, value)
    if declared_type == "list":
        if isinstance(value, list):
            return value
        raise ValueError(f"Dax input {key!r} must be list.")
    if declared_type == "dict":
        if isinstance(value, dict):
            return value
        raise ValueError(f"Dax input {key!r} must be dict.")
    raise ValueError(f"Dax input {key!r} declares unsupported type {declared_type!r}.")


def _coerce_bool(key: str, value: Any) -> bool:
    """Coerce Dax bool inputs from bools or common CLI-style strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    raise ValueError(f"Dax input {key!r} must be bool.")


def _first_failure_message(results: list[dict[str, Any]]) -> str:
    """Return the first failed Dax step message, if one exists."""
    for result in results:
        if not result["success"]:
            return str(result.get("message") or "")
    return ""


def _first_failure_step(results: list[dict[str, Any]]) -> Any:
    """Return the best-effort failed Dax step identifier from result data."""
    for result in results:
        if result["success"]:
            continue
        data = result.get("data")
        if isinstance(data, dict):
            return data.get("step") or data.get("name") or data.get("skill")
        return None
    return None


def _elapsed_ms(started: float) -> float:
    """Measure elapsed wall time in milliseconds for SkillResult.duration_ms."""
    return (time.monotonic() - started) * 1000.0


def _skill_result_to_dict(result: SkillResult[Any]) -> dict[str, Any]:
    """Convert DimOS SkillResult to metadata without exposing MCP content."""
    return {
        "success": result.success,
        "message": result.message,
        "error_code": result.error_code,
        "metadata": result.metadata,
    }


__all__ = [
    "DaxDropVlaActionClient",
    "DaxSkillError",
    "DaxSkillSdkAdapter",
]
