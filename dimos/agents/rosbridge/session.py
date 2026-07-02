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

from dimos.core.global_config import GlobalConfig, global_config


class RosbridgeSession:
    """Shared long-lived py_rosbridge client for dimos ROS adapters."""

    def __init__(
        self,
        *,
        target: str,
        ready_timeout_s: float = 10.0,
        max_receive_mb: int = 64,
        client: Any | None = None,
    ) -> None:
        self._target = target
        self._ready_timeout_s = ready_timeout_s
        self._max_receive_mb = max_receive_mb
        self._client = client
        self._owns_client = client is None

    @classmethod
    def from_config(cls, config: GlobalConfig | None = None) -> RosbridgeSession:
        cfg = config or global_config
        return cls(
            target=cfg.rosbridge_grpc_address,
            ready_timeout_s=cfg.rosbridge_ready_timeout_s,
            max_receive_mb=cfg.rosbridge_max_receive_mb,
        )

    @property
    def target(self) -> str:
        return self._target

    

    def get_client(self) -> Any:
        """Return a lazily-created py_rosbridge client with visible reader errors."""
        def on_disconnect(exc: BaseException) -> None:
            print(f"reader error: {type(exc).__name__}: {exc}", flush=True)
        if self._client is None:
            from py_rosbridge import RosbridgeClient

            self._client = RosbridgeClient(
                self._target,
                ready_timeout=self._ready_timeout_s,
                max_receive_message_length=self._max_receive_mb * 1024 * 1024,
                on_disconnect=on_disconnect,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
        self._client = None

    def __enter__(self) -> RosbridgeSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["RosbridgeSession"]
