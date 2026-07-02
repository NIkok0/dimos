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
from py_rosbridge.codecs import geometry_msgs, std_msgs

from dimos.agents.rosbridge.codecs.robot_interfaces import (
    NavStatus,
    NavStatusCodec,
    NavigateToPoseFeedback,
    NavigateToPoseFeedbackCodec,
    NavigateToPoseGoal,
    NavigateToPoseGoalCodec,
    NavigateToPoseResult,
    NavigateToPoseResultCodec,
    SlamStatus,
    SlamStatusCodec,
    TYPE_REGISTRY,
)


def test_slam_status_codec_round_trips_real_robot_interface() -> None:
    msg = SlamStatus(
        header=std_msgs.Header(frame_id="map"),
        status="located",
        current_map_name="",
        pose=geometry_msgs.Pose(
            position=geometry_msgs.Point(x=1.0, y=2.0, z=0.0),
            orientation=geometry_msgs.Quaternion(w=1.0),
        ),
        score=0.95,
        process=100.0,
        expect_time=0.0,
        relocated=True,
        reloc_used_time=1.25,
        opt_works_remain=2,
        angle=0.1,
    )

    decoded = SlamStatusCodec.decode(SlamStatusCodec.encode(msg))

    assert decoded.header == msg.header
    assert decoded.status == "located"
    assert decoded.current_map_name == ""
    assert decoded.pose == msg.pose
    assert decoded.score == pytest.approx(0.95)
    assert decoded.process == pytest.approx(100.0)
    assert decoded.relocated is True
    assert decoded.opt_works_remain == 2
    assert decoded.angle == pytest.approx(0.1)


def test_nav_status_codec_round_trips_real_robot_interface() -> None:
    msg = NavStatus(
        timestamp=123.5,
        status_code=1003,
        description="navigation success",
        uuid=bytes([1, 2, 3, 4]),
    )

    decoded = NavStatusCodec.decode(NavStatusCodec.encode(msg))

    assert decoded.timestamp == pytest.approx(123.5)
    assert decoded.status_code == 1003
    assert decoded.description == "navigation success"
    assert decoded.uuid == bytes([1, 2, 3, 4])


def test_navigate_to_pose_action_codecs_round_trip_real_robot_interface() -> None:
    goal = NavigateToPoseGoal(
        pose=geometry_msgs.PoseStamped(
            header=std_msgs.Header(frame_id="map"),
            pose=geometry_msgs.Pose(
                position=geometry_msgs.Point(x=1.0, y=2.0, z=0.0),
                orientation=geometry_msgs.Quaternion(w=1.0),
            ),
        ),
        behavior_tree="",
    )
    result = NavigateToPoseResult(
        result_code=0,
        result_message="导航成功",
        result_pose=goal.pose,
    )
    feedback = NavigateToPoseFeedback(
        current_pose=goal.pose,
        distance_remaining=0.5,
        speed=0.2,
        navigation_state=1002,
        navigation_state_description="NAV_MOVING",
        uuid=bytes([9, 8, 7]),
    )

    assert NavigateToPoseGoalCodec.decode(NavigateToPoseGoalCodec.encode(goal)) == goal
    assert NavigateToPoseResultCodec.decode(NavigateToPoseResultCodec.encode(result)) == result
    decoded_feedback = NavigateToPoseFeedbackCodec.decode(NavigateToPoseFeedbackCodec.encode(feedback))
    assert decoded_feedback.current_pose == feedback.current_pose
    assert decoded_feedback.distance_remaining == pytest.approx(0.5)
    assert decoded_feedback.speed == pytest.approx(0.2)
    assert decoded_feedback.navigation_state == 1002
    assert decoded_feedback.uuid == bytes([9, 8, 7])
    goal_fields = {field.name for field in NavigateToPoseGoalCodec.fields}
    feedback_fields = {field.name for field in NavigateToPoseFeedbackCodec.fields}
    assert goal_fields == {"pose", "behavior_tree"}
    assert feedback_fields == {
        "current_pose",
        "navigation_time",
        "estimated_time_remaining",
        "distance_remaining",
        "speed",
        "navigation_state",
        "navigation_state_description",
        "uuid",
    }


def test_robot_interfaces_registry_is_separate_from_dax_dimos_services() -> None:
    assert TYPE_REGISTRY["robot_interfaces/msg/SlamStatus"] is SlamStatusCodec
    assert TYPE_REGISTRY["robot_interfaces/msg/NavStatus"] is NavStatusCodec
    assert TYPE_REGISTRY["robot_interfaces/action/NavigateToPose/Goal"] is NavigateToPoseGoalCodec
    assert TYPE_REGISTRY["robot_interfaces/action/NavigateToPose/Result"] is NavigateToPoseResultCodec
    assert TYPE_REGISTRY["robot_interfaces/action/NavigateToPose/Feedback"] is (
        NavigateToPoseFeedbackCodec
    )
    assert all(not key.startswith("dax_dimos_interfaces/") for key in TYPE_REGISTRY)
