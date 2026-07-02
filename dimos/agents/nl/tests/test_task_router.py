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

import pytest

from dimos.agents.nl.task.router import (
    SkillRoute,
    TaskIntent,
    TaskRouteCatalog,
    TaskRouter,
    compose_action_plan,
    default_task_route_catalog,
)


def _make_intent(intent_type: str, **slots: object) -> TaskIntent:
    return TaskIntent(
        request_id="test-req",
        raw_instruction="test",
        intent_type=intent_type,
        slots=dict(slots),
    )


class TestTaskRouterRoute:
    def test_unknown_intent_returns_unsupported(self) -> None:
        catalog = TaskRouteCatalog([SkillRoute(
            name="move_relative",
            intent_type="move_relative",
            handler_name="execute_action_plan",
            required_slots=("direction", "distance_units"),
            template_name="move_relative",
        )])
        router = TaskRouter(catalog)
        result = router.route(_make_intent("nonexistent"))
        assert not result.success
        assert result.error_code == "UNSUPPORTED_INTENT"

    def test_known_intent_matches(self) -> None:
        catalog = TaskRouteCatalog([SkillRoute(
            name="move_relative",
            intent_type="move_relative",
            handler_name="execute_action_plan",
            required_slots=("direction", "distance_units"),
            template_name="move_relative",
        )])
        router = TaskRouter(catalog)
        result = router.route(_make_intent("move_relative", direction="forward", distance_units=20.0))
        assert result.success
        assert result.metadata["route"].name == "move_relative"


class TestDefaultTaskRouteCatalog:
    def test_required_slots_match_catalog(self) -> None:
        catalog = default_task_route_catalog()
        pick = catalog.get("pick_sku")
        assert pick is not None
        assert pick.required_slots == ("workspace_name", "workspace_color", "sku_name", "sku_color")

    def test_pick_route_name_is_pick_sku_not_vla_prefixed(self) -> None:
        catalog = default_task_route_catalog()
        pick = catalog.get("pick_sku")
        assert pick is not None
        assert pick.name == "pick_sku"

    def test_all_five_intents_registered(self) -> None:
        catalog = default_task_route_catalog()
        for intent_type in ("move_relative", "move_to_workspace", "pick_sku", "fetch_sku", "guard_loop"):
            assert catalog.get(intent_type) is not None, f"{intent_type} missing from catalog"


class TestComposeActionPlan:
    @pytest.mark.parametrize(
        "intent_type,slots",
        [
            ("move_relative", {"direction": "forward", "distance_units": 20.0}),
            ("move_to_workspace", {"workspace_name": "table", "workspace_color": "blue"}),
            ("pick_sku", {"workspace_name": "table", "workspace_color": "blue", "sku_name": "cube", "sku_color": "red"}),
            (
                "fetch_sku",
                {
                    "source_workspace_name": "table",
                    "source_workspace_color": "blue",
                    "target_workspace_name": "table",
                    "target_workspace_color": "red",
                    "sku_name": "cube",
                    "sku_color": "yellow",
                },
            ),
            ("guard_loop", {"waypoints": [{"workspace_name": "table", "workspace_color": "blue"}, {"workspace_name": "table", "workspace_color": "red"}], "loop_count": 2}),
        ],
    )
    def test_known_templates_produce_action_plan(self, intent_type: str, slots: dict) -> None:
        catalog = default_task_route_catalog()
        route = catalog.get(intent_type)
        assert route is not None
        intent = _make_intent(intent_type, **slots)
        plan = compose_action_plan(intent, route)
        assert plan is not None
        assert plan.intent_type == intent_type

    def test_unknown_template_raises_value_error(self) -> None:
        route = SkillRoute(
            name="bogus",
            intent_type="bogus",
            handler_name="bogus",
            required_slots=(),
            template_name="nonexistent_template",
        )
        intent = _make_intent("bogus")
        with pytest.raises(ValueError, match="nonexistent_template"):
            compose_action_plan(intent, route)
