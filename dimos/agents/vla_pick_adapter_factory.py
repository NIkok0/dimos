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

from dimos.agents.dax_skill_sdk_adapter import DaxDropVlaActionClient, DaxSkillSdkAdapter
from dimos.agents.rosbridge.navigation.adapter import PyRosbridgeSysNavigationAdapter
from dimos.agents.rosbridge.navigation.client import PyRosbridgeNavigationRosClient
from dimos.agents.rosbridge.manipulation.ros_action import PyRosbridgeRosActionAdapter
from dimos.agents.rosbridge.manipulation.vla_client import PyRosbridgeVlaPickClient
from dimos.agents.ros_topic_navigation_adapter import (
    RosTopicNavigationAdapter,
)
from dimos.agents.navigation_safety import OccupancyGridSafetyChecker
from dimos.agents.rosbridge.session import RosbridgeSession
from dimos.agents.task_action_plan import ActionPlanOrchestrator, VlaActionGateway
from dimos.agents.vla_pick_adapters import (
    MockRosActionAdapter,
    MockSysNavigationAdapter,
    MockVlaPickClient,
    RosActionAdapter,
    SysNavigationAdapter,
)
from dimos.agents.workspace_resolver import WorkspaceResolver
from dimos.core.global_config import GlobalConfig, global_config


def make_rosbridge_session(config: GlobalConfig | None = None) -> RosbridgeSession:
    return RosbridgeSession.from_config(config or global_config)


def make_sys_navigation_adapter(
    config: GlobalConfig | None = None,
    *,
    session: RosbridgeSession | None = None,
) -> SysNavigationAdapter:
    cfg = config or global_config
    mode = cfg.vla_sys_nav_adapter.strip().lower()
    if mode in {"mock", ""}:
        return MockSysNavigationAdapter()
    if mode == "py_rosbridge":
        return PyRosbridgeSysNavigationAdapter.from_config(cfg, session=session)
    if mode == "ros_topic":
        if not cfg.ros_nav_workspace_catalog.strip():
            raise ValueError("ros_nav_workspace_catalog is required for ros_topic navigation")
        return RosTopicNavigationAdapter(
            ros_client=PyRosbridgeNavigationRosClient.from_config(cfg, session=session),
            workspace_resolver=WorkspaceResolver.from_file(cfg.ros_nav_workspace_catalog),
            behavior_tree=cfg.ros_nav_default_behavior_tree,
            timeout_s=cfg.ros_nav_action_timeout_s,
            safety_checker=OccupancyGridSafetyChecker.from_config(cfg),
        )
    raise ValueError(f"unsupported vla_sys_nav_adapter {cfg.vla_sys_nav_adapter!r}")


def make_vla_action_gateway(
    config: GlobalConfig | None = None,
    *,
    session: RosbridgeSession | None = None,
) -> VlaActionGateway:
    cfg = config or global_config
    mode = cfg.vla_pick_adapter.strip().lower()
    if mode in {"mock", ""}:
        client = MockVlaPickClient()
    elif mode == "py_rosbridge":
        client = PyRosbridgeVlaPickClient.from_config(cfg, session=session)
    else:
        raise ValueError(f"unsupported vla_pick_adapter {cfg.vla_pick_adapter!r}")

    dax_mode = cfg.dax_skill_adapter.strip().lower()
    if dax_mode in {"disabled", "off", "none", ""}:
        return VlaActionGateway(client)
    if dax_mode in {"dry_run", "local", "dax"}:
        return VlaActionGateway(
            DaxDropVlaActionClient(
                base_client=client,
                dax_adapter=DaxSkillSdkAdapter.from_config(cfg),
            )
        )
    raise ValueError(f"unsupported dax_skill_adapter {cfg.dax_skill_adapter!r}")


def make_ros_action_adapter(
    config: GlobalConfig | None = None,
    *,
    session: RosbridgeSession | None = None,
) -> RosActionAdapter:
    cfg = config or global_config
    mode = cfg.vla_ros_adapter.strip().lower()
    if mode in {"mock", ""}:
        return MockRosActionAdapter()
    if mode == "py_rosbridge":
        return PyRosbridgeRosActionAdapter.from_config(cfg, session=session)
    raise ValueError(f"unsupported vla_ros_adapter {cfg.vla_ros_adapter!r}")


def make_action_plan_orchestrator(config: GlobalConfig | None = None) -> ActionPlanOrchestrator:
    cfg = config or global_config
    session = make_rosbridge_session(cfg) if _uses_rosbridge(cfg) else None
    return ActionPlanOrchestrator(
        navigation=make_sys_navigation_adapter(cfg, session=session),
        vla_gateway=make_vla_action_gateway(cfg, session=session),
        ros_action=make_ros_action_adapter(cfg, session=session),
    )


def _uses_rosbridge(cfg: GlobalConfig) -> bool:
    modes = (
        cfg.vla_ros_adapter.strip().lower(),
        cfg.vla_sys_nav_adapter.strip().lower(),
        cfg.vla_pick_adapter.strip().lower(),
    )
    return any(mode in {"py_rosbridge", "ros_topic"} for mode in modes)


__all__ = [
    "make_action_plan_orchestrator",
    "make_ros_action_adapter",
    "make_rosbridge_session",
    "make_sys_navigation_adapter",
    "make_vla_action_gateway",
]
