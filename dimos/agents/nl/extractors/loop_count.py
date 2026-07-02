"""Loop count extraction utilities.

Extracts loop iteration counts from natural language text.
"""

from __future__ import annotations


def extract_loop_count(
    text: str,
    context: dict | None = None,
) -> int | None:
    from dimos.agents.nl.navigation_semantic_mapper import get_nl_semantic_mapper

    return get_nl_semantic_mapper().extract_loop_count(text)


def make_loop_count_extractor(
    default: int | None = None,
) -> callable:
    def extractor(text: str, context: dict | None = None) -> int | None:
        result = extract_loop_count(text, context)
        return result if result is not None else default

    return extractor


def __getattr__(name: str) -> dict[str, int]:
    if name == "LOOP_COUNT_ALIASES":
        from dimos.agents.nl.navigation_semantic_catalog import get_nl_semantic_catalog

        return dict(get_nl_semantic_catalog().loop_counts)
    raise AttributeError(name)
