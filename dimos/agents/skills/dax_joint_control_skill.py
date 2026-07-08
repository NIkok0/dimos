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
from pathlib import Path

from dimos.agents.annotation import skill
from dimos.agents.dax_robot_joint_config import (
    DaxRobotJointConfig,
    default_dax_robot_joint_config,
    load_dax_robot_joint_config_from_env,
)
from dimos.agents.skills.dax_joint_request_client import DaxJointRequestClient
from dimos.core.core import rpc
from dimos.core.global_config import global_config
from dimos.core.module import Module
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

# Backward-compatible module constants (defaults for tests / imports).
_DEFAULTS = default_dax_robot_joint_config()
HEAD_REJECT_STEPS: list[list[float]] = [list(s) for s in _DEFAULTS.head.reject_steps]
HEAD_ACCEPT_STEPS: list[list[float]] = [list(s) for s in _DEFAULTS.head.accept_steps]
WAVE_HOME_LEFT: list[float] = list(_DEFAULTS.wave.home_left)
WAVE_HOME_RIGHT: list[float] = list(_DEFAULTS.wave.home_right)
WAVE_REST_RIGHT: list[float] = list(_DEFAULTS.wave.rest_right)

_HEAD_GESTURE_LABEL: dict[str, str] = {"accept": "点头", "reject": "摇头"}
_HEAD_GESTURE_SUCCESS: dict[str, str] = {
    "accept": "好的，我点了一下头",
    "reject": "我摇了摇头，这个任务我做不了",
}
_HEAD_CLIENT_NOT_READY = "抱歉，机械臂服务还没连上，没法做头部动作"


class DaxJointControlSkill(Module):
    _client: DaxJointRequestClient | None = None
    _joint_config: DaxRobotJointConfig | None = None

    @rpc
    def start(self) -> None:
        super().start()
        cfg = self.config.g
        self._client = DaxJointRequestClient(
            url=cfg.dax_joint_server_url,
            timeout=cfg.dax_joint_request_timeout_s,
        )
        self._joint_config = load_dax_robot_joint_config_from_env(cfg.dax_robot_joint_config_path)
        logger.info(
            "DaxJointControlSkill connected to %s joint_config=%s",
            cfg.dax_joint_server_url,
            cfg.dax_robot_joint_config_path or "(defaults)",
        )

    @rpc
    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._joint_config = None
        super().stop()

    def _joint_config_or_default(self) -> DaxRobotJointConfig:
        if self._joint_config is not None:
            return self._joint_config
        return default_dax_robot_joint_config()

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
        """Load the wave keyframe JSON configured in GlobalConfig."""
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
        if self._client is None:
            return "抱歉，挥手动作没能完成，机械臂服务可能没启动"

        wave_cfg = self._joint_config_or_default().wave
        end_index = min(start_index + send_count, len(positions))
        selected_positions = positions[start_index:end_index]
        if not selected_positions:
            return "抱歉，挥手动画帧范围无效"

        try:
            self._client.move_dual_joints(
                wave_cfg.home_left,
                wave_cfg.home_right,
                dt=wave_cfg.move_dt,
            )
        except Exception:
            logger.exception("wave home failed")
            return "抱歉，挥手动作没能完成，机械臂服务可能没启动"

        logger.info(
            "wave frames total=%d range=%d..%d send=%d",
            len(positions),
            start_index,
            end_index - 1,
            len(selected_positions),
        )

        import time

        for index, right_arm_positions in enumerate(selected_positions, start=start_index):
            try:
                self._client.servo_dual_joints(wave_cfg.home_left, right_arm_positions)
            except Exception:
                logger.exception("wave servo failed at index %s", index)
                return "抱歉，挥手动作没能完成，机械臂服务可能没启动"
            time.sleep(send_interval)

        try:
            self._client.move_dual_joints(
                wave_cfg.home_left,
                wave_cfg.rest_right,
                dt=wave_cfg.move_dt,
            )
        except Exception:
            logger.exception("wave rest failed")
            return "抱歉，挥手动作没能完成，机械臂服务可能没启动"

        logger.info(
            "wave streamed %d frames (%d..%d)",
            len(selected_positions),
            start_index,
            end_index - 1,
        )
        return "你好！我跟你挥了挥手"

    @skill
    def wave(
        self,
        start_index: int | None = None,
        send_count: int | None = None,
        send_interval: float | None = None,
    ) -> str:
        """Make the robot wave its right arm.

        Use this only for a simple greeting gesture, for example when the user
        says hello or asks the robot to wave. For navigation, picking, carrying,
        or placing tasks, use `execute_nl_task` instead.

        Args:
            start_index: Animation frame to start from. Omit to use robot config default.
            send_count: Number of animation frames to send. Omit to use robot config default.
            send_interval: Seconds between frames. Omit to use robot config default.
        """
        wave_cfg = self._joint_config_or_default().wave
        loaded = self._load_wave_positions()
        if isinstance(loaded, str):
            return loaded
        return self._run_wave_sequence(
            loaded,
            start_index=start_index if start_index is not None else wave_cfg.start_index,
            send_count=send_count if send_count is not None else wave_cfg.send_count,
            send_interval=send_interval if send_interval is not None else wave_cfg.send_interval,
        )

    @skill
    def head_reject(self, time_from_start: float | None = None) -> str:
        """Make the robot shake its head to reject a request.

        Use this when routing would return ``unsupported_intent`` — the request
        is clearly impossible, unsafe, or outside the robot's abilities. Do not
        use when the task is ``need_clarification``; ask the user instead. For
        tasks that may be possible, use ``execute_nl_task``.

        Args:
            time_from_start: Motion duration for each head waypoint in seconds.
                Omit to use robot config default.
        """
        head_cfg = self._joint_config_or_default().head
        return self._run_head_sequence(
            head_cfg.reject_steps,
            gesture_name="reject",
            time_from_start=time_from_start
            if time_from_start is not None
            else head_cfg.time_from_start_s,
        )

    @skill
    def head_accept(self, time_from_start: float | None = None) -> str:
        """Make the robot nod to acknowledge obedience.

        Call when the user gives a followable instruction (task, cancel, stop,
        or change of plan). This is an obedience signal — it does not mean the
        task succeeded. For navigation, picking, or placing, call
        ``execute_nl_task``.

        Args:
            time_from_start: Motion duration for each head waypoint in seconds.
                Omit to use robot config default.
        """
        head_cfg = self._joint_config_or_default().head
        return self._run_head_sequence(
            head_cfg.accept_steps,
            gesture_name="accept",
            time_from_start=time_from_start
            if time_from_start is not None
            else head_cfg.time_from_start_s,
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
