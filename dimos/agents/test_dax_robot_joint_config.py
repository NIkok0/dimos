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

from pathlib import Path

import pytest

from dimos.agents.dax_robot_joint_config import (
    default_dax_robot_joint_config,
    load_dax_robot_joint_config,
    load_dax_robot_joint_config_from_env,
    resolve_dax_robot_joint_config_path,
)


def test_default_config_has_wave_and_head() -> None:
    cfg = default_dax_robot_joint_config()
    assert len(cfg.wave.home_left) == 7
    assert len(cfg.head.accept_steps) >= 1
    assert cfg.wave.start_index == 150


def test_load_from_repo_yaml() -> None:
    path = resolve_dax_robot_joint_config_path("config/dax_robot_joint.yaml")
    assert path is not None
    cfg = load_dax_robot_joint_config(path)
    assert cfg.wave.send_count == 200
    assert cfg.head.time_from_start_s == 1.0


def test_load_from_env_missing_path_uses_defaults() -> None:
    cfg = load_dax_robot_joint_config_from_env("/nonexistent/robot.yaml")
    assert cfg.wave.start_index == default_dax_robot_joint_config().wave.start_index


def test_load_partial_yaml_merges_defaults(tmp_path: Path) -> None:
    yaml_path = tmp_path / "partial.yaml"
    yaml_path.write_text(
        "wave:\n  start_index: 42\nhead:\n  time_from_start_s: 0.5\n",
        encoding="utf-8",
    )
    cfg = load_dax_robot_joint_config(yaml_path)
    assert cfg.wave.start_index == 42
    assert cfg.wave.send_count == default_dax_robot_joint_config().wave.send_count
    assert cfg.head.time_from_start_s == 0.5


def test_invalid_arm_joint_length_raises(tmp_path: Path) -> None:
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text("wave:\n  home_left: [0.0, 0.1]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="wave.home_left"):
        load_dax_robot_joint_config(yaml_path)
