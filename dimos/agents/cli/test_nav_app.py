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

import subprocess
import sys
from pathlib import Path

import pytest


def test_nav_help_does_not_import_matplotlib() -> None:
    """``dimos nav --help`` must lazy-load matplotlib (only needed for map commands)."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from dimos.robot.cli.dimos import main; "
                "import typer; "
                "typer.main.get_command(main)(['nav', '--help']); "
                "bad = [m for m in ('matplotlib',) if m in sys.modules]; "
                "assert not bad, f'Heavy deps imported: {bad}'"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_build_map_viz_argv_relative_goal_uses_plain_strings() -> None:
    """Internal relative-goal path must not leak typer OptionInfo into argparse."""
    from dimos.agents.cli import map_viz
    from dimos.agents.cli.nav_app import _build_map_viz_argv

    argv = _build_map_viz_argv(
        live=True,
        transport="foxglove",
        direction="backward",
        distance_units=20.0,
    )
    assert argv == ["--live", "--transport", "foxglove", "--direction", "backward", "--distance-units", "20.0"]
    assert all(isinstance(token, str) for token in argv)
    args = map_viz.parse_args(argv)
    assert args.direction == "backward"
    assert args.distance_units == 20.0


def test_relative_goal_argv_parses_without_subcommand_name() -> None:
    """Map viz accepts relative overlay flags without a subcommand name."""
    from dimos.agents.cli.map_viz import parse_args

    args = parse_args(
        [
            "--live",
            "--direction",
            "backward",
            "--distance-units",
            "2",
        ]
    )
    assert args.direction == "backward"
    assert args.distance_units == 2.0
    assert args.save is None
    from dimos.agents.cli.map_viz import resolve_nav_save_path

    assert resolve_nav_save_path(
        args.save,
        direction=args.direction,
        distance_units=args.distance_units,
        style="web",
    ) == Path("output/goal_backward_2.png")


def test_display_yaw_from_robot_pose_prefers_quaternion() -> None:
    from dimos.agents.cli.map_viz import display_yaw_from_robot_pose

    pose = {"x": 0.0, "y": 0.0, "yaw": 0.1, "quaternion_yaw": -2.39}
    assert display_yaw_from_robot_pose(pose) == -2.39


def test_robot_heading_triangle_points_along_display_yaw() -> None:
    import math

    from dimos.agents.cli.map_viz import robot_heading_triangle_vertices

    x, y, yaw, resolution = 1.0, 2.0, math.radians(-137.0), 0.05
    tip, _left, _right = robot_heading_triangle_vertices(x, y, yaw, resolution)
    heading = math.atan2(tip[1] - y, tip[0] - x)
    assert heading == pytest.approx(yaw, abs=1e-6)


def test_display_yaw_falls_back_to_nav_yaw_without_quaternion() -> None:
    from dimos.agents.cli.map_viz import display_yaw_from_robot_pose

    pose = {"x": 0.0, "y": 0.0, "yaw": 0.25}
    assert display_yaw_from_robot_pose(pose) == 0.25


def test_compute_relative_goal_uses_display_yaw() -> None:
    import math

    from dimos.agents.cli.map_viz import compute_relative_goal

    body_yaw = -2.39
    nav_yaw = 0.0
    rx, ry = 0.67, 0.02
    data = {
        "robot_pose": {
            "x": rx,
            "y": ry,
            "yaw": nav_yaw,
            "quaternion_yaw": body_yaw,
        }
    }
    target = compute_relative_goal(data, direction="backward", distance_units=2)

    dx = float(target.x) - rx
    dy = float(target.y) - ry
    heading = math.atan2(dy, dx)
    expected_heading = math.atan2(
        math.sin(body_yaw + math.pi),
        math.cos(body_yaw + math.pi),
    )
    assert heading == pytest.approx(expected_heading, abs=1e-4)
    assert heading != pytest.approx(math.pi, abs=0.1)
