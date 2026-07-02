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

from __future__ import annotations

import math

import pytest
from py_rosbridge.codecs import geometry_msgs, nav_msgs

from dimos.agents.navigation_contracts import WorkspacePose
from dimos.agents.navigation_safety import OccupancyGridSafetyChecker
from dimos.core.global_config import GlobalConfig


def _grid(*, width: int = 80, height: int = 80, resolution: float = 0.1) -> nav_msgs.OccupancyGrid:
    grid = nav_msgs.OccupancyGrid()
    grid.info.width = width
    grid.info.height = height
    grid.info.resolution = resolution
    grid.info.origin = geometry_msgs.Pose(
        position=geometry_msgs.Point(x=-4.0, y=-4.0, z=0.0),
        orientation=geometry_msgs.Quaternion(w=1.0),
    )
    grid.data = [0 for _ in range(width * height)]
    return grid


def _workspace(x: float, y: float, *, yaw: float = 0.0) -> WorkspacePose:
    return WorkspacePose(
        workspace_id="target",
        name="workspace",
        color="front",
        frame_id="map",
        x=x,
        y=y,
        yaw=yaw,
    )


def _seer_checker(*, mode: str = "footprint") -> OccupancyGridSafetyChecker:
    return OccupancyGridSafetyChecker.from_config(
        GlobalConfig(
            ros_nav_target_safety_mode=mode,
            ros_nav_target_safety_radius_m=0.585,
            robot_length=0.778,
            robot_width=0.54,
            ros_nav_collision_offset_m=0.085,
        )
    )


def test_free_target_within_circle_radius_is_safe() -> None:
    checker = OccupancyGridSafetyChecker(mode="circle", safety_radius_m=0.585)

    result = checker.check_target_is_safe(_grid(), _workspace(0.0, 0.0))

    assert result.safe is True
    assert result.reason == "target_area_free"
    assert result.radius_m == 0.585
    assert result.mode == "circle"


def test_occupied_cell_inside_circle_radius_blocks_navigation() -> None:
    grid = _grid()
    grid.data[40 * grid.info.width + 44] = 100
    checker = OccupancyGridSafetyChecker(mode="circle", safety_radius_m=0.585)

    result = checker.check_target_is_safe(grid, _workspace(0.0, 0.0))

    assert result.safe is False
    assert result.reason == "occupied_cell_in_target_radius"
    assert result.blocking_cell == {"mx": 44, "my": 40, "value": 100}


def test_unknown_cell_inside_circle_radius_blocks_navigation() -> None:
    grid = _grid()
    grid.data[40 * grid.info.width + 45] = -1
    checker = OccupancyGridSafetyChecker(mode="circle", safety_radius_m=0.585)

    result = checker.check_target_is_safe(grid, _workspace(0.0, 0.0))

    assert result.safe is False
    assert result.reason == "unknown_cell_in_target_radius"


def test_target_outside_map_blocks_navigation() -> None:
    checker = OccupancyGridSafetyChecker(mode="circle", safety_radius_m=0.585)

    result = checker.check_target_is_safe(_grid(), _workspace(10.0, 10.0))

    assert result.safe is False
    assert result.reason == "target_outside_map"


def test_footprint_free_target_is_safe() -> None:
    checker = _seer_checker()

    result = checker.check_target_is_safe(_grid(), _workspace(0.0, 0.0))

    assert result.safe is True
    assert result.mode == "footprint"
    assert result.radius_m == pytest.approx(0.474, abs=1e-3)


def test_footprint_occupied_cell_inside_blocks_navigation() -> None:
    grid = _grid()
    grid.data[40 * grid.info.width + 44] = 100
    checker = _seer_checker()

    result = checker.check_target_is_safe(grid, _workspace(0.0, 0.0))

    assert result.safe is False
    assert result.reason == "occupied_cell_in_target_footprint"


def test_footprint_occupied_cell_outside_lateral_edge_is_safe() -> None:
    grid = _grid()
    # 0.8 m to the side is outside half_width (0.355 m) but inside a 0.585 m circle.
    grid.data[40 * grid.info.width + 48] = 100
    checker = _seer_checker()

    result = checker.check_target_is_safe(grid, _workspace(0.0, 0.0))

    assert result.safe is True


def test_footprint_respects_target_yaw() -> None:
    grid = _grid()
    # 0.45 m ahead along +x blocks at yaw=0 but lies outside lateral half-width at yaw=pi/2.
    grid.data[40 * grid.info.width + 44] = 100
    checker = _seer_checker()

    blocked = checker.check_target_is_safe(grid, _workspace(0.0, 0.0, yaw=0.0))
    safe = checker.check_target_is_safe(grid, _workspace(0.0, 0.0, yaw=math.pi / 2.0))

    assert blocked.safe is False
    assert blocked.reason == "occupied_cell_in_target_footprint"
    assert safe.safe is True


def test_from_config_defaults_to_seer_footprint() -> None:
    checker = OccupancyGridSafetyChecker.from_config(GlobalConfig())

    assert checker.mode == "footprint"
    assert checker.safety_radius_m == pytest.approx(0.474, abs=1e-3)
