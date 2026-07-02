#!/usr/bin/env python3
"""Probe remote dax_dimos_interfaces ROS services through py_rosbridge."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from dimos.agents.rosbridge.codecs.dax_dimos_interfaces import (
    ExecutePickTaskRequest,
    ExecutePickTaskRequestCodec,
    ExecutePickTaskResponseCodec,
    GoToWorkspaceRequest,
    GoToWorkspaceRequestCodec,
    GoToWorkspaceResponseCodec,
    PickSkuRequest,
    PickSkuRequestCodec,
    PickSkuResponseCodec,
    RunDemoRequest,
    RunDemoRequestCodec,
    RunDemoResponseCodec,
    TriggerRequest,
    TriggerRequestCodec,
    TriggerResponseCodec,
)
from dimos.agents.rosbridge.session import RosbridgeSession
from dimos.core.global_config import global_config


PROBE_STEPS = (
    "connect",
    "all",
    "go_to_workspace",
    "pick_sku",
    "execute_pick_task",
    "run_demo",
    "reset_scene",
    "get_state",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe dax_dimos_interfaces rosbridge services.")
    parser.add_argument(
        "--target",
        default=global_config.rosbridge_grpc_address,
        help=f"gRPC target (default: {global_config.rosbridge_grpc_address})",
    )
    parser.add_argument("--timeout-s", type=float, default=global_config.ros_action_timeout_s)
    parser.add_argument(
        "--ready-timeout-s",
        type=float,
        default=global_config.rosbridge_ready_timeout_s,
        help=f"gRPC channel ready timeout (default: {global_config.rosbridge_ready_timeout_s})",
    )
    parser.add_argument("--step", choices=PROBE_STEPS, default="all")
    parser.add_argument("--side", default="", help="PickSku side: left/right or empty for auto")
    parser.add_argument("--workspace-color", default="blue")
    parser.add_argument("--sku-color", default="red")
    return parser.parse_args()


def _print_response(label: str, result: object) -> bool:
    response = result.response  # type: ignore[attr-defined]
    ok = bool(result.success and response.success)  # type: ignore[attr-defined]
    print(
        f"{label} grpc_success={result.success} success={response.success} "  # type: ignore[attr-defined]
        f"status={response.status!r} command={response.command!r} "
        f"failure_reason={response.failure_reason!r} result_json_len={len(response.result_json)}",
        flush=True,
    )
    return ok


def _call_service(
    client: Any,
    *,
    label: str,
    service: str,
    service_type: str,
    request: Any,
    request_codec: Any,
    response_codec: Any,
    timeout_sec: float,
) -> bool:
    print(f"service={service}", flush=True)
    print(f"service_type={service_type}", flush=True)
    try:
        result = client.call_service(
            service,
            service_type,
            request,
            request_codec=request_codec,
            response_codec=response_codec,
            timeout_sec=timeout_sec,
            wait_timeout=timeout_sec + 1.0,
        )
    except Exception as exc:
        if exc.__class__.__name__ == "RosbridgeError" or "Stream removed" in str(exc):
            print(
                f"ERROR: {label} call failed — remote closed the gRPC stream.\n"
                f"  service={service}\n"
                f"  type={service_type}\n"
                f"  details={exc}\n"
                "  Likely causes on 10.69.6.121:\n"
                "    1. rosbridge crashed while forwarding to ROS (check server logs)\n"
                "    2. ROS service not registered: ros2 service list | grep " + service + "\n"
                "    3. dax_dimos_interfaces not built/sourced after srv update\n"
                "    4. srv type/fields mismatch vs dimos codecs\n"
                "  Try simpler probe first: --step get_state or --step connect",
                file=sys.stderr,
                flush=True,
            )
            return False
        raise
    return _print_response(label, result)


def main() -> int:
    args = parse_args()
    print(f"target={args.target}", flush=True)

    session = RosbridgeSession(target=args.target, ready_timeout_s=args.ready_timeout_s)
    try:
        client = session.get_client()
    except Exception as exc:
        if exc.__class__.__name__ == "FutureTimeoutError":
            print(
                f"ERROR: gRPC channel to {args.target} not ready within {args.ready_timeout_s}s.\n"
                "  - Remote rosbridge is likely not running, or port 9091 is not listening.\n"
                "  - Check: timeout 3 bash -c 'echo > /dev/tcp/HOST/9091'\n"
                "  - Ask wenchao to start rosbridge_grpc_server and confirm ROS_DOMAIN_ID.",
                file=sys.stderr,
                flush=True,
            )
            return 1
        raise
    print("gRPC channel ready", flush=True)
    if args.step == "connect":
        return 0
    exit_code = 0

    try:
        if args.step in {"all", "go_to_workspace"}:
            if not _call_service(
                client,
                label="go_to_workspace",
                service=global_config.ros_go_to_workspace_service,
                service_type=global_config.ros_go_to_workspace_service_type,
                request=GoToWorkspaceRequest(workspace_name="table", workspace_color="blue"),
                request_codec=GoToWorkspaceRequestCodec,
                response_codec=GoToWorkspaceResponseCodec,
                timeout_sec=args.timeout_s,
            ):
                exit_code = 2

        if args.step in {"all", "pick_sku"}:
            if not _call_service(
                client,
                label="pick_sku",
                service=global_config.ros_pick_sku_service,
                service_type=global_config.ros_pick_sku_service_type,
                request=PickSkuRequest(
                    workspace_name="table",
                    workspace_color="blue",
                    sku_name="cube",
                    sku_color="red",
                    side=args.side,
                ),
                request_codec=PickSkuRequestCodec,
                response_codec=PickSkuResponseCodec,
                timeout_sec=args.timeout_s,
            ):
                exit_code = 2

        if args.step in {"all", "execute_pick_task"}:
            if not _call_service(
                client,
                label="execute_pick_task",
                service=global_config.ros_execute_pick_task_service,
                service_type=global_config.ros_execute_pick_task_service_type,
                request=ExecutePickTaskRequest(
                    workspace_name="table",
                    workspace_color="blue",
                    sku_name="cube",
                    sku_color="red",
                ),
                request_codec=ExecutePickTaskRequestCodec,
                response_codec=ExecutePickTaskResponseCodec,
                timeout_sec=args.timeout_s,
            ):
                exit_code = 2

        if args.step in {"all", "run_demo"}:
            if not _call_service(
                client,
                label="run_demo",
                service=global_config.ros_run_demo_service,
                service_type=global_config.ros_run_demo_service_type,
                request=RunDemoRequest(
                    workspace_color=args.workspace_color,
                    sku_color=args.sku_color,
                ),
                request_codec=RunDemoRequestCodec,
                response_codec=RunDemoResponseCodec,
                timeout_sec=args.timeout_s,
            ):
                exit_code = 2

        if args.step in {"all", "reset_scene"}:
            if not _call_service(
                client,
                label="reset_scene",
                service=global_config.ros_reset_scene_service,
                service_type=global_config.ros_reset_scene_service_type,
                request=TriggerRequest(),
                request_codec=TriggerRequestCodec,
                response_codec=TriggerResponseCodec,
                timeout_sec=args.timeout_s,
            ):
                exit_code = 2

        if args.step in {"all", "get_state"}:
            if not _call_service(
                client,
                label="get_state",
                service=global_config.ros_get_state_service,
                service_type=global_config.ros_get_state_service_type,
                request=TriggerRequest(),
                request_codec=TriggerRequestCodec,
                response_codec=TriggerResponseCodec,
                timeout_sec=args.timeout_s,
            ):
                exit_code = 2
    finally:
        session.close()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
