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

"""``dimos nav`` — live navigation debug tools (SLAM, map, relative goals)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from dimos.core.global_config import global_config

app = typer.Typer(
    help="Navigation debug tools for live robot / rosbridge / foxglove",
    no_args_is_help=True,
)


def _exit_code(code: int) -> None:
    if code != 0:
        raise typer.Exit(code)


def _default_foxglove_url() -> str:
    host = global_config.rosbridge_grpc_address.rsplit(":", 1)[0]
    return f"ws://{host}:8765"


def _build_map_viz_argv(
    *,
    live: bool = True,
    file: Path | None = None,
    transport: Literal["grpc", "foxglove"] = "grpc",
    target: str = "",
    topic: str = "/map",
    topic_type: str = "nav_msgs/msg/OccupancyGrid",
    slam_topic: str = "",
    slam_topic_type: str = "",
    timeout_s: float = 15.0,
    max_receive_mb: int | None = None,
    style: Literal["web", "debug"] = "web",
    show_robot: bool | None = None,
    map_name: str = "",
    save: Path | None = None,
    dpi: int = 150,
    verbose: bool = False,
    direction: Literal["forward", "backward", "left", "right"] | None = None,
    distance_units: float = 2.0,
) -> list[str]:
    """Build argparse argv for ``map_viz.main`` (plain Python defaults for internal reuse)."""
    if file is not None and live:
        typer.echo("Note: --file ignores --live (loading from JSON)", err=True)
    if file is None and not live:
        typer.echo("Error: pass --live (default) or --file <json>", err=True)
        raise typer.Exit(1)

    argv: list[str] = []
    if file is not None:
        argv.extend(["--file", str(file)])
    elif live:
        argv.append("--live")
    if transport != "grpc":
        argv.extend(["--transport", transport])
    if target:
        argv.extend(["--target", target])
    if topic != "/map":
        argv.extend(["--topic", topic])
    if topic_type != "nav_msgs/msg/OccupancyGrid":
        argv.extend(["--topic-type", topic_type])
    if slam_topic:
        argv.extend(["--slam-topic", slam_topic])
    if slam_topic_type:
        argv.extend(["--slam-topic-type", slam_topic_type])
    if timeout_s != 15.0:
        argv.extend(["--timeout-s", str(timeout_s)])
    if max_receive_mb is not None:
        argv.extend(["--max-receive-mb", str(max_receive_mb)])
    if style != "web":
        argv.extend(["--style", style])
    if show_robot is True:
        argv.append("--show-robot")
    elif show_robot is False:
        argv.append("--no-show-robot")
    if map_name:
        argv.extend(["--map-name", map_name])
    if save is not None:
        argv.extend(["--save", str(save)])
    if dpi != 150:
        argv.extend(["--dpi", str(dpi)])
    if verbose:
        argv.append("--verbose")
    if direction is not None:
        argv.extend(["--direction", direction])
    if distance_units != 2.0:
        argv.extend(["--distance-units", str(distance_units)])
    return argv


def _run_map_viz(**kwargs: object) -> None:
    from dimos.agents.cli import map_viz

    _exit_code(map_viz.main(_build_map_viz_argv(**kwargs)))  # type: ignore[arg-type]


@app.command("slam")
def nav_slam(
    target: str = typer.Option(
        "",
        "--target",
        help="rosbridge gRPC host:port (default: GlobalConfig.rosbridge_grpc_address)",
    ),
    topic: str = typer.Option("", "--topic", help="SLAM topic (default: /slam_status)"),
    topic_type: str = typer.Option("", "--topic-type", help="SLAM message type"),
    ready_timeout_s: float = typer.Option(
        0.0, "--ready-timeout-s", help="gRPC channel ready timeout (0 = config default)"
    ),
    timeout_s: float = typer.Option(
        0.0, "--timeout-s", help="Message wait timeout (0 = config default)"
    ),
    watch: bool = typer.Option(False, "--watch", help="Keep printing until interrupted"),
    max_messages: int = typer.Option(1, "--max-messages", help="Messages when not using --watch"),
    qos_reliability: Literal["best_effort", "reliable"] = typer.Option(
        "best_effort", "--qos-reliability", help="Subscription reliability"
    ),
) -> None:
    """Probe /slam_status via rosbridge gRPC (JSON, uses SlamStatus.angle for yaw)."""
    from dimos.agents.cli import slam_probe

    argv: list[str] = []
    if target:
        argv.extend(["--target", target])
    if topic:
        argv.extend(["--topic", topic])
    if topic_type:
        argv.extend(["--topic-type", topic_type])
    if ready_timeout_s > 0:
        argv.extend(["--ready-timeout-s", str(ready_timeout_s)])
    if timeout_s > 0:
        argv.extend(["--timeout-s", str(timeout_s)])
    if watch:
        argv.append("--watch")
    if max_messages != 1:
        argv.extend(["--max-messages", str(max_messages)])
    if qos_reliability != "best_effort":
        argv.extend(["--qos-reliability", qos_reliability])
    _exit_code(slam_probe.main(argv))


@app.command("map-probe")
def nav_map_probe(
    target: str = typer.Option("", "--target", help="rosbridge gRPC host:port"),
    topic: str = typer.Option("", "--topic", help="Map topic (default: /map)"),
    topic_type: str = typer.Option("", "--topic-type", help="OccupancyGrid message type"),
    ready_timeout_s: float = typer.Option(0.0, "--ready-timeout-s"),
    timeout_s: float = typer.Option(0.0, "--timeout-s"),
    watch: bool = typer.Option(False, "--watch"),
    max_messages: int = typer.Option(1, "--max-messages"),
    max_receive_mb: int = typer.Option(64, "--max-receive-mb"),
) -> None:
    """Probe /map via rosbridge gRPC (OccupancyGrid summary, no motion)."""
    from dimos.agents.cli import map_probe

    argv: list[str] = []
    if target:
        argv.extend(["--target", target])
    if topic:
        argv.extend(["--topic", topic])
    if topic_type:
        argv.extend(["--topic-type", topic_type])
    if ready_timeout_s > 0:
        argv.extend(["--ready-timeout-s", str(ready_timeout_s)])
    if timeout_s > 0:
        argv.extend(["--timeout-s", str(timeout_s)])
    if watch:
        argv.append("--watch")
    if max_messages != 1:
        argv.extend(["--max-messages", str(max_messages)])
    if max_receive_mb != 64:
        argv.extend(["--max-receive-mb", str(max_receive_mb)])
    _exit_code(map_probe.main(argv))


@app.command("foxglove")
def nav_foxglove(
    url: str = typer.Option("", "--url", help=f"Foxglove WebSocket URL (default: {_default_foxglove_url()})"),
    list_channels: bool = typer.Option(False, "--list", help="List advertised channels"),
    filter_substring: str = typer.Option("", "--filter", help="Filter channels by topic substring"),
    probe_map: bool = typer.Option(False, "--probe-map", help="Fetch one /map summary"),
    probe_slam: bool = typer.Option(False, "--probe-slam", help="Fetch one /slam_status summary"),
    timeout_s: float = typer.Option(15.0, "--timeout-s"),
) -> None:
    """Probe ros-foxglove-bridge (ws://host:8765) channels and topics."""
    from dimos.agents.cli import foxglove_probe

    argv: list[str] = []
    if url:
        argv.extend(["--url", url])
    if list_channels:
        argv.append("--list")
    if filter_substring:
        argv.extend(["--filter", filter_substring])
    if probe_map:
        argv.append("--probe-map")
    if probe_slam:
        argv.append("--probe-slam")
    if timeout_s != 15.0:
        argv.extend(["--timeout-s", str(timeout_s)])
    _exit_code(foxglove_probe.main(argv))


@app.command("map")
def nav_map(
    live: bool = typer.Option(
        True,
        "--live/--no-live",
        help="Subscribe to live /map and /slam_status (default). Use --file to load JSON instead.",
    ),
    file: Path | None = typer.Option(None, "--file", help="Load map from saved JSON instead of live subscribe"),
    transport: Literal["grpc", "foxglove"] = typer.Option("grpc", "--transport"),
    target: str = typer.Option("", "--target", help="gRPC host:port or foxglove ws:// URL"),
    topic: str = typer.Option("/map", "--topic"),
    topic_type: str = typer.Option("nav_msgs/msg/OccupancyGrid", "--topic-type"),
    slam_topic: str = typer.Option("", "--slam-topic"),
    slam_topic_type: str = typer.Option("", "--slam-topic-type"),
    timeout_s: float = typer.Option(15.0, "--timeout-s"),
    max_receive_mb: int | None = typer.Option(None, "--max-receive-mb"),
    style: Literal["web", "debug"] = typer.Option("web", "--style", help="web = robot UI style"),
    show_robot: bool | None = typer.Option(None, "--show-robot/--no-show-robot"),
    map_name: str = typer.Option("", "--map-name"),
    save: Path | None = typer.Option(
        None,
        "--save",
        help="Save PNG (default: output/map.png or output/goal_<dir>_<units>.png)",
    ),
    dpi: int = typer.Option(150, "--dpi"),
    verbose: bool = typer.Option(False, "--verbose"),
    direction: Literal["forward", "backward", "left", "right"] | None = typer.Option(
        None, "--direction", help="Overlay relative-move goal on the map"
    ),
    distance_units: float = typer.Option(
        2.0, "--distance-units", help="Relative move units when --direction is set (1 = 5 cm)"
    ),
) -> None:
    """Visualize OccupancyGrid with robot pose; optional relative-move goal overlay."""
    _run_map_viz(
        live=live,
        file=file,
        transport=transport,
        target=target,
        topic=topic,
        topic_type=topic_type,
        slam_topic=slam_topic,
        slam_topic_type=slam_topic_type,
        timeout_s=timeout_s,
        max_receive_mb=max_receive_mb,
        style=style,
        show_robot=show_robot,
        map_name=map_name,
        save=save,
        dpi=dpi,
        verbose=verbose,
        direction=direction,
        distance_units=distance_units,
    )


@app.command("relative-goal")
def nav_relative_goal(
    direction: Literal["forward", "backward", "left", "right"] = typer.Option(
        ..., "--direction", help="Body-frame move direction"
    ),
    distance_units: float = typer.Option(2.0, "--distance-units", help="Semantic units (1 = 5 cm cell)"),
    transport: Literal["grpc", "foxglove"] = typer.Option("foxglove", "--transport"),
    target: str = typer.Option("", "--target", help="gRPC host:port or foxglove ws:// URL"),
    topic: str = typer.Option("/map", "--topic"),
    topic_type: str = typer.Option("nav_msgs/msg/OccupancyGrid", "--topic-type"),
    slam_topic: str = typer.Option("", "--slam-topic"),
    slam_topic_type: str = typer.Option("", "--slam-topic-type"),
    timeout_s: float = typer.Option(15.0, "--timeout-s"),
    save: Path | None = typer.Option(
        None,
        "--save",
        help="Save PNG (default: output/goal_<dir>_<units>.png)",
    ),
    dpi: int = typer.Option(150, "--dpi"),
) -> None:
    """Alias for ``dimos nav map --live --direction ...`` (relative goal overlay)."""
    _run_map_viz(
        live=True,
        transport=transport,
        target=target,
        topic=topic,
        topic_type=topic_type,
        slam_topic=slam_topic,
        slam_topic_type=slam_topic_type,
        timeout_s=timeout_s,
        save=save,
        dpi=dpi,
        direction=direction,
        distance_units=distance_units,
    )


@app.command("goal-dry-run")
def nav_goal_dry_run(
    workspace_name: str = typer.Option("front_workspace", "--workspace-name"),
    workspace_color: str = typer.Option("", "--workspace-color"),
    workspace_catalog: str = typer.Option("", "--workspace-catalog"),
    behavior_tree: str = typer.Option("", "--behavior-tree"),
    timeout_s: float = typer.Option(0.0, "--timeout-s"),
) -> None:
    """Resolve a workspace catalog entry and print NavigateToPose goal JSON (no ROS I/O)."""
    from dimos.agents.cli import goal_dry_run

    argv = ["--dry-run", "--step", "goal"]
    if workspace_name != "front_workspace":
        argv.extend(["--workspace-name", workspace_name])
    if workspace_color:
        argv.extend(["--workspace-color", workspace_color])
    if workspace_catalog:
        argv.extend(["--workspace-catalog", workspace_catalog])
    if behavior_tree:
        argv.extend(["--behavior-tree", behavior_tree])
    if timeout_s > 0:
        argv.extend(["--timeout-s", str(timeout_s)])
    _exit_code(goal_dry_run.main(argv))
