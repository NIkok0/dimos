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

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from dimos.agents.skills.vis_bridge_skill import VisBridgeSkill
from dimos.core.global_config import global_config


def _make_skill() -> VisBridgeSkill:
    """Build a VisBridgeSkill without running Module.__init__ (avoids LCM)."""
    module = object.__new__(VisBridgeSkill)
    from queue import Queue
    from threading import Event

    module._queue = Queue()
    module._worker_stop = Event()
    module._thread = None
    module._session_id = None
    module._seq = 0
    module._ai_content = ""
    module._ai_reasoning = ""
    return module


@pytest.fixture
def skill() -> VisBridgeSkill:
    return _make_skill()


def _ok_response(body: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = body
    resp.text = ""
    return resp


class _PostRecorder:
    """Tracks POST calls and returns scripted responses."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, json: dict[str, Any], timeout: float | None = None) -> Any:
        self.calls.append((url, json))
        if not self._responses:
            return _ok_response({})
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.fixture(autouse=True)
def _configure_vis_bridge_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(global_config, "vis_bridge_url", "http://fe.test:8080")
    monkeypatch.setattr(global_config, "vis_bridge_timeout_s", 1.0)
    monkeypatch.setattr(global_config, "vis_bridge_max_retries", 3)


def test_full_turn_posts_input_thoughts_outputs_in_order(skill: VisBridgeSkill) -> None:
    responses = [
        _ok_response({"session_id": "sess_1"}),
        _ok_response({"session_id": "sess_1", "received_seq": 1}),
        _ok_response({"session_id": "sess_1", "received_seq": 2}),
        _ok_response({"session_id": "sess_1", "received_seq": 3}),
        _ok_response({"session_id": "sess_1"}),
    ]
    recorder = _PostRecorder(responses)
    with patch("dimos.agents.skills.vis_bridge_skill.requests.post", side_effect=recorder):
        skill._handle_user_input("你好")
        skill._handle_reasoning({"content": "plan: starting"})
        skill._handle_reasoning({"content": "thought: 用户在打招呼"})
        skill._handle_reasoning({"content": "action: respond"})
        skill._handle_agent_message(AIMessage(content="你好，我是 Dax"))
        skill._handle_idle()

    urls = [c[0] for c in recorder.calls]
    assert urls == [
        "http://fe.test:8080/vis/input",
        "http://fe.test:8080/vis/thoughts",
        "http://fe.test:8080/vis/thoughts",
        "http://fe.test:8080/vis/thoughts",
        "http://fe.test:8080/vis/outputs",
    ]
    assert recorder.calls[0][1] == {"text": "你好"}
    assert recorder.calls[1][1] == {"session_id": "sess_1", "seq": 1, "content": "plan: starting"}
    assert recorder.calls[2][1]["seq"] == 2
    assert recorder.calls[3][1]["seq"] == 3
    assert recorder.calls[4][1]["result"]["content"] == "你好，我是 Dax"


def test_vis_input_failure_skips_thoughts_and_outputs(skill: VisBridgeSkill) -> None:
    recorder = _PostRecorder([])
    with patch(
        "dimos.agents.skills.vis_bridge_skill.requests.post",
        side_effect=_PostRecorder([_ok_response({})]),
    ) as _mock_post:
        # No session_id in response -> _post_vis_input returns None
        pass
    # Use a dedicated mock that returns empty body (no session_id)
    mock_post = MagicMock(return_value=_ok_response({}))
    with patch("dimos.agents.skills.vis_bridge_skill.requests.post", mock_post):
        skill._handle_user_input("你好")
        skill._handle_reasoning({"content": "thought"})
        skill._handle_agent_message(AIMessage(content="reply"))
        skill._handle_idle()

    # Only /vis/input attempted; session not established so no thoughts/outputs.
    assert mock_post.call_count == 1
    assert mock_post.call_args.args[0].endswith("/vis/input")


def test_thoughts_422_aborts_session_and_skips_outputs(skill: VisBridgeSkill) -> None:
    bad = MagicMock()
    bad.status_code = 422
    bad.text = '{"code":42200,"message":"seq is not continuous"}'
    responses = [_ok_response({"session_id": "sess_2"}), bad]
    recorder = _PostRecorder(responses)
    with patch("dimos.agents.skills.vis_bridge_skill.requests.post", side_effect=recorder):
        skill._handle_user_input("去抓方块")
        skill._handle_reasoning({"content": "thought 1"})
        # After 422 the session must be aborted; subsequent events are no-ops.
        skill._handle_reasoning({"content": "thought 2"})
        skill._handle_agent_message(AIMessage(content="done"))
        skill._handle_idle()

    # /vis/input + one /vis/thoughts only; outputs never sent.
    assert len(recorder.calls) == 2
    assert recorder.calls[1][0].endswith("/vis/thoughts")


def test_empty_vis_bridge_url_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(global_config, "vis_bridge_url", None)
    skill = _make_skill()
    mock_post = MagicMock()
    with patch("dimos.agents.skills.vis_bridge_skill.requests.post", mock_post):
        # LCM callbacks early-return when url is None.
        skill._on_human_input("你好")
        skill._on_reasoning({"content": "x"})
        skill._on_agent_message(AIMessage(content="r"))
        skill._on_idle(True)
    mock_post.assert_not_called()


def test_idempotent_retry_on_timeout_then_success(skill: VisBridgeSkill) -> None:
    import requests as _requests

    recorder = _PostRecorder(
        [
            _ok_response({"session_id": "sess_3"}),
            _requests.ConnectionError("timeout"),
            _ok_response({"session_id": "sess_3", "received_seq": 1}),
        ]
    )
    with patch("dimos.agents.skills.vis_bridge_skill.requests.post", side_effect=recorder):
        skill._handle_user_input("hello")
        ok = skill._post_vis_thoughts(skill._session_id or "", 1, "thought")

    assert ok is True
    # Two thoughts POST attempts (first failed, second succeeded); seq unchanged.
    thoughts_calls = [c for c in recorder.calls if c[0].endswith("/vis/thoughts")]
    assert len(thoughts_calls) == 2
    assert thoughts_calls[0][1]["seq"] == 1
    assert thoughts_calls[1][1]["seq"] == 1
    assert thoughts_calls[0][1]["content"] == thoughts_calls[1][1]["content"]


def test_outputs_includes_reasoning_content_when_present(skill: VisBridgeSkill) -> None:
    responses = [
        _ok_response({"session_id": "sess_4"}),
        _ok_response({"session_id": "sess_4"}),
    ]
    recorder = _PostRecorder(responses)
    with patch("dimos.agents.skills.vis_bridge_skill.requests.post", side_effect=recorder):
        skill._handle_user_input("hi")
        skill._handle_agent_message(
            AIMessage(
                content="你好",
                additional_kwargs={"reasoning_content": "用户在打招呼"},
            )
        )
        skill._handle_idle()

    outputs_call = recorder.calls[-1]
    assert outputs_call[0].endswith("/vis/outputs")
    result = outputs_call[1]["result"]
    assert result["content"] == "你好"
    assert result["reasoning_content"] == "用户在打招呼"


def test_non_ai_agent_message_is_ignored(skill: VisBridgeSkill) -> None:
    """human/tool messages on /agent should not update the AI reply buffer."""
    responses = [_ok_response({"session_id": "sess_5"}), _ok_response({"session_id": "sess_5"})]
    recorder = _PostRecorder(responses)
    with patch("dimos.agents.skills.vis_bridge_skill.requests.post", side_effect=recorder):
        skill._handle_user_input("hi")
        skill._handle_agent_message(HumanMessage(content="ignored"))
        skill._handle_idle()

    # outputs result content should be empty (no AIMessage seen)
    assert recorder.calls[-1][1]["result"]["content"] == ""
    assert "reasoning_content" not in recorder.calls[-1][1]["result"]


def test_new_user_input_abandons_existing_session(skill: VisBridgeSkill) -> None:
    responses = [
        _ok_response({"session_id": "sess_a"}),
        _ok_response({"session_id": "sess_b"}),
        _ok_response({"session_id": "sess_b"}),
    ]
    recorder = _PostRecorder(responses)
    with patch("dimos.agents.skills.vis_bridge_skill.requests.post", side_effect=recorder):
        skill._handle_user_input("first")
        # Second user_input before idle — old session abandoned, new one created.
        skill._handle_user_input("second")
        skill._handle_reasoning({"content": "thought"})
        skill._handle_idle()

    # Two /vis/input calls (one per user_input), one thoughts, one outputs.
    input_calls = [c for c in recorder.calls if c[0].endswith("/vis/input")]
    assert len(input_calls) == 2
    assert recorder.calls[-1][1]["session_id"] == "sess_b"
