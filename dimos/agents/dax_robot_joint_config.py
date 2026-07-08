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

"""Load per-robot joint pose config for DaxJointControlSkill (YAML)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_WAVE_HOME_LEFT: list[float] = [
    0.49968776484597655,
    0.34976398209966364,
    0.0,
    -1.4997614262387273,
    0.0,
    -0.4497713482389387,
    0.2,
]
_DEFAULT_WAVE_HOME_RIGHT: list[float] = [
    -1.11065948,
    -0.9408707,
    0.0107924733,
    -2.14151549,
    -1.30853546,
    0.09318465,
    -0.119986169,
]
_DEFAULT_WAVE_REST_RIGHT: list[float] = [
    0.49968776484597655,
    -0.34976398209966364,
    0.0,
    -1.4997614262387273,
    0.0,
    -0.4497713482389387,
    0.2,
]
_DEFAULT_HEAD_ACCEPT: list[list[float]] = [
    [0.0, 0.5],
    [0.0, 0.0],
    [0.0, 0.5],
    [0.0, 0.0],
]
_DEFAULT_HEAD_REJECT: list[list[float]] = [
    [0.5, 0.0],
    [0.0, 0.0],
    [-0.5, 0.0],
    [0.0, 0.0],
]


@dataclass(frozen=True)
class DaxWaveJointConfig:
    home_left: list[float]
    home_right: list[float]
    rest_right: list[float]
    start_index: int
    send_count: int
    send_interval: float
    move_dt: float


@dataclass(frozen=True)
class DaxHeadJointConfig:
    accept_steps: list[list[float]]
    reject_steps: list[list[float]]
    time_from_start_s: float


@dataclass(frozen=True)
class DaxRobotJointConfig:
    wave: DaxWaveJointConfig
    head: DaxHeadJointConfig


def default_dax_robot_joint_config() -> DaxRobotJointConfig:
    """Built-in defaults (X7Pro-style poses) when no YAML is configured."""
    return DaxRobotJointConfig(
        wave=DaxWaveJointConfig(
            home_left=list(_DEFAULT_WAVE_HOME_LEFT),
            home_right=list(_DEFAULT_WAVE_HOME_RIGHT),
            rest_right=list(_DEFAULT_WAVE_REST_RIGHT),
            start_index=150,
            send_count=200,
            send_interval=0.01,
            move_dt=0.01,
        ),
        head=DaxHeadJointConfig(
            accept_steps=[list(step) for step in _DEFAULT_HEAD_ACCEPT],
            reject_steps=[list(step) for step in _DEFAULT_HEAD_REJECT],
            time_from_start_s=1.0,
        ),
    )


def resolve_dax_robot_joint_config_path(path_str: str) -> Path | None:
    """Resolve config path relative to cwd, then repo/install root."""
    if not path_str.strip():
        return None
    path = Path(path_str)
    if path.is_file():
        return path
    if not path.is_absolute():
        for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
            candidate = base / path
            if candidate.is_file():
                return candidate
    return path if path.is_file() else None


def _as_float_list(value: Any, *, field: str, size: int | None = None) -> list[float]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    out = [float(v) for v in value]
    if size is not None and len(out) != size:
        raise ValueError(f"{field} must have length {size}, got {len(out)}")
    return out


def _as_head_steps(value: Any, *, field: str) -> list[list[float]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list of [head0, head1] pairs")
    steps: list[list[float]] = []
    for index, step in enumerate(value):
        if not isinstance(step, list) or len(step) != 2:
            raise ValueError(f"{field}[{index}] must be [head_joint0, head_joint1]")
        steps.append([float(step[0]), float(step[1])])
    return steps


def load_dax_robot_joint_config(path: Path) -> DaxRobotJointConfig:
    """Load robot joint config from YAML, merging missing keys with defaults."""
    defaults = default_dax_robot_joint_config()
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root must be a mapping")

    wave_raw = raw.get("wave") if isinstance(raw.get("wave"), dict) else {}
    head_raw = raw.get("head") if isinstance(raw.get("head"), dict) else {}

    wave = DaxWaveJointConfig(
        home_left=_as_float_list(
            wave_raw.get("home_left", defaults.wave.home_left),
            field="wave.home_left",
            size=7,
        ),
        home_right=_as_float_list(
            wave_raw.get("home_right", defaults.wave.home_right),
            field="wave.home_right",
            size=7,
        ),
        rest_right=_as_float_list(
            wave_raw.get("rest_right", defaults.wave.rest_right),
            field="wave.rest_right",
            size=7,
        ),
        start_index=int(wave_raw.get("start_index", defaults.wave.start_index)),
        send_count=int(wave_raw.get("send_count", defaults.wave.send_count)),
        send_interval=float(wave_raw.get("send_interval", defaults.wave.send_interval)),
        move_dt=float(wave_raw.get("move_dt", defaults.wave.move_dt)),
    )
    head = DaxHeadJointConfig(
        accept_steps=_as_head_steps(
            head_raw.get("accept_steps", defaults.head.accept_steps),
            field="head.accept_steps",
        ),
        reject_steps=_as_head_steps(
            head_raw.get("reject_steps", defaults.head.reject_steps),
            field="head.reject_steps",
        ),
        time_from_start_s=float(head_raw.get("time_from_start_s", defaults.head.time_from_start_s)),
    )
    return DaxRobotJointConfig(wave=wave, head=head)


def load_dax_robot_joint_config_from_env(path_str: str) -> DaxRobotJointConfig:
    """Load from ``DAX_ROBOT_JOINT_CONFIG_PATH`` or fall back to built-in defaults."""
    resolved = resolve_dax_robot_joint_config_path(path_str)
    if resolved is None:
        return default_dax_robot_joint_config()
    return load_dax_robot_joint_config(resolved)


__all__ = [
    "DaxHeadJointConfig",
    "DaxRobotJointConfig",
    "DaxWaveJointConfig",
    "default_dax_robot_joint_config",
    "load_dax_robot_joint_config",
    "load_dax_robot_joint_config_from_env",
    "resolve_dax_robot_joint_config_path",
]
