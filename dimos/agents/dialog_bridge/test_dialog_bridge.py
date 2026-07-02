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

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from dimos.agents.dialog_bridge import nl_builder, response
from dimos.agents.mcp.mcp_adapter import McpError
from dimos.agents.navigation_mcp.backend import NavigationBackend


class _FakeMcp:
    def __init__(self, *, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def call_tool_text(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        return self.text


def test_build_move_relative_nl() -> None:
    assert nl_builder.build_move_relative_nl("backward", 1.0) == "向后移动1米"
    assert nl_builder.build_move_relative_nl("forward", 0.5) == "向前移动0.5米"


def test_build_move_relative_nl_invalid() -> None:
    with pytest.raises(ValueError, match="direction"):
        nl_builder.build_move_relative_nl("up", 1.0)
    with pytest.raises(ValueError, match="distance_meters"):
        nl_builder.build_move_relative_nl("forward", 0)


def test_build_move_to_workspace_nl() -> None:
    assert nl_builder.build_move_to_workspace_nl("front_workspace") == "移动到前方固定工作区"
    assert nl_builder.build_move_to_workspace_nl("table", "blue") == "前往蓝色桌子"
    assert nl_builder.build_move_to_workspace_nl("table", "红色") == "前往红色桌子"


def test_build_move_to_workspace_nl_requires_color_for_table() -> None:
    with pytest.raises(ValueError, match="workspace_color"):
        nl_builder.build_move_to_workspace_nl("table", "")


def test_parse_mcp_tool_text_json() -> None:
    raw = json.dumps({"success": True, "message": "Action plan completed.", "duration_ms": 12.3})
    parsed = response.parse_mcp_tool_text(raw)
    assert parsed["success"] is True
    assert parsed["message"] == "Action plan completed."


def test_build_dialog_response_success() -> None:
    raw = json.dumps({"success": True, "message": "正在向后移动。"})
    body = response.build_dialog_response(request_id="req-1", mcp_text=raw)
    assert body["success"] is True
    assert "好的" in body["message"]
    assert body["request_id"] == "req-1"


def test_build_dialog_response_failure() -> None:
    raw = json.dumps(
        {"success": False, "message": "定位未就绪", "error_code": "NAV_NOT_READY"}
    )
    body = response.build_dialog_response(request_id="req-2", mcp_text=raw)
    assert body["success"] is False
    assert "抱歉" in body["message"]
    assert body["error_code"] == "NAV_NOT_READY"


def test_mcp_error_message_busy() -> None:
    msg = response.mcp_error_message(
        McpError("Cannot start 'execute_nl_task': capability 'movement' is held")
    )
    assert "其他任务" in msg


def test_navigation_backend_move_relative() -> None:
    mcp = _FakeMcp(text=json.dumps({"success": True, "message": "已开始相对移动。"}))
    backend = NavigationBackend(mcp)
    raw = backend.move_relative("backward", 1.0)
    data = json.loads(raw)
    assert data["success"] is True
    assert mcp.calls[0][0] == "execute_nl_task"
    assert mcp.calls[0][1]["text"] == "向后移动1米"


def test_navigation_backend_invalid_direction() -> None:
    backend = NavigationBackend(_FakeMcp())
    raw = backend.move_relative("up", 1.0)
    data = json.loads(raw)
    assert data["success"] is False
    assert data["error_code"] == "INVALID_INPUT"


def test_navigation_backend_mcp_connection_error() -> None:
    backend = NavigationBackend(_FakeMcp(error=ConnectionError("refused")))
    raw = backend.move_relative("forward", 1.0)
    data = json.loads(raw)
    assert data["success"] is False
    assert data["error_code"] == "MCP_ERROR"


def test_build_navigation_mcp_registers_tools() -> None:
    pytest.importorskip("mcp")
    from dimos.agents.navigation_mcp.server import build_navigation_mcp

    mcp = build_navigation_mcp(NavigationBackend(MagicMock()))
    tool_names = {tool.name for tool in mcp._tool_manager.list_tools()}  # noqa: SLF001
    assert tool_names == {
        "move_relative",
        "move_to_workspace",
        "execute_navigation_task",
    }
