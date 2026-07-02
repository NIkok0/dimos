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

"""Backward-compatible re-exports for navigation bridge."""

from __future__ import annotations

from dimos.agents.nl.task.nl_intent_bridge import (
    get_nl_hybrid_router,
    parse_nl_intent,
    reset_nl_hybrid_router,
    routing_decision_to_task_intent,
)

get_navigation_hybrid_router = get_nl_hybrid_router
reset_navigation_hybrid_router = reset_nl_hybrid_router
parse_navigation_intent = parse_nl_intent

__all__ = [
    "get_navigation_hybrid_router",
    "get_nl_hybrid_router",
    "parse_navigation_intent",
    "parse_nl_intent",
    "reset_navigation_hybrid_router",
    "reset_nl_hybrid_router",
    "routing_decision_to_task_intent",
]
