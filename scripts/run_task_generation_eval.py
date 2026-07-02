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

"""Run task-generation eval on the 607-case JSONL dataset.

Full real-LLM run with checkpoint/resume (recommended):

    cd ~/Projects/dimos
    PYTHONUNBUFFERED=1 .venv/bin/python scripts/run_task_generation_eval.py \\
      --checkpoint output/task_generation_eval_600_checkpoint.jsonl \\
      --resume \\
      --report output/task_generation_eval_600_report.json \\
      --progress-every 10

Re-run the same command after an interrupt to continue from the checkpoint.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from dimos.agents.nl.testing.task_generation_eval_runner import run_eval


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)

    load_dotenv()
    repo_root = Path(__file__).resolve().parents[1]
    default_checkpoint = repo_root / "output" / "task_generation_eval_600_checkpoint.jsonl"
    parser = argparse.ArgumentParser(description="Run task generation eval and write report.")
    parser.add_argument(
        "--dataset",
        default=str(repo_root / "output" / "task_generation_eval_600.jsonl"),
        help="Path to JSONL eval dataset.",
    )
    parser.add_argument(
        "--report",
        default=str(repo_root / "output" / "task_generation_eval_600_report.json"),
        help="Path to write JSON report.",
    )
    parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="Use oracle LLM mock (deterministic pipeline eval).",
    )
    parser.add_argument(
        "--generate-dataset",
        action="store_true",
        help="Generate dataset with generate_task_generation_eval_dataset.py if missing.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate only the first N dataset rows (after --offset).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip the first N dataset rows before evaluating.",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help=(
            "Append per-case JSONL checkpoint "
            f"(default when set: {default_checkpoint.name})."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip case ids already present in the checkpoint file.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Print progress to stderr every N newly processed cases (0=off).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override NL LLM model (e.g. deepseek-chat, gpt-4o).",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.is_file():
        if not args.generate_dataset:
            print(f"Dataset not found: {dataset_path}", file=sys.stderr)
            print("Re-run with --generate-dataset or generate manually.", file=sys.stderr)
            sys.exit(1)
        generator = repo_root / "scripts" / "generate_task_generation_eval_dataset.py"
        subprocess.run(
            [sys.executable, str(generator), "--output", str(dataset_path)],
            check=True,
        )

    checkpoint_path = args.checkpoint
    if checkpoint_path is None and args.resume:
        checkpoint_path = str(default_checkpoint)

    llm_mode = "oracle" if args.mock_llm else "real"
    report = run_eval(
        dataset_path,
        llm_mode=llm_mode,
        output_path=args.report,
        limit=args.limit,
        offset=args.offset,
        checkpoint_path=checkpoint_path,
        resume=args.resume,
        progress_every=args.progress_every,
        model=args.model,
    )
    summary = report["summary"]
    print(f"Wrote report to {args.report}")
    print(f"total={summary['total']}")
    print(f"intent_accuracy={summary['intent_accuracy']:.4f}")
    print(f"slot_exact_match={summary['slot_exact_match']:.4f}")
    print(f"action_plan_exact_match={summary['action_plan_exact_match']:.4f}")
    print(
        "failure_classification_accuracy="
        f"{summary['failure_classification_accuracy']:.4f}"
    )


if __name__ == "__main__":
    main()
