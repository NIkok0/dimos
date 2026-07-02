"""Workspace extraction utilities (catalog-backed)."""

from __future__ import annotations

from typing import Callable

from dimos.agents.nl.navigation_semantic_mapper import get_navigation_semantic_mapper


def extract_workspace(
    text: str,
    context: dict | None = None,
) -> tuple[str | None, str | None]:
    """Extract workspace name and color from text."""
    _ = context
    name, color = get_navigation_semantic_mapper().normalize_workspace(text)
    if name is None:
        return None, None
    return name, color or ""


def make_workspace_extractor(
    allowed_workspaces: list[str] | None = None,
    require_color: bool | None = None,
) -> Callable[[str, dict | None], tuple[str | None, str | None]]:
    allowed_set = set(allowed_workspaces) if allowed_workspaces else None

    def extractor(text: str, context: dict | None = None) -> tuple[str | None, str | None]:
        name, color = extract_workspace(text, context)
        if allowed_set is not None and name not in allowed_set:
            return None, ""
        if require_color is not None:
            if require_color and not color:
                return None, ""
            if not require_color:
                color = ""
        return name, color

    return extractor


def extract_workspace_name(
    text: str,
    context: dict | None = None,
) -> str | None:
    name, _ = extract_workspace(text, context)
    return name


def extract_workspace_color(
    text: str,
    context: dict | None = None,
) -> str:
    _, color = extract_workspace(text, context)
    return color or ""


__all__ = [
    "extract_workspace",
    "extract_workspace_color",
    "extract_workspace_name",
    "make_workspace_extractor",
]
