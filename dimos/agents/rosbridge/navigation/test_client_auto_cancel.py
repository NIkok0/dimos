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

from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

import pytest
from py_rosbridge.codecs import geometry_msgs, std_msgs

from dimos.agents.rosbridge.codecs.robot_interfaces import NavStatus
from dimos.agents.rosbridge.navigation.client import PyRosbridgeNavigationRosClient


class _FakeActionGoalHandle:
    def __init__(self) -> None:
        self._result_future: Future[Any] = Future()
        self.cancel_calls = 0

    def cancel(self, *, timeout: float | None = None) -> SimpleNamespace:
        self.cancel_calls += 1
        if not self._result_future.done():
            self._complete_cancelled()
        return SimpleNamespace(accepted=True, message="")

    def result(self, timeout: float | None = None) -> Any:
        return self._result_future.result(timeout=timeout)

    def _complete_cancelled(self) -> None:
        result_pose = geometry_msgs.PoseStamped(
            header=std_msgs.Header(frame_id="map"),
            pose=geometry_msgs.Pose(
                position=geometry_msgs.Point(x=0.0, y=0.0, z=0.0),
                orientation=geometry_msgs.Quaternion(w=1.0),
            ),
        )
        self._result_future.set_result(
            SimpleNamespace(
                goal_id="goal-123",
                action="/navigate_to_pose",
                type="robot_interfaces/action/NavigateToPose",
                status=2,
                result=SimpleNamespace(
                    result_code=2,
                    result_message="导航取消",
                    result_pose=result_pose,
                ),
            )
        )


class _StaticRosbridgeSession:
    target = "test-target:9091"

    def __init__(self, client: Any) -> None:
        self._client = client

    def get_client(self) -> Any:
        return self._client


class _RecordingRosbridgeClient:
    def __init__(self, handle: _FakeActionGoalHandle) -> None:
        self._handle = handle

    def send_action_goal(self, *args: Any, **kwargs: Any) -> _FakeActionGoalHandle:
        return self._handle


def _client(
    *,
    auto_cancel_enabled: bool = True,
    auto_cancel_status_codes: frozenset[int] | None = None,
) -> PyRosbridgeNavigationRosClient:
    return PyRosbridgeNavigationRosClient(
        session=_StaticRosbridgeSession(_RecordingRosbridgeClient(_FakeActionGoalHandle())),  # type: ignore[arg-type]
        slam_status_topic="/slam_status",
        slam_status_topic_type="robot_interfaces/msg/SlamStatus",
        map_topic="/map",
        map_topic_type="nav_msgs/msg/OccupancyGrid",
        nav_status_topic="/navigation_current_status",
        nav_status_topic_type="robot_interfaces/msg/NavStatus",
        navigate_action="/navigate_to_pose",
        navigate_action_type="robot_interfaces/action/NavigateToPose",
        timeout_s=5.0,
        topic_timeout_s=0.01,
        auto_cancel_enabled=auto_cancel_enabled,
        auto_cancel_status_codes=auto_cancel_status_codes,
        auto_cancel_poll_s=0.01,
        auto_cancel_wait_s=1.0,
    )


def _inject_nav_status(client: PyRosbridgeNavigationRosClient, *, status_code: int) -> None:
    client._nav_status_messages.put_nowait(  # noqa: SLF001
        NavStatus(status_code=status_code, description=f"code={status_code}")
    )


@pytest.mark.parametrize("status_code", [1005, 1006, 1007])
def test_wait_for_action_result_auto_cancels_on_configured_codes(status_code: int) -> None:
    handle = _FakeActionGoalHandle()
    client = _client()
    _inject_nav_status(client, status_code=status_code)

    event, trigger = client._wait_for_action_result(  # noqa: SLF001
        handle,
        timeout_s=1.0,
        request_id="req-1",
        goal_log={"workspace_id": "front"},
    )

    assert handle.cancel_calls == 1
    assert trigger == {"status_code": status_code, "description": f"code={status_code}"}
    assert event.result.result_code == 2


def test_wait_for_action_result_does_not_cancel_on_moving_status() -> None:
    handle = _FakeActionGoalHandle()
    client = _client()
    _inject_nav_status(client, status_code=1002)
    handle._complete_cancelled()

    event, trigger = client._wait_for_action_result(  # noqa: SLF001
        handle,
        timeout_s=1.0,
        request_id="req-1",
        goal_log={"workspace_id": "front"},
    )

    assert handle.cancel_calls == 0
    assert trigger is None
    assert event.result.result_code == 2


def test_wait_for_action_result_respects_disabled_auto_cancel() -> None:
    handle = _FakeActionGoalHandle()
    client = _client(auto_cancel_enabled=False)
    _inject_nav_status(client, status_code=1006)
    handle._complete_cancelled()

    event, trigger = client._wait_for_action_result(  # noqa: SLF001
        handle,
        timeout_s=1.0,
        request_id="req-1",
        goal_log={"workspace_id": "front"},
    )

    assert handle.cancel_calls == 0
    assert trigger is None


def test_send_navigate_to_pose_returns_auto_cancel_metadata() -> None:
    handle = _FakeActionGoalHandle()
    rosbridge = _RecordingRosbridgeClient(handle)
    client = PyRosbridgeNavigationRosClient(
        session=_StaticRosbridgeSession(rosbridge),  # type: ignore[arg-type]
        slam_status_topic="/slam_status",
        slam_status_topic_type="robot_interfaces/msg/SlamStatus",
        map_topic="/map",
        map_topic_type="nav_msgs/msg/OccupancyGrid",
        nav_status_topic="/navigation_current_status",
        nav_status_topic_type="robot_interfaces/msg/NavStatus",
        navigate_action="/navigate_to_pose",
        navigate_action_type="robot_interfaces/action/NavigateToPose",
        timeout_s=2.0,
        topic_timeout_s=0.01,
        auto_cancel_poll_s=0.01,
        auto_cancel_wait_s=1.0,
    )
    client._subscribed = True  # noqa: SLF001
    _inject_nav_status(client, status_code=1006)

    result = client.send_navigate_to_pose(
        {
            "pose": {"frame_id": "map", "x": 1.0, "y": 0.0, "yaw": 0.0},
            "behavior_tree": "",
            "workspace_id": "front_workspace",
        },
        timeout_s=2.0,
        request_id="req-auto-cancel",
    )

    assert handle.cancel_calls == 1
    assert result.nav_status_code == 1006
    assert result.raw["auto_cancelled"] is True
    assert result.raw["auto_cancel_trigger_code"] == 1006
