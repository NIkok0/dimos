"""Slot extractors for NL parsing.

Reusable extractors for common slot types like distance, direction, colors.
"""

from dimos.agents.nl.extractors.distance import (
    extract_distance_units,
    meters_to_relative_distance_units,
)
from dimos.agents.nl.extractors.direction import (
    extract_direction,
)
from dimos.agents.nl.extractors.color import (
    extract_colors_in_order,
    extract_first_color,
    is_color_mentioned,
    COLOR_ALIASES,
)
from dimos.agents.nl.extractors.workspace import (
    extract_workspace,
    extract_workspace_name,
    extract_workspace_color,
)

__all__ = [
    # Distance extractors
    "extract_distance_units",
    "meters_to_relative_distance_units",
    # Direction extractors
    "extract_direction",
    # Color extractors
    "extract_colors_in_order",
    "extract_first_color",
    "is_color_mentioned",
    "COLOR_ALIASES",
    # Workspace extractors
    "extract_workspace",
    "extract_workspace_name",
    "extract_workspace_color",
]
