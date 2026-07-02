#!/usr/bin/env python3
"""Visualize OccupancyGrid from rosbridge or file.

Default style matches the robot web UI: grey unknown, white free, black walls,
blue robot marker with heading arrow.

Usage:
    # Prefer dimos CLI:
    dimos nav map --transport foxglove \\
        --direction backward --distance-units 2
    # (default save: output/goal_backward_2.png; --live is optional, on by default)

    # Live from robot (web-style map + robot pose from /slam_status)
    python scripts/visualize_occupancy_grid.py --live --target 10.69.6.133:9091
    python scripts/visualize_occupancy_grid.py --live --transport foxglove --target ws://10.69.6.133:8765

    # Save to file
    python scripts/visualize_occupancy_grid.py --live --target 10.69.6.133:9091 --save map.png

    # Debug dual-panel view (array index + world coords)
    python scripts/visualize_occupancy_grid.py --live --style debug --save debug.png

    # From saved JSON
    python scripts/visualize_occupancy_grid.py --file map_data.json

Environment Variables:
    ROSBRIDGE_MAX_RECEIVE_MB: Default gRPC max message size in MB (default: 64)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from dimos.agents.rosbridge.navigation.client import planar_yaw_from_slam_message
    from dimos.core.global_config import global_config
except ImportError:
    planar_yaw_from_slam_message = None  # type: ignore[assignment,misc]
    global_config = None

try:
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Polygon
except ImportError:
    print("Error: matplotlib and numpy required")
    print("Install: pip install matplotlib numpy")
    sys.exit(1)

# Web UI palette (grey unknown / white free / black occupied)
COLOR_UNKNOWN = (189, 189, 189)
COLOR_FREE = (255, 255, 255)
COLOR_OCCUPIED = (0, 0, 0)
COLOR_ROBOT = "#4285F4"
COLOR_FIG_BG = "#BDBDBD"
COLOR_GOAL = "#43A047"
COLOR_MOVE_ARROW = "#E53935"
DEFAULT_NAV_OUTPUT_DIR = Path("output")


def _default_live_target(transport: str) -> str:
    if global_config is None:
        return "10.69.6.133:9091" if transport == "grpc" else "ws://10.69.6.133:8765"
    if transport == "foxglove":
        host = global_config.rosbridge_grpc_address.rsplit(":", 1)[0]
        return f"ws://{host}:8765"
    return global_config.rosbridge_grpc_address


def _default_foxglove_url() -> str:
    return _default_live_target("foxglove")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualize OccupancyGrid")

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--live", action="store_true", help="Subscribe via rosbridge")
    input_group.add_argument("--file", type=Path, help="Load from JSON file")

    parser.add_argument(
        "--transport",
        choices=("grpc", "foxglove"),
        default="grpc",
        help="Live transport: grpc=py_rosbridge, foxglove=ros-foxglove-bridge WebSocket",
    )
    parser.add_argument(
        "--target",
        default=_default_live_target("grpc"),
        help="rosbridge gRPC target or foxglove ws:// URL",
    )
    parser.add_argument("--topic", default="/map", help="Map topic name")
    parser.add_argument("--topic-type", default="nav_msgs/msg/OccupancyGrid", help="Topic type")
    parser.add_argument(
        "--slam-topic",
        default=None,
        help="SLAM status topic (default from GlobalConfig or /slam_status)",
    )
    parser.add_argument(
        "--slam-topic-type",
        default=None,
        help="SLAM status type (default from GlobalConfig)",
    )
    parser.add_argument("--timeout-s", type=float, default=15.0, help="Connection timeout")
    parser.add_argument(
        "--max-receive-mb",
        type=int,
        default=None,
        help="Max gRPC message size in MB (default from ROSBRIDGE_MAX_RECEIVE_MB or 64)",
    )

    parser.add_argument(
        "--style",
        choices=("web", "debug"),
        default="web",
        help="web = single map like robot web UI; debug = dual-panel diagnostics",
    )
    parser.add_argument(
        "--show-robot",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Overlay robot pose (default: on for --live, off for --file)",
    )
    parser.add_argument("--map-name", default="", help="Map title label (auto from SLAM if empty)")
    parser.add_argument(
        "--save",
        type=Path,
        default=None,
        help=f"Save PNG (default: {DEFAULT_NAV_OUTPUT_DIR}/map.png or goal_<dir>_<units>.png)",
    )
    parser.add_argument("--dpi", type=int, default=150, help="Output DPI")
    parser.add_argument("--verbose", action="store_true", help="Print subscription debug logs")
    parser.add_argument(
        "--direction",
        choices=("forward", "backward", "left", "right"),
        default=None,
        help="Overlay relative-move goal (body frame); requires live SLAM pose",
    )
    parser.add_argument(
        "--distance-units",
        type=float,
        default=2.0,
        help="Relative move distance in semantic units (1 unit = 5 cm) when --direction is set",
    )

    return parser.parse_args(argv)


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message)


def load_from_file(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _grid_bytes_to_list(data_bytes: Any) -> list[int]:
    if isinstance(data_bytes, (bytes, bytearray)):
        return [b - 256 if b > 127 else b for b in data_bytes]
    return list(data_bytes)


def _default_slam_topic() -> str:
    if global_config is not None:
        return global_config.ros_nav_slam_status_topic
    return "/slam_status"


def _default_slam_topic_type() -> str:
    if global_config is not None:
        return global_config.ros_nav_slam_status_topic_type
    return "robot_interfaces/msg/SlamStatus"


def default_nav_save_path(
    *,
    direction: str | None,
    distance_units: float,
    style: str,
) -> Path:
    """Return the default PNG path under ``output/`` for nav map debug."""
    if direction is not None:
        units_label = (
            str(int(distance_units))
            if float(distance_units).is_integer()
            else str(distance_units).replace(".", "_")
        )
        return DEFAULT_NAV_OUTPUT_DIR / f"goal_{direction}_{units_label}.png"
    if style == "debug":
        return DEFAULT_NAV_OUTPUT_DIR / "map_debug.png"
    return DEFAULT_NAV_OUTPUT_DIR / "map.png"


def resolve_nav_save_path(
    save: Path | None,
    *,
    direction: str | None,
    distance_units: float,
    style: str,
) -> Path:
    """Use explicit ``--save`` or the project ``output/`` default."""
    return save if save is not None else default_nav_save_path(
        direction=direction,
        distance_units=distance_units,
        style=style,
    )


def _default_max_receive_mb(max_receive_mb: int | None) -> int:
    if max_receive_mb is not None:
        return max_receive_mb
    if global_config is not None:
        return global_config.rosbridge_max_receive_mb
    return 64


def load_from_foxglove(
    url: str,
    topic: str,
    *,
    timeout_s: float,
    slam_topic: str,
    fetch_robot_pose: bool,
    verbose: bool = False,
) -> dict[str, Any]:
    from py_rosbridge.codecs import nav_msgs

    from dimos.agents.foxglove.client import FoxgloveBridgeClient
    from dimos.agents.rosbridge.codecs.robot_interfaces import SlamStatusCodec

    _log(verbose, f"Connecting to foxglove bridge {url}...")
    client = FoxgloveBridgeClient(url)

    subscriptions: list[tuple[str, type[Any]]] = [(topic, nav_msgs.OccupancyGridCodec)]
    if fetch_robot_pose:
        subscriptions.append((slam_topic, SlamStatusCodec))

    messages = client.subscribe_many(subscriptions, timeout_s=timeout_s)
    grid_msg = messages[topic]

    robot_pose: dict[str, float] | None = None
    map_name = ""
    if fetch_robot_pose:
        slam_msg = messages.get(slam_topic)
        if slam_msg is not None:
            pose = slam_msg.pose
            quaternion_yaw = _yaw_from_pose(pose)
            angle_yaw = planar_yaw_from_slam_message(slam_msg)
            robot_pose = {
                "x": float(pose.position.x),
                "y": float(pose.position.y),
                "yaw": angle_yaw,
                "quaternion_yaw": quaternion_yaw,
                "angle_bearing_rad": float(getattr(slam_msg, "angle", angle_yaw)),
            }
            map_name = str(getattr(slam_msg, "current_map_name", "") or "")
            _log(verbose, f"SLAM pose: {robot_pose}, map={map_name!r}")
        else:
            _log(verbose, "No /slam_status received; robot marker skipped")

    info = grid_msg.info
    origin = info.origin
    grid_data = _grid_bytes_to_list(grid_msg.data)

    return {
        "header": {"frame_id": grid_msg.header.frame_id},
        "info": {
            "resolution": float(info.resolution),
            "width": int(info.width),
            "height": int(info.height),
            "origin": {
                "x": float(origin.position.x),
                "y": float(origin.position.y),
                "z": float(origin.position.z),
            },
        },
        "data": grid_data,
        "robot_pose": robot_pose,
        "map_name": map_name,
    }


def load_from_rosbridge(
    target: str,
    topic: str,
    topic_type: str,
    timeout_s: float,
    *,
    max_receive_mb: int | None = None,
    slam_topic: str,
    slam_topic_type: str,
    fetch_robot_pose: bool,
    verbose: bool = False,
) -> dict[str, Any]:
    import queue
    import threading
    import time

    try:
        from py_rosbridge import RosbridgeClient
        from py_rosbridge.codecs import nav_msgs

        from dimos.agents.rosbridge.codecs.robot_interfaces import SlamStatusCodec
        from dimos.agents.rosbridge.qos_profiles import MAP_TOPIC_QOS, SLAM_STATUS_TOPIC_QOS
    except ImportError:
        print("Error: py_rosbridge not available")
        print("Make sure PYTHONPATH includes py_rosbridge and dimos")
        sys.exit(1)

    map_messages: queue.Queue[Any] = queue.Queue(maxsize=1)
    slam_messages: queue.Queue[Any] = queue.Queue(maxsize=1)
    map_subscribed = threading.Event()

    def on_map_message(event: Any) -> None:
        try:
            map_messages.put_nowait(event.message)
        except queue.Full:
            try:
                map_messages.get_nowait()
            except queue.Empty:
                pass
            map_messages.put_nowait(event.message)

    def on_slam_message(event: Any) -> None:
        try:
            slam_messages.put_nowait(event.message)
        except queue.Full:
            try:
                slam_messages.get_nowait()
            except queue.Empty:
                pass
            slam_messages.put_nowait(event.message)

    def on_frame(frame: Any) -> None:
        kind = frame.WhichOneof("frame")
        if kind == "status" and "Subscribed" in frame.status.message and not map_subscribed.is_set():
            map_subscribed.set()

    max_mb = _default_max_receive_mb(max_receive_mb)
    _log(verbose, f"Connecting to {target} (max receive {max_mb} MB)...")

    with RosbridgeClient(
        target,
        ready_timeout=timeout_s,
        max_receive_message_length=max_mb * 1024 * 1024,
    ) as client:
        client.add_frame_callback(on_frame)

        if fetch_robot_pose:
            client.subscribe(
                slam_topic,
                slam_topic_type,
                on_slam_message,
                codec=SlamStatusCodec,
                qos=SLAM_STATUS_TOPIC_QOS,
            )

        client.subscribe(
            topic,
            topic_type,
            on_map_message,
            codec=nav_msgs.OccupancyGridCodec,
            qos=MAP_TOPIC_QOS,
        )

        if map_subscribed.wait(timeout=3.0):
            time.sleep(1.5)
        else:
            _log(verbose, "Warning: map subscription not confirmed")

        grid_msg = None
        for attempt in range(10):
            try:
                grid_msg = map_messages.get(timeout=1.0)
                _log(verbose, f"Map received on attempt {attempt + 1}")
                break
            except queue.Empty:
                _log(verbose, f"Waiting for map... attempt {attempt + 1}/10")

        if grid_msg is None:
            print("Timeout waiting for /map")
            sys.exit(1)

        robot_pose: dict[str, float] | None = None
        map_name = ""
        if fetch_robot_pose:
            try:
                slam_msg = slam_messages.get(timeout=min(timeout_s, 5.0))
                pose = slam_msg.pose
                quaternion_yaw = _yaw_from_pose(pose)
                angle_yaw = (
                    planar_yaw_from_slam_message(slam_msg)
                    if planar_yaw_from_slam_message is not None
                    else float(getattr(slam_msg, "angle", quaternion_yaw))
                )
                robot_pose = {
                    "x": float(pose.position.x),
                    "y": float(pose.position.y),
                    "yaw": angle_yaw,
                    "quaternion_yaw": quaternion_yaw,
                    "angle_bearing_rad": float(getattr(slam_msg, "angle", angle_yaw)),
                }
                map_name = str(getattr(slam_msg, "current_map_name", "") or "")
                _log(verbose, f"SLAM pose: {robot_pose}, map={map_name!r}")
            except queue.Empty:
                _log(verbose, "No /slam_status received; robot marker skipped")

    info = grid_msg.info
    origin = info.origin
    grid_data = _grid_bytes_to_list(grid_msg.data)

    return {
        "header": {"frame_id": grid_msg.header.frame_id},
        "info": {
            "resolution": float(info.resolution),
            "width": int(info.width),
            "height": int(info.height),
            "origin": {
                "x": float(origin.position.x),
                "y": float(origin.position.y),
                "z": float(origin.position.z),
            },
        },
        "data": grid_data,
        "robot_pose": robot_pose,
        "map_name": map_name,
    }


def _yaw_from_pose(pose: Any) -> float:
    q = pose.orientation
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


def create_web_colormap(grid: np.ndarray) -> np.ndarray:
    """Grey unknown / white free / black occupied — matches robot web UI."""
    rgb = np.empty((*grid.shape, 3), dtype=np.uint8)
    rgb[:] = COLOR_UNKNOWN

    free_mask = grid == 0
    occupied_mask = grid >= 50
    partial_mask = (grid > 0) & (grid < 50)

    rgb[free_mask] = COLOR_FREE
    rgb[occupied_mask] = COLOR_OCCUPIED

    if np.any(partial_mask):
        values = grid[partial_mask].astype(np.float32)
        gray = (255.0 - values * 2.55).astype(np.uint8)
        rgb[partial_mask, 0] = gray
        rgb[partial_mask, 1] = gray
        rgb[partial_mask, 2] = gray

    return rgb


def create_occupancy_colormap(grid: np.ndarray) -> np.ndarray:
    """Legacy debug palette."""
    return create_web_colormap(grid)


def _world_extent(
    width: int,
    height: int,
    resolution: float,
    origin_x: float,
    origin_y: float,
) -> list[float]:
    world_w = width * resolution
    world_h = height * resolution
    return [origin_x, origin_x + world_w, origin_y, origin_y + world_h]


def display_yaw_from_robot_pose(robot_pose: dict[str, Any]) -> float:
    """Map icon heading for PNG export (quaternion yaw, matches Web UI / hardware)."""
    quat_yaw = robot_pose.get("quaternion_yaw")
    if quat_yaw is not None:
        return float(quat_yaw)
    return float(robot_pose["yaw"])


def robot_heading_triangle_vertices(
    x: float,
    y: float,
    display_yaw: float,
    resolution: float,
) -> list[tuple[float, float]]:
    """Return tip-left-right vertices for the navigation-style pose triangle."""
    radius = max(resolution * 3.0, 0.15)
    tip_len = max(resolution * 5.0, 0.35)
    base_back = radius * 0.35
    half_width = radius * 0.8

    tip = (x + math.cos(display_yaw) * tip_len, y + math.sin(display_yaw) * tip_len)
    base_cx = x - math.cos(display_yaw) * base_back
    base_cy = y - math.sin(display_yaw) * base_back
    perp_x = -math.sin(display_yaw) * half_width
    perp_y = math.cos(display_yaw) * half_width
    left = (base_cx + perp_x, base_cy + perp_y)
    right = (base_cx - perp_x, base_cy - perp_y)
    return [tip, left, right]


def print_robot_yaw_diagnostics(robot_pose: dict[str, Any]) -> None:
    """Log body (quat) vs nav (angle) yaw for map PNG verification."""
    body_deg = math.degrees(display_yaw_from_robot_pose(robot_pose))
    nav_deg = math.degrees(float(robot_pose["yaw"]))
    print(f"  Goal body yaw (quat): {body_deg:.1f}°  Nav yaw (angle): {nav_deg:.1f}°")


def draw_robot_marker(ax: Any, x: float, y: float, display_yaw: float, resolution: float) -> None:
    """Blue circle + blue heading triangle (display/body yaw, matches goal overlay)."""
    radius = max(resolution * 3.0, 0.15)

    ax.add_patch(
        Circle(
            (x, y),
            radius=radius,
            facecolor=COLOR_ROBOT,
            edgecolor=COLOR_ROBOT,
            linewidth=0,
            zorder=10,
        )
    )
    triangle = robot_heading_triangle_vertices(x, y, display_yaw, resolution)
    ax.add_patch(
        Polygon(
            triangle,
            closed=True,
            facecolor=COLOR_ROBOT,
            edgecolor="white",
            linewidth=0.8,
            zorder=11,
        )
    )


def slam_state_from_robot_pose(robot_pose: dict[str, Any]) -> Any:
    """Build SlamState for map goal overlay (same body-yaw logic as move_relative)."""
    from dimos.agents.navigation_contracts import SlamState

    raw: dict[str, Any] = {}
    quat_yaw = robot_pose.get("quaternion_yaw")
    if quat_yaw is not None:
        raw["quaternion_yaw"] = float(quat_yaw)
    return SlamState(
        status="located",
        pose={
            "frame_id": "map",
            "x": float(robot_pose.get("x", 0.0)),
            "y": float(robot_pose.get("y", 0.0)),
            "yaw": float(robot_pose.get("yaw", 0.0)),
        },
        raw=raw,
    )


def compute_relative_goal(
    data: dict[str, Any],
    *,
    direction: str,
    distance_units: float,
) -> Any:
    """Return WorkspacePose goal or NavigationResult failure from live map data."""
    from dimos.agents.ros_topic_navigation_adapter import _relative_target_from_slam_state

    robot = data.get("robot_pose")
    if robot is None:
        raise ValueError("no robot pose from /slam_status")
    slam_state = slam_state_from_robot_pose(robot)
    return _relative_target_from_slam_state(
        slam_state,
        direction=direction,
        distance_units=distance_units,
    )


def draw_goal_marker(
    ax: Any,
    x: float,
    y: float,
    *,
    resolution: float,
    color: str = COLOR_GOAL,
    label: str = "goal",
) -> None:
    radius = max(resolution * 2.5, 0.12)
    ax.add_patch(
        Circle(
            (x, y),
            radius=radius,
            facecolor=color,
            edgecolor="white",
            linewidth=1.5,
            zorder=12,
        )
    )
    ax.text(
        x,
        y + radius * 2.2,
        label,
        ha="center",
        va="bottom",
        fontsize=9,
        color=color,
        fontweight="bold",
        zorder=13,
    )


def draw_move_arrow(
    ax: Any,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    resolution: float,
    color: str = COLOR_MOVE_ARROW,
    linestyle: str = "--",
) -> None:
    dx = x1 - x0
    dy = y1 - y0
    if math.hypot(dx, dy) < 1e-6:
        return
    head = max(resolution * 4.0, 0.25)
    ax.annotate(
        "",
        xy=(x1, y1),
        xytext=(x0, y0),
        arrowprops={
            "arrowstyle": "->",
            "color": color,
            "linewidth": 2.0,
            "linestyle": linestyle,
            "shrinkA": 0,
            "shrinkB": 0,
            "mutation_scale": head * 8,
        },
        zorder=11,
    )


def _print_relative_goal_summary(
    robot: dict[str, Any],
    target: Any,
    *,
    direction: str,
    distance_units: float,
) -> None:
    rx, ry = float(robot["x"]), float(robot["y"])
    nav_yaw = float(robot["yaw"])
    body_yaw = display_yaw_from_robot_pose(robot)
    gx, gy = float(target.x), float(target.y)
    distance_m = distance_units * 0.05
    print(
        f"  relative {direction} × {distance_units} units ({distance_m:.2f} m)\n"
        f"  robot: x={rx:.3f} y={ry:.3f} body_yaw_deg={math.degrees(body_yaw):.1f}\n"
        f"  goal:  x={gx:.3f} y={gy:.3f} yaw_deg={math.degrees(float(target.yaw)):.1f}\n"
        f"  delta: dx={gx - rx:.3f} dy={gy - ry:.3f} dist_m={distance_m:.3f}\n"
        f"  Goal body yaw (quat): {math.degrees(body_yaw):.1f}°  "
        f"Nav yaw (angle): {math.degrees(nav_yaw):.1f}°"
    )


def visualize_web_style(
    data: dict[str, Any],
    *,
    show_robot: bool,
    map_name: str,
    save_path: Path | None,
    dpi: int,
    relative_direction: str | None = None,
    relative_distance_units: float = 2.0,
) -> None:
    info = data["info"]
    width = info["width"]
    height = info["height"]
    resolution = info["resolution"]
    origin_x = info["origin"]["x"]
    origin_y = info["origin"]["y"]

    grid = np.array(data["data"], dtype=np.int8).reshape((height, width))
    rgb = create_web_colormap(grid)
    extent = _world_extent(width, height, resolution, origin_x, origin_y)

    fig, ax = plt.subplots(figsize=(10, 10), facecolor=COLOR_FIG_BG)
    ax.set_facecolor(COLOR_FIG_BG)
    # ROS row 0 = south-west (origin_y); imshow origin="lower" maps row 0 to min-y — no flip.
    ax.imshow(rgb, extent=extent, origin="lower", interpolation="nearest")
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    robot_pose = data.get("robot_pose")
    if show_robot and robot_pose is not None:
        draw_robot_marker(
            ax,
            robot_pose["x"],
            robot_pose["y"],
            display_yaw_from_robot_pose(robot_pose),
            resolution,
        )

    overlay_title = ""
    if relative_direction is not None:
        target = compute_relative_goal(
            data,
            direction=relative_direction,
            distance_units=relative_distance_units,
        )
        if hasattr(target, "status"):
            raise ValueError(getattr(target, "message", str(target)))
        assert robot_pose is not None
        rx, ry = float(robot_pose["x"]), float(robot_pose["y"])
        gx, gy = float(target.x), float(target.y)
        draw_move_arrow(ax, rx, ry, gx, gy, resolution=resolution)
        draw_goal_marker(ax, gx, gy, resolution=resolution)
        distance_m = relative_distance_units * 0.05
        body_yaw = display_yaw_from_robot_pose(robot_pose)
        nav_yaw = float(robot_pose["yaw"])
        nav_note = ""
        if robot_pose.get("quaternion_yaw") is not None:
            nav_note = f", nav={math.degrees(nav_yaw):.1f}°"
        overlay_title = (
            f"relative {relative_direction} × {relative_distance_units} units ({distance_m:.2f} m)\n"
            f"pose=({rx:.2f}, {ry:.2f}, body_yaw={math.degrees(body_yaw):.1f}°{nav_note}) → "
            f"goal=({gx:.2f}, {gy:.2f}, yaw={math.degrees(float(target.yaw)):.1f}°)"
        )
        _print_relative_goal_summary(
            robot_pose,
            target,
            direction=relative_direction,
            distance_units=relative_distance_units,
        )

    title = map_name or data.get("map_name") or ""
    if overlay_title:
        ax.text(
            0.02,
            0.98,
            overlay_title,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10,
            color="#212121",
            bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "edgecolor": "#CCCCCC", "alpha": 0.92},
            zorder=20,
        )
    elif title:
        ax.text(
            0.98,
            0.98,
            f"当前地图：{title}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=12,
            color="#333333",
            bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "edgecolor": "#CCCCCC", "alpha": 0.92},
            zorder=20,
        )

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=dpi, bbox_inches="tight", pad_inches=0.05, facecolor=fig.get_facecolor())
        print(f"Saved to {save_path}")
    else:
        plt.show()


def visualize_debug_style(
    data: dict[str, Any],
    *,
    show_robot: bool,
    save_path: Path | None,
    dpi: int,
) -> None:
    info = data["info"]
    width = info["width"]
    height = info["height"]
    resolution = info["resolution"]
    origin_x = info["origin"]["x"]
    origin_y = info["origin"]["y"]
    frame_id = data["header"]["frame_id"]

    grid = np.array(data["data"], dtype=np.int8).reshape((height, width))

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))

    ax_orig = axes[0]
    ax_orig.set_title(f"Array Index View (row 0 at top)\n{width}x{height}, res={resolution}m")
    ax_orig.imshow(create_web_colormap(grid), origin="upper", interpolation="nearest")
    ax_orig.set_xlabel("Column (cell)")
    ax_orig.set_ylabel("Row (cell)")

    ax_flip = axes[1]
    extent = _world_extent(width, height, resolution, origin_x, origin_y)
    ax_flip.set_title(f"World Coordinates (origin=lower, no flip)\nframe: {frame_id}")
    ax_flip.imshow(create_web_colormap(grid), extent=extent, origin="lower", interpolation="nearest")
    ax_flip.grid(True, alpha=0.3, linestyle="-", linewidth=0.5)

    if show_robot and data.get("robot_pose") is not None:
        pose = data["robot_pose"]
        draw_robot_marker(
            ax_flip,
            pose["x"],
            pose["y"],
            display_yaw_from_robot_pose(pose),
            resolution,
        )

    ax_flip.plot(origin_x, origin_y, "b*", markersize=12, label=f"Origin ({origin_x:.1f}, {origin_y:.1f})")
    ax_flip.legend(loc="lower right")
    ax_flip.set_xlabel("X (m)")
    ax_flip.set_ylabel("Y (m)")

    unknown = int(np.sum(grid < 0))
    free = int(np.sum(grid == 0))
    occupied = int(np.sum(grid >= 50))
    partial = int(np.sum((grid > 0) & (grid < 50)))
    total = width * height
    world_w = width * resolution
    world_h = height * resolution
    stats_text = (
        f"Grid: {width}x{height} = {total:,}\n"
        f"Unknown: {unknown:,} ({100 * unknown / total:.1f}%)\n"
        f"Free: {free:,} ({100 * free / total:.1f}%)\n"
        f"Occupied: {occupied:,} ({100 * occupied / total:.1f}%)\n"
        f"Partial: {partial:,} ({100 * partial / total:.1f}%)\n"
        f"World: {world_w:.2f}m x {world_h:.2f}m"
    )
    ax_flip.text(
        0.02,
        0.98,
        stats_text,
        transform=ax_flip.transAxes,
        fontsize=10,
        verticalalignment="top",
        fontfamily="monospace",
        bbox={"boxstyle": "round", "facecolor": "wheat", "alpha": 0.8},
    )

    plt.tight_layout()
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=dpi, bbox_inches="tight")
        print(f"Saved to {save_path}")
    else:
        plt.show()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    show_robot = args.show_robot if args.show_robot is not None else args.live
    if args.direction is not None:
        show_robot = True
        if args.style == "debug":
            print("Note: relative goal overlay uses web style (single map panel)", file=sys.stderr)
            args.style = "web"

    if args.file:
        print(f"Loading from {args.file}")
        data = load_from_file(args.file)
    else:
        if args.transport == "foxglove":
            foxglove_url = args.target
            if not foxglove_url.startswith("ws"):
                host = foxglove_url.rsplit(":", 1)[0]
                foxglove_url = f"ws://{host}:8765"
            data = load_from_foxglove(
                foxglove_url,
                args.topic,
                timeout_s=args.timeout_s,
                slam_topic=args.slam_topic or _default_slam_topic(),
                fetch_robot_pose=show_robot,
                verbose=args.verbose,
            )
        else:
            data = load_from_rosbridge(
                args.target,
                args.topic,
                args.topic_type,
                args.timeout_s,
                max_receive_mb=args.max_receive_mb,
                slam_topic=args.slam_topic or _default_slam_topic(),
                slam_topic_type=args.slam_topic_type or _default_slam_topic_type(),
                fetch_robot_pose=show_robot,
                verbose=args.verbose,
            )

    info = data["info"]
    print("\nMap received:")
    print(f"  Frame: {data['header']['frame_id']}")
    print(f"  Size: {info['width']}x{info['height']} cells")
    print(f"  Resolution: {info['resolution']} m/cell")
    print(f"  Origin: ({info['origin']['x']}, {info['origin']['y']})")
    print(f"  Data length: {len(data['data'])}")
    if data.get("robot_pose"):
        p = data["robot_pose"]
        print(f"  Robot: x={p['x']:.2f}, y={p['y']:.2f}, yaw={math.degrees(p['yaw']):.1f}°")
        if args.direction is not None or args.verbose:
            print_robot_yaw_diagnostics(p)
    if data.get("map_name"):
        print(f"  Map name: {data['map_name']}")

    map_name = args.map_name or data.get("map_name", "")

    if args.direction is not None and data.get("robot_pose") is None:
        print("Error: --direction requires robot pose from /slam_status", file=sys.stderr)
        return 1

    save_path = resolve_nav_save_path(
        args.save,
        direction=args.direction,
        distance_units=args.distance_units,
        style=args.style,
    )

    try:
        if args.style == "web":
            visualize_web_style(
                data,
                show_robot=show_robot,
                map_name=map_name,
                save_path=save_path,
                dpi=args.dpi,
                relative_direction=args.direction,
                relative_distance_units=args.distance_units,
            )
        else:
            if args.direction is not None:
                print("Error: --direction overlay only supports --style web", file=sys.stderr)
                return 1
            visualize_debug_style(
                data,
                show_robot=show_robot,
                save_path=save_path,
                dpi=args.dpi,
            )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
