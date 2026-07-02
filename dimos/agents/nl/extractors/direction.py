"""Direction extraction utilities (catalog-backed)."""

from __future__ import annotations

from typing import Callable

from dimos.agents.nl.navigation_semantic_mapper import get_navigation_semantic_mapper

Direction = str


def extract_direction(
    text: str,
    context: dict | None = None,
) -> Direction | None:
    """Extract relative movement direction from text."""
    _ = context
    return get_navigation_semantic_mapper().normalize_direction(text)


def make_direction_extractor(
    allowed_directions: list[str] | None = None,
) -> Callable[[str, dict | None], Direction | None]:
    allowed = set(allowed_directions) if allowed_directions else None

    def extractor(text: str, context: dict | None = None) -> Direction | None:
        direction = extract_direction(text, context)
        if direction is None:
            return None
        if allowed is not None and direction not in allowed:
            return None
        return direction

    return extractor


def has_direction(text: str, direction: str) -> bool:
    return extract_direction(text) == direction


__all__ = [
    "Direction",
    "extract_direction",
    "has_direction",
    "make_direction_extractor",
]
