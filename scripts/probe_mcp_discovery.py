#!/usr/bin/env python3
"""Probe a running DimOS MCP server: discovery, status, and optional smoke calls.

Use this to verify that an external client (voice dialogue system, frontend demo)
can discover and reach your agent skills over MCP.

Prerequisites:
  1. Start the blueprint, e.g. ``dimos run dax-agent --daemon``
  2. Run this script from the dimos repo venv.

Examples:
  python scripts/probe_mcp_discovery.py
  python scripts/probe_mcp_discovery.py --url http://192.168.1.10:9990/mcp
  python scripts/probe_mcp_discovery.py --step all --expect chat execute_nl_task
  python scripts/probe_mcp_discovery.py --step chat --chat-text "你好"
  python scripts/probe_mcp_discovery.py --step agent_events
  python scripts/probe_mcp_discovery.py --step agent_events_live --chat-text "你好"

Manual SSE smoke (two terminals):
  Terminal 1: curl -N -H 'Accept: text/event-stream' http://localhost:9990/agent_events
  Terminal 2: dimos mcp call chat --arg text="你好" --arg timeout=60
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

from dimos.agents.mcp.mcp_adapter import McpAdapter, McpError
from dimos.core.global_config import global_config

DEFAULT_DAX_TOOLS = (
    "chat",
    "execute_nl_task",
    "head_accept",
    "head_reject",
    "agent_send",
    "server_status",
    "list_modules",
)

PROBE_STEPS = (
    "connect",
    "initialize",
    "list_tools",
    "status",
    "modules",
    "agent_events",
    "agent_events_live",
    "chat",
    "all",
)

REQUIRED_SSE_EVENTS = ("user_input", "reasoning", "agent_message")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe DimOS MCP server discovery and skills.")
    parser.add_argument(
        "--url",
        default="",
        help=f"MCP JSON-RPC URL (default: http://localhost:{global_config.mcp_port}/mcp)",
    )
    parser.add_argument(
        "--ready-timeout-s",
        type=float,
        default=15.0,
        help="Seconds to wait for MCP server to respond (default: 15)",
    )
    parser.add_argument(
        "--step",
        choices=PROBE_STEPS,
        default="all",
        help="Which probe step to run (default: all)",
    )
    parser.add_argument(
        "--expect",
        nargs="*",
        default=list(DEFAULT_DAX_TOOLS),
        help="Tool names that must appear in tools/list (default: dax-agent skill set)",
    )
    parser.add_argument(
        "--no-expect",
        action="store_true",
        help="Skip checking --expect tool names",
    )
    parser.add_argument(
        "--chat-text",
        default="",
        help="Text for chat smoke test (default: skip chat call unless --step chat)",
    )
    parser.add_argument(
        "--chat-timeout-s",
        type=float,
        default=30.0,
        help="Timeout for chat tool call in seconds (default: 30)",
    )
    parser.add_argument(
        "--sse-timeout-s",
        type=float,
        default=5.0,
        help="Seconds to wait for first SSE frame on /agent_events (default: 5)",
    )
    parser.add_argument(
        "--live-timeout-s",
        type=float,
        default=90.0,
        help="Total seconds for agent_events_live SSE capture and chat (default: 90)",
    )
    return parser.parse_args()


def _mcp_base_url(mcp_url: str) -> str:
    """Strip ``/mcp`` path to get the HTTP server root for SSE endpoints."""
    parsed = urlparse(mcp_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/mcp"):
        path = path[: -len("/mcp")]
    return urlunparse((parsed.scheme, parsed.netloc, path or "", "", "", ""))


def _agent_events_url(mcp_url: str) -> str:
    return f"{_mcp_base_url(mcp_url).rstrip('/')}/agent_events"


@dataclass
class SseLiveCapture:
    """Thread-safe accumulator for live SSE probe."""

    connected: bool = False
    connected_event: Event = field(default_factory=Event)
    stop: Event = field(default_factory=Event)
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    agent_message_by_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    samples: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str = ""


def _parse_sse_data_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    payload = line[5:].lstrip()
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {"_raw": payload}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _parse_sse_events(
    lines: list[str],
) -> list[tuple[str | None, dict[str, Any] | None]]:
    """Parse SSE lines into completed (event_name, data) frames."""
    frames: list[tuple[str | None, dict[str, Any] | None]] = []
    current_event: str | None = None
    current_data: dict[str, Any] | None = None

    for line in lines:
        if line == "":
            if current_event is not None or current_data is not None:
                frames.append((current_event, current_data))
            current_event = None
            current_data = None
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line[6:].lstrip() or None
            continue
        if line.startswith("data:"):
            current_data = _parse_sse_data_line(line)

    if current_event is not None or current_data is not None:
        frames.append((current_event, current_data))
    return frames


def _agent_message_sample_score(data: dict[str, Any]) -> int:
    """Prefer ai + reasoning_content samples for agent_message display."""
    if data.get("type") == "ai" and data.get("reasoning_content"):
        return 3
    if data.get("type") == "ai":
        return 2
    return 1


def _record_sse_frame(capture: SseLiveCapture, event_name: str | None, data: dict[str, Any] | None) -> None:
    if event_name is None:
        return
    capture.counts[event_name] += 1
    if data is not None:
        if event_name not in capture.samples:
            capture.samples[event_name] = data
        elif event_name == "agent_message":
            current = capture.samples[event_name]
            if _agent_message_sample_score(data) > _agent_message_sample_score(current):
                capture.samples[event_name] = data
    if event_name == "agent_message" and data is not None:
        msg_type = str(data.get("type", "unknown"))
        capture.agent_message_by_type[msg_type] += 1


def _sse_live_reader(url: str, capture: SseLiveCapture, live_timeout_s: float) -> None:
    deadline = time.monotonic() + live_timeout_s
    current_event: str | None = None
    current_data: dict[str, Any] | None = None

    def flush_frame() -> None:
        nonlocal current_event, current_data
        if current_event is not None or current_data is not None:
            _record_sse_frame(capture, current_event, current_data)
        current_event = None
        current_data = None

    try:
        with requests.get(
            url,
            stream=True,
            timeout=(3.0, live_timeout_s + 10.0),
            headers={"Accept": "text/event-stream"},
        ) as resp:
            if resp.status_code != 200:
                capture.error = f"HTTP {resp.status_code}"
                capture.connected_event.set()
                return

            for line in resp.iter_lines(decode_unicode=True):
                if capture.stop.is_set() or time.monotonic() >= deadline:
                    break
                if line is None:
                    continue

                if line.startswith(": connected"):
                    capture.connected = True
                    capture.connected_event.set()
                    continue

                if line == "":
                    flush_frame()
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    current_event = line[6:].lstrip() or None
                    continue
                if line.startswith("data:"):
                    current_data = _parse_sse_data_line(line)

            flush_frame()
    except requests.RequestException as exc:
        capture.error = str(exc)
    finally:
        capture.connected_event.set()
        capture.stop.set()


def _format_event_sample(event_name: str, data: dict[str, Any]) -> str:
    if event_name == "reasoning":
        return f"step_type={data.get('step_type', '?')}"
    if event_name == "agent_message":
        sample = f"type={data.get('type', '?')}"
        if data.get("reasoning_content"):
            sample += ", has_reasoning=True"
        return sample
    if event_name == "user_input":
        text = str(data.get("text", ""))
        preview = text[:40] + ("..." if len(text) > 40 else "")
        return f"text={preview!r}"
    return json.dumps(data, ensure_ascii=False)[:60]


def _resolve_adapter(url: str) -> McpAdapter:
    if url:
        return McpAdapter(url=url)
    return McpAdapter.from_run_entry()


def _print_ok(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"OK  {label}{suffix}", flush=True)


def _print_fail(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"FAIL {label}{suffix}", file=sys.stderr, flush=True)


def step_connect(adapter: McpAdapter, ready_timeout_s: float) -> bool:
    print(f"Probing MCP at {adapter.url}", flush=True)
    if not adapter.wait_for_ready(timeout=ready_timeout_s):
        _print_fail("connect", f"no response within {ready_timeout_s}s")
        return False
    _print_ok("connect", adapter.url)
    return True


def step_initialize(adapter: McpAdapter) -> bool:
    try:
        result = adapter.initialize()
    except (McpError, requests.RequestException) as exc:
        _print_fail("initialize", str(exc))
        return False

    server_info = result.get("result", {}).get("serverInfo", {})
    name = server_info.get("name", "?")
    version = server_info.get("version", "?")
    _print_ok("initialize", f"server={name} version={version}")
    return True


def step_list_tools(adapter: McpAdapter, expect: list[str], *, check_expect: bool) -> bool:
    try:
        tools = adapter.list_tools()
    except (McpError, requests.RequestException) as exc:
        _print_fail("list_tools", str(exc))
        return False

    names = sorted(t.get("name", "") for t in tools)
    _print_ok("list_tools", f"{len(names)} tools")
    for tool in tools:
        name = tool.get("name", "")
        desc = (tool.get("description") or "").split("\n")[0][:80]
        print(f"  - {name}: {desc}", flush=True)

    if not check_expect:
        return True

    missing = [name for name in expect if name not in names]
    if missing:
        _print_fail("list_tools expect", f"missing: {', '.join(missing)}")
        return False
    _print_ok("list_tools expect", f"all {len(expect)} expected tools present")
    return True


def step_status(adapter: McpAdapter) -> bool:
    try:
        raw = adapter.call_tool_text("server_status")
        data: dict[str, Any] = json.loads(raw)
    except (McpError, requests.RequestException, json.JSONDecodeError) as exc:
        _print_fail("server_status", str(exc))
        return False

    _print_ok(
        "server_status",
        f"pid={data.get('pid')} modules={len(data.get('modules', []))} "
        f"skills={len(data.get('skills', []))}",
    )
    print(json.dumps(data, indent=2, ensure_ascii=False), flush=True)
    return True


def step_modules(adapter: McpAdapter) -> bool:
    try:
        raw = adapter.call_tool_text("list_modules")
        data: dict[str, Any] = json.loads(raw)
    except (McpError, requests.RequestException, json.JSONDecodeError) as exc:
        _print_fail("list_modules", str(exc))
        return False

    modules = data.get("modules", {})
    _print_ok("list_modules", f"{len(modules)} modules")
    print(json.dumps(data, indent=2, ensure_ascii=False), flush=True)
    return True


def step_agent_events(mcp_url: str, sse_timeout_s: float) -> bool:
    events_url = _agent_events_url(mcp_url)
    print(f"Probing SSE {events_url}", flush=True)
    try:
        with requests.get(
            events_url,
            stream=True,
            timeout=(3.0, sse_timeout_s + 3.0),
            headers={"Accept": "text/event-stream"},
        ) as resp:
            if resp.status_code != 200:
                _print_fail("agent_events", f"HTTP {resp.status_code}")
                return False

            deadline = time.monotonic() + sse_timeout_s
            for line in resp.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                if line.startswith(": connected"):
                    _print_ok("agent_events", "SSE connected")
                    return True
                if time.monotonic() >= deadline:
                    break
    except requests.RequestException as exc:
        _print_fail("agent_events", str(exc))
        return False

    _print_fail("agent_events", f"no connected frame within {sse_timeout_s}s")
    return False


def step_agent_events_live(
    adapter: McpAdapter,
    mcp_url: str,
    chat_text: str,
    live_timeout_s: float,
) -> bool:
    events_url = _agent_events_url(mcp_url)
    text = chat_text or "你好"
    print(
        f"Probing live SSE {events_url} with chat(text={text!r}, timeout={live_timeout_s})",
        flush=True,
    )

    capture = SseLiveCapture()
    reader = Thread(
        target=_sse_live_reader,
        args=(events_url, capture, live_timeout_s),
        daemon=True,
    )
    reader.start()

    connect_deadline = time.monotonic() + min(15.0, live_timeout_s)
    while not capture.connected_event.is_set():
        if time.monotonic() >= connect_deadline:
            capture.stop.set()
            reader.join(timeout=2.0)
            _print_fail("agent_events_live", "no SSE connected frame within 15s")
            if capture.error:
                _print_fail("agent_events_live", capture.error)
            return False
        time.sleep(0.05)

    if capture.error:
        capture.stop.set()
        reader.join(timeout=2.0)
        _print_fail("agent_events_live", capture.error)
        return False

    _print_ok("agent_events_live", "connected")

    chat_reply = ""
    try:
        chat_reply = adapter.call_tool_text(
            "chat",
            {"text": text, "timeout": live_timeout_s},
        )
    except (McpError, requests.RequestException) as exc:
        chat_reply = f"Error: {exc}"

    capture.stop.set()
    reader.join(timeout=5.0)

    ok = True
    for event_name in REQUIRED_SSE_EVENTS:
        count = capture.counts.get(event_name, 0)
        if count < 1:
            _print_fail(event_name, f"count={count} (expected >= 1)")
            ok = False
            continue
        sample = ""
        if event_name in capture.samples:
            sample = f" (sample: {_format_event_sample(event_name, capture.samples[event_name])})"
        _print_ok(event_name, f"x{count}{sample}")

    ai_count = capture.agent_message_by_type.get("ai", 0)
    if capture.counts.get("agent_message", 0) >= 1 and ai_count < 1:
        _print_fail("agent_message ai", "no agent_message with type=ai")
        ok = False
    elif ai_count >= 1:
        by_type = ", ".join(f"{k} x{v}" for k, v in sorted(capture.agent_message_by_type.items()))
        _print_ok("agent_message types", by_type)

    if not ok:
        received = ", ".join(f"{k}={v}" for k, v in sorted(capture.counts.items())) or "none"
        _print_fail("agent_events_live", f"received events: {received}")
        return False

    preview = chat_reply[:200] + ("..." if len(chat_reply) > 200 else "")
    if chat_reply.startswith("Error:"):
        _print_fail("chat (soft)", preview)
    elif chat_reply:
        _print_ok("chat", preview)

    return ok


def step_chat(adapter: McpAdapter, text: str, chat_timeout_s: float) -> bool:
    if not text:
        _print_fail("chat", "pass --chat-text to run chat smoke test")
        return False

    print(f"Calling chat(text={text!r}, timeout={chat_timeout_s})", flush=True)
    try:
        reply = adapter.call_tool_text(
            "chat",
            {"text": text, "timeout": chat_timeout_s},
        )
    except (McpError, requests.RequestException) as exc:
        _print_fail("chat", str(exc))
        return False

    preview = reply[:200] + ("..." if len(reply) > 200 else "")
    if reply.startswith("Error:"):
        _print_fail("chat", preview)
        return False

    _print_ok("chat", preview)
    print(reply, flush=True)
    return True



def main() -> int:
    args = parse_args()
    adapter = _resolve_adapter(args.url)
    check_expect = not args.no_expect

    if args.step == "all":
        targets = ["connect", "initialize", "list_tools", "status", "modules", "agent_events"]
        if args.chat_text:
            targets.append("chat")
    else:
        targets = [args.step]

    steps_ok = True
    for target in targets:
        if target == "connect":
            if not step_connect(adapter, args.ready_timeout_s):
                return 1
        elif target == "initialize":
            steps_ok &= step_initialize(adapter)
        elif target == "list_tools":
            steps_ok &= step_list_tools(adapter, args.expect, check_expect=check_expect)
        elif target == "status":
            steps_ok &= step_status(adapter)
        elif target == "modules":
            steps_ok &= step_modules(adapter)
        elif target == "agent_events":
            steps_ok &= step_agent_events(adapter.url, args.sse_timeout_s)
        elif target == "agent_events_live":
            if not step_connect(adapter, args.ready_timeout_s):
                return 1
            steps_ok &= step_agent_events_live(
                adapter,
                adapter.url,
                args.chat_text,
                args.live_timeout_s,
            )
        elif target == "chat":
            steps_ok &= step_chat(adapter, args.chat_text, args.chat_timeout_s)

    return 0 if steps_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
