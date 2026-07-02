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

import math
from typing import Any

import pytest
from py_rosbridge.codecs import geometry_msgs, nav_msgs
from py_rosbridge.client import QosDurability, QosReliability

from dimos.agents.rosbridge.navigation.client import (
    PyRosbridgeNavigationRosClient,
    planar_yaw_from_slam_message,
)
from dimos.agents.rosbridge.codecs.robot_interfaces import SlamStatus
from dimos.agents.ros_topic_navigation_adapter import (
    NavigateToPoseActionResult,
    RosTopicNavigationAdapter,
)
from dimos.agents.workspace_resolver import WorkspaceResolver


class FakeNavigationRosClient:
    def __init__(
        self,
        *,
        slam_status: str = "located",
        nav_status_code: int = 1003,
        action_result: NavigateToPoseActionResult | None = None,
    ) -> None:
        self._slam_status = slam_status
        self._nav_status_code = nav_status_code
        self._action_result = action_result or NavigateToPoseActionResult(
            result_code=0,
            result_message="导航成功",
            result_pose={"frame_id": "map", "x": 1.8, "y": 0.0, "yaw": 0.0},
            uuid="nav-123",
            nav_status_code=nav_status_code,
            nav_description="NAV_SUCCESS",
        )
        self.sent_goals: list[dict[str, Any]] = []
        self.occupancy_grid: Any | None = None

    def get_slam_state(self) -> dict[str, Any]:
        return {
            "status": self._slam_status,
            "pose": {"frame_id": "map", "x": 0.0, "y": 0.0, "yaw": 0.0},
            "raw": {"status": self._slam_status},
        }

    def get_occupancy_grid(self) -> Any | None:
        return self.occupancy_grid

    def send_navigate_to_pose(
        self,
        goal: dict[str, Any],
        *,
        timeout_s: float,
        request_id: str = "",
    ) -> NavigateToPoseActionResult:
        self.sent_goals.append(
            {"goal": goal, "timeout_s": timeout_s, "request_id": request_id}
        )
        return self._action_result


def _slam_client_at(x: float, y: float, yaw: float) -> FakeNavigationRosClient:
    """Fake ROS client with a fixed map-frame SLAM pose."""
    client = FakeNavigationRosClient()
    client.get_slam_state = lambda: {  # type: ignore[method-assign]
        "status": "located",
        "pose": {"frame_id": "map", "x": x, "y": y, "yaw": yaw},
        "raw": {"status": "located"},
    }
    client.occupancy_grid = _free_grid()
    return client


class _SubscribeEvent:
    def __init__(self, message: Any) -> None:
        self.message = message


class _RecordingRosbridgeClient:
    def __init__(self) -> None:
        self.subscriptions: list[dict[str, Any]] = []

    def subscribe(
        self,
        topic: str,
        topic_type: str,
        callback: Any,
        *,
        codec: Any,
        qos: Any | None = None,
    ) -> None:
        self.subscriptions.append(
            {
                "topic": topic,
                "topic_type": topic_type,
                "callback": callback,
                "codec": codec,
                "qos": qos,
            }
        )


class _StaticRosbridgeSession:
    target = "test-target:9091"

    def __init__(self, client: _RecordingRosbridgeClient) -> None:
        self._client = client

    def get_client(self) -> _RecordingRosbridgeClient:
        return self._client


def _resolver() -> WorkspaceResolver:
    return WorkspaceResolver.from_mapping(
        {
            "front_workspace": {
                "workspace_id": "front_workspace",
                "name": "workspace",
                "color": "front",
                "frame_id": "map",
                "x": 1.8,
                "y": 0.0,
                "yaw": 0.0,
                "aliases": ["前方固定工作区"],
            },
            "blue_table": {
                "workspace_id": "blue_table",
                "name": "table",
                "color": "blue",
                "frame_id": "map",
                "x": 2.4,
                "y": 0.6,
                "yaw": 1.57,
            },
        }
    )


def _free_grid() -> nav_msgs.OccupancyGrid:
    grid = nav_msgs.OccupancyGrid()
    grid.info.width = 80
    grid.info.height = 80
    grid.info.resolution = 0.1
    grid.info.origin = geometry_msgs.Pose(
        position=geometry_msgs.Point(x=-4.0, y=-4.0, z=0.0),
        orientation=geometry_msgs.Quaternion(w=1.0),
    )
    grid.data = [0 for _ in range(grid.info.width * grid.info.height)]
    return grid


def test_py_rosbridge_navigation_client_subscribes_like_py_rosbridge_examples() -> None:
    rosbridge_client = _RecordingRosbridgeClient()
    client = PyRosbridgeNavigationRosClient(
        session=_StaticRosbridgeSession(rosbridge_client),  # type: ignore[arg-type]
        slam_status_topic="/slam_status",
        slam_status_topic_type="robot_interfaces/msg/SlamStatus",
        map_topic="/map",
        map_topic_type="nav_msgs/msg/OccupancyGrid",
        nav_status_topic="/navigation_current_status",
        nav_status_topic_type="robot_interfaces/msg/NavStatus",
        navigate_action="/navigate_to_pose",
        navigate_action_type="robot_interfaces/action/NavigateToPose",
        timeout_s=1.0,
        topic_timeout_s=0.01,
    )

    client._ensure_subscribed()  # noqa: SLF001 - subscription wiring is the behavior under test.

    assert [item["topic"] for item in rosbridge_client.subscriptions] == [
        "/slam_status",
        "/map",
        "/navigation_current_status",
    ]
    slam_qos = rosbridge_client.subscriptions[0]["qos"]
    assert slam_qos is not None
    assert slam_qos.depth == 1
    assert slam_qos.reliability is QosReliability.BEST_EFFORT
    assert slam_qos.durability is QosDurability.VOLATILE

    map_qos = rosbridge_client.subscriptions[1]["qos"]
    assert map_qos is not None
    assert map_qos.depth == 1
    assert map_qos.reliability is QosReliability.RELIABLE
    assert map_qos.durability is QosDurability.TRANSIENT_LOCAL

    slam_msg = SlamStatus(status="located")
    map_msg = _free_grid()
    nav_msg = object()
    rosbridge_client.subscriptions[0]["callback"](_SubscribeEvent(slam_msg))
    rosbridge_client.subscriptions[1]["callback"](_SubscribeEvent(map_msg))
    rosbridge_client.subscriptions[2]["callback"](_SubscribeEvent(nav_msg))

    assert client._latest_message(client._slam_messages) is slam_msg  # noqa: SLF001
    assert client._latest_message(client._map_messages) is map_msg  # noqa: SLF001
    assert client._latest_message(client._nav_status_messages) is nav_msg  # noqa: SLF001

    rosbridge_client.subscriptions[0]["callback"](_SubscribeEvent(SlamStatus(status="lost")))
    latest_slam_msg = SlamStatus(status="located")
    rosbridge_client.subscriptions[0]["callback"](_SubscribeEvent(latest_slam_msg))

    assert client._latest_message(client._slam_messages) is latest_slam_msg  # noqa: SLF001


def test_py_rosbridge_navigation_client_reuses_single_published_map() -> None:
    rosbridge_client = _RecordingRosbridgeClient()
    client = PyRosbridgeNavigationRosClient(
        session=_StaticRosbridgeSession(rosbridge_client),  # type: ignore[arg-type]
        slam_status_topic="/slam_status",
        slam_status_topic_type="robot_interfaces/msg/SlamStatus",
        map_topic="/map",
        map_topic_type="nav_msgs/msg/OccupancyGrid",
        nav_status_topic="/navigation_current_status",
        nav_status_topic_type="robot_interfaces/msg/NavStatus",
        navigate_action="/navigate_to_pose",
        navigate_action_type="robot_interfaces/action/NavigateToPose",
        timeout_s=1.0,
        topic_timeout_s=0.01,
    )
    map_msg = _free_grid()

    client._ensure_subscribed()  # noqa: SLF001 - subscription wiring is the behavior under test.
    rosbridge_client.subscriptions[1]["callback"](_SubscribeEvent(map_msg))

    assert client.get_occupancy_grid() is map_msg
    assert client.get_occupancy_grid() is map_msg


def test_localization_not_ready_does_not_send_navigation_goal() -> None:
    client = FakeNavigationRosClient(slam_status="lost")
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="front_workspace",
        table_color="",
    )

    assert result.status == "failed"
    assert result.message == "localization is not ready: lost"
    assert client.sent_goals == []
    assert result.final_robot_state["error_code"] == "NAV_LOCALIZATION_LOST"


def test_slam_status_unavailable_does_not_send_navigation_goal() -> None:
    class UnavailableSlamClient(FakeNavigationRosClient):
        def get_slam_state(self) -> dict[str, Any]:
            return {
                "status": "unavailable",
                "pose": {},
                "raw": {"reason": "slam_status_timeout", "topic": "/slam_status"},
            }

    client = UnavailableSlamClient()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.move_relative(
        request_id="req-relative-nav-test",
        direction="backward",
        distance_units=20.0,
    )

    assert result.status == "failed"
    assert "rosbridge did not receive SLAM status from /slam_status" in result.message
    assert "SLAM offline" not in result.message
    assert client.sent_goals == []
    assert result.final_robot_state["error_code"] == "NAV_SLAM_STATUS_UNAVAILABLE"


def test_successful_navigation_sends_pose_goal_and_returns_arrived() -> None:
    client = FakeNavigationRosClient()
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="front_workspace",
        table_color="",
    )

    assert result.status == "arrived"
    assert result.message == "导航成功"
    assert client.sent_goals == [
        {
            "goal": {
                "pose": {
                    "frame_id": "map",
                    "x": 1.8,
                    "y": 0.0,
                    "yaw": 0.0,
                },
                "workspace_id": "front_workspace",
                "behavior_tree": "no_route_slow",
            },
            "timeout_s": 60.0,
            "request_id": "req-nav-test",
        }
    ]
    assert result.final_robot_state["workspace"]["workspace_id"] == "front_workspace"
    assert result.final_robot_state["nav_status_code"] == 1003
    assert result.final_robot_state["uuid"] == "nav-123"
    assert result.final_robot_state["safety_check"]["reason"] == "target_area_free"


def test_relative_backward_move_computes_goal_from_current_pose_and_sends_navigation() -> None:
    client = FakeNavigationRosClient()
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.move_relative(
        request_id="req-relative-nav-test",
        direction="backward",
        distance_units=1.0,
    )

    assert result.status == "arrived"
    assert client.sent_goals == [
        {
            "goal": {
                "pose": {
                    "frame_id": "map",
                    "x": -0.05,
                    "y": 0.0,
                    "yaw": 0.0,
                },
                "workspace_id": "relative_backward_1.0",
                "behavior_tree": "no_route_slow",
            },
            "timeout_s": 60.0,
            "request_id": "req-relative-nav-test",
        }
    ]
    assert result.final_robot_state["relative_motion"] == {
        "direction": "backward",
        "distance_units": 1.0,
        "distance_m": 0.05,
        "map_cell_size_m": 0.05,
        "current_yaw": 0.0,
    }
    assert result.final_robot_state["safety_check"]["reason"] == "target_area_free"


def test_relative_move_treats_ros_action_succeeded_status_as_arrived() -> None:
    client = FakeNavigationRosClient(
        action_result=NavigateToPoseActionResult(
            result_code=0,
            result_message="SUCCEEDED",
            result_pose={"frame_id": "map", "x": -0.05, "y": 0.0, "yaw": 0.0},
            uuid="goal-e43d416781174566b6e4e8108d1bdd4c",
            nav_status_code=4,
            raw={"action_status": 4, "result_code": 0},
        ),
    )
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.move_relative(
        request_id="req-relative-nav-test",
        direction="backward",
        distance_units=1.0,
    )

    assert result.status == "arrived"
    assert result.final_robot_state.get("error_code") in {"", None}
    assert result.message == "SUCCEEDED"


def test_relative_move_converts_semantic_units_to_map_meters() -> None:
    client = FakeNavigationRosClient()
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.move_relative(
        request_id="req-relative-nav-test",
        direction="backward",
        distance_units=2.0,
    )

    assert result.status == "arrived"
    assert client.sent_goals[0]["goal"]["pose"]["x"] == -0.1
    assert result.final_robot_state["relative_motion"]["distance_m"] == 0.1


@pytest.mark.parametrize(
    ("direction", "expected_x", "expected_y", "expected_yaw"),
    [
        ("forward", 0.59694, -0.04828, -2.39),
        ("backward", 0.74306, 0.08828, -2.39),
        ("left", 0.60172, 0.09306, 2.322389),
        ("right", 0.73828, -0.05306, -0.819204),
    ],
)
def test_relative_move_at_live_robot_pose(
    direction: str,
    expected_x: float,
    expected_y: float,
    expected_yaw: float,
) -> None:
    """Goal math at typical factory SLAM pose (x=0.67, y=0.02, yaw≈-137°)."""
    client = _slam_client_at(0.67, 0.02, -2.39)
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.move_relative(
        request_id="req-live-pose",
        direction=direction,
        distance_units=2.0,
    )

    assert result.status == "arrived"
    pose = client.sent_goals[0]["goal"]["pose"]
    assert pose["x"] == pytest.approx(expected_x, abs=1e-4)
    assert pose["y"] == pytest.approx(expected_y, abs=1e-4)
    assert pose["yaw"] == pytest.approx(expected_yaw, abs=1e-4)


def test_body_yaw_from_slam_state_prefers_quaternion() -> None:
    from dimos.agents.navigation_contracts import SlamState, body_yaw_from_slam_state

    slam = SlamState(
        status="located",
        pose={"frame_id": "map", "x": 0.0, "y": 0.0, "yaw": 0.1},
        raw={"quaternion_yaw": -2.39},
    )
    assert body_yaw_from_slam_state(slam) == -2.39


def test_body_yaw_from_slam_state_falls_back_to_pose_yaw() -> None:
    from dimos.agents.navigation_contracts import SlamState, body_yaw_from_slam_state

    slam = SlamState(
        status="located",
        pose={"frame_id": "map", "x": 0.0, "y": 0.0, "yaw": 0.25},
        raw={},
    )
    assert body_yaw_from_slam_state(slam) == 0.25


def test_relative_move_prefers_quaternion_yaw_over_nav_yaw() -> None:
    """Relative goals use quaternion body heading, not angle-converted pose.yaw."""
    client = FakeNavigationRosClient()
    client.get_slam_state = lambda: {  # type: ignore[method-assign]
        "status": "located",
        "pose": {"frame_id": "map", "x": 0.67, "y": 0.02, "yaw": 0.0},
        "raw": {"status": "located", "quaternion_yaw": -2.39},
    }
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.move_relative(
        request_id="req-quat-priority",
        direction="backward",
        distance_units=2.0,
    )

    assert result.status == "arrived"
    pose = client.sent_goals[0]["goal"]["pose"]
    assert pose["x"] == pytest.approx(0.74306, abs=1e-4)
    assert pose["y"] == pytest.approx(0.08828, abs=1e-4)
    assert pose["yaw"] == pytest.approx(-2.39, abs=1e-4)
    assert result.final_robot_state["relative_motion"]["current_yaw"] == pytest.approx(-2.39)


def test_backward_goal_yaw_keeps_body_heading_not_flipped() -> None:
    """Backward reverse-gear: move behind robot but keep goal yaw = body heading."""
    body_yaw = -2.39
    client = FakeNavigationRosClient()
    client.get_slam_state = lambda: {  # type: ignore[method-assign]
        "status": "located",
        "pose": {"frame_id": "map", "x": 0.67, "y": 0.02, "yaw": 0.0},
        "raw": {"status": "located", "quaternion_yaw": body_yaw},
    }
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.move_relative(
        request_id="req-reverse-gear",
        direction="backward",
        distance_units=2.0,
    )

    assert result.status == "arrived"
    pose = client.sent_goals[0]["goal"]["pose"]
    move_heading = body_yaw + math.pi
    assert pose["yaw"] == pytest.approx(body_yaw, abs=1e-4)
    assert pose["yaw"] != pytest.approx(move_heading, abs=0.1)


def test_relative_left_right_swapped_vs_rep103_at_origin_yaw() -> None:
    """Left/right use Dax body frame (+Y right), not REP-103 (+Y left)."""
    client = _slam_client_at(0.0, 0.0, 0.0)
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    left = adapter.move_relative(request_id="r1", direction="left", distance_units=1.0)
    right = adapter.move_relative(request_id="r2", direction="right", distance_units=1.0)

    assert left.status == "arrived"
    assert right.status == "arrived"
    left_pose = left.final_robot_state["goal"]["pose"]
    right_pose = right.final_robot_state["goal"]["pose"]
    assert left_pose["x"] == pytest.approx(0.0, abs=1e-6)
    assert left_pose["y"] == pytest.approx(-0.05, abs=1e-6)
    assert right_pose["x"] == pytest.approx(0.0, abs=1e-6)
    assert right_pose["y"] == pytest.approx(0.05, abs=1e-6)


def test_planar_yaw_converts_slam_angle_from_north_bearing() -> None:
    """SlamStatus.angle is from map +Y; ROS yaw is CCW from +X."""
    import math

    from dimos.agents.rosbridge.codecs.robot_interfaces import SlamStatus
    from dimos.agents.rosbridge.navigation.client import planar_yaw_from_slam_message

    north = SlamStatus(status="located", angle=0.0)
    east = SlamStatus(status="located", angle=math.pi / 2)
    south = SlamStatus(status="located", angle=math.pi)
    factory = SlamStatus(status="located", angle=1.54321)

    assert planar_yaw_from_slam_message(north) == pytest.approx(math.pi / 2)
    assert planar_yaw_from_slam_message(east) == pytest.approx(0.0, abs=1e-6)
    assert planar_yaw_from_slam_message(south) == pytest.approx(-math.pi / 2)
    assert planar_yaw_from_slam_message(factory) == pytest.approx(
        math.atan2(math.cos(1.54321), math.sin(1.54321))
    )


def test_get_slam_state_prefers_angle_over_quaternion() -> None:
    """get_slam_state stores angle-converted yaw in pose.yaw; quat stays in raw."""
    rosbridge_client = _RecordingRosbridgeClient()
    client = PyRosbridgeNavigationRosClient(
        session=_StaticRosbridgeSession(rosbridge_client),  # type: ignore[arg-type]
        slam_status_topic="/slam_status",
        slam_status_topic_type="robot_interfaces/msg/SlamStatus",
        map_topic="/map",
        map_topic_type="nav_msgs/msg/OccupancyGrid",
        nav_status_topic="/navigation_current_status",
        nav_status_topic_type="robot_interfaces/msg/NavStatus",
        navigate_action="/navigate_to_pose",
        navigate_action_type="robot_interfaces/action/NavigateToPose",
        timeout_s=1.0,
        topic_timeout_s=0.01,
    )
    client._ensure_subscribed()  # noqa: SLF001

    slam_msg = SlamStatus(status="located", angle=1.54321)
    slam_msg.pose.position.x = 0.67
    slam_msg.pose.position.y = 0.02
    slam_msg.pose.orientation.w = 1.0
    rosbridge_client.subscriptions[0]["callback"](_SubscribeEvent(slam_msg))

    state = client.get_slam_state()
    expected_yaw = math.atan2(math.cos(1.54321), math.sin(1.54321))
    assert state["pose"]["yaw"] == pytest.approx(expected_yaw)
    assert state["raw"]["angle"] == pytest.approx(1.54321)
    assert state["raw"]["quaternion_yaw"] == pytest.approx(0.0)
    assert planar_yaw_from_slam_message(slam_msg) == pytest.approx(expected_yaw)


def test_relative_forward_uses_current_yaw_not_boot_heading() -> None:
    """Forward/backward are relative to present heading, not a captured boot yaw."""
    pose = {"frame_id": "map", "x": 0.0, "y": 0.0, "yaw": 0.0}
    client = FakeNavigationRosClient()
    client.get_slam_state = lambda: {  # type: ignore[method-assign]
        "status": "located",
        "pose": dict(pose),
        "raw": {"status": "located"},
    }
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    first = adapter.move_relative(request_id="r1", direction="forward", distance_units=2.0)
    assert first.status == "arrived"
    assert client.sent_goals[0]["goal"]["pose"]["x"] == pytest.approx(0.1, abs=1e-4)

    pose = {"frame_id": "map", "x": 0.1, "y": 0.0, "yaw": math.pi / 2}
    second = adapter.move_relative(request_id="r2", direction="forward", distance_units=2.0)
    assert second.status == "arrived"
    second_pose = client.sent_goals[1]["goal"]["pose"]
    assert second_pose["x"] == pytest.approx(0.1, abs=1e-4)
    assert second_pose["y"] == pytest.approx(0.1, abs=1e-4)


def test_relative_move_blocked_by_target_radius_does_not_send_navigation() -> None:
    client = FakeNavigationRosClient()
    grid = _free_grid()
    grid.data[40 * grid.info.width + 36] = 100
    client.occupancy_grid = grid
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.move_relative(
        request_id="req-relative-nav-test",
        direction="backward",
        distance_units=1.0,
    )

    assert result.status == "failed"
    assert client.sent_goals == []
    assert result.final_robot_state["error_code"] == "NAV_TARGET_UNSAFE"
    assert result.final_robot_state["safety_check"]["reason"] == "occupied_cell_in_target_footprint"


def test_missing_occupancy_grid_does_not_send_navigation_goal() -> None:
    client = FakeNavigationRosClient()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="front_workspace",
        table_color="",
    )

    assert result.status == "failed"
    assert result.message == "navigation target failed map safety check: occupancy_grid_unavailable"
    assert client.sent_goals == []
    assert result.final_robot_state["error_code"] == "NAV_TARGET_UNSAFE"
    assert result.final_robot_state["safety_check"]["reason"] == "occupancy_grid_unavailable"


def test_occupied_target_radius_does_not_send_navigation_goal() -> None:
    client = FakeNavigationRosClient()
    grid = _free_grid()
    grid.data[40 * grid.info.width + 58] = 100
    client.occupancy_grid = grid
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="front_workspace",
        table_color="",
    )

    assert result.status == "failed"
    assert result.message == "navigation target failed map safety check: occupied_cell_in_target_footprint"
    assert client.sent_goals == []
    assert result.final_robot_state["error_code"] == "NAV_TARGET_UNSAFE"
    assert result.final_robot_state["safety_check"]["radius_m"] == pytest.approx(0.474, abs=1e-3)
    assert result.final_robot_state["safety_check"]["mode"] == "footprint"
    assert result.final_robot_state["safety_check"]["blocking_cell"] == {
        "mx": 58,
        "my": 40,
        "value": 100,
    }


def test_resolve_name_and_color_before_sending_goal() -> None:
    client = FakeNavigationRosClient()
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="table",
        table_color="blue",
    )

    assert result.status == "arrived"
    assert client.sent_goals[0]["goal"]["workspace_id"] == "blue_table"
    assert client.sent_goals[0]["goal"]["pose"]["x"] == 2.4


def test_blocked_navigation_returns_failed_with_blocked_metadata() -> None:
    client = FakeNavigationRosClient(
        nav_status_code=1006,
        action_result=NavigateToPoseActionResult(
            result_code=1,
            result_message="路径被阻挡",
            result_pose={},
            uuid="nav-blocked",
            nav_status_code=1006,
            nav_description="NAV_PATH_IS_BLOCKED",
        ),
    )
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="front_workspace",
        table_color="",
    )

    assert result.status == "failed"
    assert result.message == "路径被阻挡"
    assert result.final_robot_state["error_code"] == "NAVIGATION_BLOCKED"
    assert result.final_robot_state["status"] == "blocked"


def test_target_blocked_navigation_returns_failed_with_target_blocked_metadata() -> None:
    client = FakeNavigationRosClient(
        nav_status_code=1007,
        action_result=NavigateToPoseActionResult(
            result_code=1,
            result_message="终点被障碍物覆盖",
            result_pose={},
            uuid="nav-target-blocked",
            nav_status_code=1007,
            nav_description="NAV_TARGET_COVERED_BY_OBSTACLE",
        ),
    )
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="front_workspace",
        table_color="",
    )

    assert result.status == "failed"
    assert result.final_robot_state["error_code"] == "NAV_TARGET_BLOCKED"
    assert result.final_robot_state["status"] == "target_blocked"


def test_auto_cancelled_blocked_navigation_returns_failed_with_metadata() -> None:
    client = FakeNavigationRosClient(
        action_result=NavigateToPoseActionResult(
            result_code=2,
            result_message="导航取消",
            result_pose={},
            uuid="nav-auto-cancel",
            nav_status_code=1006,
            nav_description="NAV_PATH_IS_BLOCKED",
            raw={
                "auto_cancelled": True,
                "auto_cancel_trigger_code": 1006,
            },
        )
    )
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="front_workspace",
        table_color="",
    )

    assert result.status == "failed"
    assert result.final_robot_state["error_code"] == "NAVIGATION_BLOCKED"
    assert result.final_robot_state["auto_cancelled"] is True
    assert result.final_robot_state["auto_cancel_trigger_code"] == 1006


def test_cancelled_action_returns_cancelled_status() -> None:
    client = FakeNavigationRosClient(
        action_result=NavigateToPoseActionResult(
            result_code=2,
            result_message="导航取消",
            result_pose={},
            uuid="nav-cancelled",
            nav_status_code=1004,
            nav_description="NAV_CALCLED",
        )
    )
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="front_workspace",
        table_color="",
    )

    assert result.status == "cancelled"
    assert result.final_robot_state["error_code"] == "NAVIGATION_CANCELLED"


def test_client_timeout_returns_timeout_status() -> None:
    class TimeoutClient(FakeNavigationRosClient):
        def send_navigate_to_pose(
            self,
            goal: dict[str, Any],
            *,
            timeout_s: float,
            request_id: str = "",
        ) -> NavigateToPoseActionResult:
            self.sent_goals.append(
                {"goal": goal, "timeout_s": timeout_s, "request_id": request_id}
            )
            raise TimeoutError("navigation timed out")

    client = TimeoutClient()
    client.occupancy_grid = _free_grid()
    adapter = RosTopicNavigationAdapter(ros_client=client, workspace_resolver=_resolver())

    result = adapter.navigate_to_workspace(
        request_id="req-nav-test",
        workspace_type="front_workspace",
        table_color="",
    )

    assert result.status == "timeout"
    assert result.message == "navigation timed out"
    assert result.final_robot_state["error_code"] == "NAVIGATION_TIMEOUT"
