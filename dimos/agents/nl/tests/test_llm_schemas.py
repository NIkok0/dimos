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

from dimos.agents.nl.llm.schemas import IntentCandidate, NLUnderstandingResult, PickSkuSlots


def test_nl_understanding_accepts_null_clarification_question() -> None:
    result = NLUnderstandingResult.model_validate(
        {
            "primary_intent": {
                "intent_type": "move_relative",
                "confidence": 0.9,
                "slots": {"direction": "forward", "distance_meters": 1.0},
            },
            "needs_clarification": False,
            "clarification_question": None,
        }
    )
    assert result.clarification_question == ""


def test_intent_candidate_accepts_null_reasoning() -> None:
    result = IntentCandidate.model_validate(
        {
            "intent_type": "pick_sku",
            "confidence": 0.9,
            "slots": {},
            "reasoning": None,
        }
    )
    assert result.reasoning == ""


def test_pick_sku_slots_accepts_null_goal_table_color() -> None:
    result = PickSkuSlots.model_validate(
        {
            "table_color": "blue",
            "object_color": "red",
            "goal_table_color": None,
        }
    )
    assert result.goal_table_color == ""
