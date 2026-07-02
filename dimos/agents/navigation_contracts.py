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

"""Contracts for real lower-body navigation adapters.

This module keeps ROS navigation payloads behind a small DimOS-facing data model.
ActionPlan steps still speak in task-level terms such as ``move_to_workspace``;
adapters can translate those terms into ``NavigateToPose`` goals and normalize ROS
status topics back into stable metadata for orchestration, logs, and tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

NavigationNormalizedStatus = Literal[
    "idle",
    "accepted",
    "planning_succeeded",
    "moving",
    "arrived",
    "cancelled",
    "preempted",
    "blocked",
    "target_blocked",
    "refreshing",
    "local_succeeded",
    "local_cancelled",
    "recovery",
    "failed",
    "timeout",
    "unknown",
]

_NAV_STATUS_BY_CODE: dict[int, NavigationNormalizedStatus] = {
    -1: "unknown",
    0: "idle",
    1000: "accepted",
    1001: "planning_succeeded",
    1002: "moving",
    1003: "arrived",
    1004: "cancelled",
    1005: "preempted",
    1006: "blocked",
    1007: "target_blocked",
    1008: "refreshing",
    1009: "local_succeeded",
    1010: "local_cancelled",
    2000: "recovery",
    3000: "failed",
    3001: "failed",
    3002: "failed",
    3003: "failed",
    3004: "failed",
}

# ROS 2 action_msgs/GoalStatus values (0-6). Robot NavStatus uses 1000+.
_ROS_ACTION_GOAL_STATUS_MAX = 6


def is_ros_action_goal_status_code(code: int) -> bool:
    """Return True when *code* is a ROS2 action goal status, not robot NavStatus."""
    return 0 <= code <= _ROS_ACTION_GOAL_STATUS_MAX


def normalized_status_from_navigate_action(
    *,
    result_code: int,
    nav_status_code: int | None,
) -> NavigationNormalizedStatus:
    """Map NavigateToPose action feedback into a stable navigation status.

    py_rosbridge exposes ROS2 action goal status in ``event.status`` (for example
    4 = SUCCEEDED). That must not be passed through ``normalize_nav_status_code``,
    which expects robot_interfaces NavStatus values such as 1003 = arrived.
    """
    if nav_status_code is not None and not is_ros_action_goal_status_code(nav_status_code):
        return normalize_nav_status_code(nav_status_code)
    return status_from_navigate_result_code(result_code)


def status_from_navigate_result_code(result_code: int) -> NavigationNormalizedStatus:
    """Map NavigateToPose result.result_code into a normalized navigation status."""
    if result_code == 0:
        return "arrived"
    if result_code == 2:
        return "cancelled"
    return "failed"

# One semantic relative-move unit equals one map cell/pixel at 5 cm resolution.
MAP_CELL_SIZE_M = 0.05


def relative_distance_units_to_meters(distance_units: float) -> float:
    """Convert task-level relative distance units into map-frame meters."""
    return distance_units * MAP_CELL_SIZE_M


def meters_to_relative_distance_units(meters: float) -> float:
    """Convert meters into task-level relative distance units (map cells)."""
    return meters / MAP_CELL_SIZE_M


def relative_motion_metadata(
    *,
    direction: str,
    distance_units: float,
    current_yaw: float | None = None,
    quaternion_yaw: float | None = None,
) -> dict[str, Any]:
    """Return relative-move metadata with both semantic units and meters."""
    payload: dict[str, Any] = {
        "direction": direction,
        "distance_units": distance_units,
        "distance_m": relative_distance_units_to_meters(distance_units),
        "map_cell_size_m": MAP_CELL_SIZE_M,
    }
    if current_yaw is not None:
        payload["current_yaw"] = current_yaw
    if quaternion_yaw is not None:
        payload["quaternion_yaw"] = quaternion_yaw
    return payload


def normalize_nav_status_code(code: int) -> NavigationNormalizedStatus:
    """Return DimOS' stable navigation status name for one ROS nav status code."""
    return _NAV_STATUS_BY_CODE.get(code, "unknown")


def parse_nav_auto_cancel_status_codes(raw: str) -> frozenset[int]:
    """Parse a comma-separated NavStatus code list for auto-cancel triggers."""
    codes: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            codes.add(int(token))
        except ValueError as exc:
            raise ValueError(f"invalid nav auto-cancel status code: {token!r}") from exc
    if not codes:
        raise ValueError("nav auto-cancel status codes must not be empty")
    return frozenset(codes)


def should_auto_cancel_nav_status(code: int, *, allowed: frozenset[int]) -> bool:
    """Return whether one NavStatus code should trigger action auto-cancel."""
    return code in allowed


@dataclass(frozen=True)
class WorkspacePose:
    """Represent a named workspace goal pose in the navigation map frame."""

    workspace_id: str
    name: str
    color: str
    frame_id: str
    x: float
    y: float
    yaw: float

    def to_metadata(self) -> dict[str, Any]:
        """Return the workspace pose in the metadata shape consumed by orchestrators."""
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "color": self.color,
            "pose": {
                "frame_id": self.frame_id,
                "x": self.x,
                "y": self.y,
                "yaw": self.yaw,
            },
        }


@dataclass(frozen=True)
class SlamState:
    """Represent the latest SLAM/localization status needed before navigation."""

    status: str
    pose: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)

    def is_navigation_ready(self) -> bool:
        """Return whether the robot is localized enough to accept navigation goals."""
        return self.status == "located"

    def to_metadata(self) -> dict[str, Any]:
        """Return SLAM status metadata for diagnostics and failure reports."""
        return {
            "status": self.status,
            "pose": self.pose,
            "raw": self.raw,
        }


def body_yaw_from_slam_state(slam_state: SlamState) -> float:
    """Return body-forward heading for relative motion (prefer pose quaternion yaw).

    ``pose.yaw`` stores SlamStatus.angle converted to map-frame ROS yaw.
    When ``raw.quaternion_yaw`` is present it matches Web UI / hardware heading
    and is used for body-frame forward/backward/left/right goals.
    """
    raw_quat = slam_state.raw.get("quaternion_yaw")
    if raw_quat is not None:
        return float(raw_quat)
    return float(slam_state.pose["yaw"])


@dataclass(frozen=True)
class NavigateToPoseGoal:
    """Represent the DimOS-normalized fields needed to send a NavigateToPose goal."""

    pose: WorkspacePose
    behavior_tree: str

    def to_metadata(self) -> dict[str, Any]:
        """Return the goal fields safe to store in logs and action metadata."""
        return {
            "pose": self.pose.to_metadata()["pose"],
            "workspace_id": self.pose.workspace_id,
            "behavior_tree": self.behavior_tree,
        }


@dataclass(frozen=True)
class RealNavigationResult:
    """Represent one completed real navigation step after ROS status normalization."""

    status: NavigationNormalizedStatus
    workspace: WorkspacePose
    message: str
    nav_status_code: int | None = None
    uuid: str = ""
    result_pose: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """Return navigation result metadata for ActionPlan step stores."""
        return {
            "workspace": self.workspace.to_metadata(),
            "status": self.status,
            "message": self.message,
            "nav_status_code": self.nav_status_code,
            "uuid": self.uuid,
            "result_pose": self.result_pose,
            "raw": self.raw,
        }


__all__ = [
    "MAP_CELL_SIZE_M",
    "NavigateToPoseGoal",
    "NavigationNormalizedStatus",
    "RealNavigationResult",
    "SlamState",
    "WorkspacePose",
    "body_yaw_from_slam_state",
    "is_ros_action_goal_status_code",
    "meters_to_relative_distance_units",
    "normalize_nav_status_code",
    "normalized_status_from_navigate_action",
    "parse_nav_auto_cancel_status_codes",
    "relative_distance_units_to_meters",
    "should_auto_cancel_nav_status",
    "status_from_navigate_result_code",
    "relative_motion_metadata",
]
