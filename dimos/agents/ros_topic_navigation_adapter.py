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

"""Adapter for real ROS topic/action navigation behind DimOS task actions.

The ActionPlan layer still calls ``navigate_to_workspace`` with task-level slots.
This adapter resolves those slots to curated map-frame poses, checks SLAM readiness,
submits a ``NavigateToPose`` goal through an injected ROS client, and normalizes the
result into the existing ``NavigationResult`` shape used by Dax Agent orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import uuid
from typing import Any, Protocol

from dimos.agents.navigation_contracts import (
    NavigateToPoseGoal,
    NavigationNormalizedStatus,
    RealNavigationResult,
    SlamState,
    WorkspacePose,
    body_yaw_from_slam_state,
    normalized_status_from_navigate_action,
    relative_distance_units_to_meters,
    relative_motion_metadata,
)
from dimos.agents.navigation_safety import (
    NavigationSafetyResult,
    OccupancyGridSafetyChecker,
)
from dimos.agents.vla_pick_adapters import NavigationResult
from dimos.agents.workspace_resolver import (
    WorkspaceResolutionError,
    WorkspaceResolver,
)
from dimos.core.global_config import global_config


@dataclass(frozen=True)
class NavigateToPoseActionResult:
    """Normalized result returned by a low-level NavigateToPose ROS client."""

    result_code: int
    result_message: str
    result_pose: dict[str, Any] = field(default_factory=dict)
    uuid: str = ""
    nav_status_code: int | None = None
    nav_description: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class NavigationRosClient(Protocol):
    """Minimal ROS navigation client API required by RosTopicNavigationAdapter."""

    def get_slam_state(self) -> dict[str, Any]: ...

    def get_occupancy_grid(self) -> Any | None: ...

    def send_navigate_to_pose(
        self,
        goal: dict[str, Any],
        *,
        timeout_s: float,
        request_id: str = "",
    ) -> NavigateToPoseActionResult: ...


class RosTopicNavigationAdapter:
    """Resolve workspaces and execute them through a real ROS navigation client."""

    def __init__(
        self,
        *,
        ros_client: NavigationRosClient,
        workspace_resolver: WorkspaceResolver,
        behavior_tree: str | None = None,
        timeout_s: float = 60.0,
        safety_checker: OccupancyGridSafetyChecker | None = None,
    ) -> None:
        self._ros_client = ros_client
        self._workspace_resolver = workspace_resolver
        self._behavior_tree = (
            global_config.ros_nav_default_behavior_tree
            if behavior_tree is None
            else behavior_tree
        )
        self._timeout_s = timeout_s
        self._safety_checker = safety_checker or OccupancyGridSafetyChecker.from_config(
            global_config
        )
        self.calls: list[dict[str, str]] = []

    def _relative_motion_meta(
        self,
        *,
        direction: str,
        distance_units: float,
        slam_state: SlamState,
    ) -> dict[str, Any]:
        body_yaw: float | None = None
        quaternion_yaw: float | None = None
        try:
            body_yaw = body_yaw_from_slam_state(slam_state)
        except (KeyError, TypeError, ValueError):
            pass
        raw_quat = slam_state.raw.get("quaternion_yaw")
        if raw_quat is not None:
            try:
                quaternion_yaw = float(raw_quat)
            except (TypeError, ValueError):
                pass
        return relative_motion_metadata(
            direction=direction,
            distance_units=distance_units,
            current_yaw=body_yaw,
            quaternion_yaw=quaternion_yaw,
        )

    def navigate_to_workspace(
        self,
        *,
        request_id: str,
        workspace_type: str,
        table_color: str,
    ) -> NavigationResult:
        """Resolve one workspace and run NavigateToPose if localization is ready."""
        sys_task_id = f"sys-{uuid.uuid4().hex[:8]}"
        self.calls.append(
            {
                "request_id": request_id,
                "workspace_type": workspace_type,
                "table_color": table_color,
            }
        )

        try:
            workspace = self._workspace_resolver.resolve(
                workspace_name=workspace_type,
                workspace_color=table_color,
            )
        except WorkspaceResolutionError as exc:
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="failed",
                workspace_type=workspace_type,
                table_color=table_color,
                message=str(exc),
                final_robot_state={
                    "error_code": "NAV_WORKSPACE_NOT_FOUND",
                    "workspace_type": workspace_type,
                    "table_color": table_color,
                },
            )

        slam_state = _slam_state_from_raw(self._ros_client.get_slam_state())
        if not slam_state.is_navigation_ready():
            if slam_state.status == "lost":
                error_code = "NAV_LOCALIZATION_LOST"
            elif slam_state.status == "unavailable":
                error_code = "NAV_SLAM_STATUS_UNAVAILABLE"
            else:
                error_code = "NAV_LOCALIZATION_NOT_READY"
            message = _localization_not_ready_message(slam_state)
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="failed",
                workspace_type=workspace_type,
                table_color=table_color,
                message=message,
                final_robot_state={
                    "error_code": error_code,
                    "slam_state": slam_state.to_metadata(),
                    "workspace": workspace.to_metadata(),
                },
            )

        goal = NavigateToPoseGoal(
            pose=workspace,
            behavior_tree=self._behavior_tree,
        )
        safety_check = self._check_target_safety(workspace)
        if not safety_check.safe:
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="failed",
                workspace_type=workspace_type,
                table_color=table_color,
                message=f"navigation target failed map safety check: {safety_check.reason}",
                final_robot_state={
                    "error_code": "NAV_TARGET_UNSAFE",
                    "workspace": workspace.to_metadata(),
                    "goal": goal.to_metadata(),
                    "slam_state": slam_state.to_metadata(),
                    "safety_check": safety_check.to_metadata(),
                },
            )

        try:
            action_result = self._ros_client.send_navigate_to_pose(
                goal.to_metadata(),
                timeout_s=self._timeout_s,
                request_id=request_id,
            )
        except TimeoutError as exc:
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="timeout",
                workspace_type=workspace_type,
                table_color=table_color,
                message=str(exc) or "navigation timed out",
                final_robot_state={
                    "error_code": "NAVIGATION_TIMEOUT",
                    "workspace": workspace.to_metadata(),
                    "goal": goal.to_metadata(),
                    "slam_state": slam_state.to_metadata(),
                },
            )
        except Exception as exc:
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="failed",
                workspace_type=workspace_type,
                table_color=table_color,
                message=str(exc) or exc.__class__.__name__,
                final_robot_state={
                    "error_code": "NAVIGATION_FAILED",
                    "workspace": workspace.to_metadata(),
                    "goal": goal.to_metadata(),
                    "slam_state": slam_state.to_metadata(),
                },
            )

        real_result = _real_result_from_action_result(
            workspace=workspace,
            action_result=action_result,
        )
        nav_status, error_code = _navigation_result_status(real_result.status, action_result)
        return NavigationResult(
            sys_task_id=sys_task_id,
            status=nav_status,
            workspace_type=workspace_type,
            table_color=table_color,
            message=real_result.message,
            final_robot_state={
                **real_result.to_metadata(),
                "goal": goal.to_metadata(),
                "slam_state": slam_state.to_metadata(),
                "safety_check": safety_check.to_metadata(),
                "error_code": error_code,
                **_auto_cancel_metadata(action_result),
            },
        )

    def move_relative(
        self,
        *,
        request_id: str,
        direction: str,
        distance_units: float,
    ) -> NavigationResult:
        """Compute a body-frame relative target, safety-check it, and navigate."""
        sys_task_id = f"sys-{uuid.uuid4().hex[:8]}"
        self.calls.append(
            {
                "request_id": request_id,
                "workspace_type": "relative",
                "table_color": "",
            }
        )

        slam_state = _slam_state_from_raw(self._ros_client.get_slam_state())
        if not slam_state.is_navigation_ready():
            if slam_state.status == "lost":
                error_code = "NAV_LOCALIZATION_LOST"
            elif slam_state.status == "unavailable":
                error_code = "NAV_SLAM_STATUS_UNAVAILABLE"
            else:
                error_code = "NAV_LOCALIZATION_NOT_READY"
            message = _localization_not_ready_message(slam_state)
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="failed",
                workspace_type="relative",
                table_color="",
                message=message,
                final_robot_state={
                    "error_code": error_code,
                    "slam_state": slam_state.to_metadata(),
                    "relative_motion": self._relative_motion_meta(
                        direction=direction,
                        distance_units=distance_units,
                        slam_state=slam_state,
                    ),
                },
            )

        target = _relative_target_from_slam_state(
            slam_state,
            direction=direction,
            distance_units=distance_units,
        )
        if isinstance(target, NavigationResult):
            return target

        goal = NavigateToPoseGoal(
            pose=target,
            behavior_tree=self._behavior_tree,
        )
        safety_check = self._check_target_safety(target)
        if not safety_check.safe:
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="failed",
                workspace_type="relative",
                table_color="",
                message=f"navigation target failed map safety check: {safety_check.reason}",
                final_robot_state={
                    "error_code": "NAV_TARGET_UNSAFE",
                    "workspace": target.to_metadata(),
                    "goal": goal.to_metadata(),
                    "slam_state": slam_state.to_metadata(),
                    "safety_check": safety_check.to_metadata(),
                    "relative_motion": self._relative_motion_meta(
                        direction=direction,
                        distance_units=distance_units,
                        slam_state=slam_state,
                    ),
                },
            )

        try:
            action_result = self._ros_client.send_navigate_to_pose(
                goal.to_metadata(),
                timeout_s=self._timeout_s,
                request_id=request_id,
            )
        except TimeoutError as exc:
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="timeout",
                workspace_type="relative",
                table_color="",
                message=str(exc) or "navigation timed out",
                final_robot_state={
                    "error_code": "NAVIGATION_TIMEOUT",
                    "workspace": target.to_metadata(),
                    "goal": goal.to_metadata(),
                    "slam_state": slam_state.to_metadata(),
                    "safety_check": safety_check.to_metadata(),
                    "relative_motion": self._relative_motion_meta(
                        direction=direction,
                        distance_units=distance_units,
                        slam_state=slam_state,
                    ),
                },
            )
        except Exception as exc:
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="failed",
                workspace_type="relative",
                table_color="",
                message=str(exc) or exc.__class__.__name__,
                final_robot_state={
                    "error_code": "NAVIGATION_FAILED",
                    "workspace": target.to_metadata(),
                    "goal": goal.to_metadata(),
                    "slam_state": slam_state.to_metadata(),
                    "safety_check": safety_check.to_metadata(),
                    "relative_motion": self._relative_motion_meta(
                        direction=direction,
                        distance_units=distance_units,
                        slam_state=slam_state,
                    ),
                },
            )

        real_result = _real_result_from_action_result(
            workspace=target,
            action_result=action_result,
        )
        nav_status, error_code = _navigation_result_status(real_result.status, action_result)
        return NavigationResult(
            sys_task_id=sys_task_id,
            status=nav_status,
            workspace_type="relative",
            table_color="",
            message=real_result.message,
            final_robot_state={
                **real_result.to_metadata(),
                "goal": goal.to_metadata(),
                "slam_state": slam_state.to_metadata(),
                "safety_check": safety_check.to_metadata(),
                "relative_motion": self._relative_motion_meta(
                    direction=direction,
                    distance_units=distance_units,
                    slam_state=slam_state,
                ),
                "error_code": error_code,
                **_auto_cancel_metadata(action_result),
            },
        )

    def _check_target_safety(self, workspace: Any) -> NavigationSafetyResult:
        """Read OccupancyGrid and check the configured target safety region."""
        grid = self._ros_client.get_occupancy_grid()
        if grid is None:
            return NavigationSafetyResult(
                safe=False,
                reason="occupancy_grid_unavailable",
                radius_m=self._safety_checker.safety_radius_m,
            )
        return self._safety_checker.check_target_is_safe(grid, workspace)


def _slam_state_from_raw(raw: dict[str, Any]) -> SlamState:
    """Convert a ROS client SLAM snapshot into the DimOS SlamState contract."""
    return SlamState(
        status=str(raw.get("status", "")),
        pose=_dict_or_empty(raw.get("pose")),
        raw=_dict_or_empty(raw.get("raw", raw)),
    )


def _localization_not_ready_message(slam_state: SlamState) -> str:
    """Describe localization readiness without implying the robot SLAM node is offline."""
    if slam_state.status != "unavailable":
        return f"localization is not ready: {slam_state.status}"

    reason = slam_state.raw.get("reason", "")
    topic = slam_state.raw.get("topic", "")
    if not reason and not topic:
        return "localization status is unavailable through rosbridge"

    return (
        "localization status unavailable: rosbridge did not receive SLAM status"
        f"{f' from {topic}' if topic else ''}"
        f"{f' ({reason})' if reason else ''}"
    )


def _relative_target_from_slam_state(
    slam_state: SlamState,
    *,
    direction: str,
    distance_units: float,
) -> WorkspacePose | NavigationResult:
    """Compute a map-frame target from current SLAM pose and body-frame direction.

    Uses ``body_yaw_from_slam_state`` (quaternion yaw when present, else ``pose.yaw``)
    for forward/backward/left/right relative to the present hardware heading.
    Backward uses reverse-gear semantics: target behind the robot, goal yaw unchanged.
    """
    pose = slam_state.pose
    try:
        x = float(pose["x"])
        y = float(pose["y"])
        body_yaw = body_yaw_from_slam_state(slam_state)
    except (TypeError, ValueError, KeyError) as exc:
        return NavigationResult(
            sys_task_id=f"sys-{uuid.uuid4().hex[:8]}",
            status="failed",
            workspace_type="relative",
            table_color="",
            message="slam pose is missing x/y/yaw for relative movement",
            final_robot_state={
                "error_code": "NAV_SLAM_POSE_INVALID",
                "slam_state": slam_state.to_metadata(),
                "raw_error": str(exc),
            },
        )

    move_heading = _direction_heading(body_yaw, direction)
    if move_heading is None:
        return NavigationResult(
            sys_task_id=f"sys-{uuid.uuid4().hex[:8]}",
            status="failed",
            workspace_type="relative",
            table_color="",
            message=f"unsupported relative direction: {direction}",
            final_robot_state={
                "error_code": "NAV_RELATIVE_DIRECTION_INVALID",
                "slam_state": slam_state.to_metadata(),
                "relative_motion": relative_motion_metadata(
                    direction=direction,
                    distance_units=distance_units,
                    current_yaw=body_yaw,
                ),
            },
        )

    goal_yaw = _goal_yaw_for_relative_direction(body_yaw, direction)
    distance_m = relative_distance_units_to_meters(distance_units)
    target_x = x + distance_m * math.cos(move_heading)
    target_y = y + distance_m * math.sin(move_heading)
    return WorkspacePose(
        workspace_id=f"relative_{direction}_{distance_units}",
        name="relative",
        color=direction,
        frame_id=str(pose.get("frame_id", "map")),
        x=round(target_x, 6),
        y=round(target_y, 6),
        yaw=round(_normalize_yaw(goal_yaw), 6),
    )


def _goal_yaw_for_relative_direction(body_yaw: float, direction: str) -> float:
    """Return goal orientation for a relative move (backward keeps body heading)."""
    if direction == "backward":
        return body_yaw
    heading = _direction_heading(body_yaw, direction)
    assert heading is not None
    return heading


def _direction_heading(yaw: float, direction: str) -> float | None:
    """Return the map-frame heading for a body-frame relative direction.

    Dax hardware Nav2 uses a body frame where lateral +Y is to the robot's right,
    opposite REP-103 (+Y left). Left/right offsets are therefore swapped vs REP-103.
    """
    if direction == "forward":
        return yaw
    if direction == "backward":
        return yaw + math.pi
    if direction == "left":
        return yaw - math.pi / 2.0
    if direction == "right":
        return yaw + math.pi / 2.0
    return None


def _normalize_yaw(yaw: float) -> float:
    """Normalize a planar yaw angle to the range [-pi, pi]."""
    return math.atan2(math.sin(yaw), math.cos(yaw))


def _real_result_from_action_result(
    *,
    workspace: Any,
    action_result: NavigateToPoseActionResult,
) -> RealNavigationResult:
    """Convert a NavigateToPose action result into DimOS navigation metadata."""
    normalized = normalized_status_from_navigate_action(
        result_code=action_result.result_code,
        nav_status_code=action_result.nav_status_code,
    )
    return RealNavigationResult(
        status=normalized,
        workspace=workspace,
        message=action_result.result_message,
        nav_status_code=action_result.nav_status_code,
        uuid=action_result.uuid,
        result_pose=action_result.result_pose,
        raw={
            **action_result.raw,
            "result_code": action_result.result_code,
            "nav_description": action_result.nav_description,
        },
    )


def _auto_cancel_metadata(action_result: NavigateToPoseActionResult) -> dict[str, Any]:
    """Return adapter metadata when the ROS client auto-cancelled navigation."""
    if not action_result.raw.get("auto_cancelled"):
        return {}
    return {
        "auto_cancelled": True,
        "auto_cancel_trigger_code": action_result.raw.get("auto_cancel_trigger_code"),
    }


def _navigation_result_status(
    status: NavigationNormalizedStatus,
    action_result: NavigateToPoseActionResult,
) -> tuple[str, str]:
    """Return legacy NavigationResult status plus a detailed error code."""
    if action_result.result_code == 0 and status == "arrived":
        return "arrived", ""
    if status == "blocked":
        return "failed", "NAVIGATION_BLOCKED"
    if status == "target_blocked":
        return "failed", "NAV_TARGET_BLOCKED"
    if status == "preempted":
        return "failed", "NAVIGATION_PREEMPTED"
    if status == "cancelled" or action_result.result_code == 2:
        return "cancelled", "NAVIGATION_CANCELLED"
    return "failed", "NAVIGATION_FAILED"


def _dict_or_empty(value: Any) -> dict[str, Any]:
    """Return value when it is a dict, otherwise an empty diagnostic mapping."""
    return value if isinstance(value, dict) else {}


__all__ = [
    "NavigateToPoseActionResult",
    "NavigationRosClient",
    "RosTopicNavigationAdapter",
]
