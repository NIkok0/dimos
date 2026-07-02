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

"""FastMCP server exposing navigation-only tools via Streamable HTTP."""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from dimos.agents.navigation_mcp.backend import NavigationBackend

RelativeDirection = Literal["forward", "backward", "left", "right"]
WorkspaceName = Literal["front_workspace", "table"]


def build_navigation_mcp(
    backend: NavigationBackend,
    *,
    host: str = "0.0.0.0",
    port: int = 8093,
    streamable_http_path: str = "/mcp",
) -> FastMCP:
    """Create a FastMCP instance with navigation tools bound to ``backend``."""
    mcp = FastMCP(
        "dimos-navigation",
        instructions=(
            "DimOS robot navigation tools. Use move_relative or move_to_workspace "
            "for structured navigation. Returns JSON with a spoken message field."
        ),
        stateless_http=True,
        json_response=True,
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )

    @mcp.tool()
    def move_relative(direction: RelativeDirection, distance_meters: float) -> str:
        """Move the robot relative to its body frame.

        Args:
            direction: forward, backward, left, or right.
            distance_meters: Distance in meters (e.g. 1.0 for one meter).
        """
        return backend.move_relative(direction, distance_meters)

    @mcp.tool()
    def move_to_workspace(
        workspace_name: WorkspaceName,
        workspace_color: str = "",
    ) -> str:
        """Navigate to a named workspace.

        Args:
            workspace_name: front_workspace for the fixed front area, or table.
            workspace_color: Required when workspace_name is table (e.g. red, blue, 红色).
        """
        return backend.move_to_workspace(workspace_name, workspace_color)

    @mcp.tool()
    def execute_navigation_task(text: str) -> str:
        """Execute a natural-language navigation command not covered by structured tools.

        Args:
            text: Navigation instruction, e.g. 向左移动0.5米.
        """
        return backend.execute_navigation_task(text)

    return mcp


def run_navigation_mcp(
    backend: NavigationBackend,
    *,
    host: str = "0.0.0.0",
    port: int = 8093,
    mount_path: str = "/mcp",
) -> None:
    """Run the navigation MCP server (blocks until stopped)."""
    mcp = build_navigation_mcp(
        backend,
        host=host,
        port=port,
        streamable_http_path=mount_path,
    )
    mcp.run(transport="streamable-http")


__all__ = ["RelativeDirection", "WorkspaceName", "build_navigation_mcp", "run_navigation_mcp"]
