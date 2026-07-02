#!/usr/bin/env python3
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

"""Probe real navigation interface contracts without exposing ROS to the agent.

This script is a human-facing联调 helper. It uses the same workspace catalog and
goal contract as Dax Agent's navigation adapter, prints dry-run goals by default,
and refuses real ROS reads/sends until a concrete ROS2 or rosbridge client is wired
in. That keeps early validation useful while avoiding accidental robot motion.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from dimos.agents.navigation_contracts import NavigateToPoseGoal
from dimos.agents.workspace_resolver import (
    WorkspaceResolutionError,
    WorkspaceResolver,
)
from dimos.core.global_config import global_config

PROBE_STEPS = ("goal", "slam_status", "nav_status", "send_goal")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse navigation probe CLI arguments."""
    parser = argparse.ArgumentParser(description="Probe Dax Agent navigation interface contracts.")
    parser.add_argument("--step", choices=PROBE_STEPS, default="goal")
    parser.add_argument("--workspace-catalog", default=global_config.ros_nav_workspace_catalog)
    parser.add_argument("--workspace-name", default="front_workspace")
    parser.add_argument("--workspace-color", default="")
    parser.add_argument("--behavior-tree", default=global_config.ros_nav_default_behavior_tree)
    parser.add_argument("--timeout-s", type=float, default=global_config.ros_nav_action_timeout_s)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved NavigateToPose goal without reading or sending ROS data.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Reserved for the future real ROS client; currently fails loudly.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one navigation probe step and return a process-style exit code."""
    args = parse_args(argv)

    if args.step == "goal" or args.dry_run:
        return _print_dry_run_goal(args)

    _print_unimplemented()
    return 2


def _print_dry_run_goal(args: argparse.Namespace) -> int:
    """Resolve one workspace and print the NavigateToPose goal JSON."""
    if not args.workspace_catalog:
        print("ERROR: --workspace-catalog is required for navigation goal dry-run", file=sys.stderr)
        return 2
    try:
        resolver = WorkspaceResolver.from_file(args.workspace_catalog)
        workspace = resolver.resolve(
            workspace_name=args.workspace_name,
            workspace_color=args.workspace_color,
        )
    except WorkspaceResolutionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    goal = NavigateToPoseGoal(
        pose=workspace,
        behavior_tree=args.behavior_tree,
    )
    print(
        "DRY_RUN navigate_to_pose_goal="
        + json.dumps(goal.to_metadata(), ensure_ascii=False, sort_keys=True),
        flush=True,
    )
    return 0


def _print_unimplemented() -> None:
    """Explain why non-dry-run probing is intentionally disabled for now."""
    print(
        "ERROR: Real ROS navigation probe is not implemented yet. "
        "Use --dry-run to validate workspace catalog and NavigateToPose goal shape.",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
