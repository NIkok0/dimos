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

"""Probe /map through py_rosbridge without touching other navigation topics.

This script validates the OccupancyGrid transport used by relative navigation
safety checks. It subscribes only to ``/map`` with the real robot's reliable and
transient-local QoS, then prints the map frame, resolution, dimensions, origin,
and occupancy counts without sending any motion command.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
from collections.abc import Sequence
from typing import Any

import grpc

from py_rosbridge import RosbridgeClient
from py_rosbridge.codecs import nav_msgs

from dimos.agents.rosbridge.qos_profiles import MAP_TOPIC_QOS
from dimos.core.global_config import global_config


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse gRPC target, map topic, and collection options."""
    parser = argparse.ArgumentParser(description="Probe /map via rosbridge gRPC.")
    parser.add_argument("--target", default=global_config.rosbridge_grpc_address)
    parser.add_argument("--topic", default=global_config.ros_nav_map_topic)
    parser.add_argument("--topic-type", default=global_config.ros_nav_map_topic_type)
    parser.add_argument("--ready-timeout-s", type=float, default=global_config.rosbridge_ready_timeout_s)
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=global_config.ros_nav_localization_timeout_s,
    )
    parser.add_argument("--watch", action="store_true", help="Keep printing maps until interrupted.")
    parser.add_argument("--max-messages", type=int, default=1, help="Messages to print when not using --watch.")
    parser.add_argument(
        "--max-receive-mb",
        type=int,
        default=64,
        help="gRPC max receive message size in MiB for large OccupancyGrid messages.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Subscribe to OccupancyGrid and print one or more decoded summaries."""
    args = parse_args(argv)
    messages: queue.Queue[Any] = queue.Queue(maxsize=1)
    frame_count = 0

    def on_message(event: Any) -> None:
        _replace_latest(messages, event.message)

    def on_disconnect(exc: BaseException) -> None:
        print(f"READER_ERROR={type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

    def on_frame(frame: Any) -> None:
        nonlocal frame_count
        frame_count += 1
        kind = frame.WhichOneof("frame")
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

    print(
        json.dumps(
            {
                "grpc_target": args.target,
                "map_topic": args.topic,
                "map_topic_type": args.topic_type,
                "timeout_s": args.timeout_s,
                "max_receive_mb": args.max_receive_mb,
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
                codec=nav_msgs.OccupancyGridCodec,
                qos=MAP_TOPIC_QOS,
            )
            printed = 0
            while True:
                try:
                    grid = _latest_message(messages, timeout_s=args.timeout_s)
                except queue.Empty:
                    print(
                        "MAP_STATE="
                        + json.dumps(
                            {
                                "status": "unavailable",
                                "reason": "occupancy_grid_timeout",
                                "topic": args.topic,
                                "timeout_s": args.timeout_s,
                                "raw_frames_seen": frame_count,
                                "client_connected": client.is_connected,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                    return 2
                print("MAP_STATE=" + json.dumps(_summarize_grid(grid), ensure_ascii=False, sort_keys=True), flush=True)
                printed += 1
                if not args.watch and printed >= max(1, args.max_messages):
                    return 0
    except grpc.FutureTimeoutError:
        print(
            "MAP_STATE="
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


def _summarize_grid(grid: Any) -> dict[str, Any]:
    """Convert a full OccupancyGrid into small debug metadata."""
    info = grid.info
    origin = info.origin
    data = _as_sequence(grid.data)
    total_cells = int(info.width) * int(info.height)
    return {
        "status": "available",
        "header": {
            "frame_id": grid.header.frame_id,
            "stamp": {
                "sec": int(grid.header.stamp.sec),
                "nanosec": int(grid.header.stamp.nanosec),
            },
        },
        "info": {
            "resolution": float(info.resolution),
            "width": int(info.width),
            "height": int(info.height),
            "total_cells": total_cells,
            "data_len": len(data),
            "origin": {
                "x": float(origin.position.x),
                "y": float(origin.position.y),
                "z": float(origin.position.z),
            },
        },
        "occupancy": _count_occupancy(data),
    }


def _as_sequence(data: Any) -> Sequence[int]:
    """Normalize py_rosbridge int8 array storage to a simple integer sequence."""
    if isinstance(data, bytes | bytearray):
        return [value - 256 if value > 127 else value for value in data]
    return list(data)


def _count_occupancy(data: Sequence[int]) -> dict[str, int]:
    """Count common OccupancyGrid value classes used by the safety gate."""
    unknown = 0
    free = 0
    occupied = 0
    other = 0
    for value in data:
        if value < 0:
            unknown += 1
        elif value == 0:
            free += 1
        elif value >= 50:
            occupied += 1
        else:
            other += 1
    return {
        "unknown": unknown,
        "free": free,
        "occupied_ge_50": occupied,
        "other_1_to_49": other,
    }


def _replace_latest(messages: queue.Queue[Any], message: Any) -> None:
    """Keep only the freshest map message for predictable probe output."""
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


def _latest_message(messages: queue.Queue[Any], *, timeout_s: float) -> Any:
    """Wait for one message and drain stale queued values."""
    latest = messages.get(timeout=timeout_s)
    while True:
        try:
            latest = messages.get_nowait()
        except queue.Empty:
            return latest


if __name__ == "__main__":
    raise SystemExit(main())
