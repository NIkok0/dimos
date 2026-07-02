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

"""Synchronous chat bridge skill for external voice/frontend consumers.

`chat` sends user text into the agent loop (via the same LCM ``/human_input``
channel that ``agent_send`` uses) and blocks until the agent finishes
processing, then returns the concatenated text of every ``AIMessage`` the
agent produced. This gives downstream MCP consumers (a voice dialogue system,
a demo frontend) a single synchronous ``tools/call`` entrypoint that returns
the agent's full reply for TTS or display.

The module subscribes to the ``agent`` (``Out[BaseMessage]``) and
``agent_idle`` (``Out[bool]``) streams that ``McpClient`` publishes; these
auto-connect via ``autoconnect`` by ``(name, type)`` matching.
"""

from __future__ import annotations

import time
from threading import Event, Lock
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages.base import BaseMessage
from reactivex.disposable import Disposable

from dimos.agents.annotation import skill
from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.core.stream import In
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

_DEFAULT_TIMEOUT_S = 120.0
# After agent_idle=True, wait briefly for straggling AIMessages on /agent (separate LCM topic).
_IDLE_GRACE_S = 2.0


class ChatBridgeSkill(Module):
    """Bridges external synchronous callers to the async agent loop.

    Streams:
        agent: In[BaseMessage]  — auto-connected to McpClient.agent.
        agent_idle: In[bool]    — auto-connected to McpClient.agent_idle.
    """

    agent: In[BaseMessage]
    agent_idle: In[bool]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._idle_event = Event()
        self._reply_buffer: list[str] = []
        self._buf_lock = Lock()
        self._call_lock = Lock()
        self._subscription_ready = Event()
        self._saw_busy = False

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

    @rpc
    def start(self) -> None:
        super().start()
        self.register_disposable(
            Disposable(self.agent.subscribe(self._on_agent_message))
        )
        self.register_disposable(
            Disposable(self.agent_idle.subscribe(self._on_agent_idle))
        )
        self._subscription_ready.set()
        logger.info("ChatBridgeSkill subscribed to agent + agent_idle streams")

    @rpc
    def stop(self) -> None:
        super().stop()

    def _on_agent_idle(self, idle: bool) -> None:
        if idle:
            with self._buf_lock:
                if self._saw_busy:
                    self._idle_event.set()
            return
        with self._buf_lock:
            self._saw_busy = True

    def _on_agent_message(self, message: BaseMessage) -> None:
        if not isinstance(message, AIMessage):
            return
        text = self._ai_message_text(message)
        if not text:
            return
        with self._buf_lock:
            self._reply_buffer.append(text)

    def _publish_human_input(self, text: str) -> None:
        from dimos.core.transport import pLCMTransport

        transport: pLCMTransport[str] = pLCMTransport("/human_input")
        transport.start()
        try:
            transport.publish(text)
        finally:
            transport.stop()

    @skill
    def chat(self, text: str, timeout: float = _DEFAULT_TIMEOUT_S) -> str:
        """Send user text to the agent and wait for its full reply.

        Use this for voice dialogue or frontend integration: send transcribed
        speech (or a typed instruction), receive the agent's final text reply
        to pass to TTS or display. Blocks until the agent finishes processing,
        including any robot task execution triggered by execute_nl_task.

        Concurrent calls are serialized so replies from different turns do not
        interleave.

        Args:
            text: User's transcribed speech or typed instruction, forwarded
                verbatim into the agent loop.
            timeout: Max seconds to wait for the agent to finish. Default 120.

        Returns:
            The concatenated text of all AIMessage replies the agent produced
            for this turn, or an error string if the agent did not finish in
            time.
        """
        if not text:
            return "Error: text cannot be empty"

        with self._call_lock:
            self._idle_event.clear()
            with self._buf_lock:
                self._reply_buffer.clear()
                self._saw_busy = False

            logger.info("ChatBridgeSkill chat sending text", text_preview=text[:120])
            self._publish_human_input(text)

            finished = self._idle_event.wait(timeout=timeout)
            if finished:
                grace_deadline = time.monotonic() + _IDLE_GRACE_S
                while time.monotonic() < grace_deadline:
                    with self._buf_lock:
                        if self._reply_buffer:
                            break
                    time.sleep(0.05)

            if not finished:
                logger.warning(
                    "ChatBridgeSkill chat timed out",
                    timeout=timeout,
                    text_preview=text[:120],
                )
                return f"Error: agent did not respond within {timeout}s"

            with self._buf_lock:
                reply = "\n".join(self._reply_buffer).strip()
            if not reply:
                reply = "(no reply)"
            logger.info("ChatBridgeSkill chat returning reply", reply_preview=reply[:120])
            return reply


chat_bridge_skill = ChatBridgeSkill.blueprint

__all__ = ["ChatBridgeSkill", "chat_bridge_skill"]
