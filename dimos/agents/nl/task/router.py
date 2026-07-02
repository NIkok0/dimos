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

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from dimos.agents.skill_result import SkillResult
from dimos.agents.task_action_plan import (
    ActionPlan,
    FetchSkuTemplate,
    GuardLoopTemplate,
    MoveRelativeTemplate,
    MoveToWorkspaceTemplate,
    PickSkuTemplate,
)
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

NlTaskRouterError = Literal[
    "NEED_CLARIFICATION",
    "UNSUPPORTED_INTENT",
    "INVALID_SLOT",
    "ROUTE_NOT_CONFIGURED",
]

RouteHandlerKey = Literal[
    "action_plan",
    "move_to_workspace",
    "move_relative",
    "pick_sku",
    "fetch_sku",
    "guard_loop",
]

RouteHandler = Callable[..., SkillResult[Any]]


@dataclass(frozen=True)
class TaskIntent:
    request_id: str
    raw_instruction: str
    intent_type: str
    slots: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillRoute:
    name: str
    intent_type: str
    handler_name: str
    required_slots: tuple[str, ...]
    template_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class TaskExecutor(Protocol):
    def execute_text(self, text: str, request_id: str = "") -> SkillResult[Any]: ...


class TaskRouteCatalog:
    def __init__(self, routes: list[SkillRoute] | None = None) -> None:
        self._routes_by_intent: dict[str, SkillRoute] = {}
        for route in routes or []:
            self.register(route)

    def register(self, route: SkillRoute) -> None:
        self._routes_by_intent[route.intent_type] = route

    def get(self, intent_type: str) -> SkillRoute | None:
        return self._routes_by_intent.get(intent_type)


class TaskRouter:
    def __init__(self, catalog: TaskRouteCatalog) -> None:
        self._catalog = catalog

    def route(self, intent: TaskIntent) -> SkillResult[NlTaskRouterError]:
        route = self._catalog.get(intent.intent_type)
        if route is None:
            logger.info(
                "NL route rejected",
                trace_layer="agent_nl",
                trace_stage="route_rejected",
                request_id=intent.request_id,
                intent_type=intent.intent_type,
                phase="route",
                reason="unsupported_intent",
            )
            return SkillResult(
                success=False,
                error_code="UNSUPPORTED_INTENT",
                message=f"No whitelisted route for intent {intent.intent_type!r}.",
                metadata={"intent": intent.to_dict()},
            )

        logger.info(
            "NL route matched",
            trace_layer="agent_nl",
            trace_stage="route_matched",
            request_id=intent.request_id,
            intent_type=intent.intent_type,
            phase="route",
            route=route.name,
            template=route.template_name,
            route_detail=route.to_dict(),
        )
        return SkillResult.ok(
            "Matched NL task route.",
            intent=intent.to_dict(),
            route=route,
        )


class InProcessTaskExecutor:
    def __init__(
        self,
        router: TaskRouter,
        *,
        route_handlers: dict[RouteHandlerKey, RouteHandler],
    ) -> None:
        self._router = router
        self._route_handlers = route_handlers

    def execute_text(self, text: str, request_id: str = "") -> SkillResult[Any]:
        logger.info(
            "NL task received",
            trace_layer="agent_nl",
            trace_stage="received",
            request_id=request_id,
            phase="parse",
            text=text,
        )
        intent = parse_nl_task_intent(text, request_id=request_id)
        if isinstance(intent, SkillResult):
            logger.info(
                "NL task parse failed",
                trace_layer="agent_nl",
                trace_stage="parse_failed",
                request_id=request_id,
                phase="parse",
                error_code=intent.error_code,
                message=intent.message,
                metadata=intent.metadata,
            )
            return intent
        logger.info(
            "NL task parsed",
            trace_layer="agent_nl",
            trace_stage="parsed",
            request_id=intent.request_id,
            intent_type=intent.intent_type,
            phase="parse",
            slots=intent.slots,
            intent=intent.to_dict(),
        )

        route_result = self._router.route(intent)
        if not route_result.success:
            logger.info(
                "NL task routing failed",
                trace_layer="agent_nl",
                trace_stage="routing_failed",
                request_id=intent.request_id,
                intent_type=intent.intent_type,
                phase="route",
                error_code=route_result.error_code,
                message=route_result.message,
                metadata=route_result.metadata,
            )
            return route_result

        route = route_result.metadata["route"]
        if not isinstance(route, SkillRoute):
            logger.info(
                "NL task route metadata invalid",
                trace_layer="agent_nl",
                trace_stage="route_metadata_invalid",
                request_id=intent.request_id,
                intent_type=intent.intent_type,
                phase="route",
            )
            return SkillResult(
                success=False,
                error_code="ROUTE_NOT_CONFIGURED",
                message="Route metadata was not executable.",
                metadata={"intent": intent.to_dict()},
            )

        try:
            action_plan = compose_action_plan(intent, route)
        except (ValueError, KeyError, TypeError) as exc:
            logger.info(
                "NL task action plan compose failed",
                trace_layer="agent_nl",
                trace_stage="action_plan_compose_failed",
                request_id=intent.request_id,
                intent_type=intent.intent_type,
                phase="plan",
                route=route.name,
                template=route.template_name,
                error=str(exc),
            )
            return SkillResult(
                success=False,
                error_code="UNSUPPORTED_INTENT",
                message=f"Action plan composition failed: {exc}",
                metadata={
                    "intent": intent.to_dict(),
                    "route": route.to_dict(),
                },
            )
        logger.info(
            "NL task action plan composed",
            trace_layer="agent_nl",
            trace_stage="action_plan_composed",
            request_id=intent.request_id,
            intent_type=intent.intent_type,
            phase="plan",
            route=route.name,
            template=route.template_name,
            step_count=len(action_plan.steps),
            action_plan=action_plan.to_dict(),
        )
        plan_handler = self._route_handlers.get("action_plan")
        if plan_handler is not None and action_plan is not None:
            result = plan_handler(intent=intent.to_dict(), action_plan=action_plan)
            result.metadata.setdefault("intent", intent.to_dict())
            result.metadata.setdefault("route", route.to_dict())
            result.metadata.setdefault("action_plan", action_plan.to_dict())
            logger.info(
                "NL task completed",
                trace_layer="agent_nl",
                trace_stage="completed",
                request_id=intent.request_id,
                intent_type=intent.intent_type,
                route=route.name,
                success=result.success,
                error_code=result.error_code,
                phase=result.metadata.get("phase"),
                message=result.message,
                action_plan=action_plan.to_dict(),
            )
            return result

        handler = self._route_handlers.get(route.name)
        if handler is None:
            logger.info(
                "NL task handler missing",
                trace_layer="agent_nl",
                trace_stage="handler_missing",
                request_id=intent.request_id,
                intent_type=intent.intent_type,
                phase="execute",
                route=route.name,
            )
            return SkillResult(
                success=False,
                error_code="ROUTE_NOT_CONFIGURED",
                message=f"No handler configured for route {route.name!r}.",
                metadata={
                    "intent": intent.to_dict(),
                    "route": route.to_dict(),
                    "action_plan": action_plan.to_dict(),
                },
            )

        result = handler(**dict(intent.slots))
        result.metadata.setdefault("intent", intent.to_dict())
        result.metadata.setdefault("route", route.to_dict())
        result.metadata.setdefault("action_plan", action_plan.to_dict())
        logger.info(
            "NL task completed",
            trace_layer="agent_nl",
            trace_stage="completed",
            request_id=intent.request_id,
            intent_type=intent.intent_type,
            route=route.name,
            success=result.success,
            error_code=result.error_code,
            phase=result.metadata.get("phase"),
            message=result.message,
            action_plan=action_plan.to_dict(),
        )
        return result


_ROUTE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "move_to_workspace",
        "intent_type": "move_to_workspace",
        "handler_name": "execute_action_plan",
        "template_name": "move_to_workspace",
    },
    {
        "name": "move_relative",
        "intent_type": "move_relative",
        "handler_name": "execute_action_plan",
        "template_name": "move_relative",
    },
    {
        "name": "pick_sku",
        "intent_type": "pick_sku",
        "handler_name": "execute_action_plan",
        "template_name": "pick_sku",
    },
    {
        "name": "fetch_sku",
        "intent_type": "fetch_sku",
        "handler_name": "execute_fetch_task",
        "template_name": "fetch_sku",
    },
    {
        "name": "guard_loop",
        "intent_type": "guard_loop",
        "handler_name": "execute_guard_loop",
        "template_name": "guard_loop",
    },
)


def _required_slots_from_catalog(intent_type: str) -> tuple[str, ...] | None:
    try:
        from dimos.agents.nl.bootstrap import ensure_nl_semantics_loaded

        catalog = ensure_nl_semantics_loaded()
        spec = catalog.intents.get(intent_type)
        if spec is not None:
            return spec.required_slots
    except Exception as exc:
        logger.warning(
            "Failed to load required_slots from catalog",
            intent_type=intent_type,
            error=str(exc),
        )
    return None


def default_task_route_catalog() -> TaskRouteCatalog:
    routes: list[SkillRoute] = []
    for definition in _ROUTE_DEFINITIONS:
        required_slots = _required_slots_from_catalog(definition["intent_type"])
        if required_slots is None:
            raise RuntimeError(
                f"required_slots for intent {definition['intent_type']!r} not found "
                "in nl_semantics catalog — ensure config/nl_semantics.yaml is loaded."
            )
        routes.append(
            SkillRoute(
                name=definition["name"],
                intent_type=definition["intent_type"],
                handler_name=definition["handler_name"],
                required_slots=required_slots,
                template_name=definition["template_name"],
            )
        )
    return TaskRouteCatalog(routes)


def parse_nl_task_intent(
    raw_instruction: str,
    *,
    request_id: str = "",
) -> TaskIntent | SkillResult[NlTaskRouterError]:
    from dimos.agents.nl.task.nl_intent_bridge import parse_nl_intent

    return parse_nl_intent(raw_instruction, request_id=request_id)


def compose_action_plan(intent: TaskIntent, route: SkillRoute) -> ActionPlan:
    if route.template_name == "move_relative":
        return MoveRelativeTemplate().compose(intent.to_dict())
    if route.template_name == "move_to_workspace":
        return MoveToWorkspaceTemplate().compose(intent.to_dict())
    if route.template_name == "pick_sku":
        return PickSkuTemplate().compose(intent.to_dict())
    if route.template_name == "fetch_sku":
        return FetchSkuTemplate().compose(intent.to_dict())
    if route.template_name == "guard_loop":
        return GuardLoopTemplate().compose(intent.to_dict())
    raise ValueError(
        f"No ActionPlan template registered for route template {route.template_name!r}."
    )


__all__ = [
    "InProcessTaskExecutor",
    "NlTaskRouterError",
    "RouteHandlerKey",
    "SkillRoute",
    "TaskExecutor",
    "TaskIntent",
    "TaskRouteCatalog",
    "TaskRouter",
    "compose_action_plan",
    "default_task_route_catalog",
    "parse_nl_task_intent",
]
