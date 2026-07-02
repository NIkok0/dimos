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

from pathlib import Path

import pytest

from dimos.agents.nl.navigation_semantic_catalog import (
    DEFAULT_NAVIGATION_SEMANTICS_PATH,
    NavigationSemanticCatalog,
    reset_navigation_semantic_catalog,
)
from dimos.agents.nl.navigation_semantic_mapper import (
    get_navigation_semantic_mapper,
    reset_navigation_semantic_mapper,
)


@pytest.fixture(autouse=True)
def _reset_catalog_singletons() -> None:
    reset_navigation_semantic_catalog()
    reset_navigation_semantic_mapper()
    yield
    reset_navigation_semantic_catalog()
    reset_navigation_semantic_mapper()


class TestNavigationSemanticCatalog:
    def test_load_default_yaml(self) -> None:
        catalog = NavigationSemanticCatalog.from_file(DEFAULT_NAVIGATION_SEMANTICS_PATH)
        assert catalog.version == "nl_semantics_v1"
        assert "forward" in catalog.directions
        assert "front_workspace" in catalog.workspaces
        assert "move_relative" in catalog.intents
        assert "pick_sku" in catalog.intents

    def test_merge_workspace_catalog_aliases(self, tmp_path: Path) -> None:
        workspace_yaml = tmp_path / "workspaces.yaml"
        workspace_yaml.write_text(
            """
front_workspace:
  workspace_id: front_workspace
  name: workspace
  color: front
  aliases:
    - 自定义前方区
blue_table:
  workspace_id: blue_table
  name: table
  color: blue
  aliases:
    - 蓝色工位
""".strip(),
            encoding="utf-8",
        )
        catalog = NavigationSemanticCatalog.from_file(DEFAULT_NAVIGATION_SEMANTICS_PATH)
        merged = catalog.merge_workspace_catalog_file(workspace_yaml)
        front_aliases = merged.workspaces["front_workspace"].aliases
        table_aliases = merged.workspaces["table"].aliases
        assert "自定义前方区" in front_aliases
        assert "蓝色工位" in table_aliases

    def test_invalid_yaml_rejects_empty_direction_aliases(self, tmp_path: Path) -> None:
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(
            "version: v1\nmovement_triggers: [go]\nobject_task_exclusions: [pick]\n"
            "directions:\n  forward:\n    aliases: []\n"
            "distances:\n  semantic_aliases:\n    一点: 0.5\n"
            "colors:\n  red:\n    aliases: [red]\n    nl: 红色\n"
            "workspaces:\n  front_workspace:\n    requires_color: false\n"
            "    aliases: [front]\n"
            "canonical_templates:\n  move_relative: test\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="aliases"):
            NavigationSemanticCatalog.from_file(bad_yaml)

    def test_pick_table_colors_and_trusted_combinations_loaded(self) -> None:
        catalog = NavigationSemanticCatalog.from_file(DEFAULT_NAVIGATION_SEMANTICS_PATH)
        assert catalog.pick.table_colors == ("blue", "red", "green")
        assert "blue" in catalog.pick.trusted_combinations
        assert "red" in catalog.pick.trusted_combinations["blue"]
        assert "yellow" in catalog.pick.trusted_combinations["blue"]

    def test_skus_loaded_with_aliases(self) -> None:
        catalog = NavigationSemanticCatalog.from_file(DEFAULT_NAVIGATION_SEMANTICS_PATH)
        assert "cube" in catalog.skus
        assert "方块" in catalog.skus["cube"].aliases
        assert "立方体" in catalog.skus["cube"].aliases
        assert "box" in catalog.skus
        assert "盒子" in catalog.skus["box"].aliases

    def test_trusted_combinations_key_must_be_in_table_colors(self, tmp_path: Path) -> None:
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(
            "version: v1\nmovement_triggers: [go]\nobject_task_exclusions: [pick]\n"
            "directions:\n  forward:\n    aliases: [forward]\n"
            "distances:\n  semantic_aliases:\n    一点: 0.5\n"
            "colors:\n  red:\n    aliases: [red]\n    nl: 红色\n"
            "workspaces:\n  front_workspace:\n    requires_color: false\n"
            "    aliases: [front]\n"
            "canonical_templates:\n  move_relative: test\n"
            "pick:\n  terms: [pick]\n  table_colors: [blue]\n"
            "  trusted_combinations:\n    purple: [red]\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="trusted_combinations"):
            NavigationSemanticCatalog.from_file(bad_yaml)


class TestNavigationSemanticMapper:
    def test_normalize_direction(self) -> None:
        mapper = get_navigation_semantic_mapper()
        assert mapper.normalize_direction("向后移动1米") == "backward"

    def test_normalize_workspace_front(self) -> None:
        mapper = get_navigation_semantic_mapper()
        assert mapper.normalize_workspace("前往前方工作区") == ("front_workspace", "")

    def test_normalize_workspace_table(self) -> None:
        mapper = get_navigation_semantic_mapper()
        assert mapper.normalize_workspace("前往红色桌子") == ("table", "red")

    def test_build_canonical_nl_move_relative(self) -> None:
        mapper = get_navigation_semantic_mapper()
        text = mapper.build_canonical_nl(
            "move_relative",
            {"direction": "backward", "distance_units": 20.0},
        )
        assert text == "向后移动1米"

    def test_build_canonical_nl_move_to_workspace(self) -> None:
        mapper = get_navigation_semantic_mapper()
        text = mapper.build_canonical_nl(
            "move_to_workspace",
            {"workspace_name": "table", "workspace_color": "blue"},
        )
        assert text == "前往蓝色桌子"

    def test_normalize_sku_name_alias_to_canonical(self) -> None:
        mapper = get_navigation_semantic_mapper()
        assert mapper._normalize_sku_name("方块") == "cube"
        assert mapper._normalize_sku_name("立方体") == "cube"
        assert mapper._normalize_sku_name("盒子") == "box"
        assert mapper._normalize_sku_name("瓶子") == "bottle"

    def test_pick_sku_rejects_untrusted_color_combination(self) -> None:
        mapper = get_navigation_semantic_mapper()
        result = mapper.validate_required_slots(
            "pick_sku",
            {
                "workspace_name": "table",
                "workspace_color": "blue",
                "sku_name": "cube",
                "sku_color": "blue",
            },
        )
        assert result is not None
        assert result.error_code == "INVALID_SLOT"
        assert "Same-color pick" in result.message

    def test_pick_sku_accepts_trusted_color_combination(self) -> None:
        mapper = get_navigation_semantic_mapper()
        result = mapper.validate_required_slots(
            "pick_sku",
            {
                "workspace_name": "table",
                "workspace_color": "blue",
                "sku_name": "cube",
                "sku_color": "red",
            },
        )
        assert result is None

    def test_pick_sku_rejects_unsupported_table_color(self) -> None:
        mapper = get_navigation_semantic_mapper()
        result = mapper.validate_required_slots(
            "pick_sku",
            {
                "workspace_name": "table",
                "workspace_color": "purple",
                "sku_name": "cube",
                "sku_color": "red",
            },
        )
        assert result is not None
        assert result.error_code == "INVALID_SLOT"

    def test_move_relative_rejects_unknown_direction_from_catalog(self) -> None:
        mapper = get_navigation_semantic_mapper()
        result = mapper.validate_move_relative_slots({"direction": "up"})
        assert result is not None
        assert result.error_code == "INVALID_SLOT"

    def test_move_relative_accepts_catalog_direction(self) -> None:
        mapper = get_navigation_semantic_mapper()
        result = mapper.validate_move_relative_slots({"direction": "forward"})
        assert result is None
