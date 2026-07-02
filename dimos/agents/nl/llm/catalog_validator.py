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

"""Validate and normalize LLM parse output using the NL semantic catalog."""

from __future__ import annotations

from dimos.agents.nl.llm.schemas import IntentCandidate, IntentValidationResult
from dimos.agents.nl.navigation_semantic_mapper import (
    NavigationSemanticMapper,
    get_nl_semantic_mapper,
)


class CatalogSlotValidator:
    """Normalize LLM slots via mapper and validate required fields."""

    def __init__(self, mapper: NavigationSemanticMapper | None = None) -> None:
        self._mapper = mapper or get_nl_semantic_mapper()

    def validate(
        self,
        candidate: IntentCandidate,
        raw_text: str,
    ) -> IntentValidationResult:
        intent_type = candidate.intent_type
        normalized = self._mapper.normalize_llm_slots(
            intent_type,
            dict(candidate.slots),
            raw_text=raw_text,
        )
        validation = self._mapper.validate_required_slots(intent_type, normalized)
        if validation is not None:
            return IntentValidationResult(
                is_valid=False,
                validated_slots=normalized,
                validation_errors=[validation.message or "Validation failed"],
                confidence_adjustment=-0.5,
                rejected_error_code=validation.error_code,
            )
        return IntentValidationResult(
            is_valid=True,
            validated_slots=normalized,
            validation_errors=[],
            confidence_adjustment=0.0,
        )


__all__ = ["CatalogSlotValidator"]
