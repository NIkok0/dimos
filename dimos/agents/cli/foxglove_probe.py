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

"""Probe ros-foxglove-bridge topics over WebSocket.

Foxglove bridge exposes the same ROS graph as gRPC rosbridge, but over
``ws://host:8765`` with the ``foxglove.websocket.v1`` subprotocol.

Usage:
    python scripts/probe_foxglove_bridge.py --url ws://10.69.6.133:8765
    python scripts/probe_foxglove_bridge.py --url ws://10.69.6.133:8765 --list
    python scripts/probe_foxglove_bridge.py --url ws://10.69.6.133:8765 --probe-map
    python scripts/probe_foxglove_bridge.py --url ws://10.69.6.133:8765 --filter slam
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from py_rosbridge.codecs import nav_msgs

from dimos.agents.foxglove.client import FoxgloveBridgeClient
from dimos.agents.rosbridge.codecs.robot_interfaces import SlamStatusCodec
from dimos.core.global_config import global_config


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe ros-foxglove-bridge over WebSocket.")
    parser.add_argument(
        "--url",
        default=_default_foxglove_url(),
        help="Foxglove WebSocket URL (default: ws://<rosbridge host>:8765)",
    )
    parser.add_argument("--list", action="store_true", help="Print all advertised channels.")
    parser.add_argument(
        "--filter",
        default="",
        help="Only list channels whose topic contains this substring.",
    )
    parser.add_argument("--probe-map", action="store_true", help="Fetch one /map message summary.")
    parser.add_argument(
        "--probe-slam",
        action="store_true",
        help="Fetch one /slam_status message summary.",
    )
    parser.add_argument("--timeout-s", type=float, default=15.0, help="Subscribe timeout.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    client = FoxgloveBridgeClient(args.url)

    if args.list or (not args.probe_map and not args.probe_slam):
        channels = client.list_channels()
        if args.filter:
            channels = [ch for ch in channels if args.filter in ch.topic]
        print(
            json.dumps(
                {
                    "url": args.url,
                    "channel_count": len(channels),
                    "channels": [
                        {
                            "id": ch.id,
                            "topic": ch.topic,
                            "encoding": ch.encoding,
                            "schema": ch.schema_name,
                        }
                        for ch in channels
                    ],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        if not args.probe_map and not args.probe_slam:
            return 0

    if args.probe_map:
        grid = client.subscribe_once(
            global_config.ros_nav_map_topic,
            nav_msgs.OccupancyGridCodec,
            timeout_s=args.timeout_s,
        )
        print("MAP_STATE=" + json.dumps(_summarize_grid(grid), ensure_ascii=False, sort_keys=True))

    if args.probe_slam:
        slam = client.subscribe_once(
            global_config.ros_nav_slam_status_topic,
            SlamStatusCodec,
            timeout_s=args.timeout_s,
        )
        print("SLAM_STATE=" + json.dumps(_summarize_slam(slam), ensure_ascii=False, sort_keys=True))

    return 0


def _default_foxglove_url() -> str:
    target = global_config.rosbridge_grpc_address
    host = target.rsplit(":", 1)[0]
    return f"ws://{host}:8765"


def _summarize_grid(grid: Any) -> dict[str, Any]:
    info = grid.info
    origin = info.origin
    data = list(grid.data)
    total_cells = int(info.width) * int(info.height)
    return {
        "status": "available",
        "transport": "foxglove",
        "header": {"frame_id": grid.header.frame_id},
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


def _summarize_slam(slam: Any) -> dict[str, Any]:
    pose = slam.pose
    return {
        "status": "available",
        "transport": "foxglove",
        "current_map_name": str(slam.current_map_name),
        "slam_status": str(slam.status),
        "relocated": bool(slam.relocated),
        "pose": {
            "x": float(pose.position.x),
            "y": float(pose.position.y),
            "z": float(pose.position.z),
        },
    }


def _count_occupancy(data: Sequence[int]) -> dict[str, int]:
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


if __name__ == "__main__":
    raise SystemExit(main())
