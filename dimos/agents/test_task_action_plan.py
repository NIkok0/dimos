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

from typing import Any

from dimos.agents.skill_result import SkillResult
from dimos.agents.task_action_plan import (
    ActionPlanOrchestrator,
    ActionStep,
    DaxPlaceInputResolver,
    GuardLoopTemplate,
    MoveRelativeTemplate,
    MoveToWorkspaceTemplate,
    PickSkuTemplate,
    FetchSkuTemplate,
    VlaActionGateway,
)
from dimos.agents.dax_skill_sdk_adapter import DaxDropVlaActionClient
from dimos.agents.robot_action_catalog import get_robot_action_spec
from dimos.agents.rosbridge.navigation.client import PyRosbridgeNavigationRosClient
from dimos.agents.ros_topic_navigation_adapter import RosTopicNavigationAdapter
from dimos.agents.vla_pick_adapter_factory import (
    make_action_plan_orchestrator,
    make_sys_navigation_adapter,
    make_vla_action_gateway,
)
from dimos.agents.vla_pick_adapters import (
    MockRosActionAdapter,
    MockSysNavigationAdapter,
    MOCK_NAV_DISABLED_MESSAGE,
    NavigationResult,
)
from dimos.agents.vla_pick_output_receiver import VlaPickRequest, VlaReceiverResult
from dimos.core.global_config import GlobalConfig


def _pick_intent() -> dict[str, Any]:
    return {
        "request_id": "req-action-plan-test",
        "raw_instruction": "\u53bb\u84dd\u8272\u684c\u5b50\u6293\u7ea2\u8272\u65b9\u5757",
        "intent_type": "pick_sku",
        "slots": {
            "workspace_name": "table",
            "workspace_color": "blue",
            "sku_name": "cube",
            "sku_color": "red",
        },
    }


def _fetch_intent() -> dict[str, Any]:
    raw_instruction = "\u628a\u84dd\u8272\u684c\u5b50\u7684\u7ea2\u8272\u65b9\u5757"
    raw_instruction += "\u62ff\u5230\u7eff\u8272\u684c\u5b50"
    return {
        "request_id": "req-fetch-test",
        "raw_instruction": raw_instruction,
        "intent_type": "fetch_sku",
        "slots": {
            "source_workspace_name": "table",
            "source_workspace_color": "blue",
            "target_workspace_name": "table",
            "target_workspace_color": "green",
            "sku_name": "cube",
            "sku_color": "red",
        },
    }


def _guard_intent() -> dict[str, Any]:
    raw_instruction = "\u5728\u84dd\u8272\u684c\u5b50\u548c\u7eff\u8272\u684c\u5b50"
    raw_instruction += "\u4e4b\u95f4\u5de1\u903b\u4e24\u5708"
    return {
        "request_id": "req-guard-test",
        "raw_instruction": raw_instruction,
        "intent_type": "guard_loop",
        "slots": {
            "waypoints": [
                {"workspace_name": "table", "workspace_color": "blue"},
                {"workspace_name": "table", "workspace_color": "green"},
            ],
            "loop_count": 2,
        },
    }


def _move_intent() -> dict[str, Any]:
    return {
        "request_id": "req-move-test",
        "raw_instruction": "\u79fb\u52a8\u5230\u524d\u65b9\u56fa\u5b9a\u5de5\u4f5c\u533a",
        "intent_type": "move_to_workspace",
        "slots": {
            "workspace_name": "front_workspace",
            "workspace_color": "",
        },
    }


def _relative_move_intent() -> dict[str, Any]:
    return {
        "request_id": "req-relative-move-test",
        "raw_instruction": "\u5411\u540e\u79fb\u52a82\u4e2a\u5355\u4f4d",
        "intent_type": "move_relative",
        "slots": {
            "direction": "backward",
            "distance_units": 2.0,
            "raw_distance_mentioned": True,
        },
    }


def _valid_pick_payload() -> dict[str, Any]:
    return {
        "request_id": "req-action-plan-test",
        "target_meta": {
            "object_type": "cube",
            "object_color": "red",
            "table_color": "blue",
        },
        "joint_action": {"left_arm": [1.0]},
    }


def _valid_drop_payload() -> dict[str, Any]:
    return {
        "request_id": "req-relocate-test",
        "target_meta": {
            "object_type": "cube",
            "object_color": "red",
            "table_color": "green",
        },
        "joint_action": {"left_arm": [0.0]},
    }


class RecordingVlaActionClient:
    def __init__(
        self,
        *,
        pick_result: VlaReceiverResult | None = None,
        drop_result: VlaReceiverResult | None = None,
    ) -> None:
        self.pick_requests: list[VlaPickRequest] = []
        self.drop_actions: list[list[dict[str, Any]]] = []
        pick_payload = _valid_pick_payload()
        drop_payload = _valid_drop_payload()
        self._pick_result = pick_result or SkillResult.ok(
            "pick ok",
            raw_payload=pick_payload,
            validated_payload=pick_payload,
            validation_passed=True,
            held_object={
                "sku_name": "cube",
                "sku_color": "red",
                "sku_id": "FODR0000000046",
                "arm_name": "left",
                "grasp_type": "Default",
            },
        )
        self._drop_result = drop_result or SkillResult.ok(
            "drop ok",
            raw_payload=drop_payload,
            validated_payload=drop_payload,
            validation_passed=True,
        )

    def pick_sku(self, request: VlaPickRequest) -> VlaReceiverResult:
        self.pick_requests.append(request)
        return self._pick_result

    def execute_pick_task(self, request: VlaPickRequest) -> VlaReceiverResult:
        self.pick_requests.append(request)
        return self._pick_result

    def execute_action_list(
        self,
        actions: list[dict[str, Any]],
        *,
        request: VlaPickRequest,
    ) -> VlaReceiverResult:
        self.drop_actions.append(actions)
        return self._drop_result


class RecordingDaxAdapter:
    def __init__(self, result: SkillResult | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = result or SkillResult.ok(
            "dax place ok",
            composite_skill="place.yaml",
            inputs={
                "arm_name": "left",
                "grasp_type": "Default",
                "target_name": "FODR0000000046",
            },
        )

    def place(self, **kwargs: Any) -> SkillResult:
        self.calls.append(kwargs)
        return self._result


class SequencedNavigationAdapter:
    def __init__(self, results: list[NavigationResult]) -> None:
        self._results = results
        self.calls: list[dict[str, str]] = []

    def navigate_to_workspace(
        self,
        *,
        request_id: str,
        workspace_type: str,
        table_color: str,
    ) -> NavigationResult:
        self.calls.append(
            {
                "request_id": request_id,
                "workspace_type": workspace_type,
                "table_color": table_color,
            }
        )
        return self._results[len(self.calls) - 1]


class RelativeNavigationAdapter(SequencedNavigationAdapter):
    def __init__(self, results: list[NavigationResult]) -> None:
        super().__init__(results)
        self.relative_calls: list[dict[str, Any]] = []

    def move_relative(
        self,
        *,
        request_id: str,
        direction: str,
        distance_units: float,
    ) -> NavigationResult:
        self.relative_calls.append(
            {
                "request_id": request_id,
                "direction": direction,
                "distance_units": distance_units,
            }
        )
        return self._results[len(self.relative_calls) - 1]


def test_pick_template_expands_to_move_then_vla_pick() -> None:
    plan = PickSkuTemplate().compose(_pick_intent())

    assert [step.executor for step in plan.steps] == ["sys_navigation", "vla"]
    assert [step.action_type for step in plan.steps] == ["move_to_workspace", "vla_pick_sku"]
    assert plan.steps[1].depends_on == ("step-1",)


def test_move_template_expands_to_single_navigation_step() -> None:
    plan = MoveToWorkspaceTemplate().compose(_move_intent())

    assert plan.intent_type == "move_to_workspace"
    assert plan.template == "move_to_workspace_template"
    assert [step.executor for step in plan.steps] == ["sys_navigation"]
    assert [step.action_type for step in plan.steps] == ["move_to_workspace"]
    assert plan.steps[0].args == {
        "workspace_name": "front_workspace",
        "workspace_color": "",
    }


def test_relative_move_template_expands_to_single_navigation_step() -> None:
    plan = MoveRelativeTemplate().compose(_relative_move_intent())

    assert plan.intent_type == "move_relative"
    assert plan.template == "move_relative_template"
    assert [step.executor for step in plan.steps] == ["sys_navigation"]
    assert [step.action_type for step in plan.steps] == ["move_relative"]
    assert plan.steps[0].args == {
        "direction": "backward",
        "distance_units": 2.0,
        "raw_distance_mentioned": True,
    }


def test_fetch_template_expands_to_move_pick_move_drop() -> None:
    plan = FetchSkuTemplate().compose(_fetch_intent())

    assert [step.executor for step in plan.steps] == [
        "sys_navigation",
        "vla",
        "sys_navigation",
        "vla",
    ]
    assert [step.action_type for step in plan.steps] == [
        "move_to_workspace",
        "vla_pick_sku",
        "move_to_workspace",
        "vla_drop_sku",
    ]
    assert plan.steps[3].args["workspace_color"] == "green"


def test_action_plan_templates_only_emit_cataloged_actions() -> None:
    plans = [
        MoveToWorkspaceTemplate().compose(_move_intent()),
        MoveRelativeTemplate().compose(_relative_move_intent()),
        PickSkuTemplate().compose(_pick_intent()),
        FetchSkuTemplate().compose(_fetch_intent()),
        GuardLoopTemplate().compose(_guard_intent()),
    ]

    for plan in plans:
        for step in plan.steps:
            assert get_robot_action_spec(step.action_type) is not None


def test_guard_template_expands_to_finite_navigation_loop() -> None:
    plan = GuardLoopTemplate().compose(_guard_intent())

    assert plan.intent_type == "guard_loop"
    assert [step.executor for step in plan.steps] == [
        "sys_navigation",
        "sys_navigation",
        "sys_navigation",
        "sys_navigation",
    ]
    assert [step.action_type for step in plan.steps] == [
        "move_to_workspace",
        "move_to_workspace",
        "move_to_workspace",
        "move_to_workspace",
    ]
    assert [step.args["workspace_color"] for step in plan.steps] == [
        "blue",
        "green",
        "blue",
        "green",
    ]


def test_vla_gateway_sends_only_vla_action_step() -> None:
    client = RecordingVlaActionClient()
    gateway = VlaActionGateway(client)
    nav_step = ActionStep(
        step_id="step-1",
        executor="sys_navigation",
        action_type="move_to_workspace",
        args={"workspace_name": "table", "workspace_color": "blue"},
    )
    pick_step = ActionStep(
        step_id="step-2",
        executor="vla",
        action_type="vla_pick_sku",
        args={
            "workspace_name": "table",
            "workspace_color": "blue",
            "sku_name": "cube",
            "sku_color": "red",
        },
    )

    result = gateway.execute("req-action-plan-test", pick_step)

    assert result.success
    assert client.pick_requests == [
        VlaPickRequest(
            workspace_type="table",
            table_color="blue",
            object_type="cube",
            object_color="red",
            request_id="req-action-plan-test",
        )
    ]
    assert client.drop_actions == []
    assert nav_step.executor == "sys_navigation"


def test_action_plan_orchestrator_blocks_vla_when_navigation_fails() -> None:
    plan = PickSkuTemplate().compose(_pick_intent())
    nav = MockSysNavigationAdapter(status="failed", message="blocked")
    ros = MockRosActionAdapter()
    client = RecordingVlaActionClient()
    orchestrator = ActionPlanOrchestrator(
        navigation=nav,
        vla_gateway=VlaActionGateway(client),
        ros_action=ros,
    )

    result = orchestrator.run(_pick_intent(), plan)

    assert not result.success
    assert result.error_code == "SYS_NAVIGATION_FAILED"
    assert len(nav.calls) == 1
    assert client.pick_requests == []
    assert ros.last_payload is None


def test_action_plan_orchestrator_executes_relative_move_through_navigation_adapter() -> None:
    plan = MoveRelativeTemplate().compose(_relative_move_intent())
    nav = RelativeNavigationAdapter(
        [
            NavigationResult(
                sys_task_id="sys-relative-nav",
                status="arrived",
                workspace_type="relative",
                table_color="",
                message="relative move arrived",
                final_robot_state={
                    "relative_motion": {
                        "direction": "backward",
                        "distance_units": 2.0,
                    },
                    "goal": {
                        "pose": {
                            "frame_id": "map",
                            "x": -1.0,
                            "y": 0.0,
                            "yaw": 0.0,
                        }
                    },
                },
            )
        ]
    )
    orchestrator = ActionPlanOrchestrator(
        navigation=nav,
        vla_gateway=VlaActionGateway(RecordingVlaActionClient()),
        ros_action=MockRosActionAdapter(),
    )

    result = orchestrator.run(_relative_move_intent(), plan)

    assert result.success
    assert nav.calls == []
    assert nav.relative_calls == [
        {
            "request_id": "req-relative-move-test",
            "direction": "backward",
            "distance_units": 2.0,
        }
    ]
    assert result.metadata["navigation_results"][0]["relative_motion"] == {
        "direction": "backward",
        "distance_units": 2.0,
    }


def test_default_mock_navigation_fails_without_fake_robot_motion() -> None:
    plan = MoveRelativeTemplate().compose(_relative_move_intent())
    orchestrator = ActionPlanOrchestrator()

    result = orchestrator.run(_relative_move_intent(), plan)

    assert not result.success
    assert result.error_code == "SYS_NAVIGATION_FAILED"
    assert MOCK_NAV_DISABLED_MESSAGE in result.message
    assert result.metadata["navigation_results"][0]["final_robot_state"]["adapter_mode"] == "mock"


def test_action_plan_orchestrator_exposes_real_navigation_metadata() -> None:
    plan = PickSkuTemplate().compose(_pick_intent())
    nav = SequencedNavigationAdapter(
        [
            NavigationResult(
                sys_task_id="sys-real-nav",
                status="arrived",
                workspace_type="table",
                table_color="blue",
                message="导航成功",
                final_robot_state={
                    "workspace": {
                        "workspace_id": "blue_table",
                        "pose": {"frame_id": "map", "x": 2.4, "y": 0.6, "yaw": 1.57},
                    },
                    "status": "arrived",
                    "nav_status_code": 1003,
                    "uuid": "nav-123",
                },
            )
        ]
    )
    orchestrator = ActionPlanOrchestrator(
        navigation=nav,
        vla_gateway=VlaActionGateway(RecordingVlaActionClient()),
        ros_action=MockRosActionAdapter(),
    )

    result = orchestrator.run(_pick_intent(), plan)

    assert result.success
    navigation_result = result.metadata["navigation_results"][0]
    assert navigation_result["workspace"]["workspace_id"] == "blue_table"
    assert navigation_result["workspace"]["pose"]["frame_id"] == "map"
    assert navigation_result["nav_status_code"] == 1003
    assert navigation_result["uuid"] == "nav-123"


def test_action_plan_orchestrator_blocks_second_move_when_pick_fails() -> None:
    plan = FetchSkuTemplate().compose(_fetch_intent())
    client = RecordingVlaActionClient(
        pick_result=SkillResult(
            success=False,
            error_code="VLA_TARGET_MISMATCH",
            message="wrong object",
            metadata={"raw_payload": {"error": "wrong object"}},
        )
    )
    orchestrator = ActionPlanOrchestrator(
        navigation=MockSysNavigationAdapter(status="arrived"),
        vla_gateway=VlaActionGateway(client),
        ros_action=MockRosActionAdapter(),
    )

    result = orchestrator.run(_fetch_intent(), plan)

    assert not result.success
    assert result.error_code == "VLA_TARGET_MISMATCH"
    assert len(orchestrator.navigation.calls) == 1
    assert len(client.pick_requests) == 1
    assert client.drop_actions == []


def test_action_plan_orchestrator_preserves_drop_failure_payload() -> None:
    plan = FetchSkuTemplate().compose(_fetch_intent())
    raw_payload = {"error_code": "DROP_FAILED", "message": "cannot place object"}
    client = RecordingVlaActionClient(
        drop_result=SkillResult(
            success=False,
            error_code="VLA_EXECUTION_FAILED",
            message="cannot place object",
            metadata={"raw_payload": raw_payload},
        )
    )
    ros = MockRosActionAdapter()
    orchestrator = ActionPlanOrchestrator(
        navigation=MockSysNavigationAdapter(status="arrived"),
        vla_gateway=VlaActionGateway(client),
        ros_action=ros,
    )

    result = orchestrator.run(_fetch_intent(), plan)

    assert not result.success
    assert result.error_code == "VLA_EXECUTION_FAILED"
    assert result.metadata["raw_payload"] is raw_payload
    assert len(client.drop_actions) == 1
    assert ros.last_payload is client._pick_result.metadata["validated_payload"]


def test_dax_drop_wrapper_delegates_pick_to_base_client() -> None:
    base_client = RecordingVlaActionClient()
    dax = RecordingDaxAdapter()
    client = DaxDropVlaActionClient(base_client=base_client, dax_adapter=dax)
    request = VlaPickRequest(
        workspace_type="table",
        table_color="blue",
        object_type="cube",
        object_color="red",
        request_id="req-action-plan-test",
    )

    result = client.pick_sku(request)

    assert result.success
    assert len(base_client.pick_requests) == 1
    assert dax.calls == []


def test_dax_drop_wrapper_rejects_unresolved_place_inputs() -> None:
    base_client = RecordingVlaActionClient()
    dax = RecordingDaxAdapter()
    client = DaxDropVlaActionClient(base_client=base_client, dax_adapter=dax)
    request = VlaPickRequest(
        workspace_type="table",
        table_color="green",
        object_type="cube",
        object_color="red",
        request_id="req-drop-unresolved",
    )

    result = client.execute_action_list(
        [{"action": "drop_sku", "sku": {"name": "cube", "color": "red"}}],
        request=request,
    )

    assert not result.success
    assert result.error_code == "DAX_INPUT_INVALID"
    assert "place.yaml inputs" in result.message
    assert dax.calls == []


def test_fetch_drop_uses_dax_without_forwarding_drop_to_ros() -> None:
    plan = FetchSkuTemplate().compose(_fetch_intent())
    base_client = RecordingVlaActionClient()
    dax = RecordingDaxAdapter()
    ros = MockRosActionAdapter()
    orchestrator = ActionPlanOrchestrator(
        navigation=MockSysNavigationAdapter(status="arrived"),
        vla_gateway=VlaActionGateway(DaxDropVlaActionClient(base_client=base_client, dax_adapter=dax)),
        ros_action=ros,
    )

    result = orchestrator.run(_fetch_intent(), plan)

    assert result.success
    assert len(base_client.pick_requests) == 1
    assert base_client.drop_actions == []
    assert dax.calls == [
        {
            "request_id": "req-fetch-test",
            "arm_name": "left",
            "grasp_type": "Default",
            "target_name": "FODR0000000046",
        }
    ]
    assert len(ros.calls) == 1
    assert ros.last_payload is base_client._pick_result.metadata["validated_payload"]
    assert result.metadata["vla_results"][-1]["metadata"]["composite_skill"] == "place.yaml"
    assert "validated_payload" not in result.metadata["vla_results"][-1]["metadata"]


def test_dax_place_input_resolver_uses_held_object_only() -> None:
    resolver = DaxPlaceInputResolver()
    drop_step = FetchSkuTemplate().compose(_fetch_intent()).steps[-1]

    result = resolver.resolve_place_inputs(
        step=drop_step,
        held_object={
            "sku_name": "cube",
            "sku_color": "red",
            "sku_id": "FODR0000000046",
            "arm_name": "right",
            "grasp_type": "Box",
        },
    )

    assert result.success
    assert result.metadata["inputs"] == {
        "arm_name": "right",
        "grasp_type": "Box",
        "target_name": "FODR0000000046",
    }
    assert "workspace_name" not in result.metadata["inputs"]
    assert "sku_color" not in result.metadata["inputs"]


def test_dax_place_input_resolver_rejects_missing_held_object_fields() -> None:
    resolver = DaxPlaceInputResolver()
    drop_step = FetchSkuTemplate().compose(_fetch_intent()).steps[-1]

    result = resolver.resolve_place_inputs(
        step=drop_step,
        held_object={"sku_name": "cube", "sku_color": "red", "sku_id": "FODR0000000046"},
    )

    assert not result.success
    assert result.error_code == "DAX_INPUT_INVALID"
    assert "arm_name" in result.message


def test_dax_drop_failure_stops_action_plan_at_drop_phase() -> None:
    plan = FetchSkuTemplate().compose(_fetch_intent())
    dax = RecordingDaxAdapter(
        SkillResult(
            success=False,
            error_code="DAX_SKILL_FAILED",
            message="place failed",
            metadata={"composite_skill": "place.yaml"},
        )
    )
    ros = MockRosActionAdapter()
    orchestrator = ActionPlanOrchestrator(
        navigation=MockSysNavigationAdapter(status="arrived"),
        vla_gateway=VlaActionGateway(
            DaxDropVlaActionClient(base_client=RecordingVlaActionClient(), dax_adapter=dax)
        ),
        ros_action=ros,
    )

    result = orchestrator.run(_fetch_intent(), plan)

    assert not result.success
    assert result.error_code == "DAX_SKILL_FAILED"
    assert result.metadata["phase"] == "vla_drop_sku"
    assert result.metadata["composite_skill"] == "place.yaml"
    assert len(dax.calls) == 1


def test_target_navigation_failure_does_not_call_dax_drop() -> None:
    plan = FetchSkuTemplate().compose(_fetch_intent())
    dax = RecordingDaxAdapter()
    nav = MockSysNavigationAdapter()
    nav._status = "arrived"

    original_navigate = nav.navigate_to_workspace

    def _navigate_then_fail(**kwargs: Any):
        if len(nav.calls) == 1:
            nav._status = "failed"
            nav._message = "target blocked"
        return original_navigate(**kwargs)

    nav.navigate_to_workspace = _navigate_then_fail  # type: ignore[method-assign]
    orchestrator = ActionPlanOrchestrator(
        navigation=nav,
        vla_gateway=VlaActionGateway(
            DaxDropVlaActionClient(base_client=RecordingVlaActionClient(), dax_adapter=dax)
        ),
        ros_action=MockRosActionAdapter(),
    )

    result = orchestrator.run(_fetch_intent(), plan)

    assert not result.success
    assert result.error_code == "SYS_NAVIGATION_FAILED"
    assert dax.calls == []


def test_target_navigation_blocked_preserves_metadata_and_skips_drop() -> None:
    plan = FetchSkuTemplate().compose(_fetch_intent())
    dax = RecordingDaxAdapter()
    nav = SequencedNavigationAdapter(
        [
            NavigationResult(
                sys_task_id="sys-source-nav",
                status="arrived",
                workspace_type="table",
                table_color="blue",
                message="source arrived",
                final_robot_state={
                    "workspace": {"workspace_id": "blue_table"},
                    "nav_status_code": 1003,
                    "uuid": "nav-source",
                },
            ),
            NavigationResult(
                sys_task_id="sys-target-nav",
                status="failed",
                workspace_type="table",
                table_color="green",
                message="路径被阻挡",
                final_robot_state={
                    "workspace": {"workspace_id": "green_table"},
                    "status": "blocked",
                    "nav_status_code": 1006,
                    "uuid": "nav-target",
                    "error_code": "NAVIGATION_BLOCKED",
                },
            ),
        ]
    )
    orchestrator = ActionPlanOrchestrator(
        navigation=nav,
        vla_gateway=VlaActionGateway(
            DaxDropVlaActionClient(base_client=RecordingVlaActionClient(), dax_adapter=dax)
        ),
        ros_action=MockRosActionAdapter(),
    )

    result = orchestrator.run(_fetch_intent(), plan)

    assert not result.success
    assert result.error_code == "SYS_NAVIGATION_FAILED"
    assert result.metadata["phase"] == "move_to_workspace"
    assert result.metadata["navigation_results"][1]["workspace"]["workspace_id"] == "green_table"
    assert result.metadata["navigation_results"][1]["nav_status_code"] == 1006
    assert result.metadata["navigation_results"][1]["error_code"] == "NAVIGATION_BLOCKED"
    assert dax.calls == []


def test_factory_wraps_vla_client_when_dax_adapter_enabled() -> None:
    gateway = make_vla_action_gateway(
        GlobalConfig(vla_pick_adapter="mock", dax_skill_adapter="dry_run")
    )

    assert gateway._client.__class__.__name__ == "DaxDropVlaActionClient"


def test_factory_keeps_dax_disabled_by_default() -> None:
    gateway = make_vla_action_gateway(
        GlobalConfig(vla_pick_adapter="mock", dax_skill_adapter="disabled")
    )

    assert gateway._client.__class__.__name__ == "MockVlaPickClient"


def test_factory_rejects_unknown_dax_adapter_mode() -> None:
    try:
        make_vla_action_gateway(GlobalConfig(vla_pick_adapter="mock", dax_skill_adapter="surprise"))
    except ValueError as exc:
        assert "unsupported dax_skill_adapter" in str(exc)
    else:
        raise AssertionError("expected unknown dax adapter mode to fail")


def test_factory_creates_ros_topic_navigation_adapter(tmp_path) -> None:
    catalog_path = tmp_path / "workspaces.yaml"
    catalog_path.write_text(
        """
front_workspace:
  workspace_id: front_workspace
  name: workspace
  color: front
  frame_id: map
  x: 1.8
  y: 0.0
  yaw: 0.0
""".strip(),
        encoding="utf-8",
    )

    adapter = make_sys_navigation_adapter(
        GlobalConfig(
            vla_sys_nav_adapter="ros_topic",
            ros_nav_workspace_catalog=str(catalog_path),
        )
    )

    assert isinstance(adapter, RosTopicNavigationAdapter)
    assert isinstance(adapter._ros_client, PyRosbridgeNavigationRosClient)


def test_factory_rejects_ros_topic_without_workspace_catalog() -> None:
    try:
        make_sys_navigation_adapter(
            GlobalConfig(vla_sys_nav_adapter="ros_topic", ros_nav_workspace_catalog="")
        )
    except ValueError as exc:
        assert "ros_nav_workspace_catalog" in str(exc)
    else:
        raise AssertionError("expected ros_topic navigation without workspace catalog to fail")


def test_action_plan_orchestrator_accepts_ros_topic_navigation_adapter(tmp_path) -> None:
    catalog_path = tmp_path / "workspaces.yaml"
    catalog_path.write_text(
        """
front_workspace:
  workspace_id: front_workspace
  name: workspace
  color: front
  frame_id: map
  x: 1.8
  y: 0.0
  yaw: 0.0
""".strip(),
        encoding="utf-8",
    )

    orchestrator = make_action_plan_orchestrator(
        GlobalConfig(
            vla_sys_nav_adapter="ros_topic",
            ros_nav_workspace_catalog=str(catalog_path),
            vla_pick_adapter="mock",
            vla_ros_adapter="mock",
            dax_skill_adapter="disabled",
        )
    )

    assert isinstance(orchestrator.navigation, RosTopicNavigationAdapter)


def test_guard_orchestrator_does_not_call_vla_or_ros() -> None:
    plan = GuardLoopTemplate().compose(_guard_intent())
    client = RecordingVlaActionClient()
    ros = MockRosActionAdapter()
    orchestrator = ActionPlanOrchestrator(
        navigation=MockSysNavigationAdapter(status="arrived"),
        vla_gateway=VlaActionGateway(client),
        ros_action=ros,
    )

    result = orchestrator.run(_guard_intent(), plan)

    assert result.success
    assert len(orchestrator.navigation.calls) == 4
    assert client.pick_requests == []
    assert client.drop_actions == []
    assert ros.last_payload is None


def test_guard_orchestrator_stops_on_navigation_failure() -> None:
    plan = GuardLoopTemplate().compose(_guard_intent())
    client = RecordingVlaActionClient()
    ros = MockRosActionAdapter()
    orchestrator = ActionPlanOrchestrator(
        navigation=MockSysNavigationAdapter(status="failed", message="guard blocked"),
        vla_gateway=VlaActionGateway(client),
        ros_action=ros,
    )

    result = orchestrator.run(_guard_intent(), plan)

    assert not result.success
    assert result.error_code == "SYS_NAVIGATION_FAILED"
    assert len(orchestrator.navigation.calls) == 1
    assert client.pick_requests == []
    assert client.drop_actions == []
    assert ros.last_payload is None
