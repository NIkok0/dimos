#!/usr/bin/env python3
"""Probe a live /vis/* frontend with a simulated agent turn (no robot tools needed).

Use when dax-agent tools (wave, dax_server, rosbridge) are down but you still
want to verify the demo frontend receives thoughts (think/result) and outputs
(tool_calls with status working/completed/failed).

Requires: ``pip install requests`` (included in dax-agent venv).

Examples:
  python scripts/vis_bridge_probe.py --url http://10.69.6.113:8765
  python scripts/vis_bridge_probe.py --url http://10.69.6.113:8765 --text "帮我挥挥手"
  python scripts/vis_bridge_probe.py --tool wave --tool execute_nl_task
    # each --tool gets its own session (input + thoughts + one tool_call)
  python scripts/vis_bridge_probe.py --no-tools
  python scripts/vis_bridge_probe.py --failed
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any

import requests

DEFAULT_URL = "http://10.69.6.113:8765"
DEFAULT_TEXT = "你好，帮我挥挥手"
DEFAULT_THOUGHTS = [
    "thought: 用户在打招呼并请求挥手",
    "我是 Dax，由 Dimensional 开发的 AI 操作员。收到，正在执行挥手。",
]


def _post(url: str, data: dict[str, Any], timeout: float) -> dict[str, Any]:
    print(f"POST {url}")
    print(f"  body: {json.dumps(data, ensure_ascii=False)}")
    resp = requests.post(url, json=data, timeout=timeout)
    print(f"  -> HTTP {resp.status_code} {resp.text[:200]}")
    resp.raise_for_status()
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return body if isinstance(body, dict) else {}


def _default_tool_calls(names: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, name in enumerate(names, start=1):
        out.append(
            {
                "name": name,
                "args": {} if name == "wave" else {"task": "去货架拿一瓶水"},
                "id": f"probe_call_{i}_{uuid.uuid4().hex[:8]}",
                "type": "tool_call",
            }
        )
    return out


def _post_outputs(
    base: str,
    session_id: str,
    tool_calls: list[dict[str, Any]],
    *,
    status: str,
    outputs_format: str,
    timeout_s: float,
) -> None:
    if outputs_format == "legacy":
        outputs_body: dict[str, Any] = {
            "session_id": session_id,
            "result": {"tool_calls": tool_calls},
            "status": status,
        }
    else:
        outputs_body = {
            "session_id": session_id,
            "tool_calls": tool_calls,
            "status": status,
        }
    _post(f"{base}/vis/outputs", outputs_body, timeout_s)


def run_probe(
    base_url: str,
    *,
    text: str,
    thoughts: list[str],
    tool_calls: list[dict[str, Any]],
    timeout_s: float,
    outputs_format: str,
    final_status: str,
) -> str:
    base = base_url.rstrip("/")

    session_body = _post(f"{base}/vis/input", {"text": text}, timeout_s)
    session_id = str(session_body.get("session_id", ""))
    if not session_id:
        raise RuntimeError(f"/vis/input did not return session_id: {session_body}")

    seq = 0
    think_steps = thoughts[:-1] if len(thoughts) > 1 else thoughts
    result_text = thoughts[-1] if len(thoughts) > 1 else None

    for thought in think_steps:
        seq += 1
        _post(
            f"{base}/vis/thoughts",
            {"session_id": session_id, "seq": seq, "think": thought},
            timeout_s,
        )

    for tc in tool_calls:
        seq += 1
        _post(
            f"{base}/vis/thoughts",
            {
                "session_id": session_id,
                "seq": seq,
                "think": f"Tool call: {tc.get('name', 'unknown')}",
            },
            timeout_s,
        )
        _post_outputs(
            base,
            session_id,
            [tc],
            status="working",
            outputs_format=outputs_format,
            timeout_s=timeout_s,
        )

    if result_text is not None:
        seq += 1
        _post(
            f"{base}/vis/thoughts",
            {"session_id": session_id, "seq": seq, "result": result_text},
            timeout_s,
        )

    _post_outputs(
        base,
        session_id,
        tool_calls,
        status=final_status,
        outputs_format=outputs_format,
        timeout_s=timeout_s,
    )

    return session_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate one VisBridge turn against /vis/* frontend")
    parser.add_argument("--url", default=DEFAULT_URL, help="Frontend base URL")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="User input for /vis/input")
    parser.add_argument(
        "--thought",
        action="append",
        dest="thoughts",
        default=None,
        help="Content for /vis/thoughts (repeatable)",
    )
    parser.add_argument(
        "--tool",
        action="append",
        dest="tools",
        default=None,
        help="Tool name for /vis/outputs (repeatable; default: wave)",
    )
    parser.add_argument("--no-tools", action="store_true", help="Send completed with empty tool_calls")
    parser.add_argument(
        "--failed",
        action="store_true",
        help="Send final status=failed instead of completed",
    )
    parser.add_argument(
        "--outputs-format",
        choices=("flat", "legacy"),
        default="legacy",
        help="legacy=result.tool_calls (113 frontend); flat=top-level tool_calls",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    thoughts = args.thoughts or list(DEFAULT_THOUGHTS)
    tool_calls: list[dict[str, Any]] = []
    if not args.no_tools:
        tool_calls = _default_tool_calls(args.tools or ["wave"])
    final_status = "failed" if args.failed else "completed"

    print(f"==> Simulated VisBridge turn -> {args.url}")
    try:
        if args.no_tools:
            session_ids = [
                run_probe(
                    args.url,
                    text=args.text,
                    thoughts=thoughts,
                    tool_calls=[],
                    timeout_s=args.timeout,
                    outputs_format=args.outputs_format,
                    final_status=final_status,
                )
            ]
        elif args.tools and len(args.tools) > 1:
            session_ids = []
            for tool_name in args.tools:
                print(f"\n--- session for tool: {tool_name} ---")
                session_ids.append(
                    run_probe(
                        args.url,
                        text=args.text,
                        thoughts=thoughts,
                        tool_calls=_default_tool_calls([tool_name]),
                        timeout_s=args.timeout,
                        outputs_format=args.outputs_format,
                        final_status=final_status,
                    )
                )
        else:
            session_ids = [
                run_probe(
                    args.url,
                    text=args.text,
                    thoughts=thoughts,
                    tool_calls=tool_calls,
                    timeout_s=args.timeout,
                    outputs_format=args.outputs_format,
                    final_status=final_status,
                )
            ]
    except requests.RequestException as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if len(session_ids) == 1:
        print(f"==> Done. session_id={session_ids[0]}")
    else:
        print(f"==> Done. session_ids={session_ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
