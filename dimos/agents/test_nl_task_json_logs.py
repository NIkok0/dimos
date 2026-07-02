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

"""Tests for production-grade JSON trace logs in the NL task path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dimos.agents.nl.task import InProcessTaskExecutor, TaskRouter, default_task_route_catalog
from dimos.agents.skill_result import SkillResult
from dimos.agents.task_action_plan import ActionPlan, ActionPlanOrchestrator, ActionStep
from dimos.agents.vla_pick_adapters import MockRosActionAdapter, MockSysNavigationAdapter
from dimos.agents.vla_pick_adapters import NavigationResult
from dimos.utils import logging_config
from dimos.utils.logging_config import set_run_log_dir


def _reset_log_dir(log_dir: Path) -> None:
    """Point all existing DimOS log handlers at a test-local main.jsonl."""
    logging_config._RUN_LOG_DIR = None
    logging_config._LOG_FILE_PATH = None
    set_run_log_dir(log_dir)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read structured JSON log records from a JSONL file."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class ArrivingNavigationAdapter(MockSysNavigationAdapter):
    """Navigation test double that reports successful relative movement."""

    def move_relative(
        self,
        *,
        request_id: str,
        direction: str,
        distance_units: float,
    ) -> NavigationResult:
        """Return an arrived result so logging assertions can inspect success logs."""
        return NavigationResult(
            sys_task_id="nav-json-test",
            status="arrived",
            workspace_type="relative",
            table_color="",
            message="arrived",
            final_robot_state={
                "relative_motion": {
                    "direction": direction,
                    "distance_units": distance_units,
                }
            },
        )


def test_nl_task_json_logs_include_trace_fields(tmp_path: Path) -> None:
    """NL execution writes machine-searchable trace fields into main.jsonl."""
    log_dir = tmp_path / "logs"
    _reset_log_dir(log_dir)

    def handler(*, intent: dict[str, Any], action_plan: ActionPlan) -> SkillResult[Any]:
        return SkillResult.ok("ok", phase="SUCCEEDED")

    executor = InProcessTaskExecutor(
        TaskRouter(default_task_route_catalog()),
        route_handlers={"action_plan": handler},
    )

    result = executor.execute_text("向后移动2个单位", request_id="req-json-trace")

    assert result.success
    records = _read_jsonl(log_dir / "main.jsonl")
    completed = next(record for record in records if record["event"] == "NL task completed")
    composed = next(record for record in records if record["event"] == "NL task action plan composed")

    assert completed["trace_layer"] == "agent_nl"
    assert completed["trace_stage"] == "completed"
    assert completed["request_id"] == "req-json-trace"
    assert completed["intent_type"] == "move_relative"
    assert completed["route"] == "move_relative"
    assert completed["phase"] == "SUCCEEDED"
    assert completed["success"] is True
    assert composed["action_plan"]["steps"][0]["action_type"] == "move_relative"


def test_action_plan_json_logs_include_step_fields(tmp_path: Path) -> None:
    """ActionPlan execution writes step-level fields for operational debugging."""
    log_dir = tmp_path / "logs"
    _reset_log_dir(log_dir)
    plan = ActionPlan(
        request_id="req-action-json-trace",
        intent_type="move_relative",
        template="move_relative_template",
        steps=[
            ActionStep(
                step_id="step-1",
                executor="sys_navigation",
                action_type="move_relative",
                args={"direction": "backward", "distance_units": 1.0},
            )
        ],
    )

    result = ActionPlanOrchestrator(
        navigation=ArrivingNavigationAdapter(),
        ros_action=MockRosActionAdapter(),
    ).run({"request_id": plan.request_id, "intent_type": plan.intent_type}, plan)

    assert result.success
    records = _read_jsonl(log_dir / "main.jsonl")
    step_started = next(record for record in records if record["event"] == "ActionPlan step started")
    completed = next(record for record in records if record["event"] == "ActionPlan completed")

    assert step_started["trace_layer"] == "action_plan"
    assert step_started["trace_stage"] == "step_started"
    assert step_started["request_id"] == "req-action-json-trace"
    assert step_started["step_id"] == "step-1"
    assert step_started["executor"] == "sys_navigation"
    assert step_started["action_type"] == "move_relative"
    assert step_started["phase"] == "move_relative"
    assert completed["trace_stage"] == "completed"
    assert completed["completed_steps"] == ["step-1"]
