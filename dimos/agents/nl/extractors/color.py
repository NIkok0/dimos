"""Color extraction utilities.

Extracts color references from natural language text.
All color aliases live in nl_semantics.yaml; this module delegates to the mapper.
"""

from __future__ import annotations

from typing import Callable


def _color_aliases_from_catalog() -> dict[str, tuple[str, ...]]:
    from dimos.agents.nl.navigation_semantic_catalog import get_nl_semantic_catalog

    catalog = get_nl_semantic_catalog()
    return {
        name: tuple(spec.aliases) for name, spec in catalog.colors.items()
    }


def extract_colors_in_order(
    text: str,
    context: dict | None = None,
) -> list[str]:
    from dimos.agents.nl.navigation_semantic_mapper import get_nl_semantic_mapper

    return get_nl_semantic_mapper().extract_colors_in_order(text)


def extract_first_color(
    text: str,
    context: dict | None = None,
    exclude: set[str] | None = None,
) -> str | None:
    from dimos.agents.nl.navigation_semantic_mapper import get_nl_semantic_mapper

    return get_nl_semantic_mapper().normalize_color(text, exclude=exclude)


def make_color_extractor(
    exclude: set[str] | None = None,
    default: str | None = None,
) -> Callable[[str, dict | None], str | None]:
    def extractor(text: str, context: dict | None = None) -> str | None:
        result = extract_first_color(text, context, exclude)
        return result if result is not None else default

    return extractor


def is_color_mentioned(text: str, color: str | None = None) -> bool:
    if color:
        aliases = _color_aliases_from_catalog().get(color, ())
        normalized = text.lower().replace(" ", "")
        return any(alias.lower().replace(" ", "") in normalized for alias in aliases)

    return len(extract_colors_in_order(text)) > 0


def __getattr__(name: str) -> dict[str, tuple[str, ...]]:
    if name == "COLOR_ALIASES":
        return _color_aliases_from_catalog()
    raise AttributeError(name)


__all__ = [
    "COLOR_ALIASES",
    "extract_colors_in_order",
    "extract_first_color",
    "is_color_mentioned",
    "make_color_extractor",
]
