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

"""Proxy navigation MCP tool calls to dax-agent ``execute_nl_task``."""

from __future__ import annotations

import json
from typing import Any, Protocol
import uuid

from dimos.agents.dialog_bridge import nl_builder, response
from dimos.agents.mcp.mcp_adapter import McpAdapter


class McpTaskCaller(Protocol):
    """Minimal MCP client surface for navigation execution."""

    def call_tool_text(self, name: str, arguments: dict[str, Any] | None = None) -> str: ...


class NavigationBackend:
    """Translate structured navigation params into NL tasks on dax-agent."""

    def __init__(self, mcp: McpTaskCaller) -> None:
        self._mcp = mcp

    @classmethod
    def from_url(cls, url: str, *, timeout: int = 60) -> NavigationBackend:
        return cls(McpAdapter(url=url, timeout=timeout))

    def move_relative(self, direction: str, distance_meters: float) -> str:
        request_id = uuid.uuid4().hex
        try:
            text = nl_builder.build_move_relative_nl(direction, distance_meters)
        except ValueError as exc:
            return self._error_json(request_id=request_id, message=str(exc), error_code="INVALID_INPUT")
        return self.run_nl_task(text, request_id=request_id)

    def move_to_workspace(self, workspace_name: str, workspace_color: str = "") -> str:
        request_id = uuid.uuid4().hex
        try:
            text = nl_builder.build_move_to_workspace_nl(workspace_name, workspace_color)
        except ValueError as exc:
            return self._error_json(request_id=request_id, message=str(exc), error_code="INVALID_INPUT")
        return self.run_nl_task(text, request_id=request_id)

    def execute_navigation_task(self, text: str) -> str:
        request_id = uuid.uuid4().hex
        cleaned = text.strip()
        if not cleaned:
            return self._error_json(
                request_id=request_id,
                message="text must not be empty",
                error_code="INVALID_INPUT",
            )
        return self.run_nl_task(cleaned, request_id=request_id)

    def run_nl_task(self, text: str, *, request_id: str) -> str:
        """Call dax-agent ``execute_nl_task`` and return JSON for MCP tool output."""
        try:
            raw = self._mcp.call_tool_text(
                "execute_nl_task",
                {"text": text, "request_id": request_id},
            )
        except Exception as exc:
            body = response.build_error_response(
                request_id=request_id,
                message=response.mcp_error_message(exc),
                error_code="MCP_ERROR",
            )
            return json.dumps(body, ensure_ascii=False)

        body = response.build_dialog_response(request_id=request_id, mcp_text=raw)
        return json.dumps(body, ensure_ascii=False)

    @staticmethod
    def _error_json(*, request_id: str, message: str, error_code: str) -> str:
        body = response.build_error_response(
            request_id=request_id,
            message=message,
            error_code=error_code,
        )
        return json.dumps(body, ensure_ascii=False)


__all__ = ["McpTaskCaller", "NavigationBackend"]
