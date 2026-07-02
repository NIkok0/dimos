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

"""Head gesture and arm wave skills backed by dax_server HTTP joint control."""

from __future__ import annotations

import json
import time
from pathlib import Path

from dimos.agents.annotation import skill
from dimos.agents.skills.dax_joint_request_client import DaxJointRequestClient
from dimos.core.core import rpc
from dimos.core.global_config import global_config
from dimos.core.module import Module
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

# [head_joint0, head_joint1] waypoints for impossible-task refusal (reject).
HEAD_REJECT_STEPS: list[list[float]] = [
    [0.5, 0.0],
    [0.0, 0.0],
    [-0.5, 0.0],
    [0.0, 0.0],
]

# [head_joint0, head_joint1] waypoints for obedience acknowledgment (accept).
HEAD_ACCEPT_STEPS: list[list[float]] = [
    [0.0, 0.5],
    [0.0, 0.0],
    [0.0, 0.5],
    [0.0, 0.0],
]

# 7-DOF arm poses for the wave animation (mirrored from scripts/robot_arm_move.py).
WAVE_HOME_LEFT: list[float] = [
    0.49968776484597655,
    0.34976398209966364,
    0.0,
    -1.4997614262387273,
    0.0,
    -0.4497713482389387,
    0.2,
]
WAVE_HOME_RIGHT: list[float] = [
    -1.11065948,
    -0.9408707,
    0.0107924733,
    -2.14151549,
    -1.30853546,
    0.09318465,
    -0.119986169,
]
WAVE_REST_RIGHT: list[float] = [
    0.49968776484597655,
    -0.34976398209966364,
    0.0,
    -1.4997614262387273,
    0.0,
    -0.4497713482389387,
    0.2,
]

_DEFAULT_WAVE_START_INDEX = 150
_DEFAULT_WAVE_SEND_COUNT = 200
_DEFAULT_WAVE_SEND_INTERVAL = 0.01

# Chinese labels + success lines for head gestures (keyed by gesture_name).
_HEAD_GESTURE_LABEL: dict[str, str] = {"accept": "点头", "reject": "摇头"}
_HEAD_GESTURE_SUCCESS: dict[str, str] = {
    "accept": "好的，我点了一下头",
    "reject": "我摇了摇头，这个任务我做不了",
}
_HEAD_CLIENT_NOT_READY = "抱歉，机械臂服务还没连上，没法做头部动作"


class DaxJointControlSkill(Module):
    _client: DaxJointRequestClient | None = None

    @rpc
    def start(self) -> None:
        super().start()
        cfg = self.config.g
        self._client = DaxJointRequestClient(
            url=cfg.dax_joint_server_url,
            timeout=cfg.dax_joint_request_timeout_s,
        )
        logger.info("DaxJointControlSkill connected to %s", cfg.dax_joint_server_url)

    @rpc
    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        super().stop()

    def _run_head_sequence(
        self,
        steps: list[list[float]],
        *,
        gesture_name: str,
        time_from_start: float,
    ) -> str:
        if self._client is None:
            return _HEAD_CLIENT_NOT_READY

        for index, heads in enumerate(steps, start=1):
            try:
                self._client.move_heads(heads, time_from_start=time_from_start)
            except Exception:
                logger.exception("head gesture %s failed at step %s", gesture_name, index)
                label = _HEAD_GESTURE_LABEL.get(gesture_name, gesture_name)
                return f"抱歉，{label}动作没能完成，机械臂服务可能没启动"

        return _HEAD_GESTURE_SUCCESS.get(
            gesture_name, f"完成了{_HEAD_GESTURE_LABEL.get(gesture_name, gesture_name)}动作"
        )

    def _load_wave_positions(self) -> list[list[float]] | str:
        """Load the wave keyframe JSON configured in GlobalConfig.

        Returns the positions list on success, or a Chinese error string when
        the path is unset, the file is missing, or the JSON is malformed.
        """
        path_str = global_config.dax_wave_animation_path
        if not path_str:
            return "抱歉，挥手动画文件没配置（需设置 DAX_WAVE_ANIMATION_PATH）"
        path = Path(path_str)
        if not path.is_file():
            return f"抱歉，挥手动画文件找不到：{path}"
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            return f"抱歉，挥手动画文件读不了：{exc}"
        positions = data.get("positions") if isinstance(data, dict) else None
        if not isinstance(positions, list) or not positions:
            return "抱歉，挥手动画文件格式不对，缺少 positions 列表"
        return positions

    def _run_wave_sequence(
        self,
        positions: list[list[float]],
        *,
        start_index: int,
        send_count: int,
        send_interval: float,
    ) -> str:

        JSON_PATH = Path("/home/miaoli/Projects/dimos/scripts/dax_hi_ani.json")
        START_INDEX = 150
        SEND_COUNT = 200
        SEND_INTERVAL = 0.01
        cfg = self.config.g
        client = DaxJointRequestClient(url=cfg.dax_joint_server_url,
            timeout=cfg.dax_joint_request_timeout_s,)

        # HOME
        left_arm_positions = [
            0.49968776484597655,
            0.34976398209966364,
            0.0,
            -1.4997614262387273,
            0.0,
            -0.4497713482389387,
            0.2,
        ]

        right_arm_positions = [-1.11065948, -0.9408707, 0.0107924733, -2.14151549, -1.30853546, 0.09318465, -0.119986169]

        try:
            client.move_dual_joints(left_arm_positions, right_arm_positions, dt=0.01)
        except Exception:
            logger.exception("wave home failed")
            return "抱歉，挥手动作没能完成，机械臂服务可能没启动"

        with JSON_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        positions = data["positions"]
        selected_positions = positions[START_INDEX : START_INDEX + SEND_COUNT]

        logger.info(
            "wave frames total=%d range=%d..%d send=%d",
            len(positions),
            START_INDEX,
            START_INDEX + len(selected_positions) - 1,
            len(selected_positions),
        )

        for index, right_arm_positions in enumerate(selected_positions, start=START_INDEX):
            try:
                client.servo_dual_joints(left_arm_positions, right_arm_positions)
            except Exception:
                logger.exception("wave servo failed at index %s", index)
                return "抱歉，挥手动作没能完成，机械臂服务可能没启动"
            time.sleep(SEND_INTERVAL)


        left_arm_positions = [
            0.49968776484597655,
            0.34976398209966364,
            0.0,
            -1.4997614262387273,
            0.0,
            -0.4497713482389387,
            0.2,
        ]

        right_arm_positions = [
            0.49968776484597655,
            -0.34976398209966364,
            0.0,
            -1.4997614262387273,
            0.0,
            -0.4497713482389387,
            0.2,]

        try:
            client.move_dual_joints(left_arm_positions, right_arm_positions, dt=0.01)
        except Exception:
            logger.exception("wave rest failed")
            return "抱歉，挥手动作没能完成，机械臂服务可能没启动"

        logger.info(
            "wave streamed %d frames (%d..%d)",
            len(selected_positions),
            START_INDEX,
            START_INDEX + len(selected_positions) - 1,
        )
        return "你好！我跟你挥了挥手"

    @skill
    def wave(
        self,
        start_index: int = _DEFAULT_WAVE_START_INDEX,
        send_count: int = _DEFAULT_WAVE_SEND_COUNT,
        send_interval: float = _DEFAULT_WAVE_SEND_INTERVAL,
    ) -> str:
        """Make the robot wave its right arm.

        Use this only for a simple greeting gesture, for example when the user
        says hello or asks the robot to wave. For navigation, picking, carrying,
        or placing tasks, use `execute_nl_task` instead.

        Args:
            start_index: Animation frame to start from. Usually keep the default.
            send_count: Number of animation frames to send. Usually keep the default.
            send_interval: Seconds between frames. Usually keep the default.
        """
        loaded = self._load_wave_positions()
        if isinstance(loaded, str):
            return loaded
        return self._run_wave_sequence(
            loaded,
            start_index=start_index,
            send_count=send_count,
            send_interval=send_interval,
        )

    @skill
    def head_reject(self, time_from_start: float = 1.0) -> str:
        """Make the robot shake its head to reject a request.

        Use this only when the user's request is clearly impossible, unsafe, or
        outside the robot's abilities. Do not use this when the task is merely
        unclear; ask the user a question instead. For complex robot tasks that
        may be possible, use `execute_nl_task`.

        Args:
            time_from_start: Motion duration for each head waypoint in seconds.
                Usually keep the default.
        """
        return self._run_head_sequence(
            HEAD_REJECT_STEPS,
            gesture_name="reject",
            time_from_start=time_from_start,
        )

    @skill
    def head_accept(self, time_from_start: float = 1.0) -> str:
        """Make the robot nod to acknowledge the user.

        Use this as a simple "I heard you" or "I will do that" gesture. This
        does not mean the task has succeeded. For the actual navigation,
        picking, carrying, or placing task, call `execute_nl_task`.

        Args:
            time_from_start: Motion duration for each head waypoint in seconds.
                Usually keep the default.
        """
        return self._run_head_sequence(
            HEAD_ACCEPT_STEPS,
            gesture_name="accept",
            time_from_start=time_from_start,
        )


dax_joint_control_skill = DaxJointControlSkill.blueprint

__all__ = [
    "DaxJointControlSkill",
    "HEAD_ACCEPT_STEPS",
    "HEAD_REJECT_STEPS",
    "WAVE_HOME_LEFT",
    "WAVE_HOME_RIGHT",
    "WAVE_REST_RIGHT",
    "dax_joint_control_skill",
]
