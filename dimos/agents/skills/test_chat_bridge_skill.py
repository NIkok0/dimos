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

from __future__ import annotations

import inspect
import time
from threading import Event, Thread
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from dimos.agents.skills.chat_bridge_skill import ChatBridgeSkill


def _make_skill() -> ChatBridgeSkill:
    """Build a ChatBridgeSkill without running Module.__init__ (avoids LCM)."""
    module = object.__new__(ChatBridgeSkill)
    module._idle_event = Event()
    module._reply_buffer: list[str] = []
    from threading import Lock

    module._buf_lock = Lock()
    module._call_lock = Lock()
    module._subscription_ready = Event()
    module._subscription_ready.set()
    module._saw_busy = False
    return module


@pytest.fixture
def skill() -> ChatBridgeSkill:
    return _make_skill()


def _make_publish_that_replies(messages: list[Any], then_idle: bool = True):
    """Return a _publish_human_input mock that injects messages then signals idle."""
    def _publish(self: ChatBridgeSkill, text: str) -> None:
        self._on_agent_idle(False)
        for msg in messages:
            self._on_agent_message(msg)
        if then_idle:
            self._on_agent_idle(True)

    return _publish


def test_chat_returns_collected_ai_messages(skill: ChatBridgeSkill) -> None:
    messages = [
        AIMessage(content="好的，我去抓红色方块"),
        AIMessage(content="已从蓝色桌子抓取红色方块，完成"),
    ]
    skill._publish_human_input = _make_publish_that_replies(messages).__get__(skill)

    result = skill.chat(text="去蓝色桌子抓红色方块", timeout=5.0)

    assert "好的" in result
    assert "完成" in result


def test_chat_ignores_non_ai_messages(skill: ChatBridgeSkill) -> None:
    messages = [
        HumanMessage(content="去蓝色桌子抓红色方块"),
        AIMessage(content="已完成"),
    ]
    skill._publish_human_input = _make_publish_that_replies(messages).__get__(skill)

    result = skill.chat(text="去蓝色桌子抓红色方块", timeout=5.0)

    assert result == "已完成"


def test_chat_timeout_returns_error(skill: ChatBridgeSkill) -> None:
    def _no_reply(self: ChatBridgeSkill, text: str) -> None:
        pass  # never signals idle

    skill._publish_human_input = _no_reply.__get__(skill)

    result = skill.chat(text="hello", timeout=0.1)

    assert result.startswith("Error: agent did not respond within")
    assert "0.1" in result


def test_chat_empty_text_returns_error(skill: ChatBridgeSkill) -> None:
    result = skill.chat(text="", timeout=5.0)
    assert result == "Error: text cannot be empty"


def test_chat_no_reply_returns_placeholder(skill: ChatBridgeSkill) -> None:
    # Signal busy then idle without any AIMessage.
    skill._publish_human_input = _make_publish_that_replies(messages=[], then_idle=True).__get__(skill)

    result = skill.chat(text="hello", timeout=5.0)

    assert result == "(no reply)"


def test_chat_serializes_concurrent_calls(skill: ChatBridgeSkill) -> None:
    """Two concurrent chat() calls must not interleave their replies."""
    # A single publish dispatch that replies based on the text it receives.
    # In production _publish_human_input is fixed; the test must not swap it
    # concurrently on the shared instance.
    def _publish(self: ChatBridgeSkill, text: str) -> None:
        self._on_agent_idle(False)
        if text == "A":
            self._on_agent_message(AIMessage(content="reply A"))
        else:
            self._on_agent_message(AIMessage(content="reply B"))
        self._on_agent_idle(True)

    skill._publish_human_input = _publish.__get__(skill)

    results: dict[str, str] = {}

    def run_chat(label: str) -> None:
        results[label] = skill.chat(text=label, timeout=10.0)

    t_a = Thread(target=run_chat, args=("A",))
    t_b = Thread(target=run_chat, args=("B",))

    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    # Each result must contain only its own reply, proving no interleave.
    assert "reply A" in results.get("A", "")
    assert "reply B" in results.get("B", "")
    assert "reply B" not in results.get("A", "")
    assert "reply A" not in results.get("B", "")


def test_on_agent_message_only_appends_non_empty_ai(skill: ChatBridgeSkill) -> None:
    skill._on_agent_message(AIMessage(content=""))
    skill._on_agent_message(AIMessage(content="hello"))
    skill._on_agent_message(HumanMessage(content="ignored"))

    assert skill._reply_buffer == ["hello"]


def test_on_agent_idle_sets_event(skill: ChatBridgeSkill) -> None:
    assert not skill._idle_event.is_set()
    skill._on_agent_idle(False)
    assert not skill._idle_event.is_set()
    skill._on_agent_idle(True)
    assert skill._idle_event.is_set()


def test_on_agent_idle_ignores_stale_idle_without_busy(skill: ChatBridgeSkill) -> None:
    skill._on_agent_idle(True)
    assert not skill._idle_event.is_set()


def test_chat_idle_before_ai_message_still_collects_reply(skill: ChatBridgeSkill) -> None:
    """agent_idle can arrive on LCM before the final AIMessage on /agent."""

    def _publish(self: ChatBridgeSkill, text: str) -> None:
        def deliver() -> None:
            self._on_agent_idle(False)
            self._on_agent_idle(True)
            time.sleep(0.15)
            self._on_agent_message(AIMessage(content="迟到但应收到"))

        Thread(target=deliver, daemon=True).start()

    skill._publish_human_input = _publish.__get__(skill)

    result = skill.chat(text="hello", timeout=5.0)

    assert "迟到但应收到" in result


def test_ai_message_text_extracts_list_content(skill: ChatBridgeSkill) -> None:
    text = ChatBridgeSkill._ai_message_text(
        AIMessage(content=[{"type": "text", "text": "你好，我是 Dax"}])
    )
    assert text == "你好，我是 Dax"


def test_chat_skill_docstring_is_complete() -> None:
    doc = inspect.getdoc(ChatBridgeSkill.chat) or ""
    assert "Send user text" in doc
    assert "Args:" in doc
    assert "text:" in doc
    assert "timeout:" in doc
    assert "Returns" in doc
