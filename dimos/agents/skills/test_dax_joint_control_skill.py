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
from unittest.mock import MagicMock

import pytest

from dimos.agents.skills.dax_joint_control_skill import (
    HEAD_ACCEPT_STEPS,
    HEAD_REJECT_STEPS,
    DaxJointControlSkill,
)


@pytest.fixture
def skill() -> DaxJointControlSkill:
    module = object.__new__(DaxJointControlSkill)
    module._client = MagicMock()
    return module


def test_head_reject_sends_reject_sequence(skill: DaxJointControlSkill) -> None:
    result = skill.head_reject(time_from_start=0.5)

    assert result == "我摇了摇头，这个任务我做不了"
    assert skill._client.move_heads.call_count == len(HEAD_REJECT_STEPS)
    for call, expected_heads in zip(skill._client.move_heads.call_args_list, HEAD_REJECT_STEPS, strict=True):
        assert call.args[0] == expected_heads
        assert call.kwargs["time_from_start"] == 0.5


def test_head_accept_sends_accept_sequence(skill: DaxJointControlSkill) -> None:
    result = skill.head_accept(time_from_start=0.75)

    assert result == "好的，我点了一下头"
    assert skill._client.move_heads.call_count == len(HEAD_ACCEPT_STEPS)
    for call, expected_heads in zip(skill._client.move_heads.call_args_list, HEAD_ACCEPT_STEPS, strict=True):
        assert call.args[0] == expected_heads
        assert call.kwargs["time_from_start"] == 0.75


def test_head_reject_returns_error_on_http_failure(skill: DaxJointControlSkill) -> None:
    skill._client.move_heads.side_effect = RuntimeError("HTTP 500")

    result = skill.head_reject()

    assert result.startswith("抱歉，摇头动作没能完成")


def test_head_accept_without_client_returns_error() -> None:
    module = object.__new__(DaxJointControlSkill)
    module._client = None
    result = module.head_accept()
    assert "机械臂服务还没连上" in result


def test_head_gesture_docstrings_use_obedience_semantics() -> None:
    reject_doc = inspect.getdoc(DaxJointControlSkill.head_reject) or ""
    accept_doc = inspect.getdoc(DaxJointControlSkill.head_accept) or ""

    assert "impossible" in reject_doc.lower()
    assert "unsupported_intent" in reject_doc.lower()
    assert "need_clarification" in reject_doc.lower()
    assert "obedience" in accept_doc.lower()
    assert "cancel" in accept_doc.lower()
