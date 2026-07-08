#!/usr/bin/env python3
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

"""Minimal dax-agent launcher for real-robot deployment.

Imports ONLY the dax-agent blueprint chain + core coordinator, bypassing the
full ``dimos`` CLI (which eagerly imports rerun/map-viz/nav-mcp/memory2). This
keeps the on-robot Python process light: no torch, mujoco, unitree, rerun.

Run on the robot after ``uv sync --extra dax-agent``::

    uv run python scripts/run_dax_agent.py

``ModuleCoordinator.build`` deploys every module in the blueprint into forkserver
workers, wires the LCM streams, and starts them. ``loop()`` then blocks the main
thread until SIGINT/SIGTERM, after which the coordinator stops every module
gracefully (SIGTERM → SIGKILL after 5s is handled by the worker managers).
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
from typing import Any

# DimOS modules call setup_logger() at import time. Ensure a writable log dir
# before any ``dimos`` import (systemd may leave /opt/dax-agent/logs root-owned).
if not os.environ.get("DIMOS_RUN_LOG_DIR"):
    _default_log_root = Path.home() / ".local" / "state" / "dimos" / "logs"
    try:
        _default_log_root.mkdir(parents=True, exist_ok=True)
        if os.access(_default_log_root, os.W_OK):
            os.environ["DIMOS_RUN_LOG_DIR"] = str(_default_log_root)
    except OSError:
        _fallback = Path("/tmp/dimos-agent-logs")
        _fallback.mkdir(parents=True, exist_ok=True)
        os.environ["DIMOS_RUN_LOG_DIR"] = str(_fallback)

from dotenv import load_dotenv

from dimos.agents.dax_agent import dax_agent
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.utils.logging_config import setup_exception_handler, set_run_log_dir


def main() -> int:
    # Populate os.environ from .env so non-GlobalConfig keys (e.g. DEEPSEEK_API_KEY,
    # DAX_AGENT_MODEL) that langchain / third-party libs read directly are available,
    # mirroring what `dimos run` does.
    load_dotenv()
    setup_exception_handler()

    # Give the run a log dir mirroring `dimos run` (best-effort; not required).
    try:
        from dimos.core.run_registry import generate_run_id
        from pathlib import Path

        run_id = generate_run_id("dax-agent")
        set_run_log_dir(Path("logs") / run_id)
    except Exception:
        pass

    print("Building dax-agent blueprint (thin entrypoint)...", flush=True)
    coordinator = ModuleCoordinator.build(dax_agent)
    print(f"dax-agent running: {coordinator.n_modules} modules deployed", flush=True)

    def _shutdown(signum: int, *_: Any) -> None:
        print(f"\nReceived signal {signum}, stopping dax-agent...", flush=True)
        # Raise KeyboardInterrupt so loop()'s try/except runs the finally -> stop().
        raise KeyboardInterrupt

    # loop() already handles SIGINT via KeyboardInterrupt; add SIGTERM so systemd
    # graceful shutdown also triggers the coordinator's finally cleanup.
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        coordinator.loop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
