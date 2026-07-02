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

from dataclasses import dataclass, field
import threading
import time
from typing import Any

from dimos.agents.dax_skill_sdk_adapter import DaxSkillSdkAdapter


@dataclass
class _FakePlan:
    """Minimal Dax Plan stand-in with only the fields the DimOS adapter needs."""

    name: str = "place_90"
    inputs: dict[str, Any] = field(
        default_factory=lambda: {
            "arm_name": {"type": "str", "required": True},
            "grasp_type": {"type": "str", "required": True},
            "target_name": {"type": "str", "required": True},
        }
    )


@dataclass
class _FakeDaxResult:
    """Minimal Dax SkillResult stand-in returned by fake run_plan callbacks."""

    success: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class _FakeRuntime:
    """Test runtime that records whether hardware setup would have been called."""

    def __init__(self) -> None:
        self.setup_calls = 0
        self.blackboard: dict[str, Any] = {}

    def setup(self) -> None:
        self.setup_calls += 1


def test_dry_run_place_loads_yaml_and_returns_inputs(tmp_path) -> None:
    yaml_path = tmp_path / "place.yaml"
    yaml_path.write_text("name: place_90\nsteps: []\n", encoding="utf-8")
    loaded_paths: list[str] = []
    runtime = _FakeRuntime()

    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=True,
        runtime_factory=lambda _config: runtime,
        load_plan_fn=lambda path: loaded_paths.append(path) or _FakePlan(),
    )

    result = adapter.place(
        request_id="req-1",
        arm_name="left",
        grasp_type="Default",
        target_name="FODR0000000046",
    )

    assert result.success
    assert loaded_paths == [str(yaml_path)]
    assert runtime.setup_calls == 0
    assert result.metadata["composite_skill"] == "place.yaml"
    assert result.metadata["inputs"] == {
        "arm_name": "left",
        "grasp_type": "Default",
        "target_name": "FODR0000000046",
    }


def test_go_home_dry_run_uses_go_home_yaml_without_inputs(tmp_path) -> None:
    yaml_path = tmp_path / "go_home.yaml"
    yaml_path.write_text("name: go_home\nsteps: []\n", encoding="utf-8")
    loaded_paths: list[str] = []

    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=True,
        load_plan_fn=lambda path: loaded_paths.append(path) or _FakePlan(name="go_home", inputs={}),
    )

    result = adapter.go_home(request_id="req-home")

    assert result.success
    assert loaded_paths == [str(yaml_path)]
    assert result.metadata["composite_skill"] == "go_home.yaml"
    assert result.metadata["inputs"] == {}


def test_missing_yaml_returns_plan_load_failed(tmp_path) -> None:
    adapter = DaxSkillSdkAdapter(composite_dir=str(tmp_path), dry_run=True)

    result = adapter.place(request_id="req-1", arm_name="", grasp_type="Default", target_name="FODR0000000046")

    assert not result.success
    assert result.error_code == "DAX_PLAN_LOAD_FAILED"
    assert "place.yaml" in result.message


def test_load_plan_import_failure_returns_sdk_unavailable(tmp_path) -> None:
    (tmp_path / "place.yaml").write_text("name: place_90\nsteps: []\n", encoding="utf-8")

    def _raise_import_error(_path: str) -> _FakePlan:
        raise ImportError("dax_skill_sdk missing")

    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=True,
        load_plan_fn=_raise_import_error,
    )

    result = adapter.place(
        request_id="req-1",
        arm_name="",
        grasp_type="Default",
        target_name="FODR0000000046",
    )

    assert not result.success
    assert result.error_code == "DAX_SDK_UNAVAILABLE"
    assert "dax_skill_sdk missing" in result.message


def test_missing_required_input_returns_input_invalid(tmp_path) -> None:
    (tmp_path / "place.yaml").write_text("name: place_90\nsteps: []\n", encoding="utf-8")
    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=True,
        default_arm_name="",
        load_plan_fn=lambda _path: _FakePlan(),
    )

    result = adapter.place(
        request_id="req-1",
        arm_name="",
        grasp_type="Default",
        target_name="FODR0000000046",
    )

    assert not result.success
    assert result.error_code == "DAX_INPUT_INVALID"
    assert "arm_name" in result.message


def test_run_composite_skill_applies_declared_defaults(tmp_path) -> None:
    (tmp_path / "custom.yaml").write_text("name: custom\nsteps: []\n", encoding="utf-8")
    plan = _FakePlan(
        name="custom",
        inputs={
            "arm_name": {"type": "str", "required": True},
            "repeat_n": {"type": "int", "default": 2},
        },
    )
    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=True,
        load_plan_fn=lambda _path: plan,
    )

    result = adapter.run_composite_skill(
        yaml_name="custom.yaml",
        inputs={"arm_name": "left"},
        request_id="req-default",
    )

    assert result.success
    assert result.metadata["inputs"] == {"arm_name": "left", "repeat_n": 2}


def test_run_composite_skill_rejects_undeclared_input(tmp_path) -> None:
    (tmp_path / "custom.yaml").write_text("name: custom\nsteps: []\n", encoding="utf-8")
    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=True,
        load_plan_fn=lambda _path: _FakePlan(name="custom", inputs={"arm_name": {"type": "str"}}),
    )

    result = adapter.run_composite_skill(
        yaml_name="custom.yaml",
        inputs={"arm_name": "left", "extra": "surprise"},
        request_id="req-extra",
    )

    assert not result.success
    assert result.error_code == "DAX_INPUT_INVALID"
    assert "extra" in result.message


def test_run_composite_skill_coerces_declared_input_types(tmp_path) -> None:
    (tmp_path / "custom.yaml").write_text("name: custom\nsteps: []\n", encoding="utf-8")
    plan = _FakePlan(
        name="custom",
        inputs={
            "repeat_n": {"type": "int", "required": True},
            "height": {"type": "float", "required": True},
            "enabled": {"type": "bool", "required": True},
        },
    )
    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=True,
        load_plan_fn=lambda _path: plan,
    )

    result = adapter.run_composite_skill(
        yaml_name="custom.yaml",
        inputs={"repeat_n": "3", "height": "1.2", "enabled": "true"},
        request_id="req-types",
    )

    assert result.success
    assert result.metadata["inputs"] == {"repeat_n": 3, "height": 1.2, "enabled": True}


def test_run_composite_skill_rejects_invalid_declared_input_type(tmp_path) -> None:
    (tmp_path / "custom.yaml").write_text("name: custom\nsteps: []\n", encoding="utf-8")
    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=True,
        load_plan_fn=lambda _path: _FakePlan(
            name="custom",
            inputs={"repeat_n": {"type": "int", "required": True}},
        ),
    )

    result = adapter.run_composite_skill(
        yaml_name="custom.yaml",
        inputs={"repeat_n": "not-an-int"},
        request_id="req-bad-type",
    )

    assert not result.success
    assert result.error_code == "DAX_INPUT_INVALID"
    assert "repeat_n" in result.message


def test_run_plan_failure_maps_to_dax_skill_failed(tmp_path) -> None:
    (tmp_path / "place.yaml").write_text("name: place_90\nsteps: []\n", encoding="utf-8")
    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=False,
        runtime_factory=lambda _config: _FakeRuntime(),
        load_plan_fn=lambda _path: _FakePlan(),
        run_plan_fn=lambda _plan, _ctx, _inputs: [
            _FakeDaxResult(False, "hand controller rejected", {"step": "open_hand"})
        ],
    )

    result = adapter.place(request_id="req-1", arm_name="left", grasp_type="Default", target_name="FODR0000000046")

    assert not result.success
    assert result.error_code == "DAX_SKILL_FAILED"
    assert result.metadata["dax_results"][0]["message"] == "hand controller rejected"
    assert result.metadata["failed_step"] == "open_hand"
    assert result.metadata["phase"] == "dax_run_plan"
    assert result.metadata["sdk"] == "dax_skill_sdk"
    assert isinstance(result.duration_ms, float)
    assert result.duration_ms >= 0.0


def test_run_plan_success_metadata_is_traceable(tmp_path) -> None:
    (tmp_path / "place.yaml").write_text("name: place_90\nsteps: []\n", encoding="utf-8")
    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=False,
        runtime_factory=lambda _config: _FakeRuntime(),
        load_plan_fn=lambda _path: _FakePlan(),
        run_plan_fn=lambda _plan, _ctx, _inputs: [_FakeDaxResult(True, "placed", {"step": "release"})],
    )

    result = adapter.place(request_id="req-1", arm_name="left", grasp_type="Default", target_name="FODR0000000046")

    assert result.success
    assert result.metadata["sdk"] == "dax_skill_sdk"
    assert result.metadata["phase"] == "dax_run_plan"
    assert result.metadata["failed_step"] is None
    assert result.metadata["dax_results"][0]["data"]["step"] == "release"
    assert isinstance(result.duration_ms, float)
    assert result.duration_ms >= 0.0


def test_run_plan_receives_step_confirm_flag(tmp_path) -> None:
    (tmp_path / "go_home.yaml").write_text("name: go_home\nsteps: []\n", encoding="utf-8")
    captured: dict[str, Any] = {}

    def _run_plan(_plan: Any, _ctx: Any, _inputs: dict[str, Any], step_confirm: bool = False):
        captured["step_confirm"] = step_confirm
        return [_FakeDaxResult(True, "home")]

    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=False,
        step_confirm=True,
        runtime_factory=lambda _config: _FakeRuntime(),
        load_plan_fn=lambda _path: _FakePlan(name="go_home", inputs={}),
        run_plan_fn=_run_plan,
    )

    result = adapter.go_home(request_id="req-home")

    assert result.success
    assert captured == {"step_confirm": True}


def test_run_plan_timeout_maps_to_execution_timeout(tmp_path) -> None:
    (tmp_path / "go_home.yaml").write_text("name: go_home\nsteps: []\n", encoding="utf-8")

    def _slow_run_plan(_plan: Any, _ctx: Any, _inputs: dict[str, Any], step_confirm: bool = False):
        time.sleep(0.03)
        return [_FakeDaxResult(True, "late")]

    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=False,
        timeout_s=0.01,
        runtime_factory=lambda _config: _FakeRuntime(),
        load_plan_fn=lambda _path: _FakePlan(name="go_home", inputs={}),
        run_plan_fn=_slow_run_plan,
    )

    result = adapter.go_home(request_id="req-timeout")

    assert not result.success
    assert result.error_code == "DAX_EXECUTION_TIMEOUT"
    assert result.metadata["phase"] == "dax_run_plan"
    assert result.metadata["composite_skill"] == "go_home.yaml"


def test_check_runtime_ready_reports_ready_runtime() -> None:
    adapter = DaxSkillSdkAdapter(
        dry_run=False,
        runtime_factory=lambda _config: _FakeRuntime(),
    )

    result = adapter.check_runtime_ready(request_id="req-ready")

    assert result.success
    assert result.metadata["phase"] == "runtime_ready"
    assert result.metadata["sdk"] == "dax_skill_sdk"


def test_runtime_setup_failure_returns_runtime_not_ready(tmp_path) -> None:
    (tmp_path / "place.yaml").write_text("name: place_90\nsteps: []\n", encoding="utf-8")

    class _FailingRuntime(_FakeRuntime):
        """Runtime test double that simulates missing ROS joint states."""

        def setup(self) -> None:
            raise RuntimeError("timeout waiting for /joint_states")

    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=False,
        runtime_factory=lambda _config: _FailingRuntime(),
        load_plan_fn=lambda _path: _FakePlan(),
    )

    result = adapter.place(request_id="req-1", arm_name="left", grasp_type="Default", target_name="FODR0000000046")

    assert not result.success
    assert result.error_code == "DAX_RUNTIME_NOT_READY"
    assert "/joint_states" in result.message
    assert result.metadata["composite_skill"] == "place.yaml"
    assert result.metadata["inputs"]["target_name"] == "FODR0000000046"


def test_run_plan_calls_are_serialized_by_execution_lock(tmp_path) -> None:
    (tmp_path / "go_home.yaml").write_text("name: go_home\nsteps: []\n", encoding="utf-8")
    active_count = 0
    max_active_count = 0
    counter_lock = threading.Lock()

    def _run_plan(_plan: Any, _ctx: Any, _inputs: dict[str, Any]) -> list[_FakeDaxResult]:
        nonlocal active_count, max_active_count
        with counter_lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
        time.sleep(0.02)
        with counter_lock:
            active_count -= 1
        return [_FakeDaxResult(True, "ok")]

    adapter = DaxSkillSdkAdapter(
        composite_dir=str(tmp_path),
        dry_run=False,
        runtime_factory=lambda _config: _FakeRuntime(),
        load_plan_fn=lambda _path: _FakePlan(name="go_home", inputs={}),
        run_plan_fn=_run_plan,
    )

    threads = [threading.Thread(target=adapter.go_home, kwargs={"request_id": f"req-{i}"}) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active_count == 1
