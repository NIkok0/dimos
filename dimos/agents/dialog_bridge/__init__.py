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

"""Shared NL builders and response formatters for navigation MCP facades."""

from dimos.agents.dialog_bridge.nl_builder import (
    RelativeDirection,
    WorkspaceName,
    build_move_relative_nl,
    build_move_to_workspace_nl,
)
from dimos.agents.dialog_bridge.response import (
    build_dialog_response,
    build_error_response,
    mcp_error_message,
    parse_mcp_tool_text,
)

__all__ = [
    "RelativeDirection",
    "WorkspaceName",
    "build_dialog_response",
    "build_error_response",
    "build_move_relative_nl",
    "build_move_to_workspace_nl",
    "mcp_error_message",
    "parse_mcp_tool_text",
]
