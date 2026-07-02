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

import pytest

from dimos.agents.chat_model_factory import make_chat_model, normalize_proxy_url


def test_normalize_proxy_url_converts_socks_to_http() -> None:
    assert normalize_proxy_url("socks://127.0.0.1:7897/") == "http://127.0.0.1:7897"
    assert normalize_proxy_url("socks5://127.0.0.1:7890") == "http://127.0.0.1:7890"


def test_make_chat_model_accepts_socks_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:7897/")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    model = make_chat_model("deepseek-chat")

    assert model.model_name == "deepseek-chat"
    assert model.http_client is not None
    assert model.http_async_client is not None

    model.http_client.close()
