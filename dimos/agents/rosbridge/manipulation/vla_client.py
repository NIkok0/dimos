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

from dimos.agents.skill_result import SkillResult
from dimos.agents.rosbridge.codecs.dax_dimos_interfaces import (
    PickSkuRequestCodec,
    PickSkuResponseCodec,
)
from dimos.agents.rosbridge.utils.dax_dimos import (
    build_pick_sku_request,
    payload_from_service_response,
    service_failure_message,
)
from dimos.agents.rosbridge.session import RosbridgeSession
from dimos.agents.vla_pick_output_receiver import (
    VlaPickRequest,
    VlaReceiverResult,
    validate_vla_pick_payload,
)
from dimos.core.global_config import GlobalConfig, global_config

from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class PyRosbridgeVlaPickClient:
    """Call remote ``/pick_sku`` (dax_dimos_interfaces) via rosbridge instead of HTTP VLA."""

    def __init__(
        self,
        *,
        session: RosbridgeSession,
        service: str,
        service_type: str,
        pick_side: str = "",
        timeout_s: float = 30.0,
    ) -> None:
        self._session = session
        self._service = service
        self._service_type = service_type
        self._pick_side = pick_side
        self._timeout_s = timeout_s
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def from_config(
        cls,
        config: GlobalConfig | None = None,
        *,
        session: RosbridgeSession | None = None,
    ) -> PyRosbridgeVlaPickClient:
        cfg = config or global_config
        return cls(
            session=session or RosbridgeSession.from_config(cfg),
            service=cfg.ros_pick_sku_service,
            service_type=cfg.ros_pick_sku_service_type,
            pick_side=cfg.vla_ros_pick_side,
            timeout_s=cfg.ros_action_timeout_s,
        )

    def pick_sku(self, request: VlaPickRequest) -> VlaReceiverResult:
        pick_request = build_pick_sku_request(
            workspace_name=request.workspace_type,
            workspace_color=request.table_color,
            sku_name=request.object_type,
            sku_color=request.object_color,
            side=self._pick_side,
        )
        self.calls.append(
            {
                "request_id": request.request_id,
                "service": self._service,
                **pick_request.__dict__,
            }
        )
        logger.info(
            "rosbridge pick_sku request_id=%s service=%s workspace=%s/%s sku=%s/%s",
            request.request_id,
            self._service,
            pick_request.workspace_name,
            pick_request.workspace_color,
            pick_request.sku_name,
            pick_request.sku_color,
        )
        try:
            result = self._session.get_client().call_service(
                self._service,
                self._service_type,
                pick_request,
                request_codec=PickSkuRequestCodec,
                response_codec=PickSkuResponseCodec,
                timeout_sec=self._timeout_s,
                wait_timeout=self._timeout_s + 1.0,
            )
        except Exception as exc:
            error_code = "VLA_UNAVAILABLE" if exc.__class__.__name__ == "FutureTimeoutError" else "VLA_EXECUTION_FAILED"
            message = str(exc) or exc.__class__.__name__
            logger.exception("rosbridge pick_sku failed request_id=%s", request.request_id)
            return SkillResult.fail(error_code, message)

        if not result.success:
            return SkillResult.fail(
                "VLA_EXECUTION_FAILED",
                f"gRPC service call failed for {self._service}",
            )

        response = result.response
        if not response.success:
            return SkillResult.fail(
                "VLA_EXECUTION_FAILED",
                service_failure_message(response),
                raw_payload=payload_from_service_response(response),
            )

        payload = payload_from_service_response(response)
        validated = validate_vla_pick_payload(
            payload,
            request=request,
            success_message="Received and validated rosbridge pick_sku output.",
        )
        if validated.success:
            return validated

        if "joint_action" not in payload:
            return SkillResult.ok(
                "pick_sku completed on remote via rosbridge.",
                request=request.trace_payload(),
                raw_payload=payload,
                ros_service_response=payload_from_service_response(response),
                validation_passed=False,
                ros_pick_completed=True,
            )
        return validated

    def execute_pick_task(self, request: VlaPickRequest) -> VlaReceiverResult:
        return self.pick_sku(request)

    def execute_action_list(
        self,
        actions: list[dict[str, Any]],
        *,
        request: VlaPickRequest,
    ) -> VlaReceiverResult:
        return SkillResult.fail(
            "VLA_OUTPUT_INVALID",
            "vla_drop_sku via rosbridge is not implemented.",
        )


__all__ = ["PyRosbridgeVlaPickClient"]
