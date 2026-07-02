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
import uuid

from dimos.agents.rosbridge.codecs.dax_dimos_interfaces import (
    ExecutePickTaskRequestCodec,
    ExecutePickTaskResponseCodec,
)
from dimos.agents.rosbridge.utils.dax_dimos import (
    build_execute_pick_task_request,
    pick_fields_from_payload,
    service_failure_message,
)
from dimos.agents.rosbridge.session import RosbridgeSession
from dimos.agents.vla_pick_adapters import RosActionResult
from dimos.core.global_config import GlobalConfig, global_config

from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class PyRosbridgeRosActionAdapter:
    """Call remote ``/execute_pick_task`` (dax_dimos_interfaces) via rosbridge."""

    def __init__(
        self,
        *,
        session: RosbridgeSession,
        service: str,
        service_type: str,
    ) -> None:
        self._session = session
        self._service = service
        self._service_type = service_type
        self.calls: list[dict[str, Any]] = []

    @classmethod
    def from_config(
        cls,
        config: GlobalConfig | None = None,
        *,
        session: RosbridgeSession | None = None,
    ) -> PyRosbridgeRosActionAdapter:
        cfg = config or global_config
        return cls(
            session=session or RosbridgeSession.from_config(cfg),
            service=cfg.ros_execute_pick_task_service,
            service_type=cfg.ros_execute_pick_task_service_type,
        )

    @property
    def _target(self) -> str:
        return self._session.target

    def close(self) -> None:
        self._session.close()

    def submit_action(
        self,
        *,
        request_id: str,
        payload: dict[str, Any],
        timeout_s: float = 30.0,
    ) -> RosActionResult:
        ros_goal_id = f"ros-{uuid.uuid4().hex[:8]}"
        request = build_execute_pick_task_request(payload)
        envelope = {
            "ros_goal_id": ros_goal_id,
            "request_id": request_id,
            "timeout_s": timeout_s,
            "payload": payload,
            "grpc_target": self._target,
            "service": self._service,
            "service_type": self._service_type,
            **pick_fields_from_payload(payload),
        }
        self.calls.append(envelope)
        logger.info(
            "rosbridge execute_pick_task request_id=%s target=%s workspace=%s/%s sku=%s/%s",
            request_id,
            self._target,
            request.workspace_name,
            request.workspace_color,
            request.sku_name,
            request.sku_color,
        )

        try:
            result = self._session.get_client().call_service(
                self._service,
                self._service_type,
                request,
                request_codec=ExecutePickTaskRequestCodec,
                response_codec=ExecutePickTaskResponseCodec,
                timeout_sec=timeout_s,
                wait_timeout=timeout_s + 1.0,
            )
        except Exception as exc:
            if exc.__class__.__name__ == "FutureTimeoutError":
                status = "timeout"
                message = f"rosbridge gRPC server {self._target} not reachable"
            else:
                status = "failed"
                message = str(exc) or exc.__class__.__name__
            logger.exception(
                "rosbridge execute_pick_task failed request_id=%s target=%s",
                request_id,
                self._target,
            )
            return RosActionResult(
                ros_goal_id=ros_goal_id,
                request_id=request_id,
                status=status,  # type: ignore[arg-type]
                message=message,
                payload=payload,
            )

        if not result.success:
            return RosActionResult(
                ros_goal_id=ros_goal_id,
                request_id=request_id,
                status="rejected",
                message=f"gRPC service call failed for {self._service}",
                payload=payload,
            )

        response = result.response
        if not response.success:
            return RosActionResult(
                ros_goal_id=ros_goal_id,
                request_id=request_id,
                status="failed",
                message=service_failure_message(response),
                payload=payload,
            )

        message = response.failure_reason or response.status or "execute_pick_task succeeded"
        if response.result_json:
            message = f"{message}; result_json={response.result_json[:200]}"
        return RosActionResult(
            ros_goal_id=ros_goal_id,
            request_id=request_id,
            status="succeeded",
            message=message,
            payload=payload,
        )


__all__ = ["PyRosbridgeRosActionAdapter"]
