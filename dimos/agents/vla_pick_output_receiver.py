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

from dataclasses import dataclass
from typing import Any, Literal

from dimos.agents.skill_result import SkillResult

VlaReceiverError = Literal[
    "VLA_UNAVAILABLE",
    "VLA_OUTPUT_INVALID",
    "VLA_TARGET_MISMATCH",
    "VLA_EXECUTION_FAILED",
]

VlaReceiverResult = SkillResult[VlaReceiverError]


@dataclass(frozen=True)
class VlaPickRequest:
    workspace_type: str
    table_color: str
    object_type: str
    object_color: str
    request_id: str = ""

    def service_payload(self) -> dict[str, str]:
        return {
            "workspace_name": self.workspace_type,
            "workspace_color": self.table_color,
            "sku_name": self.object_type,
            "sku_color": self.object_color,
        }

    def trace_payload(self) -> dict[str, str]:
        payload = {
            "workspace_type": self.workspace_type,
            "table_color": self.table_color,
            "object_type": self.object_type,
            "object_color": self.object_color,
        }
        if self.request_id:
            payload["request_id"] = self.request_id
        return payload


def validate_vla_pick_payload(
    payload: dict[str, Any],
    *,
    request: VlaPickRequest | None,
    success_message: str,
) -> VlaReceiverResult:
    """Validate a VLA pick payload from rosbridge result_json or service fields."""
    return _validate_pick_payload(
        payload,
        request=request,
        success_message=success_message,
    )


def _validate_pick_payload(
    payload: dict[str, Any],
    *,
    request: VlaPickRequest | None,
    success_message: str,
) -> VlaReceiverResult:
    raw_payload = payload

    execution_failure = _service_execution_failure(payload)
    if execution_failure is not None:
        return execution_failure

    normalized = _normalize_robotwin_payload(payload, request)
    response_format = "contract"
    if normalized is not None:
        payload = normalized
        response_format = "robotwin_status"

    target_meta = payload.get("target_meta")
    if not isinstance(target_meta, dict):
        return SkillResult(
            success=False,
            error_code="VLA_OUTPUT_INVALID",
            message="VLA output missing target_meta.",
            metadata={"raw_payload": raw_payload},
        )

    if "joint_action" not in payload:
        return SkillResult(
            success=False,
            error_code="VLA_OUTPUT_INVALID",
            message="VLA output missing joint_action.",
            metadata={"raw_payload": raw_payload},
        )

    if request is not None:
        mismatch = _first_target_mismatch(payload, target_meta, request)
        if mismatch is not None:
            return SkillResult(
                success=False,
                error_code="VLA_TARGET_MISMATCH",
                message=mismatch,
                metadata={
                    "request": request.trace_payload(),
                    "raw_payload": raw_payload,
                    "target_meta": target_meta,
                },
            )

    return SkillResult.ok(
        success_message,
        request=request.trace_payload() if request is not None else {},
        raw_payload=raw_payload,
        validated_payload=payload,
        target_meta=target_meta,
        held_object=_held_object_from_payload(payload, target_meta, request),
        validation_passed=True,
        vla_response_format=response_format,
        normalized_from_robotwin=normalized is not None,
    )


def _is_robotwin_status_payload(payload: dict[str, Any]) -> bool:
    if "target_meta" in payload:
        return False
    if payload.get("command") in {"pick_sku", "execute_pick_task", "go_to_workspace"}:
        return True
    return any(key in payload for key in ("sku_name", "workspace_name", "sku_id", "workspace_id"))


def _service_execution_failure(payload: dict[str, Any]) -> VlaReceiverResult | None:
    if "error_code" in payload and "target_meta" not in payload:
        return SkillResult(
            success=False,
            error_code="VLA_EXECUTION_FAILED",
            message=str(payload.get("message", "VLA returned an execution error.")),
            metadata={
                "raw_payload": payload,
                "vla_error_code": payload.get("error_code"),
            },
        )

    if not _is_robotwin_status_payload(payload):
        if "message" in payload and "target_meta" not in payload:
            return SkillResult(
                success=False,
                error_code="VLA_EXECUTION_FAILED",
                message=str(payload.get("message", "VLA returned an execution error.")),
                metadata={"raw_payload": payload},
            )
        return None

    if payload.get("success") is False:
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("failure_reason")
            or "VLA execution failed."
        )
        return SkillResult(
            success=False,
            error_code="VLA_EXECUTION_FAILED",
            message=str(message),
            metadata={"raw_payload": payload},
        )

    status = payload.get("status")
    if isinstance(status, str) and status.lower() not in {"succeeded", "success", "ok"}:
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("failure_reason")
            or f"VLA execution status={status!r}."
        )
        return SkillResult(
            success=False,
            error_code="VLA_EXECUTION_FAILED",
            message=str(message),
            metadata={"raw_payload": payload},
        )

    return None


def _normalize_robotwin_payload(
    payload: dict[str, Any],
    request: VlaPickRequest | None,
) -> dict[str, Any] | None:
    if isinstance(payload.get("target_meta"), dict) and "joint_action" in payload:
        return None
    if not _is_robotwin_status_payload(payload):
        return None
    if request is None:
        return None
    if payload.get("success") is False:
        return None

    status = payload.get("status")
    if isinstance(status, str) and status.lower() not in {"succeeded", "success", "ok"}:
        return None

    target_pose = payload.get("target_pose")
    object_position = target_pose if isinstance(target_pose, list) else None
    robot_position = payload.get("robot_position")
    workspace_position = robot_position if isinstance(robot_position, list) else None

    target_meta = {
        "target_object_id": str(payload.get("sku_id") or payload.get("held_object_id") or ""),
        "object_type": str(payload.get("sku_name") or request.object_type),
        "object_color": str(payload.get("sku_color") or request.object_color),
        "object_position": object_position,
        "table_id": str(payload.get("workspace_id") or ""),
        "table_color": str(payload.get("workspace_color") or request.table_color),
        "workspace_position": workspace_position,
    }

    joint_action = payload.get("joint_action")
    if not isinstance(joint_action, dict):
        joint_action = {
            "left_arm": [],
            "left_gripper": 1.0,
            "right_arm": [],
            "right_gripper": 1.0,
        }

    normalized = dict(payload)
    normalized["request_id"] = request.request_id or payload.get("request_id", "")
    normalized["frame_idx"] = payload.get("frame_idx", 0)
    normalized["target_meta"] = target_meta
    normalized["joint_action"] = joint_action
    normalized.setdefault("joint_state", {})
    normalized.setdefault("endpose", {"target_pose": target_pose} if object_position else {})
    normalized.setdefault("camera_params", {})
    return normalized


def _first_target_mismatch(
    payload: dict[str, Any],
    target_meta: dict[str, Any],
    request: VlaPickRequest,
) -> str | None:
    expected = {
        "object_type": request.object_type,
        "object_color": request.object_color,
        "table_color": request.table_color,
    }
    for field, expected_value in expected.items():
        actual_value = target_meta.get(field)
        if actual_value != expected_value:
            return f"target_meta.{field}={actual_value!r} does not match {expected_value!r}."

    actual_request_id = payload.get("request_id")
    if request.request_id and actual_request_id is not None and actual_request_id != request.request_id:
        return f"request_id={actual_request_id!r} does not match {request.request_id!r}."

    return None


def _held_object_from_payload(
    payload: dict[str, Any],
    target_meta: dict[str, Any],
    request: VlaPickRequest | None,
) -> dict[str, str]:
    """Build the object-state contract consumed by downstream drop planning."""
    existing = payload.get("held_object")
    if isinstance(existing, dict):
        return {
            "sku_name": str(existing.get("sku_name") or target_meta.get("object_type") or _request_object_type(request)),
            "sku_color": str(
                existing.get("sku_color") or target_meta.get("object_color") or _request_object_color(request)
            ),
            "sku_id": str(existing.get("sku_id") or target_meta.get("target_object_id") or ""),
            "arm_name": str(existing.get("arm_name") or _arm_name_from_payload(payload)),
            "grasp_type": str(existing.get("grasp_type") or payload.get("grasp_type") or "Default"),
        }
    return {
        "sku_name": str(target_meta.get("object_type") or _request_object_type(request)),
        "sku_color": str(target_meta.get("object_color") or _request_object_color(request)),
        "sku_id": str(target_meta.get("target_object_id") or payload.get("sku_id") or ""),
        "arm_name": _arm_name_from_payload(payload),
        "grasp_type": str(payload.get("grasp_type") or "Default"),
    }


def _arm_name_from_payload(payload: dict[str, Any]) -> str:
    """Infer the active manipulation arm from joint_action with a left-arm fallback."""
    joint_action = payload.get("joint_action")
    if not isinstance(joint_action, dict):
        return "left"
    left_action = joint_action.get("left_arm")
    right_action = joint_action.get("right_arm")
    if _non_empty_action(left_action):
        return "left"
    if _non_empty_action(right_action):
        return "right"
    return "left"


def _non_empty_action(value: Any) -> bool:
    """Return whether a joint action field contains a usable command."""
    if isinstance(value, list):
        return bool(value)
    return value is not None


def _request_object_type(request: VlaPickRequest | None) -> str:
    """Return request object type or an empty string when no request is available."""
    return request.object_type if request is not None else ""


def _request_object_color(request: VlaPickRequest | None) -> str:
    """Return request object color or an empty string when no request is available."""
    return request.object_color if request is not None else ""


# ---------------------------------------------------------------------------
# Deprecated: HTTP VLA client (VLA_SERVICE_URL :8018). Replaced by rosbridge.
# ---------------------------------------------------------------------------
#
# import requests
# from dimos.core.global_config import GlobalConfig, global_config
#
# class VlaPickHttpClient:
#     ... POST /pick_sku, /execute_pick_task, /go_to_workspace via requests ...
#

__all__ = [
    "VlaPickRequest",
    "VlaReceiverError",
    "VlaReceiverResult",
    "validate_vla_pick_payload",
]
