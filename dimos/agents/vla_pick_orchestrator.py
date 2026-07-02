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

from typing import Any, Literal

from dimos.agents.skill_result import SkillResult
from dimos.agents.vla_pick_adapters import (
    MockRosActionAdapter,
    MockSysNavigationAdapter,
    RosActionAdapter,
    SysNavigationAdapter,
)
from dimos.agents.vla_pick_output_receiver import (
    VlaPickRequest,
    VlaReceiverResult,
)
from dimos.agents.rosbridge.manipulation.vla_client import PyRosbridgeVlaPickClient

VlaPickOrchestratorError = Literal[
    "SYS_NAVIGATION_FAILED",
    "SYS_NAVIGATION_TIMEOUT",
    "CANCELLED",
    "VLA_UNAVAILABLE",
    "VLA_OUTPUT_INVALID",
    "VLA_TARGET_MISMATCH",
    "VLA_EXECUTION_FAILED",
    "ROS_ACTION_REJECTED",
    "ROS_ACTION_FAILED",
    "ROS_ACTION_TIMEOUT",
    "UNSUPPORTED_PLAN",
]

_NAVIGATION_ERROR_CODES: dict[str, VlaPickOrchestratorError] = {
    "failed": "SYS_NAVIGATION_FAILED",
    "timeout": "SYS_NAVIGATION_TIMEOUT",
    "cancelled": "CANCELLED",
}

_ROS_ERROR_CODES: dict[str, VlaPickOrchestratorError] = {
    "rejected": "ROS_ACTION_REJECTED",
    "failed": "ROS_ACTION_FAILED",
    "timeout": "ROS_ACTION_TIMEOUT",
}


class VlaPickTaskOrchestrator:
    """Execute a deterministic pick plan through atomic adapters."""

    def __init__(
        self,
        *,
        navigation: SysNavigationAdapter | None = None,
        vla_client: PyRosbridgeVlaPickClient | None = None,
        ros_action: RosActionAdapter | None = None,
    ) -> None:
        self._navigation = navigation or MockSysNavigationAdapter()
        self._vla_client = vla_client or PyRosbridgeVlaPickClient.from_config()
        self._ros_action = ros_action or MockRosActionAdapter()

    def run(self, goal: dict[str, Any], plan: dict[str, Any]) -> SkillResult[VlaPickOrchestratorError]:
        request_id = str(goal.get("request_id", ""))
        steps = plan.get("plan")
        if not isinstance(steps, list) or not steps:
            return _fail(
                "UNSUPPORTED_PLAN",
                "Pick plan is missing executable steps.",
                request_id=request_id,
                phase="PLANNING",
                plan=plan,
            )

        navigation_result = None
        vla_result: VlaReceiverResult | None = None
        ros_result = None
        phase = "EXECUTING_GO_TO_WORKSPACE"

        for step in steps:
            skill = step.get("skill")
            args = step.get("args") or {}

            if skill == "go_to_workspace":
                navigation_result = self._navigation.navigate_to_workspace(
                    request_id=request_id,
                    workspace_type=str(args.get("workspace_type", "")),
                    table_color=str(args.get("table_color", "")),
                )
                if navigation_result.status != "arrived":
                    error_code = _NAVIGATION_ERROR_CODES.get(
                        navigation_result.status,
                        "SYS_NAVIGATION_FAILED",
                    )
                    return SkillResult(
                        success=False,
                        error_code=error_code,
                        message=navigation_result.message or f"Navigation {navigation_result.status}.",
                        metadata={
                            "request_id": request_id,
                            "phase": phase,
                            "plan": plan,
                            "navigation_result": _navigation_to_dict(navigation_result),
                        },
                    )
                continue

            if skill == "pick_sku":
                phase = "EXECUTING_PICK_SKU"
                pick_request = VlaPickRequest(
                    workspace_type=str(args.get("workspace_type", "")),
                    table_color=str(args.get("table_color", "")),
                    object_type=str(args.get("object_type", "")),
                    object_color=str(args.get("object_color", "")),
                    request_id=request_id,
                )
                vla_result = self._vla_client.pick_sku(pick_request)
                if not vla_result.success:
                    return SkillResult(
                        success=False,
                        error_code=vla_result.error_code,  # type: ignore[arg-type]
                        message=vla_result.message,
                        metadata={
                            "request_id": request_id,
                            "phase": phase,
                            "plan": plan,
                            "navigation_result": (
                                _navigation_to_dict(navigation_result)
                                if navigation_result is not None
                                else None
                            ),
                            **vla_result.metadata,
                        },
                    )
                continue

            return _fail(
                "UNSUPPORTED_PLAN",
                f"Unsupported plan step skill {skill!r}.",
                request_id=request_id,
                phase=phase,
                plan=plan,
            )

        if vla_result is None or not vla_result.success:
            return _fail(
                "UNSUPPORTED_PLAN",
                "Pick plan did not include a pick_sku step.",
                request_id=request_id,
                phase=phase,
                plan=plan,
            )

        validated_payload = vla_result.metadata.get("validated_payload")
        if not isinstance(validated_payload, dict):
            return _fail(
                "VLA_OUTPUT_INVALID",
                "Validated VLA payload missing after pick_sku.",
                request_id=request_id,
                phase="VALIDATING_VLA_OUTPUT",
                plan=plan,
            )

        phase = "FORWARDING_TO_ROS"
        ros_result = self._ros_action.submit_action(
            request_id=request_id,
            payload=validated_payload,
        )
        if ros_result.status != "succeeded":
            error_code = _ROS_ERROR_CODES.get(ros_result.status, "ROS_ACTION_FAILED")
            return SkillResult(
                success=False,
                error_code=error_code,
                message=ros_result.message or f"ROS action {ros_result.status}.",
                metadata={
                    "request_id": request_id,
                    "phase": phase,
                    "plan": plan,
                    "navigation_result": (
                        _navigation_to_dict(navigation_result)
                        if navigation_result is not None
                        else None
                    ),
                    "raw_payload": validated_payload,
                    "validated_payload": validated_payload,
                    "ros_result": _ros_to_dict(ros_result),
                },
            )

        return SkillResult.ok(
            "VLA pick task completed successfully.",
            request_id=request_id,
            phase="SUCCEEDED",
            plan=plan,
            goal=goal,
            navigation_result=(
                _navigation_to_dict(navigation_result) if navigation_result is not None else None
            ),
            raw_payload=validated_payload,
            validated_payload=validated_payload,
            ros_result=_ros_to_dict(ros_result),
            validation_passed=True,
        )


def _fail(
    error_code: VlaPickOrchestratorError,
    message: str,
    **metadata: Any,
) -> SkillResult[VlaPickOrchestratorError]:
    return SkillResult(
        success=False,
        error_code=error_code,
        message=message,
        metadata=dict(metadata),
    )


def _navigation_to_dict(result: Any) -> dict[str, Any]:
    return {
        "sys_task_id": result.sys_task_id,
        "status": result.status,
        "workspace_type": result.workspace_type,
        "table_color": result.table_color,
        "message": result.message,
        "final_robot_state": result.final_robot_state,
    }


def _ros_to_dict(result: Any) -> dict[str, Any]:
    return {
        "ros_goal_id": result.ros_goal_id,
        "request_id": result.request_id,
        "status": result.status,
        "message": result.message,
        "payload": result.payload,
    }


__all__ = [
    "VlaPickOrchestratorError",
    "VlaPickTaskOrchestrator",
]
