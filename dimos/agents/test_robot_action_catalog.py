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

from dimos.agents.robot_action_catalog import (
    GO_HOME,
    MOVE_RELATIVE,
    MOVE_TO_WORKSPACE,
    VLA_DROP_SKU,
    VLA_PICK_SKU,
    default_robot_action_catalog,
    get_robot_action_spec,
    list_robot_action_specs,
    require_robot_action_spec,
)


def test_default_catalog_contains_task_level_actions_only() -> None:
    catalog = default_robot_action_catalog()

    assert set(catalog.names()) == {
        "move_to_workspace",
        "move_relative",
        "vla_pick_sku",
        "vla_drop_sku",
        "go_home",
    }


def test_action_spec_constants_keep_existing_action_names() -> None:
    assert MOVE_TO_WORKSPACE.name == "move_to_workspace"
    assert MOVE_RELATIVE.name == "move_relative"
    assert VLA_PICK_SKU.name == "vla_pick_sku"
    assert VLA_DROP_SKU.name == "vla_drop_sku"
    assert GO_HOME.name == "go_home"


def test_catalog_does_not_include_dax_atomic_skills() -> None:
    action_names = {spec.name for spec in list_robot_action_specs()}

    assert "joint_move" not in action_names
    assert "cartesian_move" not in action_names
    assert "cartesian_delta_move" not in action_names
    assert "hand_move" not in action_names


def test_default_actions_are_not_mcp_tools() -> None:
    for spec in list_robot_action_specs():
        assert spec.llm_exposable is False
        assert spec.mcp_tool is False


def test_vla_drop_sku_maps_to_dax_place_yaml() -> None:
    spec = require_robot_action_spec("vla_drop_sku")

    assert spec.executor == "upper_body_motion"
    assert spec.backend == "dax_skill_sdk"
    assert spec.adapter == "DaxSkillSdkAdapter.place"
    assert spec.yaml_name == "place.yaml"
    assert spec.required_slots == (
        "workspace_name",
        "workspace_color",
        "sku_name",
        "sku_color",
    )
    assert "target_workspace_reached" in spec.safety_gates
    assert "validated_payload" not in spec.metadata_keys


def test_go_home_maps_to_atomic_orchestrator() -> None:
    spec = require_robot_action_spec("go_home")

    assert spec.executor == "dax"
    assert spec.backend == "dax_skill_sdk"
    assert spec.adapter == "GoHomeOrchestrator.run"
    assert spec.yaml_name == ""
    assert spec.required_slots == ()
    assert "manual_or_recovery_only" in spec.safety_gates


def test_move_to_workspace_is_lower_body_ros_topic_action() -> None:
    spec = require_robot_action_spec("move_to_workspace")

    assert spec.executor == "lower_body_nav"
    assert spec.backend == "ros_topic"


def test_move_relative_is_lower_body_ros_topic_action() -> None:
    spec = require_robot_action_spec("move_relative")

    assert spec.executor == "lower_body_nav"
    assert spec.backend == "ros_topic"
    assert spec.required_slots == ("direction", "distance_units")
    assert "target_pose_computed_from_current_pose" in spec.safety_gates
    assert "target_radius_occupancy_grid_checked" in spec.safety_gates


def test_pick_sku_is_upper_body_motion_action() -> None:
    spec = require_robot_action_spec("vla_pick_sku")

    assert spec.executor == "upper_body_motion"
    assert spec.backend == "vla_py_rosbridge"


def test_get_robot_action_spec_returns_none_for_unknown_action() -> None:
    assert get_robot_action_spec("joint_move") is None


def test_specs_do_not_store_absolute_source_paths() -> None:
    for spec in list_robot_action_specs():
        assert not hasattr(spec, "source_of_truth")
        assert "/home/miaoli" not in str(spec.to_dict())
