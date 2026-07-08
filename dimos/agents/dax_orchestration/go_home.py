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

"""DimOS task orchestrators built from atomic skill steps."""

from __future__ import annotations

from typing import Any

from dimos.agents.dax_atomic_skill_client import (
    AtomicSkillStep,
    DaxAtomicSkillClient,
    DaxAtomicSkillError,
)
from dimos.agents.dax_orchestration.config_loader import load_go_home_steps_from_env
from dimos.agents.skill_result import SkillResult


class GoHomeOrchestrator:
    """Run configured atomic steps to return the upper body to home pose."""

    def __init__(
        self,
        *,
        client: DaxAtomicSkillClient,
        steps: list[AtomicSkillStep],
    ) -> None:
        self._client = client
        self._steps = steps

    @classmethod
    def from_config(cls, config: Any) -> GoHomeOrchestrator:
        """Build from GlobalConfig-like fields."""
        client = DaxAtomicSkillClient.from_config(config)
        steps = load_go_home_steps_from_env(config.dax_orchestration_go_home_path)
        return cls(client=client, steps=steps)

    def run(self, *, request_id: str) -> SkillResult[DaxAtomicSkillError]:
        """Execute the go_home step sequence."""
        result = self._client.execute_sequence(self._steps, request_id=request_id)
        result.metadata.setdefault("orchestrator", "go_home")
        result.metadata["step_count"] = len(self._steps)
        return result


class DaxGoHomeClient:
    """Orchestrator-facing adapter implementing ``DaxSkillClient.go_home``."""

    def __init__(self, orchestrator: GoHomeOrchestrator) -> None:
        self._orchestrator = orchestrator

    @classmethod
    def from_config(cls, config: Any) -> DaxGoHomeClient:
        return cls(GoHomeOrchestrator.from_config(config))

    def go_home(self, *, request_id: str) -> SkillResult[DaxAtomicSkillError]:
        return self._orchestrator.run(request_id=request_id)


__all__ = ["DaxGoHomeClient", "GoHomeOrchestrator"]
