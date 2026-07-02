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

"""Safety gate helpers for map-backed navigation goals.

This module implements a first-pass obstacle check before DimOS submits a real
navigation goal. It translates a map-frame target into OccupancyGrid cells and
scans either a circular safety radius or a yaw-aligned robot footprint around
the target. The checker rejects occupied, unknown, malformed, or out-of-map
targets early; it does not replace the robot's local planner or dynamic
obstacle avoidance while the robot is moving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Literal

from dimos.agents.navigation_contracts import WorkspacePose

SafetyCheckMode = Literal["circle", "footprint"]


@dataclass(frozen=True)
class NavigationSafetyResult:
    """Describe whether a navigation target passed the OccupancyGrid safety gate."""

    safe: bool
    reason: str
    radius_m: float
    mode: SafetyCheckMode = "circle"
    target_cell: dict[str, int] = field(default_factory=dict)
    blocking_cell: dict[str, int] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """Return this safety decision in a log-friendly metadata shape."""
        return {
            "safe": self.safe,
            "reason": self.reason,
            "radius_m": self.radius_m,
            "mode": self.mode,
            "target_cell": self.target_cell,
            "blocking_cell": self.blocking_cell,
        }


class OccupancyGridSafetyChecker:
    """Check whether a map-frame navigation target is free within a safety region."""

    def __init__(
        self,
        *,
        mode: SafetyCheckMode = "circle",
        safety_radius_m: float = 0.585,
        robot_length_m: float = 0.778,
        robot_width_m: float = 0.54,
        collision_offset_m: float = 0.085,
        occupied_threshold: int = 50,
        reject_unknown: bool = True,
    ) -> None:
        mode_normalized = mode.strip().lower()
        if mode_normalized not in {"circle", "footprint"}:
            raise ValueError(f"unsupported safety check mode: {mode!r}")
        if safety_radius_m <= 0:
            raise ValueError("safety_radius_m must be positive")
        if robot_length_m <= 0 or robot_width_m <= 0:
            raise ValueError("robot_length_m and robot_width_m must be positive")
        if collision_offset_m < 0:
            raise ValueError("collision_offset_m must be non-negative")
        self._mode: SafetyCheckMode = mode_normalized  # type: ignore[assignment]
        self._safety_radius_m = safety_radius_m
        self._robot_length_m = robot_length_m
        self._robot_width_m = robot_width_m
        self._collision_offset_m = collision_offset_m
        self._occupied_threshold = occupied_threshold
        self._reject_unknown = reject_unknown

    @classmethod
    def from_config(cls, config: Any) -> OccupancyGridSafetyChecker:
        """Build a checker from ``GlobalConfig`` navigation safety fields."""
        mode = str(getattr(config, "ros_nav_target_safety_mode", "footprint")).strip().lower()
        return cls(
            mode=mode,  # type: ignore[arg-type]
            safety_radius_m=float(getattr(config, "ros_nav_target_safety_radius_m", 0.585)),
            robot_length_m=float(getattr(config, "robot_length", 0.778)),
            robot_width_m=float(getattr(config, "robot_width", 0.54)),
            collision_offset_m=float(getattr(config, "ros_nav_collision_offset_m", 0.085)),
        )

    @property
    def safety_radius_m(self) -> float:
        """Return the configured circle radius or max footprint half-extent in meters."""
        if self._mode == "footprint":
            half_length = self._robot_length_m / 2.0 + self._collision_offset_m
            half_width = self._robot_width_m / 2.0 + self._collision_offset_m
            return max(half_length, half_width)
        return self._safety_radius_m

    @property
    def mode(self) -> SafetyCheckMode:
        """Return the active safety geometry mode."""
        return self._mode

    def check_target_is_safe(
        self,
        occupancy_grid: Any,
        target: WorkspacePose,
    ) -> NavigationSafetyResult:
        """Return whether the target point's surrounding map cells are traversable."""
        width = int(getattr(occupancy_grid.info, "width", 0))
        height = int(getattr(occupancy_grid.info, "height", 0))
        resolution = float(getattr(occupancy_grid.info, "resolution", 0.0))
        data = list(getattr(occupancy_grid, "data", []))
        if width <= 0 or height <= 0 or resolution <= 0 or len(data) < width * height:
            return self._result(False, "invalid_occupancy_grid")

        maybe_cell = self._world_to_map(occupancy_grid, target.x, target.y)
        if maybe_cell is None:
            return self._result(False, "target_outside_map")
        target_mx, target_my = maybe_cell

        if self._mode == "footprint":
            return self._check_footprint(
                occupancy_grid=occupancy_grid,
                target=target,
                target_mx=target_mx,
                target_my=target_my,
                width=width,
                height=height,
                resolution=resolution,
                data=data,
            )
        return self._check_circle(
            target_mx=target_mx,
            target_my=target_my,
            width=width,
            height=height,
            resolution=resolution,
            data=data,
        )

    def _check_circle(
        self,
        *,
        target_mx: int,
        target_my: int,
        width: int,
        height: int,
        resolution: float,
        data: list[int],
    ) -> NavigationSafetyResult:
        radius_cells = math.ceil(self._safety_radius_m / resolution)

        for my in range(target_my - radius_cells, target_my + radius_cells + 1):
            for mx in range(target_mx - radius_cells, target_mx + radius_cells + 1):
                if not self._cell_in_bounds(mx, my, width, height):
                    return self._result(
                        False,
                        "target_radius_outside_map",
                        target_cell={"mx": target_mx, "my": target_my},
                        blocking_cell={"mx": mx, "my": my, "value": -1},
                    )
                if math.hypot(mx - target_mx, my - target_my) * resolution > self._safety_radius_m:
                    continue
                blocked = self._cell_blocks(data, width, mx, my)
                if blocked is not None:
                    reason, value = blocked
                    return self._result(
                        False,
                        reason,
                        target_cell={"mx": target_mx, "my": target_my},
                        blocking_cell={"mx": mx, "my": my, "value": value},
                    )

        return self._result(
            True,
            "target_area_free",
            target_cell={"mx": target_mx, "my": target_my},
        )

    def _check_footprint(
        self,
        *,
        occupancy_grid: Any,
        target: WorkspacePose,
        target_mx: int,
        target_my: int,
        width: int,
        height: int,
        resolution: float,
        data: list[int],
    ) -> NavigationSafetyResult:
        half_length = self._robot_length_m / 2.0 + self._collision_offset_m
        half_width = self._robot_width_m / 2.0 + self._collision_offset_m
        cos_yaw = math.cos(target.yaw)
        sin_yaw = math.sin(target.yaw)

        # Axis-aligned bounds of the rotated rectangle, plus one cell padding.
        corner_offsets = (
            (half_length, half_width),
            (half_length, -half_width),
            (-half_length, half_width),
            (-half_length, -half_width),
        )
        world_xs: list[float] = []
        world_ys: list[float] = []
        for local_x, local_y in corner_offsets:
            world_xs.append(target.x + cos_yaw * local_x - sin_yaw * local_y)
            world_ys.append(target.y + sin_yaw * local_x + cos_yaw * local_y)

        min_mx = max(0, math.floor((min(world_xs) - occupancy_grid.info.origin.position.x) / resolution) - 1)
        max_mx = min(
            width - 1,
            math.ceil((max(world_xs) - occupancy_grid.info.origin.position.x) / resolution) + 1,
        )
        min_my = max(0, math.floor((min(world_ys) - occupancy_grid.info.origin.position.y) / resolution) - 1)
        max_my = min(
            height - 1,
            math.ceil((max(world_ys) - occupancy_grid.info.origin.position.y) / resolution) + 1,
        )

        for my in range(min_my, max_my + 1):
            for mx in range(min_mx, max_mx + 1):
                wx = occupancy_grid.info.origin.position.x + (mx + 0.5) * resolution
                wy = occupancy_grid.info.origin.position.y + (my + 0.5) * resolution
                if not self._point_in_oriented_footprint(
                    wx,
                    wy,
                    target.x,
                    target.y,
                    cos_yaw,
                    sin_yaw,
                    half_length,
                    half_width,
                ):
                    continue
                blocked = self._cell_blocks(data, width, mx, my)
                if blocked is not None:
                    reason, value = blocked
                    footprint_reason = reason.replace("_radius", "_footprint")
                    return self._result(
                        False,
                        footprint_reason,
                        target_cell={"mx": target_mx, "my": target_my},
                        blocking_cell={"mx": mx, "my": my, "value": value},
                    )

        return self._result(
            True,
            "target_area_free",
            target_cell={"mx": target_mx, "my": target_my},
        )

    def _cell_blocks(self, data: list[int], width: int, mx: int, my: int) -> tuple[str, int] | None:
        value = int(data[my * width + mx])
        if value < 0 and self._reject_unknown:
            return "unknown_cell_in_target_radius", value
        if value >= self._occupied_threshold:
            return "occupied_cell_in_target_radius", value
        return None

    @staticmethod
    def _point_in_oriented_footprint(
        wx: float,
        wy: float,
        cx: float,
        cy: float,
        cos_yaw: float,
        sin_yaw: float,
        half_length: float,
        half_width: float,
    ) -> bool:
        dx = wx - cx
        dy = wy - cy
        local_x = cos_yaw * dx + sin_yaw * dy
        local_y = -sin_yaw * dx + cos_yaw * dy
        return abs(local_x) <= half_length and abs(local_y) <= half_width

    def _world_to_map(self, occupancy_grid: Any, x: float, y: float) -> tuple[int, int] | None:
        """Convert map-frame meters into OccupancyGrid cell coordinates."""
        info = occupancy_grid.info
        origin = info.origin.position
        resolution = float(info.resolution)
        mx = math.floor((x - float(origin.x)) / resolution)
        my = math.floor((y - float(origin.y)) / resolution)
        width = int(info.width)
        height = int(info.height)
        if not self._cell_in_bounds(mx, my, width, height):
            return None
        return mx, my

    @staticmethod
    def _cell_in_bounds(mx: int, my: int, width: int, height: int) -> bool:
        """Return whether a map cell index is inside the OccupancyGrid bounds."""
        return 0 <= mx < width and 0 <= my < height

    def _result(
        self,
        safe: bool,
        reason: str,
        *,
        target_cell: dict[str, int] | None = None,
        blocking_cell: dict[str, int] | None = None,
    ) -> NavigationSafetyResult:
        """Build a safety result using this checker's configured geometry."""
        return NavigationSafetyResult(
            safe=safe,
            reason=reason,
            radius_m=self.safety_radius_m,
            mode=self._mode,
            target_cell=target_cell or {},
            blocking_cell=blocking_cell or {},
        )


__all__ = [
    "NavigationSafetyResult",
    "OccupancyGridSafetyChecker",
    "SafetyCheckMode",
]
