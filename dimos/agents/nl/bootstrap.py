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

"""Bootstrap NL semantic catalog loading."""

from __future__ import annotations

from dimos.agents.nl.navigation_semantic_catalog import (
    NlSemanticCatalog,
    get_nl_semantic_catalog,
    reset_nl_semantic_catalog,
)
from dimos.agents.nl.navigation_semantic_mapper import reset_nl_semantic_mapper

ensure_navigation_semantics_loaded = ensure_nl_semantics_loaded = get_nl_semantic_catalog


def reset_navigation_bootstrap() -> None:
    reset_nl_semantic_catalog()
    reset_nl_semantic_mapper()


reset_nl_bootstrap = reset_navigation_bootstrap


__all__ = [
    "ensure_navigation_semantics_loaded",
    "ensure_nl_semantics_loaded",
    "reset_navigation_bootstrap",
    "reset_nl_bootstrap",
]
