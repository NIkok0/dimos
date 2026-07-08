# Copyright 2025-2026 Dimensional Inc.
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

import re

from pydantic_settings import BaseSettings, SettingsConfigDict

from dimos.constants import DEFAULT_BUILD_NATIVE
from dimos.models.vl.types import VlModelName
from dimos.visualization.rerun.constants import (
    RERUN_ENABLE_WEB,
    RERUN_OPEN_DEFAULT,
    RerunOpenOption,
    ViewerBackend,
)


def _get_all_numbers(s: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+\.?\d*", s)]


class GlobalConfig(BaseSettings):
    robot_ip: str | None = None
    robot_ips: str | None = None
    xarm7_ip: str | None = None
    xarm6_ip: str | None = None
    can_port: str | None = None
    device_path: str | None = None  # device path for real robot (e.g. /dev/ttyUSB0)
    simulation: str = ""
    replay: bool = False
    replay_db: str = "go2_short"
    new_memory: bool = False
    viewer: ViewerBackend = "rerun"
    rerun_open: RerunOpenOption = RERUN_OPEN_DEFAULT
    rerun_web: bool = RERUN_ENABLE_WEB
    rerun_host: str | None = None
    rerun_websocket_server_port: int = 3030
    n_workers: int = 2
    memory_limit: str = "auto"
    mujoco_camera_position: str | None = None
    mujoco_room: str | None = None
    mujoco_room_from_occupancy: str | None = None
    mujoco_global_costmap_from_occupancy: str | None = None
    mujoco_global_map_from_pointcloud: str | None = None
    mujoco_start_pos: str = "-1.0, 1.0"
    mujoco_steps_per_frame: int = 7
    robot_model: str | None = None
    robot_width: float = 0.54
    robot_length: float = 0.778
    robot_rotation_diameter: float = 1.0
    nerf_speed: float = 1.0
    planner_robot_speed: float | None = None
    mcp_port: int = 9990
    mcp_tool_allowlist: str = "execute_nl_task,wave,head_accept,head_reject"
    build_native: bool = DEFAULT_BUILD_NATIVE
    dtop: bool = False
    obstacle_avoidance: bool = True
    detection_model: VlModelName = "moondream"
    listen_host: str = "0.0.0.0"
    dimsim_scene: str = "apt"
    dimsim_port: int = 8090
    # Deprecated: HTTP VLA at :8018 — all pick/nav/exec use rosbridge gRPC now.
    # vla_service_url: str = "http://127.0.0.1:8018"
    # vla_request_timeout_s: float = 30.0
    vla_pick_adapter: str = "py_rosbridge"
    vla_ros_adapter: str = "py_rosbridge"
    vla_sys_nav_adapter: str = "ros_topic"
    rosbridge_grpc_target: str = "127.0.0.1:9091"
    rosbridge_grpc_port: int = 9091
    rosbridge_ready_timeout_s: float = 10.0
    rosbridge_max_receive_mb: int = 64
    ros_go_to_workspace_service: str = "/go_to_workspace"
    ros_go_to_workspace_service_type: str = "dax_dimos_interfaces/srv/GoToWorkspace"
    ros_pick_sku_service: str = "/pick_sku"
    ros_pick_sku_service_type: str = "dax_dimos_interfaces/srv/PickSku"
    ros_execute_pick_task_service: str = "/execute_pick_task"
    ros_execute_pick_task_service_type: str = "dax_dimos_interfaces/srv/ExecutePickTask"
    ros_run_demo_service: str = "/run_demo"
    ros_run_demo_service_type: str = "dax_dimos_interfaces/srv/RunDemo"
    ros_reset_scene_service: str = "/reset_scene"
    ros_reset_scene_service_type: str = "dax_dimos_interfaces/srv/Trigger"
    ros_get_state_service: str = "/get_state"
    ros_get_state_service_type: str = "dax_dimos_interfaces/srv/Trigger"
    ros_action_timeout_s: float = 30.0
    ros_nav_map_topic: str = "/map"
    ros_nav_map_topic_type: str = "nav_msgs/msg/OccupancyGrid"
    ros_nav_slam_status_topic: str = "/slam_status"
    ros_nav_slam_status_topic_type: str = "robot_interfaces/msg/SlamStatus"
    ros_nav_status_topic: str = "/navigation_current_status"
    ros_nav_status_topic_type: str = "robot_interfaces/msg/NavStatus"
    ros_navigate_to_pose_action: str = "/navigate_to_pose"
    ros_navigate_to_pose_action_type: str = "robot_interfaces/action/NavigateToPose"
    ros_nav_default_frame_id: str = "map"
    ros_nav_default_behavior_tree: str = "no_route_slow"
    ros_nav_default_mode: int = 0
    ros_nav_cargo_mode: int = 1
    ros_nav_localization_timeout_s: float = 5.0
    ros_nav_action_timeout_s: float = 60.0
    ros_nav_workspace_catalog: str = "/home/miaoli/Projects/dimos/config/workspaces.yaml"
    ros_nav_target_safety_mode: str = "footprint"
    ros_nav_target_safety_radius_m: float = 0.585
    ros_nav_collision_offset_m: float = 0.085
    ros_nav_auto_cancel_enabled: bool = True
    ros_nav_auto_cancel_status_codes: str = "1005,1006,1007"
    ros_nav_auto_cancel_poll_s: float = 0.2
    ros_nav_auto_cancel_wait_s: float = 10.0
    nl_llm_primary_enabled: bool = True
    nl_llm_model: str = "gpt-4o"
    nl_semantics_path: str = ""
    nl_hybrid_navigation_enabled: bool = True
    nl_llm_fallback_enabled: bool = False
    nl_rule_confidence_threshold: float = 0.8
    nl_navigation_semantics_path: str = ""
    vla_ros_arm_name: str = "left"
    vla_ros_pick_side: str = ""
    dax_skill_adapter: str = "disabled"
    dax_skill_sdk_ws: str = ""
    dax_skill_composite_dir: str = ""
    dax_skill_runtime_config: str = "DaxBot_X7Pro.yaml"
    dax_skill_default_arm_name: str = "left"
    dax_skill_default_grasp_type: str = "Default"
    dax_skill_dry_run: bool = True
    dax_skill_step_confirm: bool = False
    dax_skill_timeout_s: float = 30.0
    # inprocess = RuntimeContext in DimOS worker (needs rclpy + dax_rf_planner in same Python).
    # subprocess = ros2 run via deploy/run_ros2_skill_executor.sh (recommended on dax-agent venv).
    dax_skill_executor: str = "inprocess"
    dax_skill_ros_setup: str = "/opt/ros/humble/setup.bash"
    dax_skill_ros_executor_script: str = ""
    # Atomic skill Action Server (execute_atomic_skill). go_home uses this path.
    dax_atomic_skill_executor: str = "subprocess"
    dax_atomic_skill_ws: str = ""
    dax_atomic_skill_ros_setup: str = "/opt/ros/humble/setup.bash"
    dax_atomic_skill_invoke_script: str = ""
    dax_atomic_skill_timeout_s: float = 120.0
    dax_atomic_skill_dry_run: bool = False
    dax_orchestration_go_home_path: str = "config/dax_orchestration/go_home.yaml"
    dax_joint_server_url: str = "http://127.0.0.1:5000"
    dax_joint_request_timeout_s: float = 30.0
    # Per-robot wave/head joint poses (YAML). Empty = built-in X7Pro defaults only.
    dax_robot_joint_config_path: str = "config/dax_robot_joint.yaml"
    # Path to the wave animation JSON ({"positions": [[7 floats], ...]}).
    # Empty = wave skill reports a configuration error when called.
    dax_wave_animation_path: str = ""
    # /vis/* demo frontend bridge — POSTs user input / reasoning / final reply
    # to a colleague's stop-and-wait REST API for visualization. Empty = no-op.
    vis_bridge_url: str | None = None
    vis_bridge_timeout_s: float = 30.0
    vis_bridge_max_retries: int = 3
    # 113 demo frontend expects legacy ``result.tool_calls``; use ``flat`` after frontend upgrade.
    vis_bridge_outputs_format: str = "legacy"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def update(self, **kwargs: object) -> None:
        """Update config fields in place."""
        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise AttributeError(f"GlobalConfig has no field '{key}'")
            setattr(self, key, value)

    @property
    def unitree_connection_type(self) -> str:
        if self.replay:
            return "replay"
        if self.simulation:
            return self.simulation
        return "webrtc"

    @property
    def mujoco_start_pos_float(self) -> tuple[float, float]:
        x, y = _get_all_numbers(self.mujoco_start_pos)
        return (x, y)

    @property
    def mujoco_camera_position_float(self) -> tuple[float, ...]:
        if self.mujoco_camera_position is None:
            return (-0.906, 0.008, 1.101, 4.931, 89.749, -46.378)
        return tuple(_get_all_numbers(self.mujoco_camera_position))

    @property
    def rosbridge_grpc_address(self) -> str:
        """Host or host:port for py_rosbridge; bare host gets ``rosbridge_grpc_port``."""
        target = self.rosbridge_grpc_target.strip()
        if not target:
            raise ValueError("rosbridge_grpc_target must not be empty")
        if "://" in target:
            target = target.split("://", 1)[1]
        if ":" in target:
            return target
        return f"{target}:{self.rosbridge_grpc_port}"


global_config = GlobalConfig()
