"""Distance extraction utilities.

Extracts distance values from natural language text, handling:
- Meter suffixes (1m, 1米)
- Grid/cell units (格, 步)
- Chinese numbers (一, 两, 三)
- Semantic aliases (一点, 稍微, a bit) — via mapper catalog
"""

from __future__ import annotations

import re

from dimos.utils.logging_config import setup_logger

logger = setup_logger()

#: Map cell size in meters (5cm per cell)
MAP_CELL_SIZE_M: float = 0.05


def meters_to_relative_distance_units(meters: float) -> float:
    """Convert meters to internal distance units (map cells).

    Args:
        meters: Distance in meters

    Returns:
        Distance in map cell units (1 cell = 5cm)

    Example:
        >>> meters_to_relative_distance_units(1.0)
        20.0  # 1 meter = 20 cells at 5cm resolution
    """
    return meters / MAP_CELL_SIZE_M


# Regex patterns (pattern-based, not semantic aliases — kept here)
_METER_DISTANCE_RE = re.compile(
    r"(\d+(?:\.\d+)?)(?:m(?:eter|eters)?|米|公尺)",
    re.IGNORECASE,
)

_CN_NUM_UNIT_RE = re.compile(
    r"([一二两三四五六七八九十半]+)\s*(步|格|格子|格点|米|m|单位|个单位|块|段)",
)

_NUM_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(格|格子|步|单位|米|m)")


def extract_distance_units(
    text: str,
    context: dict | None = None,
) -> float:
    """Extract distance in relative units from text (delegates to mapper catalog)."""
    _ = context
    from dimos.agents.nl.navigation_semantic_mapper import get_nl_semantic_mapper

    return get_nl_semantic_mapper().normalize_distance_units(text)


def extract_meters(text: str, context: dict | None = None) -> float | None:
    """Extract distance in meters from text.

    Returns None if no meter unit found.

    Example:
        >>> extract_meters("向后移动1米")
        1.0
        >>> extract_meters("后退两步")
        None
    """
    match = _METER_DISTANCE_RE.search(text)
    if match:
        return float(match.group(1))

    # Check for Chinese number + 米
    cn_match = _CN_NUM_UNIT_RE.search(text)
    if cn_match and cn_match.group(2) in ("米", "m"):
        cn_num = cn_match.group(1)
        # Delegate CN number parsing to mapper catalog distances
        from dimos.agents.nl.navigation_semantic_mapper import get_nl_semantic_mapper

        mapper = get_nl_semantic_mapper()
        value = mapper._catalog.distances.get(cn_num)
        return float(value) if value is not None else None

    # Check for numeric + 米
    num_match = _NUM_UNIT_RE.search(text)
    if num_match and num_match.group(2) in ("米", "m"):
        return float(num_match.group(1))

    return None


__all__ = [
    "MAP_CELL_SIZE_M",
    "extract_distance_units",
    "extract_meters",
    "meters_to_relative_distance_units",
]
