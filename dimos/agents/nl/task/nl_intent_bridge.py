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

"""LLM-primary NL intent parsing bridge to TaskIntent."""

from __future__ import annotations

import uuid
from typing import Any

from dimos.agents.nl.bootstrap import ensure_nl_semantics_loaded
from dimos.agents.nl.core.hybrid_router import HybridIntentRouter, HybridRouterConfig
from dimos.agents.nl.core.protocols import RoutingDecision
from dimos.agents.nl.core.registry import intent_parser_registry
from dimos.agents.nl.core.router import RouterConfig
from dimos.agents.nl.llm.catalog_validator import CatalogSlotValidator
from dimos.agents.nl.llm.model_resolver import resolve_nl_llm_model
from dimos.agents.nl.llm.parser import LLMIntentParser
from dimos.agents.nl.navigation_semantic_mapper import get_nl_semantic_mapper
from dimos.agents.skill_result import SkillResult
from dimos.core.global_config import global_config

_hybrid_router: HybridIntentRouter | None = None


def get_nl_hybrid_router() -> HybridIntentRouter:
    global _hybrid_router
    if _hybrid_router is not None:
        return _hybrid_router

    catalog = ensure_nl_semantics_loaded()
    hybrid_config = HybridRouterConfig(
        llm_as_primary=True,
        use_llm_fallback=False,
        validate_llm_with_rules=False,
    )
    llm_parser = LLMIntentParser(
        model=resolve_nl_llm_model(),
        validator=CatalogSlotValidator(get_nl_semantic_mapper()),
        catalog=catalog,
    )
    _hybrid_router = HybridIntentRouter(
        registry=intent_parser_registry,
        config=RouterConfig(min_confidence=0.5),
        hybrid_config=hybrid_config,
        llm_parser=llm_parser,
    )
    return _hybrid_router


def reset_nl_hybrid_router() -> None:
    global _hybrid_router
    _hybrid_router = None


def routing_decision_to_task_intent(
    decision: RoutingDecision,
    *,
    raw_instruction: str,
    request_id: str,
):
    from dimos.agents.nl.task.router import TaskIntent

    mapper = get_nl_semantic_mapper()
    slots = mapper.normalize_llm_slots(
        decision.intent_type,
        dict(decision.slots),
        raw_text=raw_instruction,
    )
    validation = mapper.validate_required_slots(decision.intent_type, slots)
    if validation is not None:
        return validation

    return TaskIntent(
        request_id=_request_id(request_id),
        raw_instruction=raw_instruction,
        intent_type=decision.intent_type,
        slots=slots,
    )


def parse_nl_intent(
    raw_instruction: str,
    *,
    request_id: str = "",
):
    if not global_config.nl_llm_primary_enabled:
        return SkillResult(
            success=False,
            error_code="UNSUPPORTED_INTENT",
            message="LLM-primary NL parsing is disabled.",
            metadata={"request_id": _request_id(request_id), "raw_instruction": raw_instruction},
        )

    router = get_nl_hybrid_router()
    decision = router.route(
        raw_instruction,
        context={"request_id": request_id},
    )
    if decision is None:
        llm_result = router.last_llm_result
        if llm_result is not None and not llm_result.success and llm_result.error_code:
            return SkillResult(
                success=False,
                error_code=llm_result.error_code,
                message=llm_result.error_code or "Could not parse instruction.",
                metadata={
                    "request_id": _request_id(request_id),
                    "raw_instruction": raw_instruction,
                },
            )
        if llm_result is not None and llm_result.success and llm_result.confidence < 0.5:
            return SkillResult(
                success=False,
                error_code="LOW_CONFIDENCE",
                message=f"LLM confidence too low ({llm_result.confidence:.2f}).",
                metadata={
                    "request_id": _request_id(request_id),
                    "raw_instruction": raw_instruction,
                },
            )
        return SkillResult(
            success=False,
            error_code="NEED_CLARIFICATION",
            message="Could not parse instruction.",
            metadata={"request_id": _request_id(request_id), "raw_instruction": raw_instruction},
        )

    return routing_decision_to_task_intent(
        decision,
        raw_instruction=raw_instruction,
        request_id=request_id,
    )


def _request_id(request_id: str) -> str:
    if request_id:
        return request_id
    return f"req-{uuid.uuid4().hex}"


__all__ = [
    "get_nl_hybrid_router",
    "parse_nl_intent",
    "reset_nl_hybrid_router",
    "routing_decision_to_task_intent",
]
