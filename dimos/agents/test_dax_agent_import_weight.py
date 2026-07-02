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

"""Import-weight guard for the dax-agent real-robot thin entrypoint.

Asserts that the dax-agent blueprint chain does not HARD-require heavy packages
(torch, transformers, rerun, mujoco, opencv, open3d, ultralytics, unitree_sdk2py).
This is what makes `uv sync --extra dax-agent` deployable on a robot without
the full DimOS heavy stack.

Two checks:

1. **Static AST scan** (always runs): walks the curated dax-agent chain files
   and asserts none has a top-level ``import torch`` / ``from transformers ...``
   etc. This proves the DimOS code itself never hard-imports these — any
   runtime leak comes from optional third-party integrations (e.g. langchain
   eagerly importing ``transformers`` when it is installed), which the robot
   env simply does not install.

2. **Runtime check** (only when torch is NOT installed): imports
   ``dimos.agents.dax_agent`` and asserts torch still is not loaded. This
   mirrors the real-robot venv produced by ``uv sync --extra dax-agent``. On a
   dev machine that happens to have torch installed, this check is skipped
   rather than falsely failing.
"""

from __future__ import annotations

import ast
import importlib.util as importlib_util
import subprocess
import sys
from pathlib import Path

import pytest

# Modules the dax-agent thin entrypoint must never hard-import at module scope.
_HEAVY_MODULES = (
    "torch",
    "transformers",
    "rerun",
    "mujoco",
    "cv2",
    "open3d",
    "ultralytics",
    "unitree_sdk2py",
    "unitree_sdk2py_sdk2py",
)

# Curated dax-agent chain files (the transitive closure of dax_agent.py
# imports that live inside the dimos repo + the thin entrypoint).
_DAX_AGENT_CHAIN_FILES: list[str] = [
    "scripts/run_dax_agent.py",
    "dimos/agents/dax_agent.py",
    "dimos/agents/dax_agent_system_prompt.py",
    "dimos/agents/annotation.py",
    "dimos/agents/skill_result.py",
    "dimos/agents/chat_model_factory.py",
    "dimos/agents/utils.py",
    "dimos/agents/system_prompt.py",
    "dimos/agents/skills/nl_task_execution_skill.py",
    "dimos/agents/skills/dax_joint_control_skill.py",
    "dimos/agents/skills/dax_joint_request_client.py",
    "dimos/agents/skills/chat_bridge_skill.py",
    "dimos/agents/skills/vis_bridge_skill.py",
    "dimos/agents/mcp/mcp_server.py",
    "dimos/agents/mcp/mcp_client.py",
    "dimos/agents/mcp/mcp_adapter.py",
    "dimos/agents/mcp/tool_stream.py",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _top_level_imports(source: str) -> set[str]:
    """Return module names imported at the top level (not inside functions)."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def test_dax_agent_chain_has_no_top_level_heavy_imports() -> None:
    """No file in the dax-agent chain hard-imports torch/rerun/mujoco/..."""
    root = _repo_root()
    offenders: list[str] = []
    for rel in _DAX_AGENT_CHAIN_FILES:
        path = root / rel
        if not path.is_file():
            pytest.fail(f"dax-agent chain file missing: {rel}")
        source = path.read_text(encoding="utf-8")
        imported = _top_level_imports(source)
        leaked = imported & set(_HEAVY_MODULES)
        if leaked:
            offenders.append(f"{rel}: {sorted(leaked)}")
    assert not offenders, "dax-agent chain hard-imports heavy modules:\n" + "\n".join(offenders)


@pytest.mark.skipif(
    importlib_util.find_spec("torch") is not None,
    reason="torch is installed in this env (dev machine); runtime leak check "
    "only meaningful in the robot's minimal `uv sync --extra dax-agent` env.",
)
def test_dax_agent_import_does_not_pull_torch_when_uninstalled() -> None:
    """In a torch-free env, importing the dax-agent blueprint must not load it.

    Mirrors the real-robot venv. If this fails, some dimos module gained a
    top-level torch/transformers import — make it lazy (import inside the
    function that needs it).
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import dimos.agents.dax_agent; "
            "assert 'torch' not in sys.modules, 'torch leaked'; "
            "assert 'transformers' not in sys.modules, 'transformers leaked'; "
            "assert 'rerun' not in sys.modules, 'rerun leaked'; "
            "assert 'mujoco' not in sys.modules, 'mujoco leaked'",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"dax-agent import leaked heavy module:\n{result.stderr}"


def test_dax_agent_extra_excludes_heavy_deps() -> None:
    """The [dax-agent] pyproject extra must not declare heavy packages."""
    import re

    root = _repo_root()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    start = pyproject.find("dax-agent = [")
    assert start != -1, "no [dax-agent] extra found in pyproject.toml"
    end = pyproject.find("\n]", start)
    block = pyproject[start:end]
    # Only inspect quoted dependency specifiers, not comments.
    deps = re.findall(r'"([^"]+)"', block)
    for dep in deps:
        dep_name = dep.split()[0].split("[")[0].split(">")[0].split("<")[0].split("=")[0].split("@")[0].strip().lower()
        for heavy in _HEAVY_MODULES:
            assert dep_name != heavy and not dep_name.startswith(heavy + "-"), (
                f"[dax-agent] extra declares heavy dep '{dep}'"
            )
