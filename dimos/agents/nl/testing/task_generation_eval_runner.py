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

"""Run task-generation eval datasets and write JSON reports."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal
from unittest.mock import patch

from dimos.agents.navigation_contracts import MAP_CELL_SIZE_M
from dimos.agents.nl.bootstrap import reset_navigation_bootstrap
from dimos.agents.nl.core.protocols import ParseResult
from dimos.agents.nl.task.nl_intent_bridge import reset_nl_hybrid_router
from dimos.agents.skill_result import SkillResult
from dimos.agents.task_generation_eval import evaluate_task_generation

LlmMode = Literal["real", "oracle"]


def load_dataset(path: str | Path) -> list[dict[str, Any]]:
    dataset_path = Path(path)
    if not dataset_path.is_file():
        raise FileNotFoundError(f"eval dataset not found: {dataset_path}")
    rows: list[dict[str, Any]] = []
    for line in dataset_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    for index, row in enumerate(rows, 1):
        row.setdefault("id", f"eval_task_{index:04d}")
    return rows


def write_report(report: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_eval(
    dataset_path: str | Path,
    *,
    llm_mode: LlmMode = "real",
    output_path: str | Path | None = None,
    limit: int | None = None,
    offset: int = 0,
    checkpoint_path: str | Path | None = None,
    resume: bool = False,
    progress_every: int = 10,
    model: str | None = None,
) -> dict[str, Any]:
    from dotenv import load_dotenv

    from dimos.core.global_config import global_config

    load_dotenv()
    if model:
        global_config.update(nl_llm_model=model)

    dataset = load_dataset(dataset_path)
    reset_navigation_bootstrap()
    reset_nl_hybrid_router()

    eval_kwargs = {
        "output_path": output_path,
        "limit": limit,
        "offset": offset,
        "checkpoint_path": checkpoint_path,
        "resume": resume,
        "progress_every": progress_every,
    }

    if llm_mode == "oracle":
        with oracle_llm_context(dataset):
            report = evaluate_task_generation(dataset_path, **eval_kwargs)
    else:
        report = evaluate_task_generation(dataset_path, **eval_kwargs)

    return report


def _records_by_id(dataset: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in dataset if row.get("id")}


def _expected_slots_to_llm_slots(
    intent_type: str,
    slots: dict[str, Any],
) -> dict[str, Any]:
    if intent_type == "pick_sku":
        return {
            "workspace_type": slots.get("workspace_name", "table"),
            "table_color": slots.get("workspace_color", ""),
            "object_type": slots.get("sku_name", "cube"),
            "object_color": slots.get("sku_color", ""),
        }
    if intent_type == "move_relative":
        distance_units = float(slots.get("distance_units", 20.0))
        return {
            "direction": slots.get("direction", "forward"),
            "distance_meters": distance_units * MAP_CELL_SIZE_M,
        }
    if intent_type == "move_to_workspace":
        return {
            "workspace_name": slots.get("workspace_name", ""),
            "workspace_color": slots.get("workspace_color", ""),
        }
    if intent_type == "fetch_sku":
        return dict(slots)
    if intent_type == "guard_loop":
        return {
            "waypoints": slots.get("waypoints", []),
            "loop_count": slots.get("loop_count", 1),
        }
    return dict(slots)


def _oracle_llm_parse(
    records_by_id: dict[str, dict[str, Any]],
    _self: Any,
    text: str,
    context: dict[str, Any] | None = None,
) -> ParseResult:
    request_id = str((context or {}).get("request_id", ""))
    record = records_by_id.get(request_id)
    if record is None:
        return ParseResult(success=False, error_code="NO_MATCH")

    if record.get("expected_status") == "fail":
        return ParseResult(
            success=False,
            error_code=str(record.get("expected_error_code", "NEED_CLARIFICATION")),
        )

    intent_type = str(record.get("expected_intent", ""))
    expected_slots = record.get("expected_slots", {})
    if not intent_type or not isinstance(expected_slots, dict):
        return ParseResult(success=False, error_code="NO_MATCH")

    return ParseResult(
        success=True,
        intent_type=intent_type,
        slots=_expected_slots_to_llm_slots(intent_type, expected_slots),
        confidence=0.95,
    )


def _oracle_parse_nl_task_intent(
    real_parse: Any,
    records_by_id: dict[str, dict[str, Any]],
    raw_instruction: str,
    *,
    request_id: str = "",
):
    record = records_by_id.get(request_id)
    if record is not None and record.get("expected_status") == "fail":
        return SkillResult(
            success=False,
            error_code=str(record.get("expected_error_code", "NEED_CLARIFICATION")),
            message=str(record.get("note", "expected failure")),
            metadata={
                "request_id": request_id,
                "raw_instruction": raw_instruction,
            },
        )
    return real_parse(raw_instruction, request_id=request_id)


def _mock_llm_init(_self: Any, **kwargs: Any) -> None:
    _self._validator = kwargs.get("validator")
    _self._catalog = kwargs.get("catalog")
    _self._system_prompt = "test"
    _self._include_few_shot = kwargs.get("include_few_shot", False)
    _self._use_structured_output = kwargs.get("use_structured_output", False)
    _self._llm = None


@contextmanager
def oracle_llm_context(dataset: list[dict[str, Any]]) -> Iterator[None]:
    import dimos.agents.nl.task.router as router_module
    import dimos.agents.task_generation_eval as eval_module

    records_by_id = _records_by_id(dataset)
    real_parse = router_module.parse_nl_task_intent
    llm_parse = lambda self, text, context=None: _oracle_llm_parse(
        records_by_id, self, text, context
    )
    parse_nl = lambda raw_instruction, *, request_id="": _oracle_parse_nl_task_intent(
        real_parse, records_by_id, raw_instruction, request_id=request_id
    )

    with (
        patch(
            "dimos.agents.nl.llm.parser.LLMIntentParser.__init__",
            _mock_llm_init,
        ),
        patch(
            "dimos.agents.nl.llm.parser.LLMIntentParser.parse",
            llm_parse,
        ),
        patch.object(eval_module, "parse_nl_task_intent", parse_nl),
        patch.object(router_module, "parse_nl_task_intent", parse_nl),
    ):
        reset_navigation_bootstrap()
        reset_nl_hybrid_router()
        yield


__all__ = [
    "load_dataset",
    "oracle_llm_context",
    "run_eval",
    "write_report",
]
