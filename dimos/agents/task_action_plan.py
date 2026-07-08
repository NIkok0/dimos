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

"""统一任务计划与机器人动作编排。

本模块把自然语言路由后的 intent 编成 ActionPlan，并按 step executor
分发给导航、VLA、Dax/ROS 等后端。设计上 ActionStep 只保留任务级语义，
不泄漏 Dax atomic skill 或 ROS topic 细节；跨步骤状态通过 metadata store
传递，例如 pick 产出的 held_object 会被 drop 解析成 place.yaml inputs。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from dimos.agents.skill_result import SkillResult
from dimos.agents.robot_action_catalog import (
    GO_HOME,
    MOVE_RELATIVE,
    MOVE_TO_WORKSPACE,
    VLA_DROP_SKU,
    VLA_PICK_SKU,
)
from dimos.agents.vla_pick_adapters import (
    MockRosActionAdapter,
    MockSysNavigationAdapter,
    MockVlaPickClient,
    RosActionAdapter,
    SysNavigationAdapter,
)
from dimos.agents.vla_pick_output_receiver import (
    VlaPickRequest,
    VlaReceiverResult,
)
from dimos.agents.vla_pick_orchestrator import VlaPickOrchestratorError
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

ActionExecutorName = Literal["sys_navigation", "vla", "ros_action", "dax"]
ActionPlanError = VlaPickOrchestratorError | Literal["UNSUPPORTED_PLAN"]


@dataclass(frozen=True)
class ActionStep:
    """One task-level action in an ActionPlan."""

    step_id: str
    executor: ActionExecutorName
    action_type: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionPlan:
    """Ordered task-level steps composed from one parsed user intent."""

    request_id: str
    intent_type: str
    template: str
    steps: list[ActionStep]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [step.to_dict() for step in self.steps]
        return payload


class TaskTemplate(Protocol):
    name: str
    intent_type: str

    def compose(self, intent: dict[str, Any]) -> ActionPlan: ...


class MoveToWorkspaceTemplate:
    """Compose a navigation-only task into one move_to_workspace step."""

    name = "move_to_workspace_template"
    intent_type = "move_to_workspace"

    def compose(self, intent: dict[str, Any]) -> ActionPlan:
        """Build a single-step ActionPlan for moving to a named workspace."""
        slots = _slots(intent)
        request_id = str(intent["request_id"])
        return ActionPlan(
            request_id=request_id,
            intent_type=self.intent_type,
            template=self.name,
            steps=[
                ActionStep(
                    step_id="step-1",
                    executor="sys_navigation",
                    action_type=MOVE_TO_WORKSPACE.name,
                    args={
                        "workspace_name": slots["workspace_name"],
                        "workspace_color": slots.get("workspace_color", ""),
                    },
                )
            ],
        )


class MoveRelativeTemplate:
    """Compose a relative-motion task into one navigation-domain step."""

    name = "move_relative_template"
    intent_type = "move_relative"

    def compose(self, intent: dict[str, Any]) -> ActionPlan:
        """Build a single-step ActionPlan for normalized body-frame movement."""
        slots = _slots(intent)
        request_id = str(intent["request_id"])
        return ActionPlan(
            request_id=request_id,
            intent_type=self.intent_type,
            template=self.name,
            steps=[
                ActionStep(
                    step_id="step-1",
                    executor="sys_navigation",
                    action_type=MOVE_RELATIVE.name,
                    args={
                        "direction": slots["direction"],
                        "distance_units": slots["distance_units"],
                        "raw_distance_mentioned": bool(slots.get("raw_distance_mentioned", False)),
                    },
                )
            ],
        )


class PickSkuTemplate:
    """Compose a pick task into navigation followed by VLA pick."""

    name = "pick_sku_template"
    intent_type = "pick_sku"

    def compose(self, intent: dict[str, Any]) -> ActionPlan:
        slots = _slots(intent)
        request_id = str(intent["request_id"])
        return ActionPlan(
            request_id=request_id,
            intent_type=self.intent_type,
            template=self.name,
            steps=[
                ActionStep(
                    step_id="step-1",
                    executor="sys_navigation",
                    action_type=MOVE_TO_WORKSPACE.name,
                    args={
                        "workspace_name": slots["workspace_name"],
                        "workspace_color": slots["workspace_color"],
                    },
                ),
                ActionStep(
                    step_id="step-2",
                    executor="vla",
                    action_type=VLA_PICK_SKU.name,
                    args={
                        "workspace_name": slots["workspace_name"],
                        "workspace_color": slots["workspace_color"],
                        "sku_name": slots["sku_name"],
                        "sku_color": slots["sku_color"],
                    },
                    depends_on=("step-1",),
                ),
            ],
        )


class FetchSkuTemplate:
    """Compose a fetch task into source navigation, pick, target navigation, and drop."""

    name = "fetch_sku_template"
    intent_type = "fetch_sku"

    def compose(self, intent: dict[str, Any]) -> ActionPlan:
        slots = _slots(intent)
        request_id = str(intent["request_id"])
        return ActionPlan(
            request_id=request_id,
            intent_type=self.intent_type,
            template=self.name,
            steps=[
                ActionStep(
                    step_id="step-1",
                    executor="sys_navigation",
                    action_type=MOVE_TO_WORKSPACE.name,
                    args={
                        "workspace_name": slots["source_workspace_name"],
                        "workspace_color": slots["source_workspace_color"],
                    },
                ),
                ActionStep(
                    step_id="step-2",
                    executor="vla",
                    action_type=VLA_PICK_SKU.name,
                    args={
                        "workspace_name": slots["source_workspace_name"],
                        "workspace_color": slots["source_workspace_color"],
                        "sku_name": slots["sku_name"],
                        "sku_color": slots["sku_color"],
                    },
                    depends_on=("step-1",),
                ),
                ActionStep(
                    step_id="step-3",
                    executor="sys_navigation",
                    action_type=MOVE_TO_WORKSPACE.name,
                    args={
                        "workspace_name": slots["target_workspace_name"],
                        "workspace_color": slots["target_workspace_color"],
                    },
                    depends_on=("step-2",),
                ),
                ActionStep(
                    step_id="step-4",
                    executor="vla",
                    action_type=VLA_DROP_SKU.name,
                    args={
                        "workspace_name": slots["target_workspace_name"],
                        "workspace_color": slots["target_workspace_color"],
                        "sku_name": slots["sku_name"],
                        "sku_color": slots["sku_color"],
                    },
                    depends_on=("step-3",),
                ),
            ],
        )


RelocateSkuTemplate = FetchSkuTemplate


class GoHomeTemplate:
    """Compose a recovery task into one Dax go_home step."""

    name = "go_home_template"
    intent_type = "go_home"

    def compose(self, intent: dict[str, Any]) -> ActionPlan:
        """Build a single-step ActionPlan that returns the body to home pose."""
        request_id = str(intent["request_id"])
        return ActionPlan(
            request_id=request_id,
            intent_type=self.intent_type,
            template=self.name,
            steps=[
                ActionStep(
                    step_id="step-1",
                    executor="dax",
                    action_type=GO_HOME.name,
                    args={},
                )
            ],
        )


class GuardLoopTemplate:
    """Compose a guard loop into a finite sequence of navigation waypoints."""

    name = "guard_loop_template"
    intent_type = "guard_loop"

    def compose(self, intent: dict[str, Any]) -> ActionPlan:
        slots = _slots(intent)
        request_id = str(intent["request_id"])
        waypoints = slots.get("waypoints")
        if not isinstance(waypoints, list) or len(waypoints) < 2:
            raise ValueError("guard_loop intent requires at least 2 waypoints")
        loop_count = int(slots.get("loop_count", 0))
        if loop_count <= 0:
            raise ValueError("guard_loop intent requires a positive loop_count")

        steps: list[ActionStep] = []
        for loop_index in range(loop_count):
            for waypoint_index, waypoint in enumerate(waypoints):
                if not isinstance(waypoint, dict):
                    raise ValueError("guard_loop waypoints must be objects")
                step_number = len(steps) + 1
                depends_on = () if step_number == 1 else (f"step-{step_number - 1}",)
                steps.append(
                    ActionStep(
                        step_id=f"step-{step_number}",
                        executor="sys_navigation",
                        action_type=MOVE_TO_WORKSPACE.name,
                        args={
                            "workspace_name": waypoint.get("workspace_name", "table"),
                            "workspace_color": str(waypoint.get("workspace_color", "")),
                            "loop_index": loop_index,
                            "waypoint_index": waypoint_index,
                        },
                        depends_on=depends_on,
                    )
                )

        return ActionPlan(
            request_id=request_id,
            intent_type=self.intent_type,
            template=self.name,
            steps=steps,
        )


class DaxSkillClient(Protocol):
    """Protocol for Dax go_home orchestration used by the action plan runner."""

    def go_home(self, *, request_id: str) -> SkillResult[Any]: ...


class VlaActionClient(Protocol):
    """Protocol implemented by VLA or wrapper clients used by the gateway."""

    def pick_sku(self, request: VlaPickRequest) -> VlaReceiverResult: ...

    def execute_pick_task(self, request: VlaPickRequest) -> VlaReceiverResult: ...

    def execute_action_list(
        self,
        actions: list[dict[str, Any]],
        *,
        request: VlaPickRequest,
    ) -> VlaReceiverResult: ...


class VlaActionGateway:
    """Translate VLA ActionStep objects into calls on a VLA-compatible client."""

    def __init__(self, client: VlaActionClient) -> None:
        self._client = client

    def execute(
        self,
        request_id: str,
        step: ActionStep,
        *,
        context: dict[str, Any] | None = None,
    ) -> VlaReceiverResult:
        """Execute one VLA-domain step with optional orchestrator context."""
        if step.executor != "vla":
            return SkillResult(
                success=False,
                error_code="VLA_OUTPUT_INVALID",
                message=f"Step {step.step_id} is not a VLA step.",
                metadata={"step": step.to_dict()},
            )

        request = _vla_request_from_step(request_id, step)
        if step.action_type == VLA_PICK_SKU.name:
            return self._client.pick_sku(request)
        if step.action_type == VLA_DROP_SKU.name:
            return self._client.execute_action_list(
                [_vla_action_payload(step, context=context)],
                request=request,
            )

        return SkillResult(
            success=False,
            error_code="VLA_OUTPUT_INVALID",
            message=f"Unsupported VLA action {step.action_type!r}.",
            metadata={"step": step.to_dict()},
        )


@dataclass(frozen=True)
class HeldObjectState:
    """Normalized state for the object currently held after a successful pick."""

    sku_name: str
    sku_color: str
    sku_id: str
    arm_name: str
    grasp_type: str

    @classmethod
    def from_mapping(cls, value: Any) -> SkillResult[str]:
        """Build held-object state from metadata and report missing contract fields."""
        if not isinstance(value, dict):
            return SkillResult(
                success=False,
                error_code="DAX_INPUT_INVALID",
                message="place_sku requires held_object metadata from a previous pick step.",
            )
        missing = [
            key
            for key in ("sku_name", "sku_color", "sku_id", "arm_name", "grasp_type")
            if not value.get(key)
        ]
        if missing:
            return SkillResult(
                success=False,
                error_code="DAX_INPUT_INVALID",
                message=f"held_object missing required fields: {', '.join(missing)}.",
                metadata={"held_object": value, "missing_fields": missing},
            )
        return SkillResult.ok(
            "held_object normalized.",
            held_object=cls(
                sku_name=str(value["sku_name"]),
                sku_color=str(value["sku_color"]),
                sku_id=str(value["sku_id"]),
                arm_name=str(value["arm_name"]),
                grasp_type=str(value["grasp_type"]),
            ),
        )


@dataclass(frozen=True)
class ResolvedBackendInput:
    """Backend-ready payload produced from task args and previous step metadata."""

    backend: str
    payload: dict[str, Any]
    source: str


class DaxPlaceInputResolver:
    """Resolve task-level drop semantics into the strict Dax place.yaml inputs."""

    def resolve_place_inputs(
        self,
        *,
        step: ActionStep,
        held_object: Any,
    ) -> SkillResult[str]:
        """Return only arm_name, grasp_type, and target_name for Dax place.yaml."""
        held_result = HeldObjectState.from_mapping(held_object)
        if not held_result.success:
            return held_result
        state = held_result.metadata["held_object"]
        inputs = {
            "arm_name": state.arm_name,
            "grasp_type": state.grasp_type,
            "target_name": state.sku_id,
        }
        return SkillResult.ok(
            "Dax place inputs resolved.",
            resolved=ResolvedBackendInput(
                backend="dax_skill_sdk",
                payload=inputs,
                source="held_object",
            ),
            inputs=inputs,
            step=step.to_dict(),
            held_object=state,
        )


class ActionPlanOrchestrator:
    """Run ActionPlan steps sequentially while preserving metadata for dependencies."""

    def __init__(
        self,
        *,
        navigation: SysNavigationAdapter | None = None,
        vla_gateway: VlaActionGateway | None = None,
        ros_action: RosActionAdapter | None = None,
        dax_skill: DaxSkillClient | None = None,
    ) -> None:
        self.navigation = navigation or MockSysNavigationAdapter()
        self._vla_gateway = vla_gateway or VlaActionGateway(MockVlaPickClient())
        self._ros_action = ros_action or MockRosActionAdapter()
        self._dax_skill = dax_skill

    def run(self, intent: dict[str, Any], plan: ActionPlan) -> SkillResult[ActionPlanError]:
        """Execute a plan with failure-early gates between navigation, VLA, and ROS."""
        logger.info(
            "ActionPlan started",
            trace_layer="action_plan",
            trace_stage="started",
            request_id=plan.request_id,
            intent_type=plan.intent_type,
            phase="started",
            template=plan.template,
            step_count=len(plan.steps),
            action_plan=plan.to_dict(),
        )
        completed_steps: list[str] = []
        navigation_results: list[dict[str, Any]] = []
        vla_results: list[dict[str, Any]] = []
        ros_results: list[dict[str, Any]] = []
        dax_results: list[dict[str, Any]] = []
        step_metadata: dict[str, dict[str, Any]] = {}

        for step in plan.steps:
            logger.info(
                "ActionPlan step started",
                trace_layer="action_plan",
                trace_stage="step_started",
                request_id=plan.request_id,
                step_id=step.step_id,
                executor=step.executor,
                action_type=step.action_type,
                phase=step.action_type,
                depends_on=step.depends_on,
                args=step.args,
                step=step.to_dict(),
            )
            missing_deps = [dep for dep in step.depends_on if dep not in completed_steps]
            if missing_deps:
                logger.info(
                    "ActionPlan step dependency failed",
                    trace_layer="action_plan",
                    trace_stage="dependency_failed",
                    request_id=plan.request_id,
                    step_id=step.step_id,
                    executor=step.executor,
                    action_type=step.action_type,
                    phase=step.action_type,
                    missing_dependencies=missing_deps,
                )
                return _fail(
                    "UNSUPPORTED_PLAN",
                    f"Step {step.step_id} dependencies were not completed.",
                    intent=intent,
                    action_plan=plan.to_dict(),
                    step=step.to_dict(),
                    missing_dependencies=missing_deps,
                )

            if step.executor == "sys_navigation":
                navigation_result = self._execute_navigation_step(plan.request_id, step)
                navigation_results.append(_navigation_to_dict(navigation_result))
                if navigation_result.status != "arrived":
                    logger.info(
                        "ActionPlan navigation step failed",
                        trace_layer="action_plan",
                        trace_stage="navigation_failed",
                        request_id=plan.request_id,
                        step_id=step.step_id,
                        executor=step.executor,
                        action_type=step.action_type,
                        phase=step.action_type,
                        status=navigation_result.status,
                        message=navigation_result.message,
                        navigation_result=_navigation_to_dict(navigation_result),
                    )
                    return _fail(
                        _navigation_error_code(navigation_result.status),
                        navigation_result.message or f"Navigation {navigation_result.status}.",
                        intent=intent,
                        action_plan=plan.to_dict(),
                        phase=step.action_type,
                        step=step.to_dict(),
                        navigation_results=navigation_results,
                    )
                completed_steps.append(step.step_id)
                step_metadata[step.step_id] = _navigation_to_dict(navigation_result)
                logger.info(
                    "ActionPlan navigation step completed",
                    trace_layer="action_plan",
                    trace_stage="navigation_completed",
                    request_id=plan.request_id,
                    step_id=step.step_id,
                    executor=step.executor,
                    action_type=step.action_type,
                    phase=step.action_type,
                    status=navigation_result.status,
                    navigation_result=_navigation_to_dict(navigation_result),
                )
                continue

            if step.executor == "vla":
                vla_result = self._vla_gateway.execute(
                    plan.request_id,
                    step,
                    context={
                        "step_metadata": step_metadata,
                        "completed_steps": completed_steps,
                    },
                )
                vla_results.append(_skill_result_to_dict(vla_result))
                if not vla_result.success:
                    logger.info(
                        "ActionPlan VLA step failed",
                        trace_layer="action_plan",
                        trace_stage="vla_failed",
                        request_id=plan.request_id,
                        step_id=step.step_id,
                        executor=step.executor,
                        action_type=step.action_type,
                        phase=step.action_type,
                        error_code=vla_result.error_code,
                        message=vla_result.message,
                        vla_result=_skill_result_to_dict(vla_result),
                    )
                    return SkillResult(
                        success=False,
                        error_code=vla_result.error_code,  # type: ignore[arg-type]
                        message=vla_result.message,
                        metadata={
                            "intent": intent,
                            "action_plan": plan.to_dict(),
                            "phase": step.action_type,
                            "step": step.to_dict(),
                            "navigation_results": navigation_results,
                            "vla_results": vla_results,
                            **vla_result.metadata,
                        },
                    )

                payload = vla_result.metadata.get("validated_payload")
                if isinstance(payload, dict) and step.action_type == VLA_PICK_SKU.name:
                    ros_result = self._ros_action.submit_action(
                        request_id=plan.request_id,
                        payload=payload,
                    )
                    ros_results.append(_ros_to_dict(ros_result))
                    if ros_result.status != "succeeded":
                        logger.info(
                            "ActionPlan ROS forwarding failed",
                            trace_layer="action_plan",
                            trace_stage="ros_forwarding_failed",
                            request_id=plan.request_id,
                            step_id=step.step_id,
                            executor=step.executor,
                            action_type=step.action_type,
                            phase="forwarding_to_ros",
                            status=ros_result.status,
                            message=ros_result.message,
                            ros_result=_ros_to_dict(ros_result),
                        )
                        return _fail(
                            _ros_error_code(ros_result.status),
                            ros_result.message or f"ROS action {ros_result.status}.",
                            intent=intent,
                            action_plan=plan.to_dict(),
                            phase="forwarding_to_ros",
                            step=step.to_dict(),
                            navigation_results=navigation_results,
                            vla_results=vla_results,
                            ros_results=ros_results,
                            raw_payload=payload,
                            validated_payload=payload,
                        )
                completed_steps.append(step.step_id)
                step_metadata[step.step_id] = dict(vla_result.metadata)
                logger.info(
                    "ActionPlan VLA step completed",
                    trace_layer="action_plan",
                    trace_stage="vla_completed",
                    request_id=plan.request_id,
                    step_id=step.step_id,
                    executor=step.executor,
                    action_type=step.action_type,
                    phase=step.action_type,
                    forwarded_to_ros=isinstance(payload, dict),
                    vla_result=_skill_result_to_dict(vla_result),
                )
                continue

            if step.executor == "dax":
                if self._dax_skill is None:
                    return _fail(
                        "UNSUPPORTED_PLAN",
                        "Dax skill adapter is not configured (set DAX_SKILL_ADAPTER).",
                        intent=intent,
                        action_plan=plan.to_dict(),
                        step=step.to_dict(),
                    )
                if step.action_type != GO_HOME.name:
                    return _fail(
                        "UNSUPPORTED_PLAN",
                        f"Unknown dax action_type {step.action_type!r}.",
                        intent=intent,
                        action_plan=plan.to_dict(),
                        step=step.to_dict(),
                    )
                dax_result = self._dax_skill.go_home(request_id=plan.request_id)
                dax_results.append(_skill_result_to_dict(dax_result))
                if not dax_result.success:
                    logger.info(
                        "ActionPlan Dax step failed",
                        trace_layer="action_plan",
                        trace_stage="dax_failed",
                        request_id=plan.request_id,
                        step_id=step.step_id,
                        executor=step.executor,
                        action_type=step.action_type,
                        phase=step.action_type,
                        error_code=dax_result.error_code,
                        message=dax_result.message,
                        dax_result=_skill_result_to_dict(dax_result),
                    )
                    return SkillResult(
                        success=False,
                        error_code=dax_result.error_code,  # type: ignore[arg-type]
                        message=dax_result.message,
                        metadata={
                            "intent": intent,
                            "action_plan": plan.to_dict(),
                            "phase": step.action_type,
                            "step": step.to_dict(),
                            "navigation_results": navigation_results,
                            "vla_results": vla_results,
                            "ros_results": ros_results,
                            "dax_results": dax_results,
                            **dax_result.metadata,
                        },
                    )
                completed_steps.append(step.step_id)
                step_metadata[step.step_id] = dict(dax_result.metadata)
                logger.info(
                    "ActionPlan Dax step completed",
                    trace_layer="action_plan",
                    trace_stage="dax_completed",
                    request_id=plan.request_id,
                    step_id=step.step_id,
                    executor=step.executor,
                    action_type=step.action_type,
                    phase=step.action_type,
                    dax_result=_skill_result_to_dict(dax_result),
                )
                continue

            logger.info(
                "ActionPlan unsupported executor",
                trace_layer="action_plan",
                trace_stage="unsupported_executor",
                request_id=plan.request_id,
                step_id=step.step_id,
                executor=step.executor,
                action_type=step.action_type,
                phase=step.action_type,
            )
            return _fail(
                "UNSUPPORTED_PLAN",
                f"Unsupported executor {step.executor!r}.",
                intent=intent,
                action_plan=plan.to_dict(),
                step=step.to_dict(),
            )

        logger.info(
            "ActionPlan completed",
            trace_layer="action_plan",
            trace_stage="completed",
            request_id=plan.request_id,
            intent_type=plan.intent_type,
            phase="SUCCEEDED",
            completed_steps=completed_steps,
            navigation_results=navigation_results,
            vla_results=vla_results,
            ros_results=ros_results,
            dax_results=dax_results,
        )
        return SkillResult.ok(
            "Action plan completed successfully.",
            intent=intent,
            action_plan=plan.to_dict(),
            phase="SUCCEEDED",
            completed_steps=completed_steps,
            navigation_results=navigation_results,
            vla_results=vla_results,
            ros_results=ros_results,
            dax_results=dax_results,
            validation_passed=True,
        )

    def _execute_navigation_step(self, request_id: str, step: ActionStep) -> Any:
        """Dispatch one navigation-domain step to workspace or relative movement."""
        if step.action_type == MOVE_RELATIVE.name:
            return self.navigation.move_relative(
                request_id=request_id,
                direction=str(step.args.get("direction", "")),
                distance_units=float(step.args.get("distance_units", 1.0)),
            )
        if step.action_type == MOVE_TO_WORKSPACE.name:
            return self.navigation.navigate_to_workspace(
                request_id=request_id,
                workspace_type=str(step.args.get("workspace_name", "")),
                table_color=str(step.args.get("workspace_color", "")),
            )
        return SkillResult(
            success=False,
            error_code="UNSUPPORTED_PLAN",
            message=f"Unknown navigation action_type {step.action_type!r}.",
            metadata={"step": step.to_dict()},
        )


# Deprecated HTTP adapter — use PyRosbridgeVlaPickClient via vla_pick_adapter_factory.
#
# class _VlaHttpActionClient:
#     def pick_sku(self, request: VlaPickRequest) -> VlaReceiverResult: ...
#     def execute_pick_task(self, request: VlaPickRequest) -> VlaReceiverResult: ...


def _slots(intent: dict[str, Any]) -> dict[str, Any]:
    """Return the slots mapping from a parsed intent."""
    slots = intent.get("slots")
    if not isinstance(slots, dict):
        raise ValueError("intent must contain slots")
    return slots


def _vla_request_from_step(request_id: str, step: ActionStep) -> VlaPickRequest:
    """Build the legacy VLA request shape from task-level step args."""
    return VlaPickRequest(
        workspace_type=str(step.args.get("workspace_name", "")),
        table_color=str(step.args.get("workspace_color", "")),
        object_type=str(step.args.get("sku_name", "")),
        object_color=str(step.args.get("sku_color", "")),
        request_id=request_id,
    )


def _vla_action_payload(step: ActionStep, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a VLA action payload and attach resolved Dax inputs for drop steps."""
    payload = {
        "action": step.action_type.removeprefix("vla_"),
        "workspace": {
            "name": step.args.get("workspace_name", ""),
            "color": step.args.get("workspace_color", ""),
        },
        "sku": {
            "name": step.args.get("sku_name", ""),
            "color": step.args.get("sku_color", ""),
        },
    }
    if step.action_type == VLA_DROP_SKU.name:
        held_object = _latest_held_object(context)
        resolved = DaxPlaceInputResolver().resolve_place_inputs(step=step, held_object=held_object)
        if resolved.success:
            payload["dax_place_inputs"] = resolved.metadata["inputs"]
            payload["held_object"] = _json_ready(resolved.metadata["held_object"])
        else:
            payload["dax_place_error"] = {
                "error_code": resolved.error_code,
                "message": resolved.message,
                "metadata": resolved.metadata,
            }
    return payload


def _navigation_error_code(status: str) -> ActionPlanError:
    """Map navigation status to the ActionPlan error-code vocabulary."""
    if status == "timeout":
        return "SYS_NAVIGATION_TIMEOUT"
    if status == "cancelled":
        return "CANCELLED"
    return "SYS_NAVIGATION_FAILED"


def _ros_error_code(status: str) -> ActionPlanError:
    """Map ROS action status to the ActionPlan error-code vocabulary."""
    if status == "rejected":
        return "ROS_ACTION_REJECTED"
    if status == "timeout":
        return "ROS_ACTION_TIMEOUT"
    return "ROS_ACTION_FAILED"


def _fail(
    error_code: ActionPlanError,
    message: str,
    **metadata: Any,
) -> SkillResult[ActionPlanError]:
    """Create a failed SkillResult with metadata."""
    return SkillResult(
        success=False,
        error_code=error_code,
        message=message,
        metadata=dict(metadata),
    )


def _navigation_to_dict(result: Any) -> dict[str, Any]:
    """Convert navigation result objects into metadata dictionaries."""
    payload = {
        "sys_task_id": result.sys_task_id,
        "status": result.status,
        "workspace_type": result.workspace_type,
        "table_color": result.table_color,
        "message": result.message,
        "final_robot_state": result.final_robot_state,
    }
    if isinstance(result.final_robot_state, dict):
        for key in (
            "workspace",
            "nav_status_code",
            "uuid",
            "result_pose",
            "raw",
            "goal",
            "slam_state",
            "error_code",
            "safety_check",
            "relative_motion",
        ):
            if key in result.final_robot_state:
                payload[key] = result.final_robot_state[key]
    return payload


def _ros_to_dict(result: Any) -> dict[str, Any]:
    """Convert ROS action result objects into metadata dictionaries."""
    return {
        "ros_goal_id": result.ros_goal_id,
        "request_id": result.request_id,
        "status": result.status,
        "message": result.message,
        "payload": result.payload,
    }


def _skill_result_to_dict(result: SkillResult[Any]) -> dict[str, Any]:
    """Convert SkillResult into a plain metadata dictionary."""
    return {
        "success": result.success,
        "message": result.message,
        "error_code": result.error_code,
        "metadata": result.metadata,
    }


def _latest_held_object(context: dict[str, Any] | None) -> Any:
    """Find the most recent held_object emitted by completed VLA steps."""
    if not isinstance(context, dict):
        return None
    metadata = context.get("step_metadata")
    completed = context.get("completed_steps")
    if not isinstance(metadata, dict) or not isinstance(completed, list):
        return None
    for step_id in reversed(completed):
        step_meta = metadata.get(step_id)
        if isinstance(step_meta, dict) and "held_object" in step_meta:
            return step_meta["held_object"]
    return None


def _json_ready(value: Any) -> Any:
    """Convert dataclasses used in metadata into JSON-friendly dictionaries."""
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value


__all__ = [
    "ActionPlan",
    "ActionPlanOrchestrator",
    "ActionStep",
    "DaxPlaceInputResolver",
    "DaxSkillClient",
    "FetchSkuTemplate",
    "GoHomeTemplate",
    "GuardLoopTemplate",
    "HeldObjectState",
    "MoveRelativeTemplate",
    "MoveToWorkspaceTemplate",
    "PickSkuTemplate",
    "RelocateSkuTemplate",
    "ResolvedBackendInput",
    "TaskTemplate",
    "VlaActionGateway",
]
