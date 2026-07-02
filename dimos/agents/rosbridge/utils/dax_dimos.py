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

import json
from typing import Any

from dimos.agents.rosbridge.codecs.dax_dimos_interfaces import (
    ExecutePickTaskRequest,
    PickSkuRequest,
)


def pick_fields_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Extract workspace/sku flat fields from a VLA validated payload."""
    target_meta = payload.get("target_meta")
    meta = target_meta if isinstance(target_meta, dict) else {}
    table_id = str(meta.get("table_id", "table"))
    workspace_name = "table" if table_id.startswith("table") else table_id
    return {
        "workspace_name": workspace_name,
        "workspace_color": str(meta.get("table_color", "")),
        "sku_name": str(meta.get("object_type", "")),
        "sku_color": str(meta.get("object_color", "")),
    }


def build_execute_pick_task_request(payload: dict[str, Any]) -> ExecutePickTaskRequest:
    fields = pick_fields_from_payload(payload)
    return ExecutePickTaskRequest(**fields)


def build_pick_sku_request(
    *,
    workspace_name: str,
    workspace_color: str,
    sku_name: str,
    sku_color: str,
    side: str = "",
) -> PickSkuRequest:
    return PickSkuRequest(
        workspace_name=workspace_name,
        workspace_color=workspace_color,
        sku_name=sku_name,
        sku_color=sku_color,
        side=side,
    )


def service_failure_message(response: Any) -> str:
    failure_reason = getattr(response, "failure_reason", "")
    if failure_reason:
        return failure_reason
    status = getattr(response, "status", "")
    if status:
        return f"service status={status!r}"
    return "service returned success=false"


def payload_from_service_response(response: Any) -> dict[str, Any]:
    """Build a dict payload from a dax_dimos_interfaces service response."""
    result_json = getattr(response, "result_json", "") or ""
    if result_json:
        try:
            parsed = json.loads(result_json)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    return {
        "command": getattr(response, "command", ""),
        "status": getattr(response, "status", ""),
        "success": bool(getattr(response, "success", False)),
        "failure_reason": getattr(response, "failure_reason", ""),
        "result_json": result_json,
    }


__all__ = [
    "build_execute_pick_task_request",
    "build_pick_sku_request",
    "payload_from_service_response",
    "pick_fields_from_payload",
    "service_failure_message",
]
