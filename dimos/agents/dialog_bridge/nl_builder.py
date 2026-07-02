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

"""Build natural-language task strings from structured Dialog MCP parameters."""

from __future__ import annotations

from typing import Literal

from dimos.agents.nl.navigation_semantic_mapper import get_navigation_semantic_mapper

RelativeDirection = Literal["forward", "backward", "left", "right"]
WorkspaceName = Literal["front_workspace", "table"]


def build_move_relative_nl(direction: str, distance_meters: float) -> str:
    """Return NL aligned with navigation semantic catalog templates."""
    if direction not in {"forward", "backward", "left", "right"}:
        raise ValueError(
            f"direction must be one of ['backward', 'forward', 'left', 'right']; "
            f"got {direction!r}"
        )
    if distance_meters <= 0:
        raise ValueError("distance_meters must be positive")

    mapper = get_navigation_semantic_mapper()
    distance_units = distance_meters / 0.05
    return mapper.build_canonical_nl(
        "move_relative",
        {"direction": direction, "distance_units": distance_units},
    )


def build_move_to_workspace_nl(workspace_name: str, workspace_color: str = "") -> str:
    """Return NL aligned with navigation semantic catalog templates."""
    if workspace_name not in {"front_workspace", "table"}:
        raise ValueError(
            "workspace_name must be 'front_workspace' or 'table'; "
            f"got {workspace_name!r}"
        )
    color = workspace_color.strip()
    if workspace_name == "table" and not color:
        raise ValueError("workspace_color is required when workspace_name is 'table'")

    mapper = get_navigation_semantic_mapper()
    return mapper.build_canonical_nl(
        "move_to_workspace",
        {
            "workspace_name": workspace_name,
            "workspace_color": color,
        },
    )


__all__ = [
    "RelativeDirection",
    "WorkspaceName",
    "build_move_relative_nl",
    "build_move_to_workspace_nl",
]
