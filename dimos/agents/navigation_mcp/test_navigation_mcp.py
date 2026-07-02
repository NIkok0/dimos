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

import asyncio
import json
import subprocess
import sys
import time
from typing import Any

import pytest

from dimos.agents.mcp.mcp_adapter import McpAdapter
from dimos.agents.navigation_mcp.backend import NavigationBackend
from dimos.agents.navigation_mcp.server import build_navigation_mcp


class _FakeMcp:
    def __init__(self, *, text: str = "") -> None:
        self.text = text
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def call_tool_text(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        self.calls.append((name, arguments))
        return self.text


@pytest.mark.integration
def test_streamable_http_call_tool_move_relative() -> None:
    """Integration: MCP client calls nav-mcp when dax-agent is running."""
    pytest.importorskip("mcp")
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    adapter = McpAdapter()
    if not adapter.wait_for_ready(timeout=2.0):
        pytest.skip("dax-agent MCP not running")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "dimos.robot.cli.dimos",
            "nav-mcp",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8093",
            "--no-check-mcp",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = "http://127.0.0.1:8093/mcp"

    async def _run() -> dict[str, Any]:
        async with streamable_http_client(url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert names == {
                    "move_relative",
                    "move_to_workspace",
                    "execute_navigation_task",
                }
                result = await session.call_tool(
                    "move_relative",
                    {"direction": "backward", "distance_meters": 0.1},
                )
                assert result.content
                text = result.content[0].text if hasattr(result.content[0], "text") else str(result.content[0])
                return json.loads(text)

    try:
        for _ in range(30):
            try:
                payload = asyncio.run(_run())
                break
            except Exception:
                time.sleep(0.5)
        else:
            out = proc.stdout.read() if proc.stdout else ""
            pytest.fail(f"nav-mcp server did not become ready: {out}")
        assert "message" in payload
        assert "request_id" in payload
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_build_navigation_mcp_tool_invocation() -> None:
    pytest.importorskip("mcp")
    mcp = build_navigation_mcp(
        NavigationBackend(
            _FakeMcp(text=json.dumps({"success": True, "message": "ok"})),
        )
    )
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}  # noqa: SLF001
    fn = tools["move_to_workspace"].fn
    raw = fn("front_workspace", "")
    data = json.loads(raw)
    assert data["success"] is True
