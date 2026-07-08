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

"""Load DimOS-side atomic skill orchestration configs (YAML)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from dimos.agents.dax_atomic_skill_client import AtomicSkillStep


def resolve_orchestration_config_path(path_str: str) -> Path | None:
    """Resolve orchestration YAML relative to cwd, then repo/install root."""
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


def load_go_home_steps(path: Path) -> list[AtomicSkillStep]:
    """Load go_home atomic steps from a DimOS orchestration YAML file."""
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root must be a mapping")
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ValueError(f"{path}: steps must be a non-empty list")

    steps: list[AtomicSkillStep] = []
    for index, item in enumerate(steps_raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: steps[{index}] must be a mapping")
        name = str(item.get("name") or f"step_{index + 1}")
        skill = str(item.get("skill") or "")
        params = item.get("params")
        if not skill:
            raise ValueError(f"{path}: steps[{index}] missing skill")
        if not isinstance(params, dict):
            raise ValueError(f"{path}: steps[{index}] params must be a mapping")
        steps.append(AtomicSkillStep(name=name, skill=skill, params=dict(params)))
    return steps


def default_go_home_steps() -> list[AtomicSkillStep]:
    """Built-in go_home sequence when no YAML is configured."""
    return [
        AtomicSkillStep(
            name="go_home_body_dual",
            skill="joint_move",
            params={
                "group": "body_dual",
                "target": [0.0] * 18,
                "dt": 0.01,
            },
        )
    ]


def load_go_home_steps_from_env(path_str: str) -> list[AtomicSkillStep]:
    """Load go_home steps from config path or fall back to defaults."""
    resolved = resolve_orchestration_config_path(path_str)
    if resolved is None:
        return default_go_home_steps()
    return load_go_home_steps(resolved)


__all__ = [
    "load_go_home_steps",
    "load_go_home_steps_from_env",
    "resolve_orchestration_config_path",
    "default_go_home_steps",
]
