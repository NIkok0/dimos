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

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dimos.agents.dax_atomic_skill_client import (
    AtomicSkillStep,
    DaxAtomicSkillClient,
    map_atomic_rc,
)
from dimos.agents.dax_orchestration.config_loader import load_go_home_steps
from dimos.agents.dax_orchestration.go_home import GoHomeOrchestrator


def test_map_atomic_rc_success() -> None:
    result = map_atomic_rc(0, {"success": True, "message": "ok", "data": {}})
    assert result.success
    assert result.metadata["rc"] == 0


def test_map_atomic_rc_server_not_ready() -> None:
    result = map_atomic_rc(2, {"success": False, "message": "not ready", "data": {}})
    assert not result.success
    assert result.error_code == "DAX_ATOMIC_SERVER_NOT_READY"


def test_execute_uses_injected_fn() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def _execute(skill: str, params: dict[str, object]) -> tuple[int, dict[str, object]]:
        calls.append((skill, params))
        return 0, {"success": True, "message": "ok", "data": {}}

    client = DaxAtomicSkillClient(execute_fn=_execute)
    result = client.execute("joint_move", {"group": "body_dual"}, request_id="req-1")

    assert result.success
    assert calls == [("joint_move", {"group": "body_dual"})]
    assert result.metadata["atomic_skill"] == "joint_move"


def test_execute_sequence_stops_on_failure() -> None:
    def _execute(skill: str, params: dict[str, object]) -> tuple[int, dict[str, object]]:
        if skill == "second":
            return 5, {"success": False, "message": "boom", "data": {}}
        return 0, {"success": True, "message": "ok", "data": {}}

    client = DaxAtomicSkillClient(execute_fn=_execute)
    result = client.execute_sequence(
        [
            AtomicSkillStep(name="first", skill="first", params={}),
            AtomicSkillStep(name="second", skill="second", params={}),
        ],
        request_id="req-seq",
    )

    assert not result.success
    assert result.metadata["failed_step"] == "second"
    assert len(result.metadata["atomic_results"]) == 2


def test_subprocess_invoke_parses_json(tmp_path: Path) -> None:
    script = tmp_path / "invoke.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    script.chmod(0o755)

    def _fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        payload = {"rc": 0, "result": {"success": True, "message": "ok", "data": {}}}
        class _Proc:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return _Proc()

    client = DaxAtomicSkillClient(
        invoke_script=str(script),
        subprocess_runner=_fake_run,
    )
    result = client.execute("joint_move", {"group": "body_dual"}, request_id="req-sub")

    assert result.success
    assert result.metadata["sdk"] == "dax_atomic_skill"


def test_load_go_home_steps_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "go_home.yaml"
    path.write_text(
        "steps:\n"
        "  - name: home\n"
        "    skill: joint_move\n"
        "    params:\n"
        "      group: body_dual\n"
        "      target: [0, 0]\n"
        "      dt: 0.01\n",
        encoding="utf-8",
    )
    steps = load_go_home_steps(path)
    assert len(steps) == 1
    assert steps[0].skill == "joint_move"


def test_go_home_orchestrator_dry_run() -> None:
    client = DaxAtomicSkillClient(dry_run=True)
    orchestrator = GoHomeOrchestrator(
        client=client,
        steps=[AtomicSkillStep(name="home", skill="joint_move", params={"group": "body_dual"})],
    )
    result = orchestrator.run(request_id="req-home")
    assert result.success
    assert result.metadata["orchestrator"] == "go_home"


def test_load_go_home_steps_requires_params(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("steps:\n  - name: x\n    skill: joint_move\n", encoding="utf-8")
    with pytest.raises(ValueError, match="params"):
        load_go_home_steps(path)
