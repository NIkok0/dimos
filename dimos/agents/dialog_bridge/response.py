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

"""Format MCP ``execute_nl_task`` results for Dialog TTS replies."""

from __future__ import annotations

import json
from typing import Any

from dimos.agents.mcp.mcp_adapter import McpError


def parse_mcp_tool_text(raw: str) -> dict[str, Any]:
    """Parse ``call_tool_text`` output into a dict (SkillResult JSON or plain text)."""
    text = raw.strip()
    if not text:
        return {"success": False, "message": "Empty response from robot agent."}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"success": True, "message": text}
    if isinstance(payload, dict):
        return payload
    return {"success": True, "message": str(payload)}


def build_dialog_response(
    *,
    request_id: str,
    mcp_text: str,
    success_prefix: str = "好的，",
    failure_prefix: str = "抱歉，",
) -> dict[str, Any]:
    """Build a voice-friendly JSON body from MCP tool output."""
    parsed = parse_mcp_tool_text(mcp_text)
    success = bool(parsed.get("success", True))
    message = str(parsed.get("message") or "").strip()
    error_code = parsed.get("error_code")

    if success:
        spoken = message if message else "任务已开始。"
        if success_prefix and not spoken.startswith(success_prefix.rstrip("，")):
            spoken = f"{success_prefix}{spoken}"
    else:
        code = str(error_code) if error_code else "ERROR"
        spoken = message if message else code
        if failure_prefix and not spoken.startswith(failure_prefix.rstrip("，")):
            spoken = f"{failure_prefix}{spoken}"

    detail = {k: v for k, v in parsed.items() if k not in {"success", "message", "error_code"}}
    return {
        "success": success,
        "message": spoken,
        "error_code": error_code,
        "request_id": request_id,
        "detail": detail,
    }


def build_error_response(
    *,
    request_id: str,
    message: str,
    error_code: str = "BRIDGE_ERROR",
) -> dict[str, Any]:
    """Build a failure response when the bridge itself fails."""
    return {
        "success": False,
        "message": message,
        "error_code": error_code,
        "request_id": request_id,
        "detail": {},
    }


def mcp_error_message(exc: BaseException) -> str:
    """Turn MCP/HTTP errors into short spoken messages."""
    if isinstance(exc, McpError):
        text = str(exc)
        if "Cannot start" in text or "capability" in text.lower():
            return "机器人正在执行其他任务，请稍后再试。"
        return text
    return f"无法连接机器人服务：{exc}"


__all__ = [
    "build_dialog_response",
    "build_error_response",
    "mcp_error_message",
    "parse_mcp_tool_text",
]
