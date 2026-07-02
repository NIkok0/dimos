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

import subprocess
import sys
from pathlib import Path

import pytest

from dimos.agents.nl.testing.task_generation_eval_runner import run_eval

REPO_ROOT = Path(__file__).resolve().parents[4]
DATASET_PATH = REPO_ROOT / "output" / "task_generation_eval_600.jsonl"
REPORT_PATH = REPO_ROOT / "output" / "task_generation_eval_600_report.json"


@pytest.fixture(scope="module")
def eval_dataset_path() -> Path:
    if not DATASET_PATH.is_file():
        generator = REPO_ROOT / "scripts" / "generate_task_generation_eval_dataset.py"
        subprocess.run(
            [sys.executable, str(generator), "--output", str(DATASET_PATH)],
            check=True,
        )
    return DATASET_PATH


class TestTaskGenerationEvalOracle:
    def test_pipeline_oracle_writes_report(self, eval_dataset_path: Path) -> None:
        report = run_eval(
            eval_dataset_path,
            llm_mode="oracle",
            output_path=REPORT_PATH,
        )
        summary = report["summary"]
        assert summary["intent_accuracy"] == 1.0
        assert summary["slot_exact_match"] == 1.0
        assert summary["action_plan_exact_match"] == 1.0
        assert summary["failure_classification_accuracy"] == 1.0
        assert REPORT_PATH.is_file()
        assert report["cases"]
        assert report["cases"][0]["case"]["id"].startswith("eval_task_")

    def test_report_schema_matches_reference(self, eval_dataset_path: Path) -> None:
        report = run_eval(eval_dataset_path, llm_mode="oracle")
        assert "summary" in report
        assert "cases" in report
        summary = report["summary"]
        assert "intent_accuracy" in summary
        assert "slot_exact_match" in summary
        assert "action_plan_exact_match" in summary
        assert "failure_classification_accuracy" in summary
        assert "counts" in summary

        first = report["cases"][0]
        assert "case" in first
        assert "parsed" in first
        assert "text" in first["case"]
        assert "status" in first["parsed"]


class TestTaskGenerationEvalCheckpoint:
    def test_checkpoint_resume_skips_completed_ids(
        self,
        eval_dataset_path: Path,
        tmp_path: Path,
    ) -> None:
        checkpoint = tmp_path / "eval_checkpoint.jsonl"
        report_path = tmp_path / "report.json"

        first = run_eval(
            eval_dataset_path,
            llm_mode="oracle",
            output_path=report_path,
            limit=3,
            checkpoint_path=checkpoint,
            resume=False,
            progress_every=0,
        )
        assert first["summary"]["total"] == 3
        assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 3

        second = run_eval(
            eval_dataset_path,
            llm_mode="oracle",
            output_path=report_path,
            limit=5,
            checkpoint_path=checkpoint,
            resume=True,
            progress_every=0,
        )
        assert second["summary"]["total"] == 5
        assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 5

        ids = {entry["case"]["id"] for entry in second["cases"]}
        assert len(ids) == 5
        assert len(ids) == len(set(ids))
        assert ids == {
            "eval_task_0001",
            "eval_task_0002",
            "eval_task_0003",
            "eval_task_0004",
            "eval_task_0005",
        }
