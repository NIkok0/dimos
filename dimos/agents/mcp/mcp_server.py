# Copyright 2025-2026 Dimensional Inc.
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
from collections.abc import AsyncGenerator, Callable
import concurrent.futures
import json
import os
import time
from typing import TYPE_CHECKING, Any
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
import uvicorn

from dimos.agents.annotation import skill
from dimos.agents.capabilities import CapabilityRegistry
from dimos.agents.mcp import tool_stream
from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.core.rpc_client import RpcCall, RPCClient
from dimos.utils.logging_config import setup_logger

if TYPE_CHECKING:
    from dimos.core.module import SkillInfo

logger = setup_logger()


_SSE_KEEPALIVE_INTERVAL = 20.0  # seconds

# How long a `tools/call` waits for a capability held by a short, self-completing
# (instant) skill before refusing. Well under the MCP client's 120s HTTP timeout.
# Background holders run until stopped, so they are never waited on (see
# `_can_wait` in `_handle_tools_call`).
DEFAULT_CAP_ACQUIRE_TIMEOUT = 30.0  # seconds

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)
app.state.skills = []
app.state.skills_by_name = {}
app.state.rpc_calls = {}
app.state.sse_queues = []
app.state.agent_event_queues: list[asyncio.Queue[dict[str, Any] | None]] = []
app.state.event_loop = None
app.state.cap_registry = CapabilityRegistry()
app.state.cap_acquire_timeout = DEFAULT_CAP_ACQUIRE_TIMEOUT
app.state.tool_allowlist = frozenset()


def _jsonrpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_result_text(req_id: Any, text: str) -> dict[str, Any]:
    return _jsonrpc_result(req_id, {"content": [{"type": "text", "text": text}]})


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _parse_tool_allowlist(raw: str) -> frozenset[str]:
    """Parse comma-separated MCP tool names; empty input keeps all tools visible."""
    return frozenset(name.strip() for name in raw.split(",") if name.strip())


def _filter_allowed_skills(skills: list[SkillInfo]) -> list[SkillInfo]:
    """Return only MCP skills allowed for the current server exposure surface."""
    allowlist: frozenset[str] = app.state.tool_allowlist
    if not allowlist:
        return skills
    return [skill for skill in skills if skill.func_name in allowlist]


def _handle_initialize(req_id: Any) -> dict[str, Any]:
    return _jsonrpc_result(
        req_id,
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}, "logging": {}},
            "serverInfo": {"name": "dimensional", "version": "1.0.0"},
        },
    )


def _handle_tools_list(req_id: Any, skills: list[SkillInfo]) -> dict[str, Any]:
    tools = []

    for s in _filter_allowed_skills(skills):
        schema = json.loads(s.args_schema)
        description = schema.pop("description", None)
        schema.pop("title", None)
        tool: dict[str, Any] = {"name": s.func_name, "inputSchema": schema}
        if description:
            tool["description"] = description
        if s.uses or s.lifecycle != "instant":
            tool["_meta"] = {
                "dimos/uses": list(s.uses),
                "dimos/lifecycle": s.lifecycle,
            }
        tools.append(tool)

    return _jsonrpc_result(req_id, {"tools": tools})


async def _handle_tools_call(
    req_id: Any, params: dict[str, Any], rpc_calls: dict[str, Any]
) -> dict[str, Any]:
    name = params.get("name", "")
    args: dict[str, Any] = params.get("arguments") or {}
    meta = params.get("_meta") or {}
    progress_token = meta.get("progressToken")

    allowlist: frozenset[str] = app.state.tool_allowlist
    if allowlist and name not in allowlist:
        logger.warning("MCP tool blocked by allowlist", tool=name)
        return _jsonrpc_result_text(req_id, f"Tool not found: {name}")

    rpc_call = rpc_calls.get(name)
    if rpc_call is None:
        logger.warning("MCP tool not found", tool=name)
        return _jsonrpc_result_text(req_id, f"Tool not found: {name}")

    skill_info = app.state.skills_by_name.get(name)
    uses: list[str] = list(skill_info.uses) if skill_info is not None else []
    lifecycle = skill_info.lifecycle if skill_info is not None else "instant"
    cap_registry: CapabilityRegistry = app.state.cap_registry

    # A per-invocation token scopes the capability hold, so a stale invocation's
    # teardown can't release a hold that a newer same-tool invocation took over.
    acquire_token = uuid.uuid4().hex
    if uses:

        def _can_wait(holder: str) -> bool:
            # Wait only on instant holders; they release when they return.
            # Background holders run until explicitly stopped, so refuse instead
            # of blocking until the timeout.
            info = app.state.skills_by_name.get(holder)
            return (info.lifecycle if info is not None else "instant") != "background"

        # Run the (possibly blocking) acquire off the event loop so waiting for a
        # busy capability doesn't stall the server.
        conflict = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: cap_registry.acquire(
                uses,
                tool_name=name,
                token=acquire_token,
                timeout=app.state.cap_acquire_timeout,
                can_wait=_can_wait,
            ),
        )
        if conflict is not None:
            cap, holder = conflict
            logger.info(
                "MCP tool refused (capability busy)",
                tool=name,
                cap=cap,
                holder=holder,
                snapshot=cap_registry.snapshot(),
            )
            # A background holder has a stop tool to call; an instant holder is
            # waited on above, so reaching here means it outlasted the timeout.
            holder_info = app.state.skills_by_name.get(holder)
            holder_lifecycle = holder_info.lifecycle if holder_info is not None else "instant"
            if holder_lifecycle == "background":
                advice = "Call the appropriate stop tool first, then retry."
            else:
                advice = "It is taking longer than expected; wait a moment and then retry."
            return _jsonrpc_result_text(
                req_id,
                f"Cannot start '{name}': capability '{cap}' is held by '{holder}'. {advice}",
            )

    logger.info("MCP tool call", tool=name, args=args, progress_token=progress_token)
    t0 = time.monotonic()

    # _mcp_context is a reserved kwarg consumed by the `@skill` wrapper; it never
    # reaches the user-visible skill signature. The acquire token rides along so
    # a background skill's ToolStream can stamp it on its stop frame for release.
    call_kwargs = dict(args)
    mcp_context: dict[str, Any] = {}
    if progress_token is not None:
        mcp_context["progress_token"] = progress_token
    if uses:
        mcp_context["acquire_token"] = acquire_token
    if mcp_context:
        call_kwargs["_mcp_context"] = mcp_context

    # Track whether we still hold the caps so we can release on failure even
    # for background skills. On success the background skill keeps them until
    # its tool-stream closes.
    caps_held = bool(uses)
    try:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: rpc_call(**call_kwargs)
            )
        except Exception as e:
            logger.exception("MCP tool error", tool=name, duration=f"{time.monotonic() - t0:.3f}s")
            return _jsonrpc_result_text(req_id, f"Error running tool '{name}': {e}")

        if lifecycle == "background":
            # Hand ownership of the caps off to the tool-stream lifecycle.
            caps_held = False
    finally:
        if caps_held:
            cap_registry.release_by_token(acquire_token)

    duration = f"{time.monotonic() - t0:.3f}s"
    response = str(result)[:200]

    if hasattr(result, "agent_encode"):
        logger.info("MCP tool done", tool=name, duration=duration, response=response)
        return _jsonrpc_result(req_id, {"content": result.agent_encode()})

    logger.info("MCP tool done", tool=name, duration=duration, response=response)
    return _jsonrpc_result_text(req_id, str(result))


async def handle_request(
    request: dict[str, Any],
    skills: list[SkillInfo],
    rpc_calls: dict[str, Any],
) -> dict[str, Any] | None:
    """Handle a single MCP JSON-RPC request.

    Returns None for JSON-RPC notifications (no ``id``), which must not
    receive a response.
    """
    method = request.get("method", "")
    params = request.get("params", {}) or {}
    req_id = request.get("id")

    # JSON-RPC notifications have no "id" -- the server must not reply.
    if "id" not in request:
        return None

    if method == "initialize":
        return _handle_initialize(req_id)
    if method == "tools/list":
        return _handle_tools_list(req_id, skills)
    if method == "tools/call":
        return await _handle_tools_call(req_id, params, rpc_calls)
    return _jsonrpc_error(req_id, -32601, f"Unknown: {method}")


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> Response:
    raw = await request.body()
    try:
        body = json.loads(raw)
    except Exception:
        logger.exception("POST /mcp JSON parse failed")
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )

    result = await handle_request(body, request.app.state.skills, request.app.state.rpc_calls)

    if result is None:
        return Response(status_code=204)
    return JSONResponse(result)


def _sse_frame(data: dict[str, Any]) -> str:
    """Format a JSON-RPC message as an SSE ``event: message`` frame."""
    return f"event: message\ndata: {json.dumps(data)}\n\n"


def _fan_out_to_sse_queues(msg: dict[str, Any]) -> None:
    """LCM subscriber callback: forward a tool-stream frame to every active SSE client.

    Also releases capabilities held by a background skill when its tool-stream
    closes (signaled by a ``dimos/tool_stopped`` frame).
    """
    if msg.get("method") == tool_stream.TOOL_STREAM_STOPPED_METHOD:
        params = msg.get("params") or {}
        token = params.get("token")
        if token:
            released = app.state.cap_registry.release_by_token(token)
            if released:
                logger.info(
                    "Capabilities released on tool-stream stop",
                    holder=params.get("tool_name"),
                    token=token,
                    released=released,
                )
    loop = app.state.event_loop
    if loop is None:
        return
    for queue in list(app.state.sse_queues):
        try:
            asyncio.run_coroutine_threadsafe(queue.put(msg), loop)
        except RuntimeError:
            pass


@app.get("/mcp")
async def mcp_sse_endpoint() -> StreamingResponse:
    """Persistent server-to-client SSE channel for MCP notifications.

    This is the Streamable-HTTP transport's out-of-band channel for
    server-initiated messages.  Every tool-stream update is fanned out here,
    so the subscription is live for the full client session and independent
    of any particular ``tools/call`` request.
    """
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    # Remember the loop so the LCM subscriber (running on an LCM thread)
    # can schedule queue.put via run_coroutine_threadsafe.
    app.state.event_loop = asyncio.get_running_loop()
    app.state.sse_queues.append(queue)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Initial comment flushes the response headers and unblocks
            # any synchronous client that's waiting on iter_lines().
            yield ": connected\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_INTERVAL)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if msg is None:
                    return
                yield _sse_frame(msg)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                app.state.sse_queues.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _fan_out_agent_event(event: dict[str, Any]) -> None:
    """Forward an agent-stream event to every active /agent_events SSE client."""
    loop = app.state.event_loop
    if loop is None:
        return
    for queue in list(app.state.agent_event_queues):
        try:
            asyncio.run_coroutine_threadsafe(queue.put(event), loop)
        except RuntimeError:
            pass


def _agent_message_sse_data(msg: Any) -> dict[str, Any]:
    """Build SSE payload for one LangChain agent message."""
    additional_kwargs = getattr(msg, "additional_kwargs", None) or {}
    reasoning = additional_kwargs.get("reasoning_content")
    data: dict[str, Any] = {
        "type": getattr(msg, "type", "unknown"),
        "content": str(getattr(msg, "content", "")),
        "tool_calls": getattr(msg, "tool_calls", None) or [],
        "tool_call_id": getattr(msg, "tool_call_id", None),
        "timestamp": time.time(),
    }
    if reasoning:
        data["reasoning_content"] = str(reasoning)
    return data


def _agent_event_sse_frame(event: dict[str, Any]) -> str:
    """Format a typed SSE frame: ``event: <name>\\ndata: <json>\\n\\n``."""
    event_name = event.get("event", "message")
    data = json.dumps(event.get("data", {}), default=str)
    return f"event: {event_name}\ndata: {data}\n\n"


@app.get("/agent_events")
async def agent_events_endpoint() -> StreamingResponse:
    """SSE stream of agent reasoning + messages + user input for frontend demos.

    Emits three typed SSE events:
    - ``user_input``: ``{"text": str, "timestamp": float}`` — what the user said.
    - ``reasoning``: ``{step_type, node, content, ...}`` — LangGraph reasoning steps.
    - ``agent_message``: ``{type, content, reasoning_content?, tool_calls, tool_call_id, timestamp}`` —
      every agent message (Human/AI/Tool). ``reasoning_content`` is the model's chain-of-thought
      text (e.g. DeepSeek ``additional_kwargs``), present on AI messages when available.

    A browser frontend uses ``new EventSource("/agent_events")`` and
    ``addEventListener`` per event type.
    """
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    app.state.event_loop = asyncio.get_running_loop()
    app.state.agent_event_queues.append(queue)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield ": connected\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_INTERVAL)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if msg is None:
                    return
                yield _agent_event_sse_frame(msg)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                app.state.agent_event_queues.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


class McpServer(Module):
    _uvicorn_server: uvicorn.Server | None = None
    _serve_future: concurrent.futures.Future[None] | None = None
    _tool_stream_cleanup: Callable[[], None] | None = None
    _agent_event_cleanup: Callable[[], None] | None = None

    @rpc
    def start(self) -> None:
        super().start()
        self._start_server()
        self._tool_stream_cleanup = tool_stream.subscribe(_fan_out_to_sse_queues)
        self._agent_event_cleanup = self._start_agent_event_subscriptions()

    @rpc
    def stop(self) -> None:
        if self._tool_stream_cleanup is not None:
            self._tool_stream_cleanup()
            self._tool_stream_cleanup = None

        if self._agent_event_cleanup is not None:
            self._agent_event_cleanup()
            self._agent_event_cleanup = None

        for queue in list(app.state.sse_queues):
            try:
                queue.put_nowait(None)
            except Exception:
                pass
        app.state.sse_queues.clear()

        for queue in list(app.state.agent_event_queues):
            try:
                queue.put_nowait(None)
            except Exception:
                pass
        app.state.agent_event_queues.clear()

        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
            loop = self._loop
            if loop is not None and self._serve_future is not None:
                self._serve_future.result(timeout=5.0)
            self._uvicorn_server = None
            self._serve_future = None
        super().stop()

    @rpc
    def on_system_modules(self, modules: list[RPCClient]) -> None:
        # TODO: this is a bit hacky, also not thread-safe
        assert self.rpc is not None
        app.state.tool_allowlist = _parse_tool_allowlist(self.config.g.mcp_tool_allowlist)
        app.state.skills = [
            skill_info for module in modules for skill_info in (module.get_skills() or [])
        ]
        allowed_skills = _filter_allowed_skills(app.state.skills)
        app.state.skills_by_name = {s.func_name: s for s in allowed_skills}
        app.state.rpc_calls = {
            skill_info.func_name: RpcCall(
                None, self.rpc, skill_info.func_name, skill_info.class_name, []
            )
            for skill_info in allowed_skills
        }

    @skill
    def server_status(self) -> str:
        """Get MCP server status: main process PID, deployed modules, and skill count."""
        from dimos.core.run_registry import get_most_recent

        skills: list[SkillInfo] = app.state.skills
        modules = list(dict.fromkeys(s.class_name for s in skills))
        entry = get_most_recent()
        pid = entry.pid if entry else os.getpid()
        return json.dumps(
            {
                "pid": pid,
                "modules": modules,
                "skills": [s.func_name for s in skills],
            }
        )

    @skill
    def list_modules(self) -> str:
        """List deployed modules and their skills."""
        skills: list[SkillInfo] = app.state.skills
        modules: dict[str, list[str]] = {}
        for s in skills:
            modules.setdefault(s.class_name, []).append(s.func_name)
        return json.dumps({"modules": modules})

    @skill
    def agent_send(self, message: str) -> str:
        """Send a message to the running DimOS agent via LCM."""
        if not message:
            raise ValueError("Message cannot be empty")

        from dimos.core.transport import pLCMTransport

        transport: pLCMTransport[str] = pLCMTransport("/human_input")
        try:
            transport.start()
            transport.publish(message)
            return f"Message sent to agent: {message[:100]}"
        finally:
            transport.stop()

    def _start_agent_event_subscriptions(self) -> Callable[[], None]:
        """Subscribe to /agent, /agent_reasoning, /human_input LCM streams.

        Uses a single shared PickleLCM instance so we do not spawn multiple LCM
        handler threads in the same worker (that race and can exceed the 5s start
        timeout). Each message is formatted as a typed SSE event dict and fanned
        out to every active /agent_events SSE client.
        """
        from dimos.protocol.pubsub.impl.lcmpubsub import PickleLCM, Topic

        lcm = PickleLCM()

        def on_human_input(text: str, _topic: Topic) -> None:
            _fan_out_agent_event(
                {"event": "user_input", "data": {"text": text, "timestamp": time.time()}}
            )

        def on_reasoning(data: dict[str, Any], _topic: Topic) -> None:
            _fan_out_agent_event({"event": "reasoning", "data": data})

        def on_agent_message(msg: Any, _topic: Topic) -> None:
            _fan_out_agent_event(
                {"event": "agent_message", "data": _agent_message_sse_data(msg)}
            )

        unsub_human = lcm.subscribe(Topic("/human_input"), on_human_input)
        unsub_reasoning = lcm.subscribe(Topic("/agent_reasoning"), on_reasoning)
        unsub_agent = lcm.subscribe(Topic("/agent"), on_agent_message)
        lcm.start()
        logger.info("agent_events SSE subscriptions started")

        def cleanup() -> None:
            try:
                unsub_human()
                unsub_reasoning()
                unsub_agent()
            except Exception:
                logger.exception("Failed to unsubscribe agent_events LCM topics")
            try:
                lcm.stop()
            except Exception:
                logger.exception("Failed to stop agent_events LCM bus")
            logger.info("agent_events SSE subscriptions stopped")

        return cleanup

    def _start_server(self, port: int | None = None) -> None:
        from dimos.core.global_config import global_config

        _port = port if port is not None else global_config.mcp_port
        _host = global_config.listen_host
        config = uvicorn.Config(app, host=_host, port=_port, log_level="warning", access_log=False)
        server = uvicorn.Server(config)
        self._uvicorn_server = server
        loop = self._loop
        assert loop is not None
        self._serve_future = asyncio.run_coroutine_threadsafe(server.serve(), loop)
