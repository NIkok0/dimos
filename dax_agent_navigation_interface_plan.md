# Dax Agent 导航接口接入方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把真机“栅格地图 + SLAM 状态 + 指点导航 action + 导航状态 topic”接入 Dax Agent 的统一任务编排链路。

**Architecture:** Dax Agent 继续只暴露 `execute_nl_task`，上层 `TaskRouter -> TaskTemplate -> ActionPlan -> ActionPlanOrchestrator` 不直接关心 ROS。新增导航接口契约和 adapter：`move_to_workspace` 先解析 workspace pose，再检查定位状态，最后通过 `/navigate_to_pose` 执行指点导航，并把 `/navigation_current_status` 与 action result 归一化为 `NavigationResult`。

**Tech Stack:** Python, DimOS ActionPlan, ROS2 Action/Topic, `robot_interfaces/action/NavigateToPose`, `nav_msgs/msg/OccupancyGrid`, `robot_interfaces/msg/SlamStatus`, `robot_interfaces/msg/NavStatus`。

---

## 1. 事实源与边界

接口维护事实源放在：

- `/home/miaoli/Projects/dimos/atom_skill.md`

其中 Dax atomic skill / YAML 是上半身操作事实源，导航接口是下半身移动事实源。两者都不能直接暴露给 LLM/MCP。

统一入口仍然是：

```text
dax-agent
  -> execute_nl_task(text, request_id="")
  -> TaskRouter
  -> TaskTemplate
  -> ActionPlan
  -> ActionPlanOrchestrator
```

底层执行分层：

```text
move_to_workspace     -> RealRosNavigationAdapter -> /navigate_to_pose
vla_pick_sku          -> VLA / py_rosbridge pick
vla_drop_sku/place    -> DaxSkillSdkAdapter.place -> place.yaml
go_home               -> DaxSkillSdkAdapter.go_home -> go_home.yaml
```

## 2. 当前代码现状

当前导航主链路已经有抽象雏形：

| 文件 | 当前职责 | 接入调整 |
|---|---|---|
| `dimos/agents/skills/task_action_plan.py` | 定义 `ActionPlan`、模板、编排器 | 保持 `move_to_workspace` 任务级动作不变，增加真实导航 adapter 的 metadata 消费 |
| `dimos/agents/skills/vla_pick_adapters.py` | 定义 `SysNavigationAdapter` 和 `NavigationResult` | 扩展 `NavigationResult` 字段或 metadata，支持真实 ROS 状态 |
| `dimos/agents/skills/py_rosbridge_nav_adapter.py` | 当前调用 `/go_to_workspace` service | 新增或替换为 `/navigate_to_pose` action adapter |
| `dimos/agents/skills/robot_action_catalog.py` | 任务级动作 catalog | `move_to_workspace` backend 继续标为 `ros_topic`/真实导航 adapter |
| `dimos/agents/skills/vla_pick_adapter_factory.py` | 根据配置创建 adapter | 增加真实导航 adapter 模式 |

建议不要把 `/map`、`/slam_status`、`/navigation_current_status`、`/navigate_to_pose` 暴露成 agent tool。它们属于 adapter 内部接口。

## 3. 接口契约

### 3.1 地图

```text
/map
nav_msgs/msg/OccupancyGrid
```

第一版只做可选订阅和调试 metadata，不作为导航前置硬依赖。后续可用于工作区可达性、地图版本、障碍物覆盖判断。

### 3.2 定位状态

```text
/slam_status
robot_interfaces/msg/SlamStatus
```

必须支持的门禁：

| status | 是否允许导航 |
|---|---|
| `located` | 允许 |
| `lost` | 不允许 |
| `relocating` | 等待或超时 |
| `building` / `extend` | 不允许生产导航 |
| `waitting` / `saved` | 第一版不直接认为可导航 |

### 3.3 导航状态

```text
/navigation_current_status
robot_interfaces/msg/NavStatus
```

关键状态归一化：

| code | 归一化 | 行为 |
|---:|---|---|
| 1000 | `accepted` | 记录 |
| 1001 | `planning_succeeded` | 记录 |
| 1002 | `moving` | 继续等待 |
| 1003 | `arrived` | step 成功 |
| 1004 | `cancelled` | step 失败 |
| 1005 | `preempted` | step 失败 |
| 1006 | `blocked` | step 失败，可后续触发 replan |
| 1007 | `target_blocked` | step 失败 |
| 2000 | `recovery` | 继续等待或按 timeout 失败 |
| 3000-3004 | `failed` | step 失败 |

### 3.4 指点导航

```text
/navigate_to_pose
robot_interfaces/action/NavigateToPose
```

Goal：

```text
geometry_msgs/PoseStamped pose
string behavior_tree
int32 mode
```

Result：

```text
uint8 result_code
string result_message
geometry_msgs/PoseStamped result_pose
```

Feedback：

```text
geometry_msgs/PoseStamped current_pose
Duration navigation_time
Duration estimated_time_remaining
float32 distance_remaining
float32 speed
int32 navigation_state
string navigation_state_description
uint8[] uuid
```

## 4. 推荐数据模型

新增导航内部数据模型，建议放在：

```text
dimos/agents/skills/navigation_contracts.py
```

建议类型：

```python
from dataclasses import dataclass, field
from typing import Any, Literal

NavigationNormalizedStatus = Literal[
    "idle",
    "accepted",
    "planning_succeeded",
    "moving",
    "arrived",
    "cancelled",
    "preempted",
    "blocked",
    "target_blocked",
    "recovery",
    "failed",
    "timeout",
    "local_succeeded",
    "unknown",
]

@dataclass(frozen=True)
class WorkspacePose:
    workspace_id: str
    name: str
    color: str
    frame_id: str
    x: float
    y: float
    yaw: float

@dataclass(frozen=True)
class SlamState:
    status: str
    pose: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class NavigateToPoseGoal:
    pose: WorkspacePose
    behavior_tree: str
    mode: int

@dataclass(frozen=True)
class RealNavigationResult:
    status: NavigationNormalizedStatus
    workspace: WorkspacePose
    message: str
    nav_status_code: int | None = None
    uuid: str = ""
    result_pose: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
```

原则：

- `WorkspacePose` 来自 workspace catalog，不来自 LLM。
- `mode` 来自任务上下文或配置，不来自 LLM。
- `raw` 保留 ROS 原始字段，方便联调。

## 5. Workspace Catalog

第一版先用静态配置维护工作区位姿，例如：

```python
{
    "front_workspace": {
        "workspace_id": "front_workspace",
        "name": "workspace",
        "color": "front",
        "frame_id": "map",
        "x": 1.8,
        "y": 0.0,
        "yaw": 0.0,
    },
    "blue_table": {
        "workspace_id": "blue_table",
        "name": "table",
        "color": "blue",
        "frame_id": "map",
        "x": 2.4,
        "y": 0.6,
        "yaw": 1.57,
    },
}
```

解析规则：

```text
ActionStep.args(workspace_name, workspace_color)
  -> WorkspaceResolver
  -> WorkspacePose
```

如果找不到 workspace，返回 `INVALID_SLOT` 或 `NAV_WORKSPACE_NOT_FOUND`，不要猜坐标。

## 6. Adapter 设计

新增：

```text
dimos/agents/skills/ros_topic_navigation_adapter.py
```

职责：

- 读取 `/slam_status`，确认定位状态。
- 解析 `move_to_workspace` 的 workspace 到 `PoseStamped`。
- 调用 `/navigate_to_pose` action。
- 订阅或消费 `/navigation_current_status` 和 action feedback/result。
- 返回统一 `NavigationResult`。

建议接口兼容现有 `SysNavigationAdapter`：

```python
class RosTopicNavigationAdapter:
    def navigate_to_workspace(
        self,
        *,
        request_id: str,
        workspace_type: str,
        table_color: str,
    ) -> NavigationResult:
        ...
```

这样 `ActionPlanOrchestrator` 第一版可以少改，后续再把参数名从 `workspace_type/table_color` 收敛成更通用的 `workspace_name/workspace_color`。

## 7. 配置项

建议新增到 `GlobalConfig`：

```text
VLA_SYS_NAV_ADAPTER=mock|py_rosbridge|ros_topic
ROS_NAV_MAP_TOPIC=/map
ROS_NAV_SLAM_STATUS_TOPIC=/slam_status
ROS_NAV_STATUS_TOPIC=/navigation_current_status
ROS_NAVIGATE_TO_POSE_ACTION=/navigate_to_pose
ROS_NAVIGATE_TO_POSE_ACTION_TYPE=robot_interfaces/action/NavigateToPose
ROS_NAV_DEFAULT_FRAME_ID=map
ROS_NAV_DEFAULT_BEHAVIOR_TREE=
ROS_NAV_DEFAULT_MODE=0
ROS_NAV_CARGO_MODE=1
ROS_NAV_LOCALIZATION_TIMEOUT_S=5.0
ROS_NAV_ACTION_TIMEOUT_S=60.0
ROS_NAV_WORKSPACE_CATALOG=/path/to/workspaces.yaml
```

已有 `ROSBRIDGE_GRPC_TARGET` 可以继续作为远程 ROS 通信目标。如果后续 Dax Agent 本机直接在 ROS2 环境中运行，也可以增加 native ROS2 adapter，但不要影响 ActionPlan 层。

## 8. 执行链路示例

用户：

```text
移动到前方固定工作区
```

链路：

```text
execute_nl_task("移动到前方固定工作区")
  -> TaskRouter: intent_type=guard_loop 或 navigation-only move
  -> TaskTemplate: ActionPlan(step-1 move_to_workspace)
  -> ActionPlanOrchestrator
  -> RosTopicNavigationAdapter.navigate_to_workspace
  -> WorkspaceResolver: front_workspace -> map pose
  -> /slam_status: located
  -> /navigate_to_pose goal
  -> feedback/status: moving
  -> result/status: succeeded / NAV_SUCCESS
  -> NavigationResult(status="arrived")
```

fetch 示例：

```text
移动到蓝色桌子抓红色 cube，再放到前方固定工作区
```

链路：

```text
move_to_workspace(blue_table)
  -> /navigate_to_pose
vla_pick_sku(red cube)
  -> VLA / py_rosbridge
move_to_workspace(front_workspace)
  -> /navigate_to_pose
vla_drop_sku
  -> DaxSkillSdkAdapter.place
```

导航失败时不调用 pick/drop。

## 9. 错误码建议

| 错误码 | 触发条件 |
|---|---|
| `NAV_WORKSPACE_NOT_FOUND` | 工作区不在 catalog |
| `NAV_LOCALIZATION_NOT_READY` | `/slam_status` 不是 `located` |
| `NAV_LOCALIZATION_LOST` | `/slam_status.status == lost` |
| `NAV_GOAL_REJECTED` | action goal 未被接受 |
| `NAVIGATION_BLOCKED` | `NAV_PATH_IS_BLOCKED` |
| `NAV_TARGET_BLOCKED` | `NAV_TARGET_COVERED_BY_OBSTACLE` |
| `NAVIGATION_CANCELLED` | result canceled 或状态取消 |
| `NAVIGATION_PREEMPTED` | 目标被抢占 |
| `NAVIGATION_TIMEOUT` | 等定位、ack、result 超时 |
| `NAVIGATION_FAILED` | result failed 或 3000-3004 |

## 10. 实施任务

### Task 1: 固化导航接口事实源

**Files:**
- Modify: `/home/miaoli/Projects/dimos/atom_skill.md`
- Create: `/home/miaoli/Projects/dimos/dax_agent_navigation_interface_plan.md`

- [ ] 确认 `atom_skill.md` 包含 `/map`、`/slam_status`、`/navigation_current_status`、`/navigate_to_pose`。
- [ ] 确认文档明确“导航接口不暴露给 MCP/LLM”。
- [ ] 确认本文档和 `atom_skill.md` 的状态码映射一致。

### Task 2: 增加导航 contracts

**Files:**
- Create: `/home/miaoli/Projects/dimos/dimos/agents/skills/navigation_contracts.py`
- Test: `/home/miaoli/Projects/dimos/dimos/agents/skills/test_navigation_contracts.py`

- [ ] 新增 `WorkspacePose`、`SlamState`、`NavigateToPoseGoal`、`RealNavigationResult`。
- [ ] 新增 `normalize_nav_status_code(code: int) -> NavigationNormalizedStatus`。
- [ ] 测试覆盖 `1003 -> arrived`、`1006 -> blocked`、`1007 -> target_blocked`、`3001 -> failed`、未知码 -> `unknown`。

### Task 3: 增加 workspace resolver

**Files:**
- Create: `/home/miaoli/Projects/dimos/dimos/agents/skills/workspace_resolver.py`
- Test: `/home/miaoli/Projects/dimos/dimos/agents/skills/test_workspace_resolver.py`

- [ ] 支持静态 dict catalog。
- [ ] 支持从 YAML/JSON 文件加载 catalog。
- [ ] `resolve(workspace_name, workspace_color)` 找不到时返回明确错误，不猜坐标。
- [ ] 测试 `front_workspace`、`blue_table`、未知 workspace。

### Task 4: 增加真实 ROS 导航 adapter

**Files:**
- Create: `/home/miaoli/Projects/dimos/dimos/agents/skills/ros_topic_navigation_adapter.py`
- Test: `/home/miaoli/Projects/dimos/dimos/agents/skills/test_ros_topic_navigation_adapter.py`

- [ ] 实现 `SysNavigationAdapter.navigate_to_workspace(...)` 兼容接口。
- [ ] 定位状态不是 `located` 时失败早返回，不发送 action goal。
- [ ] `NAV_SUCCESS` / result `SUCCEEDED` 返回 `NavigationResult.status="arrived"`。
- [ ] 阻塞、取消、失败、超时返回对应失败状态和 metadata。
- [ ] 测试使用 fake ROS client，不依赖真机。

### Task 5: 接入 adapter factory

**Files:**
- Modify: `/home/miaoli/Projects/dimos/dimos/agents/skills/vla_pick_adapter_factory.py`
- Modify: `/home/miaoli/Projects/dimos/dimos/core/global_config.py`
- Test: `/home/miaoli/Projects/dimos/dimos/agents/skills/test_vla_pick_adapter_factory.py`

- [ ] 新增 `VLA_SYS_NAV_ADAPTER=ros_topic` 分支。
- [ ] 新增导航 topic/action 配置项。
- [ ] 默认仍为 mock，避免无真机测试误触发 ROS。
- [ ] 测试 mock 默认不变，`ros_topic` 创建新 adapter。

### Task 6: 编排回归

**Files:**
- Test: `/home/miaoli/Projects/dimos/dimos/agents/skills/test_task_action_plan.py`

- [ ] fetch 成功链路中 source nav、pick、target nav、drop 顺序不变。
- [ ] source nav 定位失败时不调用 pick。
- [ ] target nav blocked 时不调用 Dax drop。
- [ ] navigation metadata 包含 workspace pose、status_code、uuid。

### Task 7: 联调命令与 smoke

**Files:**
- Create: `/home/miaoli/Projects/dimos/scripts/probe_navigation_topics.py`

- [ ] 支持读取 `/slam_status`。
- [ ] 支持读取 `/navigation_current_status`。
- [ ] 支持发送 `/navigate_to_pose` 测试 goal。
- [ ] 支持 dry-run 只打印 goal，不发送真机。
- [ ] 文档给出联调顺序：先定位状态，再空 goal dry-run，再真实前方固定工作区。

## 11. 验证计划

文档级检查：

```bash
rg -n '/map|/slam_status|/navigation_current_status|/navigate_to_pose|NavigateToPose|OccupancyGrid|SlamStatus|NavStatus' atom_skill.md dax_agent_navigation_interface_plan.md
```

后续代码实现检查：

```bash
.venv/bin/pytest \
  dimos/agents/skills/test_navigation_contracts.py \
  dimos/agents/skills/test_workspace_resolver.py \
  dimos/agents/skills/test_ros_topic_navigation_adapter.py \
  dimos/agents/skills/test_vla_pick_adapter_factory.py \
  dimos/agents/skills/test_task_action_plan.py \
  -q -o addopts=
```

联调 smoke：

```bash
dimos run dax-agent --daemon
dimos mcp list-tools
dimos agent-send "移动到前方固定工作区"
```

验收：

- MCP tool 仍只暴露统一 NL 入口。
- 日志显示 `move_to_workspace -> RosTopicNavigationAdapter -> /navigate_to_pose`。
- `/slam_status != located` 时不会发送导航 goal。
- 导航失败时后续 VLA/Dax 操作不会执行。

## 12. SDK / 导航同事对齐问题

1. `/navigate_to_pose` 是否是 ROS2 action，而不是 service？当前文档写的是 action，应按 action client 接。
2. `behavior_tree` 空字符串是否有效？如果无效，需要给默认 BT 名称。
3. `mode=1` 带货车模式具体用于哪些任务？fetch 搬运是否必须启用？
4. `/slam_status.status` 中 `waitting` 是否拼写固定为双 `t`？DimOS 需要按原始拼写兼容。
5. `/navigation_current_status.uuid` 与 action feedback/result 的 uuid 是否一致？
6. result `SUCCEEDED` 和 topic `NAV_SUCCESS` 谁是最终判据？建议 action result 为最终判据，topic 用于进度和诊断。
7. 目标点被障碍物覆盖时，导航侧是否能返回候选可达点？如果不能，第一版只失败返回。
8. `/map` 的 frame 是否固定为 `map`？如果不是，需要从 header 读取。

## 13. 不做的事

- 不让 LLM 直接传 `PoseStamped`。
- 不让 LLM 自由选择 `mode` 或 `behavior_tree`。
- 不把 `/map`、`/slam_status`、`/navigation_current_status`、`/navigate_to_pose` 注册为 MCP tool。
- 不把导航接口塞进 Dax YAML atomic skill。
- 不在第一版实现动态重规划或语义地图选点；先把固定工作区指点导航跑通。
