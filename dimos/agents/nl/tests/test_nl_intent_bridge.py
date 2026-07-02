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

from typing import Any

import pytest

from dimos.agents.nl.bootstrap import reset_navigation_bootstrap
from dimos.agents.nl.core.protocols import ParseResult
from dimos.agents.nl.llm.catalog_validator import CatalogSlotValidator
from dimos.agents.nl.llm.schemas import IntentCandidate
from dimos.agents.nl.navigation_semantic_mapper import get_nl_semantic_mapper
from dimos.agents.nl.task.nl_intent_bridge import reset_nl_hybrid_router
from dimos.agents.nl.task.router import TaskIntent, parse_nl_task_intent


@pytest.fixture(autouse=True)
def _reset_runtime() -> None:
    reset_navigation_bootstrap()
    reset_nl_hybrid_router()
    yield
    reset_navigation_bootstrap()
    reset_nl_hybrid_router()


def _mock_llm_parse(_self: Any, text: str, context: dict[str, Any] | None = None) -> ParseResult:
    if "向后移动" in text:
        return ParseResult(
            success=True,
            intent_type="move_relative",
            slots={"direction": "backward", "distance_meters": 1.0},
            confidence=0.95,
        )
    if "前方固定工作区" in text or "前方工作区" in text:
        return ParseResult(
            success=True,
            intent_type="move_to_workspace",
            slots={"workspace_name": "front_workspace", "workspace_color": ""},
            confidence=0.95,
        )
    if "蓝色桌子" in text and "抓" not in text:
        return ParseResult(
            success=True,
            intent_type="move_to_workspace",
            slots={"workspace_name": "table", "workspace_color": "blue"},
            confidence=0.95,
        )
    if "抓" in text and "方块" in text:
        return ParseResult(
            success=True,
            intent_type="pick_sku",
            slots={
                "workspace_type": "table",
                "table_color": "red",
                "object_type": "cube",
                "object_color": "blue",
            },
            confidence=0.92,
        )
    return ParseResult(success=False, error_code="NO_MATCH")


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    from dimos.agents.nl.llm import parser as llm_parser_module

    def _mock_init(self: Any, **kwargs: Any) -> None:
        self._validator = kwargs.get("validator")
        self._catalog = kwargs.get("catalog")
        self._system_prompt = "test"
        self._include_few_shot = kwargs.get("include_few_shot", False)
        self._use_structured_output = kwargs.get("use_structured_output", False)
        self._llm = None

    monkeypatch.setattr(llm_parser_module.LLMIntentParser, "__init__", _mock_init)
    monkeypatch.setattr(llm_parser_module.LLMIntentParser, "parse", _mock_llm_parse)


class TestCatalogSlotValidator:
    def test_normalizes_pick_slots(self) -> None:
        validator = CatalogSlotValidator(get_nl_semantic_mapper())
        result = validator.validate(
            IntentCandidate(
                intent_type="pick_sku",
                confidence=0.9,
                slots={
                    "workspace_type": "table",
                    "table_color": "red",
                    "object_type": "cube",
                    "object_color": "blue",
                },
            ),
            "去红色桌子抓蓝色方块",
        )
        assert result.is_valid
        assert result.validated_slots["workspace_name"] == "table"
        assert result.validated_slots["workspace_color"] == "red"
        assert result.validated_slots["sku_color"] == "blue"

    def test_rejects_missing_direction(self) -> None:
        validator = CatalogSlotValidator(get_nl_semantic_mapper())
        result = validator.validate(
            IntentCandidate(
                intent_type="move_relative",
                confidence=0.9,
                slots={"distance_meters": 1.0},
            ),
            "移动1米",
        )
        assert not result.is_valid

    def test_rejects_invalid_workspace_color(self) -> None:
        validator = CatalogSlotValidator(get_nl_semantic_mapper())
        result = validator.validate(
            IntentCandidate(
                intent_type="pick_sku",
                confidence=0.9,
                slots={
                    "workspace_type": "table",
                    "table_color": "yellow",
                    "object_type": "cube",
                    "object_color": "red",
                },
            ),
            "去黄色桌子抓红色方块",
        )
        assert not result.is_valid
        assert result.rejected_error_code == "INVALID_SLOT"

    def test_rejects_same_color_pick(self) -> None:
        validator = CatalogSlotValidator(get_nl_semantic_mapper())
        result = validator.validate(
            IntentCandidate(
                intent_type="pick_sku",
                confidence=0.9,
                slots={
                    "workspace_type": "table",
                    "table_color": "blue",
                    "object_type": "cube",
                    "object_color": "blue",
                },
            ),
            "去蓝色桌子抓蓝色方块",
        )
        assert not result.is_valid
        assert result.rejected_error_code == "INVALID_SLOT"


class TestParseNlTaskIntentWithMockLlm:
    def test_move_relative_via_llm_bridge(self) -> None:
        result = parse_nl_task_intent("向后移动1米")
        assert isinstance(result, TaskIntent)
        assert result.intent_type == "move_relative"
        assert result.slots["direction"] == "backward"
        assert result.slots["distance_units"] == 20.0

    def test_move_to_workspace_front(self) -> None:
        result = parse_nl_task_intent("移动到前方固定工作区")
        assert isinstance(result, TaskIntent)
        assert result.intent_type == "move_to_workspace"
        assert result.slots["workspace_name"] == "front_workspace"

    def test_move_to_workspace_table(self) -> None:
        result = parse_nl_task_intent("前往蓝色桌子")
        assert isinstance(result, TaskIntent)
        assert result.intent_type == "move_to_workspace"
        assert result.slots["workspace_color"] == "blue"

    def test_pick_via_llm(self) -> None:
        result = parse_nl_task_intent("去红色桌子抓蓝色方块")
        assert isinstance(result, TaskIntent)
        assert result.intent_type == "pick_sku"
        assert result.slots["sku_color"] == "blue"
