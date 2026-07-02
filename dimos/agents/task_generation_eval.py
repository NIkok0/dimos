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

import json
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from dimos.agents.skill_result import SkillResult
from dimos.agents.nl.task import (
    TaskRouter,
    compose_action_plan,
    default_task_route_catalog,
    parse_nl_task_intent,
)


def evaluate_task_generation(
    dataset_path: str | Path,
    *,
    output_path: str | Path | None = None,
    limit: int | None = None,
    offset: int = 0,
    checkpoint_path: str | Path | None = None,
    resume: bool = False,
    progress_every: int = 10,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    dataset = _load_jsonl(Path(dataset_path))
    for index, row in enumerate(dataset, 1):
        row.setdefault("id", f"eval_task_{index:04d}")

    slice_rows = dataset[offset:]
    if limit is not None:
        slice_rows = slice_rows[:limit]

    completed_ids: set[str] = set()
    if checkpoint_path is not None:
        ckpt = Path(checkpoint_path)
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        if resume and ckpt.is_file():
            completed_ids = _load_checkpoint_ids(ckpt)
        elif not resume:
            ckpt.write_text("", encoding="utf-8")

    router = TaskRouter(default_task_route_catalog())
    checkpoint_file: TextIO | None = None
    if checkpoint_path is not None:
        checkpoint_file = Path(checkpoint_path).open("a", encoding="utf-8")

    cases: list[dict[str, Any]] = []
    processed_this_run = 0
    slice_total = len(slice_rows)
    try:
        for row in slice_rows:
            case_id = str(row.get("id", ""))
            if resume and case_id in completed_ids:
                continue

            parsed = _parse_case(row, router)
            entry = {"case": row, "parsed": parsed}
            cases.append(entry)

            if checkpoint_file is not None:
                checkpoint_file.write(
                    json.dumps(
                        {"id": case_id, "case": row, "parsed": parsed},
                        ensure_ascii=False,
                    )
                    + "\n",
                )
                checkpoint_file.flush()
                completed_ids.add(case_id)

            processed_this_run += 1
            if progress_every > 0 and processed_this_run % progress_every == 0:
                elapsed = time.perf_counter() - started_at
                _print_progress(
                    completed=len(completed_ids)
                    if checkpoint_path is not None
                    else len(cases),
                    slice_total=slice_total,
                    case_id=case_id,
                    parsed=parsed,
                    elapsed_s=elapsed,
                )
    finally:
        if checkpoint_file is not None:
            checkpoint_file.close()

    if checkpoint_path is not None and Path(checkpoint_path).is_file():
        report_cases = _checkpoint_to_report_cases(Path(checkpoint_path))
    else:
        if resume:
            raise ValueError("--resume requires --checkpoint")
        report_cases = cases

    report = _build_report(report_cases)

    if output_path is not None:
        Path(output_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if processed_this_run > 0 and (
        progress_every <= 0 or processed_this_run % progress_every != 0
    ):
        elapsed = time.perf_counter() - started_at
        last = report_cases[-1]
        _print_progress(
            completed=len(completed_ids)
            if checkpoint_path is not None
            else len(report_cases),
            slice_total=slice_total,
            case_id=str(last["case"].get("id", "")),
            parsed=last["parsed"],
            elapsed_s=elapsed,
        )

    return report


def _print_progress(
    *,
    completed: int,
    slice_total: int,
    case_id: str,
    parsed: dict[str, Any],
    elapsed_s: float,
) -> None:
    status = parsed.get("status", "?")
    detail = parsed.get("intent_type") or parsed.get("error_code") or ""
    print(
        f"[{completed}/{slice_total}] id={case_id} status={status} {detail} "
        f"elapsed={elapsed_s:.1f}s",
        flush=True,
        file=sys.stderr,
    )


def _load_checkpoint_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for record in _iter_checkpoint(path):
        case_id = str(record.get("id", ""))
        if case_id:
            ids.add(case_id)
    return ids


def _iter_checkpoint(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError:
            continue
    return records


def _checkpoint_to_report_cases(path: Path) -> list[dict[str, Any]]:
    seen: set[str] = set()
    cases: list[dict[str, Any]] = []
    for record in _iter_checkpoint(path):
        case_id = str(record.get("id", ""))
        if case_id and case_id in seen:
            continue
        if case_id:
            seen.add(case_id)
        case = record.get("case")
        parsed = record.get("parsed")
        if isinstance(case, dict) and isinstance(parsed, dict):
            cases.append({"case": case, "parsed": parsed})
    return cases


def _build_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    counters = {
        "total": len(cases),
        "intent_scored": 0,
        "intent_correct": 0,
        "slot_scored": 0,
        "slot_correct": 0,
        "action_plan_scored": 0,
        "action_plan_correct": 0,
        "failure_scored": 0,
        "failure_correct": 0,
    }

    for entry in cases:
        row = entry["case"]
        parsed = entry["parsed"]
        expected_status = row.get("expected_status")

        if expected_status == "ok":
            expected_intent = row.get("expected_intent")
            if expected_intent:
                counters["intent_scored"] += 1
                if parsed.get("status") == "ok" and parsed.get("intent_type") == expected_intent:
                    counters["intent_correct"] += 1

            expected_slots = row.get("expected_slots")
            if isinstance(expected_slots, dict) and expected_slots:
                counters["slot_scored"] += 1
                if parsed.get("status") == "ok" and _slots_match(
                    parsed.get("slots"), expected_slots
                ):
                    counters["slot_correct"] += 1

            expected_plan = row.get("expected_action_plan")
            if isinstance(expected_plan, dict) and expected_plan:
                counters["action_plan_scored"] += 1
                if _action_plan_matches(parsed.get("action_plan"), expected_plan):
                    counters["action_plan_correct"] += 1

        elif expected_status == "fail":
            counters["failure_scored"] += 1
            expected_error = row.get("expected_error_code")
            if parsed.get("status") == "fail" and (
                expected_error is None or parsed.get("error_code") == expected_error
            ):
                counters["failure_correct"] += 1

    summary = {
        "total": counters["total"],
        "intent_accuracy": _ratio(counters["intent_correct"], counters["intent_scored"]),
        "slot_exact_match": _ratio(counters["slot_correct"], counters["slot_scored"]),
        "action_plan_exact_match": _ratio(
            counters["action_plan_correct"],
            counters["action_plan_scored"],
        ),
        "failure_classification_accuracy": _ratio(
            counters["failure_correct"],
            counters["failure_scored"],
        ),
        "counts": counters,
    }
    return {"summary": summary, "cases": cases}


def _parse_case(row: dict[str, Any], router: TaskRouter) -> dict[str, Any]:
    result = parse_nl_task_intent(str(row.get("text", "")), request_id=str(row.get("id", "")))
    if isinstance(result, SkillResult):
        return {
            "status": "fail",
            "error_code": result.error_code,
            "message": result.message,
            "metadata": result.metadata,
        }

    route_result = router.route(result)
    action_plan = None
    if route_result.success:
        route = route_result.metadata.get("route")
        if route is not None:
            action_plan = compose_action_plan(result, route).to_dict()

    return {
        "status": "ok",
        "intent_type": result.intent_type,
        "slots": result.slots,
        "action_plan": action_plan,
    }


def _slots_match(actual: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(actual, dict):
        return False
    return all(actual.get(key) == value for key, value in expected.items())


def _action_plan_matches(actual: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(actual, dict):
        return False
    for key in ("intent_type", "template"):
        if key in expected and actual.get(key) != expected[key]:
            return False

    expected_steps = expected.get("steps")
    if not isinstance(expected_steps, list):
        return isinstance(actual.get("steps"), list)
    actual_steps = actual.get("steps")
    if not isinstance(actual_steps, list) or len(actual_steps) != len(expected_steps):
        return False
    for actual_step, expected_step in zip(actual_steps, expected_steps, strict=True):
        if not isinstance(actual_step, dict) or not isinstance(expected_step, dict):
            return False
        for key, value in expected_step.items():
            actual_value = actual_step.get(key)
            if key == "depends_on":
                actual_value = list(actual_value or [])
                value = list(value or [])
            if actual_value != value:
                return False
    return True


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


__all__ = ["evaluate_task_generation"]
