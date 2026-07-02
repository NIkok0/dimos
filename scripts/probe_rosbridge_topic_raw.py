#!/usr/bin/env python3
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

"""Probe whether rosbridge_grpc forwards raw topic frames at all.

This script deliberately avoids DimOS message codecs. It subscribes with
RawCdrCodec and reports whether any ``topic_message`` frame arrives. Use it to
separate server-side forwarding problems from client-side decode problems.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
from typing import Any

import grpc

from py_rosbridge import RawCdrCodec, RosbridgeClient
from py_rosbridge.client import Qos, QosDurability, QosHistory, QosReliability

from dimos.core.global_config import global_config


def parse_args() -> argparse.Namespace:
    """Parse raw topic probe arguments."""
    parser = argparse.ArgumentParser(description="Probe raw topic frames via rosbridge gRPC.")
    parser.add_argument("--target", default=global_config.rosbridge_grpc_address)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--topic-type", required=True)
    parser.add_argument("--ready-timeout-s", type=float, default=global_config.rosbridge_ready_timeout_s)
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--reliability", choices=("best_effort", "reliable"), default="best_effort")
    parser.add_argument("--durability", choices=("volatile", "transient_local"), default="volatile")
    parser.add_argument("--max-receive-mb", type=int, default=64)
    return parser.parse_args()


def main() -> int:
    """Subscribe to a topic with RawCdrCodec and report frame arrival."""
    args = parse_args()
    messages: queue.Queue[bytes] = queue.Queue(maxsize=1)
    frame_counts = {"status": 0, "topic_message": 0, "other": 0}

    def on_disconnect(exc: BaseException) -> None:
        print(f"READER_ERROR={type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

    def on_frame(frame: Any) -> None:
        kind = frame.WhichOneof("frame")
        if kind in frame_counts:
            frame_counts[kind] += 1
        else:
            frame_counts["other"] += 1
        if kind == "status":
            print(
                "ROSBRIDGE_STATUS="
                + json.dumps(
                    {
                        "id": frame.id,
                        "level": int(frame.status.level),
                        "message": frame.status.message,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )

    def on_message(event: Any) -> None:
        _replace_latest(messages, event.message)

    print(
        json.dumps(
            {
                "grpc_target": args.target,
                "topic": args.topic,
                "topic_type": args.topic_type,
                "reliability": args.reliability,
                "durability": args.durability,
                "timeout_s": args.timeout_s,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )

    try:
        with RosbridgeClient(
            args.target,
            ready_timeout=args.ready_timeout_s,
            max_receive_message_length=args.max_receive_mb * 1024 * 1024,
            on_disconnect=on_disconnect,
        ) as client:
            client.add_frame_callback(on_frame)
            client.subscribe(
                args.topic,
                args.topic_type,
                on_message,
                codec=RawCdrCodec,
                qos=Qos(
                    history=QosHistory.KEEP_LAST,
                    depth=1,
                    reliability=_reliability(args.reliability),
                    durability=_durability(args.durability),
                ),
            )
            try:
                payload = messages.get(timeout=args.timeout_s)
            except queue.Empty:
                print(
                    "RAW_TOPIC_STATE="
                    + json.dumps(
                        {
                            "status": "unavailable",
                            "reason": "topic_message_timeout",
                            "client_connected": client.is_connected,
                            "frame_counts": frame_counts,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )
                return 2

            print(
                "RAW_TOPIC_STATE="
                + json.dumps(
                    {
                        "status": "available",
                        "payload_len": len(payload),
                        "payload_prefix_hex": payload[:24].hex(),
                        "client_connected": client.is_connected,
                        "frame_counts": frame_counts,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
            return 0
    except grpc.FutureTimeoutError:
        print(
            "RAW_TOPIC_STATE="
            + json.dumps(
                {
                    "status": "unavailable",
                    "reason": "grpc_channel_ready_timeout",
                    "target": args.target,
                    "ready_timeout_s": args.ready_timeout_s,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        return 3


def _replace_latest(messages: queue.Queue[bytes], message: bytes) -> None:
    """Keep only the newest raw CDR message."""
    try:
        messages.put_nowait(message)
        return
    except queue.Full:
        pass
    try:
        messages.get_nowait()
    except queue.Empty:
        pass
    messages.put_nowait(message)


def _reliability(value: str) -> QosReliability:
    """Convert reliability CLI text to py_rosbridge QoS."""
    if value == "reliable":
        return QosReliability.RELIABLE
    return QosReliability.BEST_EFFORT


def _durability(value: str) -> QosDurability:
    """Convert durability CLI text to py_rosbridge QoS."""
    if value == "transient_local":
        return QosDurability.TRANSIENT_LOCAL
    return QosDurability.VOLATILE


if __name__ == "__main__":
    raise SystemExit(main())
