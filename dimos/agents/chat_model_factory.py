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

"""LangChain chat model factory with proxy-safe httpx clients."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

_PROXY_ENV_KEYS = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)

_DEFAULT_TIMEOUT = httpx.Timeout(120.0)


def normalize_proxy_url(proxy: str) -> str:
    """Convert SOCKS proxy URLs to HTTP for httpx without httpx[socks]."""
    parsed = urlparse(proxy.strip())
    if parsed.scheme in {"socks", "socks5", "socks5h", "socks4"}:
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 7897
        return f"http://{host}:{port}"
    return proxy.strip()


def proxy_from_env() -> str | None:
    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            return normalize_proxy_url(value)
    return None


def make_sync_http_client(*, proxy: str | None = None) -> httpx.Client:
    if proxy:
        return httpx.Client(proxy=proxy, trust_env=False, timeout=_DEFAULT_TIMEOUT)
    return httpx.Client(trust_env=False, timeout=_DEFAULT_TIMEOUT)


def make_async_http_client(*, proxy: str | None = None) -> httpx.AsyncClient:
    if proxy:
        return httpx.AsyncClient(proxy=proxy, trust_env=False, timeout=_DEFAULT_TIMEOUT)
    return httpx.AsyncClient(trust_env=False, timeout=_DEFAULT_TIMEOUT)


def make_chat_model(model: str, **kwargs: Any) -> BaseChatModel:
    """Initialize a chat model without inheriting unsupported SOCKS proxy env vars.

    For DeepSeek-V4 models, automatically enables thinking mode with high reasoning effort
    to expose chain-of-thought reasoning content.
    """
    if "http_client" not in kwargs:
        proxy = proxy_from_env()
        kwargs["http_client"] = make_sync_http_client(proxy=proxy)
    if "http_async_client" not in kwargs:
        proxy = proxy_from_env()
        kwargs["http_async_client"] = make_async_http_client(proxy=proxy)

    # DeepSeek V4 models: enable thinking mode for reasoning trace
    if model.startswith("deepseek-v4"):
        # Thinking mode is enabled by default, but we set it explicitly for clarity
        # reasoning_effort can be "high" or "max" (default is "high")
        reasoning_effort = kwargs.pop("reasoning_effort", "high")
        extra_body = kwargs.pop("extra_body", {})
        extra_body["thinking"] = {"type": "enabled"}
        kwargs["extra_body"] = extra_body
        kwargs["reasoning_effort"] = reasoning_effort

    return init_chat_model(model, **kwargs)


__all__ = [
    "make_async_http_client",
    "make_chat_model",
    "make_sync_http_client",
    "normalize_proxy_url",
    "proxy_from_env",
]
