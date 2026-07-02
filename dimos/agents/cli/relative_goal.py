#!/usr/bin/env python3
"""Backward-compatible wrapper — use ``dimos nav map --direction ...`` instead."""

from __future__ import annotations

from collections.abc import Sequence

from dimos.agents.cli.map_viz import main as map_viz_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run map visualization with a required relative-move overlay."""
    extra = ["--live"]
    if argv is None:
        return map_viz_main(extra)
    return map_viz_main([*extra, *argv])


if __name__ == "__main__":
    raise SystemExit(main())
