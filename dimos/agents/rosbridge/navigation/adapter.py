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

import uuid

from dimos.agents.rosbridge.codecs.dax_dimos_interfaces import (
    GoToWorkspaceRequest,
    GoToWorkspaceRequestCodec,
    GoToWorkspaceResponseCodec,
)
from dimos.agents.rosbridge.utils.dax_dimos import service_failure_message
from dimos.agents.rosbridge.session import RosbridgeSession
from dimos.agents.vla_pick_adapters import NavigationResult
from dimos.core.global_config import GlobalConfig, global_config

from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class PyRosbridgeSysNavigationAdapter:
    """Call remote ``/go_to_workspace`` (dax_dimos_interfaces) via rosbridge."""

    def __init__(
        self,
        *,
        session: RosbridgeSession,
        service: str,
        service_type: str,
        timeout_s: float = 30.0,
    ) -> None:
        self._session = session
        self._service = service
        self._service_type = service_type
        self._timeout_s = timeout_s
        self.calls: list[dict[str, str]] = []

    @classmethod
    def from_config(
        cls,
        config: GlobalConfig | None = None,
        *,
        session: RosbridgeSession | None = None,
    ) -> PyRosbridgeSysNavigationAdapter:
        cfg = config or global_config
        return cls(
            session=session or RosbridgeSession.from_config(cfg),
            service=cfg.ros_go_to_workspace_service,
            service_type=cfg.ros_go_to_workspace_service_type,
            timeout_s=cfg.ros_action_timeout_s,
        )

    def navigate_to_workspace(
        self,
        *,
        request_id: str,
        workspace_type: str,
        table_color: str,
    ) -> NavigationResult:
        sys_task_id = f"sys-{uuid.uuid4().hex[:8]}"
        self.calls.append(
            {
                "request_id": request_id,
                "workspace_type": workspace_type,
                "table_color": table_color,
            }
        )
        logger.info(
            "rosbridge go_to_workspace request_id=%s service=%s workspace=%s/%s",
            request_id,
            self._service,
            workspace_type,
            table_color,
        )
        try:
            result = self._session.get_client().call_service(
                self._service,
                self._service_type,
                GoToWorkspaceRequest(
                    workspace_name=workspace_type,
                    workspace_color=table_color,
                ),
                request_codec=GoToWorkspaceRequestCodec,
                response_codec=GoToWorkspaceResponseCodec,
                timeout_sec=self._timeout_s,
                wait_timeout=self._timeout_s + 1.0,
            )
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            status = "timeout" if exc.__class__.__name__ == "FutureTimeoutError" else "failed"
            logger.exception("rosbridge go_to_workspace failed request_id=%s", request_id)
            return NavigationResult(
                sys_task_id=sys_task_id,
                status=status,  # type: ignore[arg-type]
                workspace_type=workspace_type,
                table_color=table_color,
                message=message,
            )

        if not result.success or not result.response.success:
            return NavigationResult(
                sys_task_id=sys_task_id,
                status="failed",
                workspace_type=workspace_type,
                table_color=table_color,
                message=service_failure_message(result.response),
            )

        message = result.response.status or "Navigation arrived."
        return NavigationResult(
            sys_task_id=sys_task_id,
            status="arrived",
            workspace_type=workspace_type,
            table_color=table_color,
            message=message,
            final_robot_state={"arm_ready": True, "gripper_ready": True},
        )

    def move_relative(
        self,
        *,
        request_id: str,
        direction: str,
        distance_units: float,
    ) -> NavigationResult:
        """Relative body-frame motion is not implemented on /go_to_workspace."""
        return NavigationResult(
            sys_task_id=f"sys-{uuid.uuid4().hex[:8]}",
            status="failed",
            workspace_type="relative",
            table_color="",
            message=(
                "py_rosbridge navigation only supports navigate_to_workspace. "
                "Set VLA_SYS_NAV_ADAPTER=ros_topic for move_relative."
            ),
            final_robot_state={
                "adapter_mode": "py_rosbridge",
                "relative_motion": {
                    "direction": direction,
                    "distance_units": distance_units,
                },
            },
        )


__all__ = ["PyRosbridgeSysNavigationAdapter"]
