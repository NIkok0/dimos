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

"""Minimal Foxglove WebSocket client for ros-foxglove-bridge."""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

import websockets

FOXGLOVE_SUBPROTOCOL = "foxglove.websocket.v1"
BINARY_OPCODE_MESSAGE_DATA = 1

T = TypeVar("T")


@dataclass(frozen=True)
class FoxgloveChannel:
    id: int
    topic: str
    encoding: str
    schema_name: str


class FoxgloveBridgeClient:
    """Subscribe to ROS topics exposed by ros-foxglove-bridge."""

    def __init__(
        self,
        url: str,
        *,
        channel_collect_timeout_s: float = 2.0,
        max_message_mb: int = 50,
    ) -> None:
        self._url = url
        self._channel_collect_timeout_s = channel_collect_timeout_s
        self._max_size = max_message_mb * 1024 * 1024

    def list_channels(self) -> list[FoxgloveChannel]:
        """Return all channels advertised by the bridge."""
        return asyncio.run(self._list_channels())

    def subscribe_once(
        self,
        topic: str,
        codec: type[Any],
        *,
        timeout_s: float = 15.0,
    ) -> Any:
        """Subscribe to one topic and return the first decoded message."""
        return asyncio.run(self._subscribe_once(topic, codec, timeout_s=timeout_s))

    def subscribe_many(
        self,
        subscriptions: Sequence[tuple[str, type[Any]]],
        *,
        timeout_s: float = 15.0,
    ) -> dict[str, Any]:
        """Subscribe to several topics in one connection; return first message per topic."""
        return asyncio.run(self._subscribe_many(subscriptions, timeout_s=timeout_s))

    async def _list_channels(self) -> list[FoxgloveChannel]:
        async with websockets.connect(
            self._url,
            subprotocols=[FOXGLOVE_SUBPROTOCOL],
            max_size=self._max_size,
        ) as ws:
            raw = await self._collect_channel_map(ws)
            return [_to_channel(channel_id, payload) for channel_id, payload in sorted(raw.items())]

    async def _subscribe_once(self, topic: str, codec: type[Any], *, timeout_s: float) -> Any:
        results = await self._subscribe_many([(topic, codec)], timeout_s=timeout_s)
        return results[topic]

    async def _subscribe_many(
        self,
        subscriptions: Sequence[tuple[str, type[Any]]],
        *,
        timeout_s: float,
    ) -> dict[str, Any]:
        if not subscriptions:
            return {}

        async with websockets.connect(
            self._url,
            subprotocols=[FOXGLOVE_SUBPROTOCOL],
            max_size=self._max_size,
        ) as ws:
            channels = await self._collect_channel_map(ws)
            topic_to_channel = {payload["topic"]: channel_id for channel_id, payload in channels.items()}

            pending = {topic: codec for topic, codec in subscriptions}
            results: dict[str, Any] = {}
            sub_id = 1
            topic_by_sub_id: dict[int, str] = {}

            for topic, _codec in subscriptions:
                channel_id = topic_to_channel.get(topic)
                if channel_id is None:
                    raise KeyError(f"topic not advertised: {topic}")
                topic_by_sub_id[sub_id] = topic
                await ws.send(
                    json.dumps(
                        {
                            "op": "subscribe",
                            "subscriptions": [{"id": sub_id, "channelId": channel_id}],
                        }
                    )
                )
                sub_id += 1

            while pending:
                msg = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
                if not isinstance(msg, bytes) or len(msg) < 13 or msg[0] != BINARY_OPCODE_MESSAGE_DATA:
                    continue
                subscription_id = struct.unpack_from("<I", msg, 1)[0]
                topic = topic_by_sub_id.get(subscription_id)
                if topic is None or topic not in pending:
                    continue
                codec = pending.pop(topic)
                results[topic] = codec.decode(msg[13:])

            return results

    async def _collect_channel_map(self, ws: Any) -> dict[int, Mapping[str, Any]]:
        channels: dict[int, Mapping[str, Any]] = {}
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=self._channel_collect_timeout_s)
            except asyncio.TimeoutError:
                break
            if not isinstance(msg, str):
                continue
            data = json.loads(msg)
            if data.get("op") != "advertise":
                continue
            for channel in data.get("channels", []):
                channels[int(channel["id"])] = channel
        return channels


def _to_channel(channel_id: int, payload: Mapping[str, Any]) -> FoxgloveChannel:
    return FoxgloveChannel(
        id=channel_id,
        topic=str(payload["topic"]),
        encoding=str(payload["encoding"]),
        schema_name=str(payload["schemaName"]),
    )
