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

from dimos.agents.annotation import skill
from dimos.agents.skill_result import SkillResult
from dimos.agents.nl.task import (
    InProcessTaskExecutor,
    TaskExecutor,
    TaskRouter,
    default_task_route_catalog,
)
from dimos.agents.task_action_plan import ActionPlan, ActionPlanOrchestrator
from dimos.agents.vla_pick_adapter_factory import make_action_plan_orchestrator
from dimos.core.module import Module


class NlTaskExecutionSkill(Module):
    def __init__(
        self,
        *,
        executor: TaskExecutor | None = None,
        action_orchestrator: ActionPlanOrchestrator | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if action_orchestrator is not None:
            self._action_orchestrator = action_orchestrator
        else:
            self._action_orchestrator = make_action_plan_orchestrator(self.config.g)
        self._executor = executor or InProcessTaskExecutor(
            TaskRouter(default_task_route_catalog()),
            route_handlers={
                "action_plan": self._execute_action_plan,
            },
        )

    @skill
    def execute_nl_task(self, text: str, request_id: str = "") -> SkillResult[Any]:
        """Run a complex robot task from the user's original instruction.

        Use this for robot work that needs planning, such as moving, navigation,
        picking up an object, carrying an object, placing an object, or patrolling.
        Pass the user's task as plain natural language in `text`.

        Important: do not break the task into steps, do not invent missing
        details, and do not translate it into low-level robot commands. If the
        user said "go to the blue table and pick up the red cube", pass that
        sentence directly.

        Args:
            text: The user's original robot-task instruction.
            request_id: Optional trace id. Leave empty unless the caller already has one.
        """

        return self._executor.execute_text(text, request_id=request_id)

    def _execute_action_plan(
        self,
        *,
        intent: dict[str, Any],
        action_plan: ActionPlan,
    ) -> SkillResult[Any]:
        return self._action_orchestrator.run(intent, action_plan)


nl_task_execution_skill = NlTaskExecutionSkill.blueprint

__all__ = [
    "NlTaskExecutionSkill",
    "nl_task_execution_skill",
]
