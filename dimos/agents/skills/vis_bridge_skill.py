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

"""Bridge from DimOS internal agent streams to a demo frontend's ``/vis/*`` REST API.

The frontend exposes a stop-and-wait REST protocol:

- ``POST /vis/input``   — start a session, returns ``session_id``
- ``POST /vis/thoughts`` — incremental reasoning step (``seq`` strictly increasing, ACK before next)
- ``POST /vis/outputs``  — final result, closes the session

This module subscribes to the four DimOS LCM streams that ``McpClient`` publishes
(``human_input``, ``agent_reasoning``, ``agent``, ``agent_idle``) and translates one
agent turn into an ordered sequence of POSTs to the frontend. A dedicated worker
thread consumes a queue of events so that LCM callbacks never block and ``seq``
ordering is guaranteed. The frontend is display-only; user input still enters
DimOS through existing channels (MCP ``chat`` / ``agent_send``, future voice system)
and is forwarded transparently.

Configure via ``GlobalConfig.vis_bridge_url`` (env ``VIS_BRIDGE_URL``,
CLI ``--vis-bridge-url``). When empty, the bridge is a no-op so existing
deployments are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from threading import Event, Thread
from typing import Any

import requests
from langchain_core.messages import AIMessage
from langchain_core.messages.base import BaseMessage
from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.global_config import global_config
from dimos.core.module import Module
from dimos.core.stream import In
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

# Stop sentinel for the worker queue.
_STOP: Any = object()


@dataclass
class _VisEvent:
    """One queued stream event for the bridge worker."""

    kind: str  # "user_input" | "reasoning" | "agent_message" | "idle"
    payload: Any


class VisBridgeSkill(Module):
    """Push DimOS agent turns to a demo frontend's ``/vis/*`` stop-and-wait API.

    Streams:
        human_input: In[str]        — auto-connected to McpClient.human_input.
        agent_reasoning: In[dict]   — auto-connected to McpClient.agent_reasoning.
        agent: In[BaseMessage]      — auto-connected to McpClient.agent.
        agent_idle: In[bool]        — auto-connected to McpClient.agent_idle.
    """

    human_input: In[str]
    agent_reasoning: In[dict]
    agent: In[BaseMessage]
    agent_idle: In[bool]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._queue: Queue[Any] = Queue()
        self._worker_stop = Event()
        self._thread: Thread | None = None
        # Session state — only touched inside the worker thread.
        self._session_id: str | None = None
        self._seq: int = 0
        self._ai_content: str = ""
        self._ai_reasoning: str = ""

    @rpc
    def start(self) -> None:
        super().start()
        self.register_disposable(Disposable(self.human_input.subscribe(self._on_human_input)))
        self.register_disposable(Disposable(self.agent_reasoning.subscribe(self._on_reasoning)))
        self.register_disposable(Disposable(self.agent.subscribe(self._on_agent_message)))
        self.register_disposable(Disposable(self.agent_idle.subscribe(self._on_idle)))
        if global_config.vis_bridge_url:
            self._thread = Thread(target=self._run, name="VisBridgeWorker", daemon=True)
            self._thread.start()
            logger.info(
                "VisBridgeSkill started",
                vis_bridge_url=global_config.vis_bridge_url,
            )
        else:
            logger.info("VisBridgeSkill idle (vis_bridge_url not configured)")

    @rpc
    def stop(self) -> None:
        self._worker_stop.set()
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        super().stop()

    # --- LCM callbacks: enqueue only, never block -------------------------

    def _on_human_input(self, text: str) -> None:
        if global_config.vis_bridge_url:
            self._queue.put(_VisEvent("user_input", text))

    def _on_reasoning(self, data: dict[str, Any]) -> None:
        if global_config.vis_bridge_url:
            self._queue.put(_VisEvent("reasoning", data))

    def _on_agent_message(self, msg: BaseMessage) -> None:
        if global_config.vis_bridge_url and isinstance(msg, AIMessage):
            self._queue.put(_VisEvent("agent_message", msg))

    def _on_idle(self, idle: bool) -> None:
        if global_config.vis_bridge_url and idle:
            self._queue.put(_VisEvent("idle", True))

    # --- Worker thread: ordered state machine -----------------------------

    def _run(self) -> None:
        while not self._worker_stop.is_set():
            ev = self._queue.get()
            if ev is _STOP:
                return
            if isinstance(ev, _VisEvent):
                try:
                    self._handle(ev)
                except Exception:
                    logger.exception("VisBridgeSkill event handling failed", kind=ev.kind)

    def _handle(self, ev: _VisEvent) -> None:
        if ev.kind == "user_input":
            self._handle_user_input(str(ev.payload))
        elif ev.kind == "reasoning":
            self._handle_reasoning(ev.payload)
        elif ev.kind == "agent_message":
            self._handle_agent_message(ev.payload)
        elif ev.kind == "idle":
            self._handle_idle()

    def _handle_user_input(self, text: str) -> None:
        if self._session_id is not None:
            logger.warning(
                "VisBridge new user_input while session active; abandoning old session",
                old_session_id=self._session_id,
            )
            self._reset_session()
        session_id = self._post_vis_input(text)
        if session_id is None:
            logger.error("VisBridge /vis/input failed; skipping turn", text_preview=text[:120])
            self._reset_session()
            return
        self._session_id = session_id
        self._seq = 0
        self._ai_content = ""
        self._ai_reasoning = ""
        logger.info("VisBridge session started", session_id=session_id, text_preview=text[:120])

    def _handle_reasoning(self, data: dict[str, Any]) -> None:
        if self._session_id is None:
            return
        content = str(data.get("content", ""))
        if not content:
            return
        self._seq += 1
        ok = self._post_vis_thoughts(self._session_id, self._seq, content)
        if not ok:
            logger.error(
                "VisBridge /vis/thoughts failed after retries; aborting session",
                session_id=self._session_id,
                seq=self._seq,
            )
            self._reset_session()

    def _handle_agent_message(self, msg: AIMessage) -> None:
        if self._session_id is None:
            return
        if not isinstance(msg, AIMessage):
            return
        text = self._ai_message_text(msg)
        if text:
            self._ai_content = text
        additional_kwargs = getattr(msg, "additional_kwargs", None) or {}
        reasoning = additional_kwargs.get("reasoning_content")
        if reasoning:
            self._ai_reasoning = str(reasoning)

    def _handle_idle(self) -> None:
        if self._session_id is None:
            return
        result: dict[str, Any] = {"content": self._ai_content}
        if self._ai_reasoning:
            result["reasoning_content"] = self._ai_reasoning
        ok = self._post_vis_outputs(self._session_id, result)
        if ok:
            logger.info(
                "VisBridge session closed",
                session_id=self._session_id,
                reply_preview=self._ai_content[:120],
            )
        else:
            logger.error("VisBridge /vis/outputs failed", session_id=self._session_id)
        self._reset_session()

    def _reset_session(self) -> None:
        self._session_id = None
        self._seq = 0
        self._ai_content = ""
        self._ai_reasoning = ""

    # --- HTTP calls (mockable in tests) -----------------------------------

    @staticmethod
    def _ai_message_text(message: AIMessage) -> str:
        content = message.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(part for part in parts if part).strip()
        if content:
            return str(content).strip()
        return ""

    def _post_vis_input(self, text: str) -> str | None:
        url = self._url("/vis/input")
        data = {"text": text}
        resp = self._post_with_retry(url, data)
        if resp is None:
            return None
        session_id = resp.get("session_id")
        return str(session_id) if session_id else None

    def _post_vis_thoughts(self, session_id: str, seq: int, content: str) -> bool:
        url = self._url("/vis/thoughts")
        data = {"session_id": session_id, "seq": seq, "content": content}
        resp = self._post_with_retry(url, data)
        return resp is not None

    def _post_vis_outputs(self, session_id: str, result: dict[str, Any]) -> bool:
        url = self._url("/vis/outputs")
        data = {"session_id": session_id, "result": result}
        resp = self._post_with_retry(url, data)
        return resp is not None

    def _url(self, path: str) -> str:
        base = global_config.vis_bridge_url or ""
        return f"{base.rstrip('/')}{path}"

    def _post_with_retry(self, url: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """POST with stop-and-wait + idempotent retry on timeout/5xx.

        Returns parsed JSON on 2xx, None on terminal failure. 422/409 are
        treated as terminal (caller aborts the session) and also return None.
        """
        max_retries = max(1, int(global_config.vis_bridge_max_retries))
        timeout_s = float(global_config.vis_bridge_timeout_s)
        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(url, json=data, timeout=timeout_s)
            except requests.RequestException as exc:
                last_error = str(exc)
                logger.warning(
                    "VisBridge POST exception, retrying",
                    url=url,
                    attempt=attempt,
                    error=last_error,
                )
                continue
            if 200 <= resp.status_code < 300:
                try:
                    return resp.json()
                except ValueError:
                    return {}
            if resp.status_code in (409, 422):
                logger.error(
                    "VisBridge POST terminal rejection",
                    url=url,
                    status=resp.status_code,
                    body=resp.text[:200],
                )
                return None
            if 500 <= resp.status_code < 600:
                last_error = f"HTTP {resp.status_code}"
                logger.warning(
                    "VisBridge POST 5xx, retrying",
                    url=url,
                    attempt=attempt,
                    status=resp.status_code,
                )
                continue
            logger.error(
                "VisBridge POST non-retryable status",
                url=url,
                status=resp.status_code,
                body=resp.text[:200],
            )
            return None
        logger.error("VisBridge POST exhausted retries", url=url, error=last_error)
        return None


vis_bridge_skill = VisBridgeSkill.blueprint

__all__ = ["VisBridgeSkill", "vis_bridge_skill"]
