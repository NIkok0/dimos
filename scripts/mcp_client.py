#!/usr/bin/env python3
"""Standalone MCP client for poking at a running DimOS MCP server.

Use this to call tools / raw JSON-RPC methods and inspect the full JSON return
values while developing or debugging skills.

Prerequisites:
  1. Start the blueprint, e.g. ``dimos run dax-agent --daemon``
  2. Run from the dimos repo venv.

Examples:
  # List all tools with their schemas
  python scripts/mcp_client.py list

  # Call a tool with key=value args (type-inferred)
  python scripts/mcp_client.py call chat --arg text="你好" --arg timeout=60
  python scripts/mcp_client.py call wave --arg start_index=150 --arg send_count=200
  python scripts/mcp_client.py call head_accept

  # Call a tool with a JSON object
  python scripts/mcp_client.py call chat --json '{"text": "你好", "timeout": 60}'

  # Show the full raw JSON-RPC response (not just the text content)
  python scripts/mcp_client.py call chat --arg text="你好" --raw

  # Send an arbitrary JSON-RPC method
  python scripts/mcp_client.py raw initialize
  python scripts/mcp_client.py raw tools/list
  python scripts/mcp_client.py raw tools/call --params '{"name": "server_status", "arguments": {}}'

  # Point at a remote server
  python scripts/mcp_client.py --url http://192.168.1.10:9990/mcp list
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from dimos.agents.mcp.mcp_adapter import McpAdapter, McpError
from dimos.core.global_config import global_config


def _infer_value(raw: str) -> Any:
    """Infer int / float / bool / json / str from a --arg key=value string."""
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        parsed = json.loads(raw)
        return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return raw


def _build_args(arg_list: list[str], json_str: str) -> dict[str, Any]:
    """Merge --arg k=v pairs and --json object into one arguments dict."""
    args: dict[str, Any] = {}
    if json_str:
        obj = json.loads(json_str)
        if not isinstance(obj, dict):
            raise SystemExit(f"--json must be a JSON object, got {type(obj).__name__}")
        args.update(obj)
    for item in arg_list:
        if "=" not in item:
            raise SystemExit(f"--arg expects key=value, got {item!r}")
        key, _, value = item.partition("=")
        args[key.strip()] = _infer_value(value)
    return args


def _print_json(label: str, data: Any) -> None:
    print(f"=== {label} ===")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_initialize(adapter: McpAdapter) -> int:
    resp = adapter.initialize()
    _print_json("initialize", resp)
    info = resp.get("result", {}).get("serverInfo", {})
    print(f"\nserver: {info.get('name')} {info.get('version')}")
    return 0


def cmd_list(adapter: McpAdapter) -> int:
    tools = adapter.list_tools()
    print(f"{len(tools)} tools:\n")
    for tool in tools:
        name = tool.get("name", "")
        desc = (tool.get("description") or "").split("\n")[0]
        schema = tool.get("inputSchema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])
        params = ", ".join(
            f"{p}: {props[p].get('type', '?')}{'*' if p in required else ''}"
            for p in props
        )
        print(f"  {name}({params})")
        print(f"    {desc[:100]}")
    return 0


def cmd_call(adapter: McpAdapter, tool: str, args: dict[str, Any], raw: bool) -> int:
    print(f"Calling tools/call name={tool!r} arguments={json.dumps(args, ensure_ascii=False)}")
    if raw:
        # Full JSON-RPC envelope, including error field if any.
        resp = adapter.call("tools/call", {"name": tool, "arguments": args})
        _print_json("raw response", resp)
        return 0 if "error" not in resp else 1
    try:
        result = adapter.call_tool(tool, args)
    except McpError as exc:
        _print_json("MCP error", {"code": exc.code, "message": str(exc)})
        return 1
    _print_json("result", result)
    content = result.get("content", [])
    if content:
        text = content[0].get("text", "")
        if text:
            print("\n--- text content ---")
            print(text)
    return 0


def cmd_raw(adapter: McpAdapter, method: str, params: dict[str, Any] | None) -> int:
    print(f"Sending JSON-RPC method={method!r} params={json.dumps(params, ensure_ascii=False) if params else '(none)'}")
    resp = adapter.call(method, params)
    _print_json("response", resp)
    return 0 if "error" not in resp else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone MCP client to call tools and inspect return values.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default="",
        help=f"MCP JSON-RPC URL (default: http://localhost:{global_config.mcp_port}/mcp)",
    )
    parser.add_argument(
        "--ready-timeout-s",
        type=float,
        default=15.0,
        help="Seconds to wait for the server (default: 15)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("initialize", help="Send initialize and print serverInfo")
    sub.add_parser("list", help="List all tools with their argument schemas").aliases = ["list-tools"]

    p_call = sub.add_parser("call", help="Call a tool by name")
    p_call.add_argument("tool", help="Tool name, e.g. chat / wave / head_accept")
    p_call.add_argument("--arg", action="append", default=[], metavar="KEY=VALUE", help="Typed arg (int/float/bool/json/str inferred)")
    p_call.add_argument("--json", dest="json_args", default="", metavar="JSON", help="Arguments as a JSON object")
    p_call.add_argument("--raw", action="store_true", help="Print the full JSON-RPC envelope instead of unwrapping")

    p_raw = sub.add_parser("raw", help="Send an arbitrary JSON-RPC method")
    p_raw.add_argument("method", help="JSON-RPC method, e.g. initialize / tools/list")
    p_raw.add_argument("--params", default="", metavar="JSON", help="Params as a JSON object")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    adapter = McpAdapter(url=args.url) if args.url else McpAdapter.from_run_entry()
    if not args.url:
        # from_run_entry may fall back to default; show what we picked.
        pass
    print(f"MCP server: {adapter.url}")

    if not adapter.wait_for_ready(timeout=args.ready_timeout_s):
        print(f"FAIL: no response within {args.ready_timeout_s}s", file=sys.stderr)
        return 1

    if args.command in ("list", "list-tools"):
        return cmd_list(adapter)
    if args.command == "initialize":
        return cmd_initialize(adapter)
    if args.command == "call":
        try:
            tool_args = _build_args(args.arg, args.json_args)
        except json.JSONDecodeError as exc:
            print(f"FAIL: bad JSON argument: {exc}", file=sys.stderr)
            return 1
        return cmd_call(adapter, args.tool, tool_args, args.raw)
    if args.command == "raw":
        params = None
        if args.params:
            try:
                params = json.loads(args.params)
            except json.JSONDecodeError as exc:
                print(f"FAIL: bad --params JSON: {exc}", file=sys.stderr)
                return 1
            if not isinstance(params, dict):
                print("FAIL: --params must be a JSON object", file=sys.stderr)
                return 1
        return cmd_raw(adapter, args.method, params)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
