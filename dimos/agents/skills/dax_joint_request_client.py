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

"""HTTP client for dax_server joint-control endpoints."""

from __future__ import annotations

from typing import Any

import requests

from dimos.core.global_config import global_config
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class DaxJointRequestClient:
    def __init__(self, url: str = global_config.dax_joint_server_url, timeout: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False

    def close(self) -> None:
        self.session.close()

    def post(self, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        full_url = self.url + "/" + endpoint.lstrip("/")
        logger.info("POST %s payload=%s", full_url, payload)
        response = self.session.post(full_url, json=payload, timeout=self.timeout)
        if not response.ok:
            raise RuntimeError(
                f"POST {full_url} failed with HTTP {response.status_code}: {response.text[:1000]}"
            )
        return response.json()

    def move_heads(
        self,
        heads: list[float],
        time_from_start: float = 1.0,
        threshold: float = 0.05,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return self.post(
            "moveheadsOffline",
            {
                "heads": heads,
                "time_from_start": time_from_start,
                "threshold": threshold,
                "timeout": timeout,
            },
        )

    def move_waist(
        self,
        waist: list[float],
        dt: float = 0.01,
        threshold: float = 0.05,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return self.post(
            "moveWaistAllCubic",
            {
                "waist": waist,
                "dt": dt,
                "threshold": threshold,
                "timeout": timeout,
            },
        )

    def move_dual_joints(
        self,
        left_joints: list[float],
        right_joints: list[float],
        dt: float = 0.01,
    ) -> dict[str, Any]:
        return self.post(
            "moveJDualOffline",
            {
                "left_joints": left_joints,
                "right_joints": right_joints,
                "dt": dt,
            },
        )

    def servo_dual_joints(self, left_joints: list[float], right_joints: list[float]) -> dict[str, Any]:
        return self.post(
            "servoJDual",
            {
                "left_joints": left_joints,
                "right_joints": right_joints,
            },
        )

    def joint_reset(self) -> dict[str, Any]:
        return self.post("jointreset", {})

    def move_reset_pose(self) -> dict[str, Any]:
        return self.post("move", {})


__all__ = ["DaxJointRequestClient"]
