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

"""Resolve NL LLM model from GlobalConfig and available API keys."""

from __future__ import annotations

import os

from dimos.core.global_config import GlobalConfig, global_config

_OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4")
_DEEPSEEK_MODEL_PREFIXES = ("deepseek",)


def resolve_nl_llm_model(config: GlobalConfig | None = None) -> str:
    """Pick an NL parsing model that matches configured keys.

    Uses ``nl_llm_model`` when set explicitly (not the generic default ``gpt-4o``),
    otherwise prefers DeepSeek when only ``DEEPSEEK_API_KEY`` is present.
    """
    cfg = config or global_config
    configured = (cfg.nl_llm_model or "").strip()

    if configured and configured != "gpt-4o":
        return configured

    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))

    if configured == "gpt-4o" and has_openai:
        return configured

    if has_deepseek and not has_openai:
        if configured.startswith(_DEEPSEEK_MODEL_PREFIXES):
            return configured
        return "deepseek-chat"

    if configured:
        return configured

    if has_openai:
        return "gpt-4o"

    if has_deepseek:
        return "deepseek-chat"

    return configured or "gpt-4o"


__all__ = ["resolve_nl_llm_model"]
