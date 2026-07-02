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

"""Bidirectional navigation NL ↔ canonical slot mapping."""

from __future__ import annotations

import re
from typing import Any

from dimos.agents.navigation_contracts import meters_to_relative_distance_units
from dimos.agents.nl.navigation_semantic_catalog import (
    NavigationSemanticCatalog,
    get_navigation_semantic_catalog,
)
from dimos.agents.skill_result import SkillResult

_METER_DISTANCE_RE = re.compile(
    r"(\d+(?:\.\d+)?)(?:m(?:eter|eters)?|米|公尺)",
    re.IGNORECASE,
)
_CN_NUM_UNIT_RE = re.compile(
    r"([一二两三四五六七八九十半]+)\s*(步|格|格子|格点|米|m|单位|个单位|块|段)",
)
_NUM_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(格|格子|步|单位|米|m)")
_BARE_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")


class NavigationSemanticMapper:
    """Maps NL fragments to canonical navigation slots using a catalog."""

    def __init__(self, catalog: NavigationSemanticCatalog) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> NavigationSemanticCatalog:
        return self._catalog

    def normalize_text(self, text: str) -> str:
        return (
            text.casefold()
            .replace(" ", "")
            .replace("　", "")
            .replace("'", "")
            .replace('"', "")
        )

    def has_any(self, text: str, needles: tuple[str, ...]) -> bool:
        normalized = self.normalize_text(text)
        return any(needle.casefold() in normalized for needle in needles)

    def is_move_like(self, text: str) -> bool:
        return self.has_any(text, self._catalog.movement_triggers)

    def is_object_task_like(self, text: str) -> bool:
        return self.has_any(text, self._catalog.object_task_exclusions)

    def has_workspace_alias(self, text: str) -> bool:
        return self.has_any(text, self._catalog.all_workspace_aliases())

    def should_suppress_relative_move(self, text: str) -> bool:
        for rule in self._catalog.conflict_rules:
            if rule.if_workspace_alias_present and rule.suppress_intent == "move_relative":
                if self.has_workspace_alias(text):
                    return True
        return False

    def normalize_direction(self, text: str) -> str | None:
        normalized = self.normalize_text(text)
        for direction in ("backward", "forward", "left", "right"):
            spec = self._catalog.directions[direction]
            for alias in sorted(spec.aliases, key=len, reverse=True):
                if alias.casefold() in normalized:
                    return direction
        return None

    def normalize_distance_units(self, text: str) -> float:
        meter_match = _METER_DISTANCE_RE.search(text)
        if meter_match is not None:
            return meters_to_relative_distance_units(float(meter_match.group(1)))

        cn_match = _CN_NUM_UNIT_RE.search(text)
        if cn_match is not None:
            cn_num = cn_match.group(1)
            unit = cn_match.group(2)
            value = float(self._catalog.distances.get(cn_num, 1.0))
            if unit in ("米", "m"):
                return meters_to_relative_distance_units(value)
            return value

        num_match = _NUM_UNIT_RE.search(text)
        if num_match is not None:
            value = float(num_match.group(1))
            unit = num_match.group(2)
            if unit in ("米", "m"):
                return meters_to_relative_distance_units(value)
            return value

        bare_match = _BARE_NUMBER_RE.search(text)
        if bare_match is not None:
            return float(bare_match.group(1))

        normalized = self.normalize_text(text)
        for token, value in sorted(
            self._catalog.distances.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if token in text or token in normalized:
                return value

        return 1.0

    def mentions_number(self, text: str) -> bool:
        return any(ch.isdigit() for ch in text) or self.has_any(
            text,
            tuple(self._catalog.distances.keys()),
        )

    def normalize_color(self, text: str, *, exclude: set[str] | None = None) -> str | None:
        colors = self.extract_colors_in_order(text)
        exclude = exclude or set()
        for color in colors:
            if color not in exclude:
                return color
        return None

    def extract_colors_in_order(self, text: str) -> list[str]:
        normalized = self.normalize_text(text)
        positions: list[tuple[int, str, int]] = []
        for color, spec in self._catalog.colors.items():
            for alias in sorted(spec.aliases, key=len, reverse=True):
                start = 0
                while True:
                    found = normalized.find(alias.casefold(), start)
                    if found < 0:
                        break
                    end = found + len(alias)
                    overlaps = any(
                        existing_start < end and found < existing_end
                        for existing_start, _, existing_end in positions
                    )
                    if not overlaps:
                        positions.append((found, color, end))
                    start = found + len(alias)
        return [color for _, color, _ in sorted(positions)]

    def extract_loop_count(self, text: str) -> int | None:
        normalized = self.normalize_text(text)
        for token, value in sorted(
            self._catalog.loop_counts.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if token.casefold() in normalized or token in text:
                return value
        return None

    def normalize_loop_count(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value if value >= 1 else None
        if isinstance(value, float):
            iv = int(value)
            return iv if iv >= 1 else None
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        return self.extract_loop_count(text)

    def _normalize_color_value(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        normalized = self.normalize_text(text)
        for color, spec in self._catalog.colors.items():
            if color == normalized or color == text.lower():
                return color
            for alias in spec.aliases:
                if alias.casefold() == normalized or alias == text:
                    return color
        return text.lower()

    def _normalize_sku_name(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        normalized = self.normalize_text(text)
        for sku_name, spec in self._catalog.skus.items():
            if sku_name == normalized or sku_name == text.lower():
                return sku_name
            for alias in spec.aliases:
                if alias.casefold() == normalized or alias == text:
                    return sku_name
        return text.lower()

    def normalize_llm_slots(
        self,
        intent_type: str,
        slots: dict[str, Any],
        *,
        raw_text: str = "",
    ) -> dict[str, Any]:
        result = dict(slots)

        if intent_type == "move_relative":
            direction = result.get("direction")
            if direction:
                normalized_dir = self.normalize_direction(str(direction))
                if normalized_dir:
                    result["direction"] = normalized_dir
            if "distance_meters" in result and "distance_units" not in result:
                result["distance_units"] = meters_to_relative_distance_units(
                    float(result.pop("distance_meters"))
                )
            elif "distance_units" not in result and raw_text:
                if self.mentions_number(raw_text):
                    result["distance_units"] = self.normalize_distance_units(raw_text)
            if raw_text:
                result["raw_distance_mentioned"] = self.mentions_number(raw_text)

        elif intent_type == "move_to_workspace":
            ws_name = result.get("workspace_name", "")
            ws_color = result.get("workspace_color", "")
            if not ws_name and raw_text:
                inferred_name, inferred_color = self.normalize_workspace(raw_text)
                if inferred_name:
                    result["workspace_name"] = inferred_name
                    if inferred_color:
                        result["workspace_color"] = inferred_color
            if result.get("workspace_color"):
                result["workspace_color"] = self._normalize_color_value(
                    result["workspace_color"]
                )
            spec = self._catalog.workspaces.get(str(result.get("workspace_name", "")))
            if spec is not None and not spec.requires_color:
                result["workspace_color"] = ""

        elif intent_type == "pick_sku":
            result = {
                "workspace_name": str(
                    result.get("workspace_name")
                    or result.get("workspace_type")
                    or ""
                ),
                "workspace_color": self._normalize_color_value(
                    result.get("workspace_color") or result.get("table_color")
                ),
                "sku_name": self._normalize_sku_name(
                    result.get("sku_name") or result.get("object_type") or ""
                ),
                "sku_color": self._normalize_color_value(
                    result.get("sku_color") or result.get("object_color")
                ),
            }

        elif intent_type == "fetch_sku":
            result = {
                "source_workspace_name": str(
                    result.get("source_workspace_name") or ""
                ),
                "source_workspace_color": self._normalize_color_value(
                    result.get("source_workspace_color")
                ),
                "target_workspace_name": str(
                    result.get("target_workspace_name") or ""
                ),
                "target_workspace_color": self._normalize_color_value(
                    result.get("target_workspace_color")
                ),
                "sku_name": self._normalize_sku_name(result.get("sku_name") or ""),
                "sku_color": self._normalize_color_value(result.get("sku_color")),
            }

        elif intent_type == "guard_loop":
            waypoints = result.get("waypoints", [])
            if not waypoints and raw_text:
                colors = self.extract_colors_in_order(raw_text)
                waypoints = [
                    {"workspace_name": "table", "workspace_color": color}
                    for color in colors[:2]
                ]
            normalized_waypoints: list[dict[str, str]] = []
            for wp in waypoints if isinstance(waypoints, list) else []:
                if not isinstance(wp, dict):
                    continue
                normalized_waypoints.append(
                    {
                        "workspace_name": str(wp.get("workspace_name") or "table"),
                        "workspace_color": self._normalize_color_value(
                            wp.get("workspace_color")
                        ),
                    }
                )
            loop_count = self.normalize_loop_count(result.get("loop_count"))
            if loop_count is None and raw_text:
                loop_count = self.extract_loop_count(raw_text)
            result = {
                "waypoints": normalized_waypoints,
                "loop_count": loop_count or 1,
            }

        return result

    def validate_required_slots(
        self,
        intent_type: str,
        slots: dict[str, Any],
    ) -> SkillResult[Any] | None:
        spec = self._catalog.intents.get(intent_type)
        if spec is None:
            return SkillResult(
                success=False,
                error_code="UNSUPPORTED_INTENT",
                message=f"Unsupported intent type: {intent_type!r}.",
            )

        if intent_type == "move_relative":
            nav_result = self.validate_move_relative_slots(slots)
            if nav_result is not None:
                return nav_result

        if intent_type == "move_to_workspace":
            nav_result = self.validate_move_to_workspace_slots(slots)
            if nav_result is not None:
                return nav_result

        missing: list[str] = []
        for slot_name in spec.required_slots:
            value = slots.get(slot_name)
            if value is None or value == "" or value == []:
                missing.append(slot_name)

        if missing:
            return SkillResult(
                success=False,
                error_code="NEED_CLARIFICATION",
                message=f"Missing required slots: {', '.join(missing)}.",
            )

        if intent_type == "guard_loop":
            waypoints = slots.get("waypoints", [])
            if not isinstance(waypoints, list) or len(waypoints) < 2:
                return SkillResult(
                    success=False,
                    error_code="NEED_CLARIFICATION",
                    message="Guard loop needs at least two waypoints.",
                )

        if intent_type == "pick_sku":
            pick_result = self._validate_pick_sku_slots(slots)
            if pick_result is not None:
                return pick_result

        if intent_type == "fetch_sku":
            fetch_result = self._validate_fetch_sku_slots(slots)
            if fetch_result is not None:
                return fetch_result

        return None

    def _validate_fetch_sku_slots(
        self,
        slots: dict[str, Any],
    ) -> SkillResult[Any] | None:
        source_color = slots.get("source_workspace_color")
        target_color = slots.get("target_workspace_color")
        sku_color = slots.get("sku_color")
        table_colors = self._catalog.pick.table_colors
        for label, color in (("source", source_color), ("target", target_color)):
            if color and table_colors and color not in table_colors:
                return SkillResult(
                    success=False,
                    error_code="INVALID_SLOT",
                    message=f"Unsupported {label} workspace color: {color!r}.",
                )
        if source_color and sku_color and source_color == sku_color:
            return SkillResult(
                success=False,
                error_code="INVALID_SLOT",
                message=f"Same-color fetch not allowed: source={source_color!r}, sku={sku_color!r}.",
            )
        if source_color and target_color and source_color == target_color:
            return SkillResult(
                success=False,
                error_code="INVALID_SLOT",
                message=f"Source and target workspace cannot be the same color: {source_color!r}.",
            )
        return None

    def _validate_pick_sku_slots(
        self,
        slots: dict[str, Any],
    ) -> SkillResult[Any] | None:
        workspace_color = slots.get("workspace_color")
        sku_color = slots.get("sku_color")
        table_colors = self._catalog.pick.table_colors
        trusted = self._catalog.pick.trusted_combinations
        if workspace_color and table_colors and workspace_color not in table_colors:
            return SkillResult(
                success=False,
                error_code="INVALID_SLOT",
                message=f"Unsupported workspace color: {workspace_color!r}.",
            )
        if workspace_color and sku_color and workspace_color == sku_color:
            return SkillResult(
                success=False,
                error_code="INVALID_SLOT",
                message=(
                    f"Same-color pick is not allowed: table={workspace_color!r}, "
                    f"sku={sku_color!r}."
                ),
            )
        if (
            workspace_color
            and sku_color
            and workspace_color in trusted
            and sku_color not in trusted[workspace_color]
        ):
            return SkillResult(
                success=False,
                error_code="INVALID_SLOT",
                message=(
                    f"Untrusted table/cube pairing: {workspace_color!r} + {sku_color!r}."
                ),
            )

        return None

    def normalize_workspace(self, text: str) -> tuple[str | None, str]:
        normalized = self.normalize_text(text)
        for workspace_name, spec in self._catalog.workspaces.items():
            if not any(alias.casefold() in normalized for alias in spec.aliases):
                continue
            if spec.requires_color:
                color = self.normalize_color(text)
                if color is None:
                    continue
                return workspace_name, color
            return workspace_name, ""
        return None, ""

    def validate_move_relative_slots(self, slots: dict[str, Any]) -> SkillResult[Any] | None:
        direction = slots.get("direction")
        if not direction:
            return SkillResult(
                success=False,
                error_code="NEED_CLARIFICATION",
                message="Relative move needs a direction.",
            )
        if direction not in self._catalog.directions:
            return SkillResult(
                success=False,
                error_code="INVALID_SLOT",
                message=f"Unsupported direction: {direction!r}.",
            )
        return None

    def validate_move_to_workspace_slots(self, slots: dict[str, Any]) -> SkillResult[Any] | None:
        workspace_name = slots.get("workspace_name")
        if not workspace_name:
            return SkillResult(
                success=False,
                error_code="NEED_CLARIFICATION",
                message="Navigation needs a target workspace.",
            )
        spec = self._catalog.workspaces.get(str(workspace_name))
        if spec is not None and spec.requires_color and not slots.get("workspace_color"):
            return SkillResult(
                success=False,
                error_code="NEED_CLARIFICATION",
                message="Table workspace navigation needs a color.",
            )
        return None

    def build_canonical_nl(self, intent_type: str, slots: dict[str, Any]) -> str:
        templates = self._catalog.canonical_templates
        if intent_type == "move_relative":
            template = str(templates.get("move_relative", "{direction_nl}移动{distance_m}米"))
            direction = str(slots.get("direction", "forward"))
            direction_nl = self._catalog.direction_nl.get(direction, direction)
            distance_units = float(slots.get("distance_units", 1.0))
            distance_m = distance_units * 0.05
            distance_text = _format_meters(distance_m)
            return template.format(direction_nl=direction_nl, distance_m=distance_text)

        if intent_type == "move_to_workspace":
            workspace_templates = templates.get("move_to_workspace", {})
            if not isinstance(workspace_templates, dict):
                raise ValueError("move_to_workspace canonical templates must be a mapping")
            workspace_name = str(slots.get("workspace_name", ""))
            if workspace_name == "front_workspace":
                return str(
                    workspace_templates.get("front_workspace", "移动到前方固定工作区")
                )
            if workspace_name == "table":
                color = str(slots.get("workspace_color", ""))
                color_nl = self._color_to_nl(color)
                table_template = str(
                    workspace_templates.get("table", "前往{color_nl}桌子")
                )
                return table_template.format(color_nl=color_nl)
            raise ValueError(f"unsupported workspace_name for canonical NL: {workspace_name!r}")

        raise ValueError(f"unsupported intent_type for canonical NL: {intent_type!r}")

    def _color_to_nl(self, color: str) -> str:
        normalized = color.strip().lower()
        if normalized in self._catalog.colors:
            return self._catalog.colors[normalized].nl
        for canonical, spec in self._catalog.colors.items():
            if normalized in {alias.casefold() for alias in spec.aliases}:
                return spec.nl
            if color.strip() in spec.aliases:
                return spec.nl
        return color.strip()


_mapper_singleton: NavigationSemanticMapper | None = None


def get_navigation_semantic_mapper(
    catalog: NavigationSemanticCatalog | None = None,
) -> NavigationSemanticMapper:
    global _mapper_singleton
    if catalog is not None:
        return NavigationSemanticMapper(catalog)
    if _mapper_singleton is None:
        _mapper_singleton = NavigationSemanticMapper(get_navigation_semantic_catalog())
    return _mapper_singleton


get_nl_semantic_mapper = get_navigation_semantic_mapper
NlSemanticMapper = NavigationSemanticMapper


def reset_navigation_semantic_mapper() -> None:
    global _mapper_singleton
    _mapper_singleton = None


reset_nl_semantic_mapper = reset_navigation_semantic_mapper


def _format_meters(distance_meters: float) -> str:
    if distance_meters == int(distance_meters):
        return str(int(distance_meters))
    return f"{distance_meters:.3f}".rstrip("0").rstrip(".")


__all__ = [
    "NavigationSemanticMapper",
    "NlSemanticMapper",
    "get_navigation_semantic_mapper",
    "get_nl_semantic_mapper",
    "reset_navigation_semantic_mapper",
    "reset_nl_semantic_mapper",
]
