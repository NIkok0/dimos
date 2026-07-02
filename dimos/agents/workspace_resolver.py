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

"""Workspace catalog resolver for real navigation goals.

This module is the boundary between task slots and map-frame navigation poses.
It accepts only curated workspace records from a mapping or file, then performs
deterministic lookup by id, alias, or ``name + color``. It deliberately avoids
guessing coordinates from language so real navigation goals remain auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml

from dimos.agents.navigation_contracts import WorkspacePose


class WorkspaceResolutionError(ValueError):
    """Raised when a task workspace cannot be resolved to a known map pose."""


@dataclass(frozen=True)
class _WorkspaceRecord:
    """Internal normalized catalog row used to build deterministic lookup indexes."""

    pose: WorkspacePose
    aliases: tuple[str, ...] = ()


class WorkspaceResolver:
    """Resolve task-level workspace slots into curated map-frame poses."""

    def __init__(self, records: tuple[_WorkspaceRecord, ...]) -> None:
        self._records = records
        self._by_id: dict[str, WorkspacePose] = {}
        self._by_alias: dict[str, WorkspacePose] = {}
        self._by_name_color: dict[tuple[str, str], WorkspacePose] = {}

        # Build all lookup tables once so resolution is simple and predictable.
        for record in records:
            pose = record.pose
            self._by_id[self._key(pose.workspace_id)] = pose
            self._by_name_color[(self._key(pose.name), self._key(pose.color))] = pose
            for alias in record.aliases:
                self._by_alias[self._key(alias)] = pose

    @classmethod
    def from_mapping(cls, catalog: dict[str, dict[str, Any]]) -> WorkspaceResolver:
        """Build a resolver from an in-memory workspace catalog mapping."""
        records = tuple(_record_from_mapping(key, value) for key, value in catalog.items())
        return cls(records)

    @classmethod
    def from_file(cls, path: str | Path) -> WorkspaceResolver:
        """Build a resolver from a JSON or YAML workspace catalog file."""
        catalog_path = Path(path)
        text = catalog_path.read_text(encoding="utf-8")
        if catalog_path.suffix.lower() == ".json":
            data = json.loads(text)
        elif catalog_path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        else:
            raise WorkspaceResolutionError(
                f"unsupported workspace catalog format: {catalog_path.suffix}"
            )

        if not isinstance(data, dict):
            raise WorkspaceResolutionError("workspace catalog must be a mapping")
        return cls.from_mapping(data)

    def resolve(self, *, workspace_name: str, workspace_color: str = "") -> WorkspacePose:
        """Return the map-frame pose for a workspace id, alias, or name/color pair."""
        name_key = self._key(workspace_name)
        color_key = self._key(workspace_color)

        if name_key in self._by_id:
            return self._by_id[name_key]
        if name_key in self._by_alias:
            return self._by_alias[name_key]
        if (name_key, color_key) in self._by_name_color:
            return self._by_name_color[(name_key, color_key)]

        raise WorkspaceResolutionError(
            f"workspace not found: name={workspace_name!r}, color={workspace_color!r}"
        )

    @staticmethod
    def _key(value: str) -> str:
        """Normalize workspace lookup keys without changing their semantic content."""
        return value.strip().lower()


def _record_from_mapping(key: str, value: dict[str, Any]) -> _WorkspaceRecord:
    """Convert one raw catalog mapping into a normalized workspace record."""
    if not isinstance(value, dict):
        raise WorkspaceResolutionError(f"workspace {key!r} must be a mapping")

    workspace_id = str(value.get("workspace_id") or key)
    aliases_raw = value.get("aliases", ())
    if aliases_raw is None:
        aliases = ()
    elif isinstance(aliases_raw, list | tuple):
        aliases = tuple(str(alias) for alias in aliases_raw)
    else:
        raise WorkspaceResolutionError(f"workspace {workspace_id!r} aliases must be a list")

    try:
        pose = WorkspacePose(
            workspace_id=workspace_id,
            name=str(value["name"]),
            color=str(value["color"]),
            frame_id=str(value.get("frame_id", "map")),
            x=float(value["x"]),
            y=float(value["y"]),
            yaw=float(value["yaw"]),
        )
    except KeyError as exc:
        raise WorkspaceResolutionError(
            f"workspace {workspace_id!r} missing required field {exc.args[0]!r}"
        ) from exc

    return _WorkspaceRecord(pose=pose, aliases=aliases)


__all__ = [
    "WorkspaceResolutionError",
    "WorkspaceResolver",
]
