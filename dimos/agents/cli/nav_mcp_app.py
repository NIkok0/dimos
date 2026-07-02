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

"""``dimos nav-mcp`` — standard MCP navigation server for external Dialog clients."""

from __future__ import annotations

import typer

from dimos.agents.mcp.mcp_adapter import McpAdapter
from dimos.agents.navigation_mcp.backend import NavigationBackend
from dimos.agents.navigation_mcp.server import run_navigation_mcp
from dimos.core.global_config import global_config

app = typer.Typer(
    help="Standard MCP navigation server (Streamable HTTP)",
    no_args_is_help=True,
)


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind address"),
    port: int = typer.Option(8093, "--port", help="HTTP port for MCP Streamable HTTP"),
    mount_path: str = typer.Option("/mcp", "--mount-path", help="MCP endpoint path"),
    mcp_url: str = typer.Option(
        "",
        "--mcp-url",
        help="dax-agent MCP URL (default: http://127.0.0.1:<mcp_port>/mcp)",
    ),
    mcp_timeout: int = typer.Option(60, "--mcp-timeout", help="dax-agent MCP call timeout (seconds)"),
    check_mcp: bool = typer.Option(
        True,
        "--check-mcp/--no-check-mcp",
        help="Fail fast if dax-agent MCP is not reachable",
    ),
) -> None:
    """Start the navigation MCP server (requires ``dimos run dax-agent -d``)."""
    url = mcp_url or f"http://127.0.0.1:{global_config.mcp_port}/mcp"
    backend = NavigationBackend.from_url(url, timeout=mcp_timeout)

    if check_mcp:
        typer.echo(f"Waiting for dax-agent MCP at {url} ...")
        adapter = McpAdapter(url=url, timeout=mcp_timeout)
        if not adapter.wait_for_ready(timeout=15.0):
            typer.echo(
                "Error: dax-agent MCP not reachable. Start it first:\n"
                "  dimos run dax-agent -d",
                err=True,
            )
            raise typer.Exit(1)
        typer.echo("dax-agent MCP ready.")

    endpoint = f"http://{host}:{port}{mount_path}"
    if host == "0.0.0.0":
        endpoint = f"http://<your-ip>:{port}{mount_path}"
    typer.echo(f"Navigation MCP listening on http://{host}:{port}{mount_path}")
    typer.echo(f"Colleague MCP Client URL: {endpoint}")
    typer.echo("Tools: move_relative, move_to_workspace, execute_navigation_task")
    run_navigation_mcp(backend, host=host, port=port, mount_path=mount_path)


__all__ = ["app"]
