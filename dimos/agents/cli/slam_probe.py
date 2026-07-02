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

"""Probe /slam_status through py_rosbridge without touching other topics.

This script is a narrow real-robot diagnostic for the localization topic used
by Dax Agent navigation. It subscribes only to ``/slam_status``, decodes the
robot_interfaces message with DimOS codecs, and prints compact JSON so failures
can be separated from map and NavigateToPose action issues.
"""

from __future__ import annotations

import argparse
import json
import math
import queue
import sys
from collections.abc import Sequence
from typing import Any

import grpc

from py_rosbridge import RosbridgeClient
from py_rosbridge.client import Qos, QosDurability, QosHistory, QosReliability

from dimos.agents.rosbridge.codecs.robot_interfaces import SlamStatusCodec
from dimos.agents.rosbridge.navigation.client import planar_yaw_from_slam_message
from dimos.core.global_config import global_config


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse gRPC target, topic, and collection options."""
    parser = argparse.ArgumentParser(description="Probe /slam_status via rosbridge gRPC.")
    parser.add_argument("--target", default=global_config.rosbridge_grpc_address)
    parser.add_argument("--topic", default=global_config.ros_nav_slam_status_topic)
    parser.add_argument("--topic-type", default=global_config.ros_nav_slam_status_topic_type)
    parser.add_argument("--ready-timeout-s", type=float, default=global_config.rosbridge_ready_timeout_s)
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=global_config.ros_nav_localization_timeout_s,
    )
    parser.add_argument("--watch", action="store_true", help="Keep printing messages until interrupted.")
    parser.add_argument("--max-messages", type=int, default=1, help="Messages to print when not using --watch.")
    parser.add_argument(
        "--qos-reliability",
        choices=("best_effort", "reliable"),
        default="best_effort",
        help="SLAM subscription reliability to test.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Subscribe to SLAM status and print one or more decoded messages."""
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
                "slam_topic": args.topic,
                "slam_topic_type": args.topic_type,
                "timeout_s": args.timeout_s,
                "qos_reliability": args.qos_reliability,
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
            on_disconnect=on_disconnect,
        ) as client:
            client.add_frame_callback(on_frame)
            client.subscribe(
                args.topic,
                args.topic_type,
                on_message,
                codec=SlamStatusCodec,
                qos=Qos(
                    history=QosHistory.KEEP_LAST,
                    depth=1,
                    reliability=_qos_reliability(args.qos_reliability),
                    durability=QosDurability.VOLATILE,
                ),
            )
            printed = 0
            while True:
                try:
                    msg = _latest_message(messages, timeout_s=args.timeout_s)
                except queue.Empty:
                    print(
                        "SLAM_STATE="
                        + json.dumps(
                            {
                                "status": "unavailable",
                                "reason": "slam_status_timeout",
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
                print("SLAM_STATE=" + json.dumps(_summarize_slam(msg), ensure_ascii=False, sort_keys=True), flush=True)
                printed += 1
                if not args.watch and printed >= max(1, args.max_messages):
                    return 0
    except grpc.FutureTimeoutError:
        print(
            "SLAM_STATE="
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


def _summarize_slam(msg: Any) -> dict[str, Any]:
    """Convert a SlamStatus message into compact debug metadata."""
    pose = msg.pose
    quaternion_yaw = _yaw_from_quaternion(pose.orientation)
    angle_yaw = planar_yaw_from_slam_message(msg)
    return {
        "status": msg.status,
        "current_map_name": msg.current_map_name,
        "pose": {
            "frame_id": msg.header.frame_id or "map",
            "x": float(pose.position.x),
            "y": float(pose.position.y),
            "z": float(pose.position.z),
            "yaw": angle_yaw,
        },
        "raw": {
            "score": float(msg.score),
            "process": float(msg.process),
            "relocated": bool(msg.relocated),
            "angle": float(msg.angle),
            "quaternion_yaw": quaternion_yaw,
            "angle_minus_quaternion_yaw": angle_yaw - quaternion_yaw,
        },
    }


def _yaw_from_quaternion(quaternion: Any) -> float:
    """Extract planar yaw from a geometry_msgs quaternion."""
    siny_cosp = 2.0 * (
        float(quaternion.w) * float(quaternion.z)
        + float(quaternion.x) * float(quaternion.y)
    )
    cosy_cosp = 1.0 - 2.0 * (
        float(quaternion.y) * float(quaternion.y)
        + float(quaternion.z) * float(quaternion.z)
    )
    return math.atan2(siny_cosp, cosy_cosp)


def _qos_reliability(value: str) -> QosReliability:
    """Convert a CLI reliability string to a py_rosbridge QoS enum."""
    if value == "reliable":
        return QosReliability.RELIABLE
    return QosReliability.BEST_EFFORT


def _replace_latest(messages: queue.Queue[Any], message: Any) -> None:
    """Keep only the freshest topic message for predictable probe output."""
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
