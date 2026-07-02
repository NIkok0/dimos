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
from typing import Any, Literal, Protocol
import uuid

NavigationStatus = Literal["arrived", "failed", "timeout", "cancelled"]

MOCK_NAV_DISABLED_MESSAGE = (
    "Navigation adapter is mock; no robot command was sent. "
    "Set VLA_SYS_NAV_ADAPTER=ros_topic and ROS_NAV_WORKSPACE_CATALOG for real motion."
)
RosActionStatus = Literal[
    "accepted",
    "rejected",
    "running",
    "succeeded",
    "failed",
    "timeout",
]


@dataclass(frozen=True)
class NavigationResult:
    sys_task_id: str
    status: NavigationStatus
    workspace_type: str
    table_color: str
    message: str = ""
    final_robot_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RosActionResult:
    ros_goal_id: str
    request_id: str
    status: RosActionStatus
    message: str = ""
    payload: dict[str, Any] | None = None


class SysNavigationAdapter(Protocol):
    def navigate_to_workspace(
        self,
        *,
        request_id: str,
        workspace_type: str,
        table_color: str,
    ) -> NavigationResult: ...

    def move_relative(
        self,
        *,
        request_id: str,
        direction: str,
        distance_units: float,
    ) -> NavigationResult: ...


class RosActionAdapter(Protocol):
    def submit_action(
        self,
        *,
        request_id: str,
        payload: dict[str, Any],
        timeout_s: float = 30.0,
    ) -> RosActionResult: ...


class MockSysNavigationAdapter:
    """In-memory navigation stub for unit tests.

    Defaults to ``failed`` so misconfigured runs do not report fake robot motion.
    Pass ``status=\"arrived\"`` only in tests that intentionally simulate success.
    """

    def __init__(
        self,
        *,
        status: NavigationStatus = "failed",
        message: str = "",
    ) -> None:
        self._status = status
        self._message = message
        self.calls: list[dict[str, str]] = []
        self.relative_calls: list[dict[str, Any]] = []

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
        return NavigationResult(
            sys_task_id=f"sys-{uuid.uuid4().hex[:8]}",
            status=self._status,
            workspace_type=workspace_type,
            table_color=table_color,
            message=self._message or self._default_message("Navigation"),
            final_robot_state={
                "adapter_mode": "mock",
                "arm_ready": True,
                "gripper_ready": True,
            },
        )

    def move_relative(
        self,
        *,
        request_id: str,
        direction: str,
        distance_units: float,
    ) -> NavigationResult:
        """Record a relative movement request and return the configured mock status."""
        self.relative_calls.append(
            {
                "request_id": request_id,
                "direction": direction,
                "distance_units": distance_units,
            }
        )
        return NavigationResult(
            sys_task_id=f"sys-{uuid.uuid4().hex[:8]}",
            status=self._status,
            workspace_type="relative",
            table_color="",
            message=self._message or self._default_message("Relative navigation"),
            final_robot_state={
                "adapter_mode": "mock",
                "relative_motion": {
                    "direction": direction,
                    "distance_units": distance_units,
                },
            },
        )

    def _default_message(self, prefix: str) -> str:
        if self._status == "failed":
            return MOCK_NAV_DISABLED_MESSAGE
        return f"{prefix} {self._status}."


class MockRosActionAdapter:
    """Phase 1 ROS action mock; records submitted payload by reference."""

    def __init__(
        self,
        *,
        status: RosActionStatus = "succeeded",
        message: str = "Action executed successfully.",
    ) -> None:
        self._status = status
        self._message = message
        self.last_payload: dict[str, Any] | None = None
        self.last_envelope: dict[str, Any] | None = None
        self.calls: list[dict[str, Any]] = []

    def submit_action(
        self,
        *,
        request_id: str,
        payload: dict[str, Any],
        timeout_s: float = 30.0,
    ) -> RosActionResult:
        self.last_payload = payload
        envelope = {
            "ros_goal_id": f"ros-{uuid.uuid4().hex[:8]}",
            "request_id": request_id,
            "timeout_s": timeout_s,
            "payload": payload,
        }
        self.last_envelope = envelope
        self.calls.append(envelope)
        return RosActionResult(
            ros_goal_id=envelope["ros_goal_id"],
            request_id=request_id,
            status=self._status,
            message=self._message,
            payload=payload,
        )


class MockVlaPickClient:
    """Phase 1 VLA pick mock for unit tests (replaces deprecated HTTP client)."""

    def __init__(
        self,
        *,
        pick_payload: dict[str, Any] | None = None,
    ) -> None:
        self.pick_requests: list[Any] = []
        self._pick_payload = pick_payload or {
            "request_id": "req-mock",
            "target_meta": {
                "object_type": "cube",
                "object_color": "red",
                "table_color": "blue",
            },
            "joint_action": {"left_arm": [1.0]},
        }

    def pick_sku(self, request: Any) -> Any:
        from dimos.agents.skill_result import SkillResult

        self.pick_requests.append(request)
        payload = dict(self._pick_payload)
        payload.setdefault("request_id", getattr(request, "request_id", ""))
        return SkillResult.ok(
            "mock pick ok",
            raw_payload=payload,
            validated_payload=payload,
            validation_passed=True,
        )

    def execute_pick_task(self, request: Any) -> Any:
        return self.pick_sku(request)

    def execute_action_list(
        self,
        actions: list[dict[str, Any]],
        *,
        request: Any,
    ) -> Any:
        return self.pick_sku(request)


__all__ = [
    "MockRosActionAdapter",
    "MockSysNavigationAdapter",
    "MockVlaPickClient",
    "NavigationResult",
    "NavigationStatus",
    "RosActionAdapter",
    "RosActionResult",
    "RosActionStatus",
    "SysNavigationAdapter",
]
