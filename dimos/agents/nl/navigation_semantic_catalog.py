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

"""Navigation semantic catalog loaded from YAML configuration."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from dimos.utils.logging_config import setup_logger

logger = setup_logger()

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_NL_SEMANTICS_PATH = _REPO_ROOT / "config" / "nl_semantics.yaml"
DEFAULT_NAVIGATION_SEMANTICS_PATH = DEFAULT_NL_SEMANTICS_PATH


@dataclass(frozen=True)
class DirectionSpec:
    aliases: tuple[str, ...]
    confidence_tiers: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceSpec:
    requires_color: bool
    aliases: tuple[str, ...]
    color_slot: str = "workspace_color"


@dataclass(frozen=True)
class ColorSpec:
    aliases: tuple[str, ...]
    nl: str


@dataclass(frozen=True)
class ConflictRule:
    name: str
    if_workspace_alias_present: bool = False
    suppress_intent: str = ""


@dataclass(frozen=True)
class IntentSpec:
    required_slots: tuple[str, ...]
    description: str = ""
    llm_slots: tuple[str, ...] = ()


@dataclass(frozen=True)
class FetchSpec:
    keywords: tuple[str, ...]
    alt_keywords: tuple[str, ...]
    sku_defaults: dict[str, Any]


@dataclass(frozen=True)
class GuardSpec:
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class PickSpec:
    terms: tuple[str, ...]
    table_colors: tuple[str, ...] = ()
    trusted_combinations: dict[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class SkuSpec:
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class NavigationSemanticCatalog:
    version: str
    intents: dict[str, IntentSpec]
    movement_triggers: tuple[str, ...]
    object_task_exclusions: tuple[str, ...]
    directions: dict[str, DirectionSpec]
    distances: dict[str, float]
    loop_counts: dict[str, int]
    colors: dict[str, ColorSpec]
    direction_nl: dict[str, str]
    workspaces: dict[str, WorkspaceSpec]
    conflict_rules: tuple[ConflictRule, ...]
    canonical_templates: dict[str, Any]
    eval_templates: dict[str, Any]
    pick: PickSpec
    fetch: FetchSpec
    guard: GuardSpec
    skus: dict[str, SkuSpec] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> NavigationSemanticCatalog:
        catalog_path = Path(path)
        if not catalog_path.is_file():
            raise FileNotFoundError(f"navigation semantics file not found: {catalog_path}")
        raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("navigation semantics yaml root must be a mapping")
        return cls._from_mapping(raw)

    @classmethod
    def from_config(cls, cfg: Any | None = None) -> NavigationSemanticCatalog:
        from dimos.core.global_config import global_config

        config = cfg or global_config
        semantics_path = (
            getattr(config, "nl_semantics_path", "")
            or getattr(config, "nl_navigation_semantics_path", "")
            or str(DEFAULT_NL_SEMANTICS_PATH)
        )
        catalog = cls.from_file(semantics_path)
        workspace_catalog = getattr(config, "ros_nav_workspace_catalog", "") or ""
        if workspace_catalog.strip():
            catalog = catalog.merge_workspace_catalog_file(workspace_catalog)
        return catalog

    @classmethod
    def _from_mapping(cls, raw: dict[str, Any]) -> NavigationSemanticCatalog:
        version = str(raw.get("version", "")).strip()
        if not version:
            raise ValueError("navigation semantics yaml requires non-empty version")

        intents_raw = raw.get("intents")
        if intents_raw is None:
            intents = _default_intents()
        else:
            intents = _parse_intents(intents_raw)
        movement_triggers = _require_str_list(raw, "movement_triggers")
        object_task_exclusions = _require_str_list(raw, "object_task_exclusions")
        pick_raw = raw.get("pick")
        pick = _parse_pick(pick_raw) if pick_raw is not None else PickSpec(terms=())
        fetch_raw = raw.get("fetch")
        fetch = _parse_fetch(fetch_raw) if fetch_raw is not None else FetchSpec(
            keywords=(), alt_keywords=(), sku_defaults={}
        )
        guard_raw = raw.get("guard")
        guard = _parse_guard(guard_raw) if guard_raw is not None else GuardSpec(keywords=())
        loop_counts_raw = raw.get("loop_counts")
        loop_counts = (
            _parse_loop_counts(loop_counts_raw) if loop_counts_raw is not None else {}
        )
        skus_raw = raw.get("skus", {})
        skus = _parse_skus(skus_raw)

        directions_raw = raw.get("directions")
        if not isinstance(directions_raw, dict) or not directions_raw:
            raise ValueError("directions must be a non-empty mapping")
        directions: dict[str, DirectionSpec] = {}
        for name, spec in directions_raw.items():
            if not isinstance(spec, dict):
                raise ValueError(f"direction {name!r} must be a mapping")
            aliases = _require_str_list(spec, "aliases", parent=name)
            tiers_raw = spec.get("confidence_tiers", {})
            if not isinstance(tiers_raw, dict):
                raise ValueError(f"direction {name!r} confidence_tiers must be a mapping")
            tiers = {str(k): float(v) for k, v in tiers_raw.items()}
            directions[name] = DirectionSpec(aliases=aliases, confidence_tiers=tiers)

        distances_raw = raw.get("distances", {})
        if not isinstance(distances_raw, dict):
            raise ValueError("distances must be a mapping")
        semantic = distances_raw.get("semantic_aliases", {})
        if not isinstance(semantic, dict) or not semantic:
            raise ValueError("distances.semantic_aliases must be a non-empty mapping")
        distances = {str(k): float(v) for k, v in semantic.items()}

        colors_raw = raw.get("colors", {})
        if not isinstance(colors_raw, dict) or not colors_raw:
            raise ValueError("colors must be a non-empty mapping")
        colors: dict[str, ColorSpec] = {}
        for name, spec in colors_raw.items():
            if not isinstance(spec, dict):
                raise ValueError(f"color {name!r} must be a mapping")
            aliases = _require_str_list(spec, "aliases", parent=name)
            nl = str(spec.get("nl", name)).strip()
            colors[name] = ColorSpec(aliases=aliases, nl=nl)

        direction_nl_raw = raw.get("direction_nl", {})
        if not isinstance(direction_nl_raw, dict):
            raise ValueError("direction_nl must be a mapping")
        direction_nl = {str(k): str(v) for k, v in direction_nl_raw.items()}

        workspaces_raw = raw.get("workspaces")
        if not isinstance(workspaces_raw, dict) or not workspaces_raw:
            raise ValueError("workspaces must be a non-empty mapping")
        workspaces: dict[str, WorkspaceSpec] = {}
        for name, spec in workspaces_raw.items():
            if not isinstance(spec, dict):
                raise ValueError(f"workspace {name!r} must be a mapping")
            aliases = _require_str_list(spec, "aliases", parent=name)
            requires_color = bool(spec.get("requires_color", False))
            color_slot = str(spec.get("color_slot", "workspace_color"))
            workspaces[name] = WorkspaceSpec(
                requires_color=requires_color,
                aliases=aliases,
                color_slot=color_slot,
            )

        conflict_rules_raw = raw.get("conflict_rules", [])
        if not isinstance(conflict_rules_raw, list):
            raise ValueError("conflict_rules must be a list")
        conflict_rules: list[ConflictRule] = []
        for index, item in enumerate(conflict_rules_raw):
            if not isinstance(item, dict):
                raise ValueError(f"conflict_rules[{index}] must be a mapping")
            conflict_rules.append(
                ConflictRule(
                    name=str(item.get("name", f"rule_{index}")),
                    if_workspace_alias_present=bool(
                        item.get("if_workspace_alias_present", False)
                    ),
                    suppress_intent=str(item.get("suppress_intent", "")),
                )
            )

        canonical_templates = raw.get("canonical_templates", {})
        if not isinstance(canonical_templates, dict):
            raise ValueError("canonical_templates must be a mapping")

        eval_templates = raw.get("eval_templates", {})
        if not isinstance(eval_templates, dict):
            raise ValueError("eval_templates must be a mapping")

        return cls(
            version=version,
            intents=intents,
            movement_triggers=movement_triggers,
            object_task_exclusions=object_task_exclusions,
            directions=directions,
            distances=distances,
            loop_counts=loop_counts,
            colors=colors,
            direction_nl=direction_nl,
            workspaces=workspaces,
            conflict_rules=tuple(conflict_rules),
            canonical_templates=canonical_templates,
            eval_templates=eval_templates,
            pick=pick,
            fetch=fetch,
            guard=guard,
            skus=skus,
        )

    def merge_workspace_catalog_file(self, path: str | Path) -> NavigationSemanticCatalog:
        catalog_path = Path(path)
        if not catalog_path.is_file():
            logger.warning("workspace catalog not found for alias merge: %s", catalog_path)
            return self

        raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            logger.warning("workspace catalog root is not a mapping: %s", catalog_path)
            return self

        front_aliases: list[str] = list(self.workspaces["front_workspace"].aliases)
        table_aliases: list[str] = list(self.workspaces["table"].aliases)

        for workspace_id, record in raw.items():
            if not isinstance(record, dict):
                continue
            aliases_raw = record.get("aliases", [])
            if not isinstance(aliases_raw, list):
                continue
            aliases = [str(alias) for alias in aliases_raw if str(alias).strip()]
            if not aliases:
                continue

            ws_id = str(record.get("workspace_id", workspace_id))
            name = str(record.get("name", ""))
            color = str(record.get("color", ""))

            if ws_id == "front_workspace" or (name == "workspace" and color == "front"):
                front_aliases.extend(aliases)
            elif name == "table":
                table_aliases.extend(aliases)

        return self._with_workspace_aliases(
            front_workspace=_dedupe_preserve_order(front_aliases),
            table=_dedupe_preserve_order(table_aliases),
        )

    def _with_workspace_aliases(
        self,
        *,
        front_workspace: tuple[str, ...],
        table: tuple[str, ...],
    ) -> NavigationSemanticCatalog:
        workspaces = dict(self.workspaces)
        front = workspaces["front_workspace"]
        table_spec = workspaces["table"]
        workspaces["front_workspace"] = replace(front, aliases=front_workspace)
        workspaces["table"] = replace(table_spec, aliases=table)
        return replace(self, workspaces=workspaces)

    def all_workspace_aliases(self) -> tuple[str, ...]:
        aliases: list[str] = []
        for spec in self.workspaces.values():
            aliases.extend(spec.aliases)
        return _dedupe_preserve_order(aliases)

    def all_direction_aliases(self) -> tuple[str, ...]:
        aliases: list[str] = []
        for spec in self.directions.values():
            aliases.extend(spec.aliases)
        return _dedupe_preserve_order(aliases)


_catalog_singleton: NavigationSemanticCatalog | None = None


def get_navigation_semantic_catalog(cfg: Any | None = None) -> NavigationSemanticCatalog:
    global _catalog_singleton
    if _catalog_singleton is None:
        _catalog_singleton = NavigationSemanticCatalog.from_config(cfg)
    return _catalog_singleton


get_nl_semantic_catalog = get_navigation_semantic_catalog
NlSemanticCatalog = NavigationSemanticCatalog


def reset_navigation_semantic_catalog() -> None:
    global _catalog_singleton
    _catalog_singleton = None


reset_nl_semantic_catalog = reset_navigation_semantic_catalog


def _default_intents() -> dict[str, IntentSpec]:
    return {
        "move_relative": IntentSpec(
            required_slots=("direction", "distance_units"),
            description="Move the robot in a relative direction",
            llm_slots=("direction", "distance_meters", "speed"),
        ),
        "move_to_workspace": IntentSpec(
            required_slots=("workspace_name",),
            description="Navigate to a named workspace",
            llm_slots=("workspace_name", "workspace_color", "approach_direction"),
        ),
        "pick_sku": IntentSpec(
            required_slots=("workspace_name", "workspace_color", "sku_name", "sku_color"),
            description="Pick up an object from a workspace",
            llm_slots=(
                "workspace_type",
                "table_color",
                "object_type",
                "object_color",
                "goal_workspace_type",
                "goal_table_color",
            ),
        ),
        "fetch_sku": IntentSpec(
            required_slots=(
                "source_workspace_name",
                "source_workspace_color",
                "target_workspace_name",
                "target_workspace_color",
                "sku_name",
                "sku_color",
            ),
            description="Fetch an object between workspaces",
            llm_slots=(
                "source_workspace_name",
                "source_workspace_color",
                "target_workspace_name",
                "target_workspace_color",
                "sku_name",
                "sku_color",
            ),
        ),
        "guard_loop": IntentSpec(
            required_slots=("waypoints", "loop_count"),
            description="Patrol between waypoints",
            llm_slots=("waypoints", "loop_count", "patrol_speed"),
        ),
        "go_home": IntentSpec(
            required_slots=(),
            description="Return the robot upper body to home pose",
            llm_slots=(),
        ),
    }


def _parse_intents(raw: Any) -> dict[str, IntentSpec]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("intents must be a non-empty mapping")
    intents: dict[str, IntentSpec] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"intent {name!r} must be a mapping")
        required = spec.get("required_slots", [])
        if not isinstance(required, list):
            raise ValueError(f"intent {name!r} required_slots must be a list")
        llm_slots_raw = spec.get("llm_slots", [])
        llm_slots = tuple(str(s) for s in llm_slots_raw) if isinstance(llm_slots_raw, list) else ()
        intents[str(name)] = IntentSpec(
            required_slots=tuple(str(s) for s in required),
            description=str(spec.get("description", "")),
            llm_slots=llm_slots,
        )
    return intents


def _parse_pick(raw: Any) -> PickSpec:
    if not isinstance(raw, dict):
        return PickSpec(terms=())
    terms_raw = raw.get("terms", [])
    terms = tuple(str(t) for t in terms_raw) if isinstance(terms_raw, list) else ()
    table_colors_raw = raw.get("table_colors", [])
    table_colors = (
        tuple(str(c) for c in table_colors_raw)
        if isinstance(table_colors_raw, list)
        else ()
    )
    trusted_raw = raw.get("trusted_combinations", {})
    trusted: dict[str, frozenset[str]] = {}
    if isinstance(trusted_raw, dict):
        for table_color, allowed in trusted_raw.items():
            if not isinstance(allowed, list):
                continue
            table_color_str = str(table_color)
            if table_colors and table_color_str not in table_colors:
                raise ValueError(
                    f"pick.trusted_combinations key {table_color_str!r} "
                    "not in pick.table_colors"
                )
            trusted[table_color_str] = frozenset(str(c) for c in allowed)
    return PickSpec(
        terms=terms,
        table_colors=table_colors,
        trusted_combinations=trusted,
    )


def _parse_skus(raw: Any) -> dict[str, SkuSpec]:
    if not isinstance(raw, dict):
        return {}
    skus: dict[str, SkuSpec] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"sku {name!r} must be a mapping")
        aliases = _require_str_list(spec, "aliases", parent=name)
        skus[str(name)] = SkuSpec(name=str(name), aliases=aliases)
    return skus


def _parse_fetch(raw: Any) -> FetchSpec:
    if not isinstance(raw, dict):
        return FetchSpec(keywords=(), alt_keywords=(), sku_defaults={})
    keywords = _optional_str_list(raw, "keywords")
    alt_keywords = _optional_str_list(raw, "alt_keywords")
    sku_defaults = raw.get("sku_defaults", {})
    if not isinstance(sku_defaults, dict):
        sku_defaults = {}
    return FetchSpec(keywords=keywords, alt_keywords=alt_keywords, sku_defaults=sku_defaults)


def _parse_guard(raw: Any) -> GuardSpec:
    if not isinstance(raw, dict):
        return GuardSpec(keywords=())
    return GuardSpec(keywords=_optional_str_list(raw, "keywords"))


def _parse_loop_counts(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    semantic = raw.get("semantic_aliases", {})
    if not isinstance(semantic, dict):
        return {}
    return {str(k): int(v) for k, v in semantic.items()}


def _optional_str_list(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _require_str_list(
    raw: dict[str, Any],
    key: str,
    *,
    parent: str = "",
) -> tuple[str, ...]:
    value = raw.get(key)
    label = f"{parent}.{key}" if parent else key
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    items = tuple(str(item).strip() for item in value if str(item).strip())
    if not items:
        raise ValueError(f"{label} must contain non-empty strings")
    return items


def _dedupe_preserve_order(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


__all__ = [
    "ColorSpec",
    "ConflictRule",
    "DEFAULT_NL_SEMANTICS_PATH",
    "DEFAULT_NAVIGATION_SEMANTICS_PATH",
    "DirectionSpec",
    "FetchSpec",
    "GuardSpec",
    "IntentSpec",
    "NavigationSemanticCatalog",
    "NlSemanticCatalog",
    "PickSpec",
    "SkuSpec",
    "WorkspaceSpec",
    "get_navigation_semantic_catalog",
    "get_nl_semantic_catalog",
    "reset_navigation_semantic_catalog",
    "reset_nl_semantic_catalog",
]
