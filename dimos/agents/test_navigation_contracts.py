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

import pytest

from dimos.agents.navigation_contracts import (
    MAP_CELL_SIZE_M,
    NavigateToPoseGoal,
    RealNavigationResult,
    SlamState,
    WorkspacePose,
    is_ros_action_goal_status_code,
    meters_to_relative_distance_units,
    normalize_nav_status_code,
    normalized_status_from_navigate_action,
    parse_nav_auto_cancel_status_codes,
    relative_distance_units_to_meters,
    should_auto_cancel_nav_status,
    status_from_navigate_result_code,
)


def test_normalize_nav_status_code_maps_success_and_progress_states() -> None:
    assert normalize_nav_status_code(0) == "idle"
    assert normalize_nav_status_code(1000) == "accepted"
    assert normalize_nav_status_code(1001) == "planning_succeeded"
    assert normalize_nav_status_code(1002) == "moving"
    assert normalize_nav_status_code(1003) == "arrived"
    assert normalize_nav_status_code(2000) == "recovery"


def test_normalize_nav_status_code_maps_failure_states() -> None:
    assert normalize_nav_status_code(1004) == "cancelled"
    assert normalize_nav_status_code(1005) == "preempted"
    assert normalize_nav_status_code(1006) == "blocked"
    assert normalize_nav_status_code(1007) == "target_blocked"
    assert normalize_nav_status_code(3000) == "failed"
    assert normalize_nav_status_code(3001) == "failed"
    assert normalize_nav_status_code(3002) == "failed"
    assert normalize_nav_status_code(3003) == "failed"
    assert normalize_nav_status_code(3004) == "failed"
    assert normalize_nav_status_code(4242) == "unknown"


def test_workspace_pose_serializes_to_navigation_metadata() -> None:
    pose = WorkspacePose(
        workspace_id="front_workspace",
        name="workspace",
        color="front",
        frame_id="map",
        x=1.8,
        y=0.0,
        yaw=0.0,
    )

    assert pose.to_metadata() == {
        "workspace_id": "front_workspace",
        "name": "workspace",
        "color": "front",
        "pose": {
            "frame_id": "map",
            "x": 1.8,
            "y": 0.0,
            "yaw": 0.0,
        },
    }


def test_navigate_to_pose_goal_uses_real_robot_action_fields() -> None:
    pose = WorkspacePose(
        workspace_id="front_workspace",
        name="workspace",
        color="front",
        frame_id="map",
        x=1.8,
        y=0.0,
        yaw=0.0,
    )
    goal = NavigateToPoseGoal(pose=pose, behavior_tree="")

    assert goal.to_metadata() == {
        "pose": pose.to_metadata()["pose"],
        "workspace_id": "front_workspace",
        "behavior_tree": "",
    }


def test_navigation_result_keeps_normalized_and_raw_ros_state() -> None:
    pose = WorkspacePose(
        workspace_id="blue_table",
        name="table",
        color="blue",
        frame_id="map",
        x=2.4,
        y=0.6,
        yaw=1.57,
    )
    result = RealNavigationResult(
        status="arrived",
        workspace=pose,
        message="导航成功",
        nav_status_code=1003,
        uuid="nav-123",
        result_pose={"frame_id": "map", "x": 2.4, "y": 0.6, "yaw": 1.57},
        raw={"description": "NAV_SUCCESS"},
    )

    assert result.to_metadata() == {
        "workspace": pose.to_metadata(),
        "status": "arrived",
        "message": "导航成功",
        "nav_status_code": 1003,
        "uuid": "nav-123",
        "result_pose": {"frame_id": "map", "x": 2.4, "y": 0.6, "yaw": 1.57},
        "raw": {"description": "NAV_SUCCESS"},
    }


def test_slam_state_detects_navigation_readiness() -> None:
    assert SlamState(status="located", pose={"x": 0.0}).is_navigation_ready()
    assert not SlamState(status="lost", pose={"x": 0.0}).is_navigation_ready()
    assert not SlamState(status="relocating", pose={"x": 0.0}).is_navigation_ready()


def test_relative_distance_units_to_meters_uses_five_centimeter_map_cells() -> None:
    assert MAP_CELL_SIZE_M == 0.05
    assert relative_distance_units_to_meters(1.0) == 0.05
    assert relative_distance_units_to_meters(2.0) == 0.1
    assert relative_distance_units_to_meters(20.0) == 1.0
    assert meters_to_relative_distance_units(1.0) == 20.0
    assert meters_to_relative_distance_units(0.5) == 10.0


def test_is_ros_action_goal_status_code_distinguishes_action_from_robot_nav() -> None:
    assert is_ros_action_goal_status_code(4)
    assert is_ros_action_goal_status_code(0)
    assert not is_ros_action_goal_status_code(1003)
    assert not is_ros_action_goal_status_code(3000)


def test_normalized_status_from_navigate_action_uses_result_code_for_action_status() -> None:
    assert normalized_status_from_navigate_action(result_code=0, nav_status_code=4) == "arrived"
    assert normalized_status_from_navigate_action(result_code=0, nav_status_code=None) == "arrived"
    assert normalized_status_from_navigate_action(result_code=1, nav_status_code=4) == "failed"
    assert normalized_status_from_navigate_action(result_code=0, nav_status_code=1003) == "arrived"
    assert normalized_status_from_navigate_action(result_code=0, nav_status_code=3000) == "failed"


def test_status_from_navigate_result_code_maps_cancelled() -> None:
    assert status_from_navigate_result_code(0) == "arrived"
    assert status_from_navigate_result_code(2) == "cancelled"
    assert status_from_navigate_result_code(1) == "failed"


def test_parse_nav_auto_cancel_status_codes() -> None:
    assert parse_nav_auto_cancel_status_codes("1005,1006,1007") == frozenset({1005, 1006, 1007})
    assert parse_nav_auto_cancel_status_codes(" 1006 ") == frozenset({1006})


def test_parse_nav_auto_cancel_status_codes_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="invalid nav auto-cancel status code"):
        parse_nav_auto_cancel_status_codes("1006,abc")


def test_should_auto_cancel_nav_status() -> None:
    allowed = parse_nav_auto_cancel_status_codes("1005,1006,1007")
    assert should_auto_cancel_nav_status(1006, allowed=allowed) is True
    assert should_auto_cancel_nav_status(1002, allowed=allowed) is False
