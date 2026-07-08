#!/usr/bin/env python3
"""Mock /vis/* frontend for VisBridgeSkill end-to-end verification.

Records every POST to /vis/input, /vis/thoughts, /vis/outputs and prints them
in order. Implements the stop-and-wait contract: session_id generation, seq
validation, idempotency on same session_id+seq+content.

Run:  python scripts/mock_vis_frontend.py --port 8088
Then: dimos run dax-agent --daemon --vis-bridge-url http://localhost:8088
"""
from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class _Session:
    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.last_seq = 0
        self.thoughts: list[tuple[int, str]] = []
        self.output: Any = None
        self.closed = False


class VisHandler(BaseHTTPRequestHandler):
    sessions: dict[str, _Session] = {}
    counter = 0

    def _send(self, code: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        body = self._read_body()
        ts = time.strftime("%H:%M:%S")

        if path == "/vis/input":
            text = str(body.get("text", ""))
            if not text:
                self._send(400, {"code": 40000, "message": "text empty"})
                return
            VisHandler.counter += 1
            sid = f"sess_{VisHandler.counter:04d}"
            VisHandler.sessions[sid] = _Session(sid)
            print(f"[{ts}] /vis/input  text={text[:60]!r} -> session_id={sid}", flush=True)
            self._send(200, {"session_id": sid})
            return

        if path == "/vis/thoughts":
            sid = str(body.get("session_id", ""))
            seq = body.get("seq")
            think = body.get("think")
            result = body.get("result")
            legacy_content = body.get("content")
            payload_text = (
                str(think)
                if think is not None
                else str(result)
                if result is not None
                else str(legacy_content or "")
            )
            if think is None and result is None and legacy_content is None:
                self._send(400, {"code": 40000, "message": "think or result required"})
                return
            sess = VisHandler.sessions.get(sid)
            if sess is None:
                self._send(404, {"code": 40400, "message": "session not found"})
                return
            if sess.closed:
                self._send(409, {"code": 40900, "message": "session closed"})
                return
            if not isinstance(seq, int):
                self._send(400, {"code": 40000, "message": "seq must be int"})
                return
            expected = sess.last_seq + 1
            if seq == sess.last_seq + 0 and seq <= sess.last_seq:
                # duplicate seq
                for s, c in sess.thoughts:
                    if s == seq:
                        if c == payload_text:
                            self._send(200, {"session_id": sid, "received_seq": seq})
                            return
                        self._send(409, {"code": 40900, "message": "payload conflict"})
                        return
            if seq != expected:
                self._send(422, {"code": 42200, "message": "seq not continuous", "expected_seq": expected})
                return
            sess.last_seq = seq
            sess.thoughts.append((seq, payload_text))
            label = "think" if think is not None else "result" if result is not None else "content"
            print(
                f"[{ts}] /vis/thoughts seq={seq} {label}={payload_text[:60]!r}",
                flush=True,
            )
            self._send(200, {"session_id": sid, "received_seq": seq})
            return

        if path == "/vis/outputs":
            sid = str(body.get("session_id", ""))
            tool_calls = body.get("tool_calls")
            if tool_calls is None:
                legacy = body.get("result")
                tool_calls = legacy.get("tool_calls") if isinstance(legacy, dict) else None
            sess = VisHandler.sessions.get(sid)
            if sess is None:
                self._send(404, {"code": 40400, "message": "session not found"})
                return
            if sess.closed:
                self._send(409, {"code": 40900, "message": "already submitted"})
                return
            sess.output = tool_calls
            sess.closed = True
            preview = json.dumps(tool_calls, ensure_ascii=False)[:80] if tool_calls else ""
            print(f"[{ts}] /vis/outputs tool_calls={preview}", flush=True)
            self._send(200, {"session_id": sid})
            return

        self._send(404, {"code": 40400, "message": "unknown path"})

    def log_message(self, *args: Any) -> None:  # silence default logging
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock /vis/* frontend")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), VisHandler)
    print(f"Mock /vis/* frontend on http://127.0.0.1:{args.port}", flush=True)
    print("Endpoints: POST /vis/input, /vis/thoughts, /vis/outputs", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
