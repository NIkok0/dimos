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

import pytest

from dimos.agents.nl.bootstrap import reset_navigation_bootstrap
from dimos.agents.nl.task.nl_intent_bridge import reset_nl_hybrid_router
from dimos.agents.nl.task.router import TaskIntent, parse_nl_task_intent


@pytest.fixture(autouse=True)
def _reset_navigation_runtime() -> None:
    reset_navigation_bootstrap()
    reset_nl_hybrid_router()
    yield
    reset_navigation_bootstrap()
    reset_nl_hybrid_router()


class TestParseNlTaskIntentNavigation:
    """Legacy module — tests moved to test_nl_intent_bridge.py."""

    def test_reexported_from_nl_bridge(self) -> None:
        from dimos.agents.nl.tests import test_nl_intent_bridge

        assert hasattr(test_nl_intent_bridge, "TestParseNlTaskIntentWithMockLlm")
