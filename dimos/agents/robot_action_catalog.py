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

"""任务级机器人动作映射表。

本模块维护 Agent 内部可编排的 task-level action，而不是 MCP tool 或
Dax atomic skill。它把动作名、slot、executor、backend、adapter/YAML、
安全门和 metadata contract 集中到一个只读 catalog，供路由、模板、评审
和测试对齐；Dax README/YAML 仍是开发事实源，不写入运行时规格。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

RobotActionExecutor = Literal["sys_navigation", "vla", "dax", "lower_body_nav", "upper_body_motion"]
RobotActionBackend = Literal["py_rosbridge", "vla_py_rosbridge", "dax_skill_sdk", "internal", "ros_topic", "sod"]


@dataclass(frozen=True)
class RobotActionSpec:
    """Describe one task-level robot action that ActionPlan may compose."""

    name: str
    description: str
    executor: RobotActionExecutor
    backend: RobotActionBackend
    required_slots: tuple[str, ...]
    optional_slots: tuple[str, ...] = ()
    adapter: str = ""
    yaml_name: str = ""
    safety_gates: tuple[str, ...] = ()
    metadata_keys: tuple[str, ...] = ()
    llm_exposable: bool = False
    mcp_tool: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly view for tests, docs, or diagnostics."""
        return asdict(self)


class RobotActionCatalog:
    """Read-only lookup table for task-level robot action specs."""

    def __init__(self, specs: tuple[RobotActionSpec, ...]) -> None:
        self._specs_by_name = {spec.name: spec for spec in specs}

    def get(self, name: str) -> RobotActionSpec | None:
        """Return an action spec by name, or None when it is not registered."""
        return self._specs_by_name.get(name)

    def require(self, name: str) -> RobotActionSpec:
        """Return an action spec or raise KeyError for programming errors."""
        spec = self.get(name)
        if spec is None:
            raise KeyError(f"robot action {name!r} is not registered")
        return spec

    def list(self) -> tuple[RobotActionSpec, ...]:
        """Return all action specs in deterministic registration order."""
        return tuple(self._specs_by_name.values())

    def names(self) -> tuple[str, ...]:
        """Return all registered action names in deterministic registration order."""
        return tuple(self._specs_by_name)


MOVE_TO_WORKSPACE = RobotActionSpec(
    name="move_to_workspace",
    description="Navigate the robot to a named workspace before manipulation or patrol.",
    executor="lower_body_nav",
    backend="ros_topic",
    required_slots=("workspace_name", "workspace_color"),
    adapter="SysNavigationAdapter.navigate_to_workspace",
    safety_gates=(
        "workspace_resolved",
        "navigation_must_arrive_before_dependent_steps",
    ),
    metadata_keys=(
        "navigation_results",
        "sys_task_id",
        "final_robot_state",
    ),
)

MOVE_RELATIVE = RobotActionSpec(
    name="move_relative",
    description="Move the robot a number of map cells (5 cm each) in a body-frame direction.",
    executor="lower_body_nav",
    backend="ros_topic",
    required_slots=("direction", "distance_units"),
    optional_slots=("raw_distance_mentioned",),
    adapter="NavigationAdapter.move_relative",
    safety_gates=(
        "localization_ready",
        "target_pose_computed_from_current_pose",
        "target_radius_occupancy_grid_checked",
        "navigation_must_arrive_before_dependent_steps",
    ),
    metadata_keys=(
        "navigation_results",
        "relative_motion",
        "computed_goal",
        "safety_check",
    ),
)

VLA_PICK_SKU = RobotActionSpec(
    name="vla_pick_sku",
    description="Use VLA perception to pick a target SKU from the current workspace.",
    executor="upper_body_motion",
    backend="vla_py_rosbridge",
    required_slots=("workspace_name", "workspace_color", "sku_name", "sku_color"),
    adapter="VlaActionClient.pick_sku",
    safety_gates=(
        "workspace_reached",
        "target_meta_matches_request",
        "joint_action_required_before_ros_forwarding",
    ),
    metadata_keys=(
        "raw_payload",
        "validated_payload",
        "target_meta",
        "joint_action",
        "validation_passed",
    ),
)

VLA_DROP_SKU = RobotActionSpec(
    name="vla_drop_sku",
    description="Place the currently held SKU into the target workspace through Dax place.",
    executor="upper_body_motion",
    backend="dax_skill_sdk",
    required_slots=("workspace_name", "workspace_color", "sku_name", "sku_color"),
    adapter="DaxSkillSdkAdapter.place",
    yaml_name="place.yaml",
    safety_gates=(
        "source_pick_succeeded",
        "target_workspace_reached",
        "do_not_forward_validated_payload_to_ros",
    ),
    metadata_keys=(
        "sdk",
        "composite_skill",
        "inputs",
        "dax_results",
        "failed_step",
        "duration_ms",
    ),
)

GO_HOME = RobotActionSpec(
    name="go_home",
    description="Return the Dax-controlled body to a known home pose for recovery or setup.",
    executor="dax",
    backend="dax_skill_sdk",
    required_slots=(),
    adapter="DaxSkillSdkAdapter.go_home",
    yaml_name="go_home.yaml",
    safety_gates=(
        "manual_or_recovery_only",
        "runtime_ready",
    ),
    metadata_keys=(
        "sdk",
        "composite_skill",
        "inputs",
        "dax_results",
        "failed_step",
        "duration_ms",
    ),
)


def default_robot_action_catalog() -> RobotActionCatalog:
    """Build the default task-level action catalog used by VLA Pick planning."""
    return RobotActionCatalog(
        (
            MOVE_TO_WORKSPACE,
            MOVE_RELATIVE,
            VLA_PICK_SKU,
            VLA_DROP_SKU,
            GO_HOME,
        )
    )


def get_robot_action_spec(name: str) -> RobotActionSpec | None:
    """Look up one action in the default catalog."""
    return default_robot_action_catalog().get(name)


def require_robot_action_spec(name: str) -> RobotActionSpec:
    """Look up one action in the default catalog and fail if missing."""
    return default_robot_action_catalog().require(name)


def list_robot_action_specs() -> tuple[RobotActionSpec, ...]:
    """List all actions in the default catalog."""
    return default_robot_action_catalog().list()


__all__ = [
    "GO_HOME",
    "MOVE_RELATIVE",
    "MOVE_TO_WORKSPACE",
    "RobotActionBackend",
    "RobotActionCatalog",
    "RobotActionExecutor",
    "RobotActionSpec",
    "VLA_DROP_SKU",
    "VLA_PICK_SKU",
    "default_robot_action_catalog",
    "get_robot_action_spec",
    "list_robot_action_specs",
    "require_robot_action_spec",
]
