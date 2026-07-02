# dax_skill_sdk

`dax_skill_sdk` 是一套面向 DaxBot 的 **YAML 技能编排 SDK**。

它的目标是：
- 把机器人动作能力封装成可复用的 **atomic skill**
- 用 YAML 把多个 atomic skill 组合成 **composite skill**
- 让同事不需要直接写 MoveIt / ROS 控制脚本，也能快速编排机器人任务

当前这套 SDK 已经支持：
- 关节空间动作
- 笛卡尔点到点动作
- 笛卡尔直线动作
- 相对末端位移动作
- 单关节修改动作
- 头部动作
- 灵巧手动作
- 等待动作
- YAML 条件 / 循环 / 输入参数 / 数据传递

---

## 1. 项目结构

```text
src/dax_skill_sdk/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/
│   └── dax_skill_sdk
├── README.md
├── test/
│   ├── test_phase1.py
│   ├── test_joint_move.py
│   ├── test_cartesian_move.py
│   ├── test_cartesian_line.py
│   ├── test_cartesian_delta_move.py
│   ├── test_joint_set.py
│   ├── test_head_move.py
│   ├── test_hand_move.py
│   ├── test_wait.py
│   ├── test_yaml_loader.py
│   ├── test_value_resolver.py
│   └── test_skill_executor.py
└── dax_skill_sdk/
    ├── __init__.py
    ├── runtime.py
    ├── registry.py
    ├── result.py
    ├── atomic_skill/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── joint_move.py
    │   ├── cartesian_move.py
    │   ├── cartesian_line.py
    │   ├── cartesian_delta_move.py
    │   ├── joint_set.py
    │   ├── head_move.py
    │   ├── hand_move.py
    │   └── wait.py
    ├── executor/
    │   ├── __init__.py
    │   ├── plan.py
    │   ├── yaml_loader.py
    │   ├── value_resolver.py
    │   └── skill_executor.py
    ├── scripts/
    │   ├── run_joint_move_dev.py
    │   ├── run_cartesian_move_dev.py
    │   ├── run_cartesian_line_dev.py
    │   └── verify_all_groups.py
    └── composite_skill/
        ├── go_home.yaml
        ├── joint_wait_demo.yaml
        ├── hand_move_demo.yaml
        ├── conditional_demo.yaml
        └── place.yaml
```

---

## 2. 框架分层

整个系统可以理解成 4 层：

### 2.1 YAML 层
路径：`dax_skill_sdk/composite_skill/*.yaml`

这是给人写任务流程的地方。比如：
- `go_home.yaml`
- `joint_wait_demo.yaml`
- `hand_move_demo.yaml`
- `place.yaml`

YAML 用来描述：
- 要执行哪些 atomic skill
- 条件分支怎么走
- 循环怎么跑
- 输入参数是什么

---

### 2.2 Executor 层
路径：`dax_skill_sdk/executor/`

这是 YAML 的解释器。

核心文件：
- `plan.py`：定义内部 AST
- `yaml_loader.py`：把 YAML 解析成 AST
- `value_resolver.py`：解析 `ref` / `expr`
- `skill_executor.py`：真正执行 AST

这层负责：
- 读取 YAML
- 校验 schema
- 解析控制流
- 处理 inputs / 变量 / 表达式
- 调度 atomic skill

---

### 2.3 Atomic Skill 层
路径：`dax_skill_sdk/atomic_skill/`

这是机器人的基础动作能力库。

每个 atomic skill 都是一个 Python 类，继承 `AtomicSkill`，实现：
- `validate(params)`
- `execute(params, ctx)`

当前已有：
- `joint_move`
- `cartesian_move`
- `cartesian_line`
- `cartesian_delta_move`
- `joint_set`
- `head_move`
- `hand_move`
- `wait`

---

### 2.4 Runtime / 底层能力层
核心文件：
- `runtime.py`
- `registry.py`
- `result.py`
- 依赖 `dax_planner_executor/ros_bridge.py`

职责：
- 创建和持有 ROS bridge
- 创建和持有 daxplanner primitive
- 管理 blackboard
- 提供统一 SkillResult
- 提供 skill 注册表

---

## 3. YAML 控制流是怎么实现的

### 3.1 DSL 与 AST
本项目的 YAML 本质上是一门 **DSL（领域专用语言）**。

executor 不会直接一边读 YAML 一边跑，而是先把 YAML 解析成 AST（抽象语法树）。

目前 AST 节点有：
- `TaskNode`
- `IfNode`
- `RepeatNode`
- `FailNode`

路径：`dax_skill_sdk/executor/plan.py`

---

### 3.2 YAML 控制流解析在哪儿写
最核心在：

- `dax_skill_sdk/executor/yaml_loader.py`

它负责把 YAML 中的：
- 普通 task
- `if / elif / else`
- `repeat times / until / for_each`
- `fail`

解析成对应的 AST 节点。

辅助逻辑：
- `plan.py`：定义节点结构
- `value_resolver.py`：解析 `ref / expr`
- `skill_executor.py`：执行这些节点

---

### 3.3 当前支持的控制流

#### 数据流
- `inputs`
- `save_as`
- `ref`
- `expr`

#### 控制流
- `if / elif / else`
- `repeat times`
- `repeat until`
- `repeat for_each`
- `continue_on_failure`
- `fail`

---

## 4. Blackboard 机制

运行时上下文中有一个共享 blackboard：

```python
ctx.blackboard = {
  "inputs": {...},
  "vars": {},
  "steps": {},
  "loop": {},
  "last": None,
}
```

用途：
- `inputs`：外部传入参数
- `vars`：`save_as` 保存的结果
- `steps`：每一步执行结果
- `loop`：循环变量
- `last`：最近一步结果

例子：

```yaml
- skill: detect_pose
  save_as: pose

- if:
    when:
      expr: "vars.pose.success"
    then:
      - skill: cartesian_move
        params:
          tcp_goal:
            ref: "vars.pose.data.goal"
```

---

## 5. Inputs：如何给 composite skill 传参数

### 5.1 YAML 声明输入

```yaml
schema_version: 2
name: place
inputs:
  arm_name:
    type: str
    required: true
  grasp_type:
    type: str
    required: true
  target_name:
    type: str
    required: true
```

支持类型：
- `str`
- `int`
- `float`
- `bool`
- `list`
- `dict`

支持：
- `required`
- `default`

---

### 5.2 CLI 注入输入

运行时通过 `--input key=value` 传入：

```bash
ros2 run dax_skill_sdk skill_executor place.yaml \
  --input arm_name=right \
  --input grasp_type=Box \
  --input target_name=FODR0000000046
```

Executor 会自动：
- 按 YAML 里的 `inputs` 做类型转换
- 检查必填项
- 补默认值
- 拒绝未声明输入

---

## 6. Atomic Skill 一览

### 6.1 joint_move
关节空间规划。

支持 group：
- `body`
- `left_arm`
- `right_arm`
- `dual_arm`
- `body_left`
- `body_right`
- `body_dual`

示例：

```yaml
- skill: joint_move
  params:
    group: body_dual
    target: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
```

---

### 6.2 cartesian_move
绝对 TCP 点到点动作。

单臂：
```yaml
- skill: cartesian_move
  params:
    group: left_arm
    tcp_goal: [0.40, 0.25, 1.00, 1, 0, 0, 0]
```

双臂：
```yaml
- skill: cartesian_move
  params:
    group: dual_arm
    left_tcp:  [0.40, 0.25, 1.00, 1, 0, 0, 0]
    right_tcp: [0.40,-0.25, 1.00, 1, 0, 0, 0]
```

---

### 6.3 cartesian_line
末端走近似直线。

做法：
- 起终点之间采样
- 每个中间点做 IK
- 用样条穿过这些点

示例：

```yaml
- skill: cartesian_line
  params:
    group: left_arm
    tcp_goal: [0.40, 0.25, 0.70, 1, 0, 0, 0]
    n_segments: 20
```

---

### 6.4 cartesian_delta_move
相对当前 TCP 做位移。

示例：

```yaml
- skill: cartesian_delta_move
  params:
    group: right_arm
    dx: 0.10
    dy: 0.0
    dz: -0.05
```

---

### 6.5 joint_set
基于当前关节状态，只改某几个关节。

示例：

```yaml
- skill: joint_set
  params:
    group: right_arm
    updates:
      right_arm_joint6: 20
```

或者：

```yaml
- skill: joint_set
  params:
    group: right_arm
    updates:
      6: 20
```

---

### 6.6 head_move
头部 2 关节动作。

```yaml
- skill: head_move
  params:
    target: [0, 20]
```

---

### 6.7 hand_move
灵巧手动作（当前走 topic 版接口）。

```yaml
- skill: hand_move
  params:
    side: right
    positions: [0, 0, 200, 200, 200, 200]
```

约束：
- `side`: `left/right`
- `positions`: 6 维
- 每个值范围 `[0, 255]`

---

### 6.8 wait
延时。

```yaml
- skill: wait
  params:
    duration: 1.0
```

---

## 7. 示例 YAML

### 7.1 hand_move_demo.yaml
最小灵巧手示例。

### 7.2 joint_wait_demo.yaml
抬肩 → 等待 → 放下。

### 7.3 conditional_demo.yaml
演示：
- `inputs`
- `if`
- `repeat`
- `expr`

### 7.4 place.yaml
从 `place_90.py` 翻译而来，支持：
- `arm_name`
- `grasp_type`
- `target_name`

当前已验证结构、输入和主要动作链路。灵巧手数值可能仍需真机标定。

---

## 8. 如何运行

### 8.1 构建

```bash
cd ~/dax_planner_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select dax_planner_executor dax_skill_sdk --symlink-install
source install/setup.bash
```

---

### 8.2 运行一个 YAML

```bash
ros2 run dax_skill_sdk skill_executor \
  src/dax_skill_sdk/dax_skill_sdk/composite_skill/joint_wait_demo.yaml
```

---

### 8.3 dry-run
只校验，不执行真机：

```bash
ros2 run dax_skill_sdk skill_executor \
  src/dax_skill_sdk/dax_skill_sdk/composite_skill/conditional_demo.yaml \
  --dry-run \
  --input task_height=1.15 \
  --input repeat_n=3
```

---

### 8.4 自动执行

```bash
ros2 run dax_skill_sdk skill_executor xxx.yaml --no-confirm
```

---

### 8.5 逐步放行调试
每个 TaskNode 执行前停下来等回车：

```bash
ros2 run dax_skill_sdk skill_executor xxx.yaml \
  --step-confirm \
  --input arm_name=right
```

适合高风险真机动作逐步验证。

---

## 9. 调试建议

### 9.1 先 dry-run
所有新 YAML 先 dry-run：

```bash
ros2 run dax_skill_sdk skill_executor your.yaml --dry-run ...
```

### 9.2 真机动作先用 smoke 版本
复杂流程先拆成小版本，例如：
- 先只测前伸/下探
- 再测 release/上抬/回撤
- 最后跑完整流程

### 9.3 逐步放行
高风险调试时优先用：
- `--step-confirm`

### 9.4 如果动作和旧 MoveIt 脚本不完全一致
常见原因：
- 灵巧手接口变了
- full body 姿态被拆成 `body_dual + head_move`
- daxplanner 与 MoveIt 的 IK / 笛卡尔路径求解器不同

遇到这种情况，建议逐段验证：
1. 准备姿态
2. 前伸/下探
3. release/上抬/回撤
4. 回收姿态

---

## 10. 迁移旧脚本的建议顺序

建议按照复杂度从低到高迁移：

1. `place.py` / `place_90.py`
2. `close_fridge_door.py`
3. `left_hand_grasp_debug.py`
4. `open_fridge_door.py`

原因：
- 前两个主要是线性流程
- `left_hand_grasp_debug.py` 需要分支和重试
- `open_fridge_door.py` 还涉及高频控制和异步安全逻辑，最复杂

---

## 11. 当前状态总结

目前 SDK 已具备：
- 原子动作库
- YAML 控制流
- CLI 输入注入
- blackboard 数据流
- 逐步确认调试模式
- `place.yaml` 这类真实业务流程迁移能力

这意味着：
> 现在已经不是“只能跑 demo 的脚手架”，而是一套能真正承载机器人任务流程迁移的 YAML 编排框架。

---

## 12. 下半身导航接口契约

这一节把真机底盘导航接口和上面的 Dax atomic skill 放在同一份维护文档中。维护原则是：

- Dax atomic skill / YAML 负责上半身操作。
- ROS 导航接口负责下半身移动。
- Agent / LLM 不直接调用 atomic skill，也不直接发布 ROS topic 或 action goal。
- DimOS 只在 Adapter 层把任务级动作转换成后端接口。

### 12.1 栅格地图

| 项目 | 内容 |
|---|---|
| 话题名称 | `/map` |
| 消息类型 | `nav_msgs/msg/OccupancyGrid` |
| 语义 | 当前导航使用的栅格地图 |
| DimOS 用途 | 调试、可视化、地图版本检查、后续工作区可达性判断 |

第一版接入不要求 Agent 直接消费 `/map`。它应该由导航 adapter 或后续 `MapStateAdapter` 读取，用于诊断和状态上报。

### 12.2 定位状态

| 项目 | 内容 |
|---|---|
| 话题名称 | `/slam_status` |
| 消息类型 | `robot_interfaces/msg/SlamStatus` |
| 语义 | SLAM / 定位状态和当前全局位姿 |

消息字段：

```text
std_msgs/Header     header
string              status
geometry_msgs/Pose  pose
float32             score
float32             process
float32             expect_time
bool                relocated
float32             reloc_used_time
int16               opt_works_remain
float32             angle
```

当前需要重点处理的 `status`：

| status | 含义 | DimOS 建议行为 |
|---|---|---|
| `waitting` | 开机空闲 | 不认为已经可导航，等待或返回定位未就绪 |
| `building` | 建图中 | 不执行生产导航 |
| `saved` | 保存地图 | 可作为地图保存完成状态 |
| `extend` | 扩展建图 | 不执行生产导航，除非后续定义扩展建图任务 |
| `relocating` | 定位中 | 等待定位完成 |
| `located` | 定位成功 | 允许发送导航 goal |
| `lost` | 定位丢失 | 失败早返回，不发送导航 goal |

第一版可以暂时忽略 `score/process/expect_time/relocated/reloc_used_time/opt_works_remain/angle`，但 metadata 中建议保留原始状态，方便联调排查。

### 12.3 导航执行状态

| 项目 | 内容 |
|---|---|
| 话题名称 | `/navigation_current_status` |
| 消息类型 | `robot_interfaces/msg/NavStatus` |
| 语义 | 当前导航任务执行状态 |

状态码：

| code | 常量 | 含义 | DimOS 归一化 |
|---:|---|---|---|
| -1 | `NAV_UNKNNOWN` | 未知状态 | `unknown` |
| 0 | `NAV_IDLE` | 空闲 | `idle` |
| 1000 | `NAV_RECEIVE_TARGETS` | 收到目标点 | `accepted` |
| 1001 | `NAV_GLOBAL_PATH_SUCCESS` | 全局路径规划成功 | `planning_succeeded` |
| 1002 | `NAV_MOVING` | 正在移动 | `moving` |
| 1003 | `NAV_SUCCESS` | 导航成功 | `arrived` |
| 1004 | `NAV_CALCLED` | 导航取消 | `cancelled` |
| 1005 | `NAV_PREEMPTED` | 目标点被抢占 | `preempted` |
| 1006 | `NAV_PATH_IS_BLOCKED` | 路径被阻挡 | `blocked` |
| 1007 | `NAV_TARGET_COVERED_BY_OBSTACLE` | 终点被障碍物覆盖 | `target_blocked` |
| 1008 | `NAV_REFRESH_GOAL` | 刷新目标点 | `refreshing` |
| 1009 | `NAV_MOVING_SUCCESSED` | 局部控制成功 | `local_succeeded` |
| 1010 | `NAV_MOVING_CANCELLED` | 局部控制取消 | `local_cancelled` |
| 2000 | `NAV_RECOVERY` | 恢复 | `recovery` |
| 3000 | `NAV_FAILURE` | 导航失败 | `failed` |
| 3001 | `NAV_GLOBAL_PATH_FAILURE` | 全局失败 | `global_path_failed` |
| 3002 | `NAV_MOVING_FAILURE` | 局部失败 | `moving_failed` |
| 3003 | `NAV_ACTION_ACK_TIMEOUT_FAILURE` | 收不到 action 服务端确认 | `ack_timeout` |
| 3004 | `NAV_SET_MAP_PARAMS_FAILURE` | 设置地图参数失败 | `map_params_failed` |

消息字段：

```text
float64  timestamp
int32    status_code
string   description
uint8[]  uuid
uint32[] finished_path
uint32[] unfinished_path
```

DimOS adapter 应把这些状态转为统一 `NavigationResult`，并保留原始 `status_code/description/uuid` 到 metadata。

### 12.4 指点导航 Action

| 项目 | 内容 |
|---|---|
| 服务名称 | `/navigate_to_pose` |
| 接口类型 | `robot_interfaces/action/NavigateToPose` |
| 语义 | 发送一个目标位姿，让底盘导航到该点 |

Goal：

```text
geometry_msgs/PoseStamped   pose
string                      behavior_tree
int32                       mode
```

`mode`：

| value | 含义 |
|---:|---|
| 0 | 正常模式 |
| 1 | 带货车模式 |

Result：

```text
uint8 SUCCEEDED = 0
uint8 FAILED = 1
uint8 CANCELED = 2

uint8                     result_code
string                    result_message
geometry_msgs/PoseStamped result_pose
```

Feedback：

```text
geometry_msgs/PoseStamped   current_pose
builtin_interfaces/Duration navigation_time
builtin_interfaces/Duration estimated_time_remaining
float32                     distance_remaining
float32                     speed
int32                       navigation_state
string                      navigation_state_description
uint8[]                     uuid
```

DimOS 第一版建议只发送 `pose/mode`，`behavior_tree` 默认为空字符串或配置值。`mode` 不应由 LLM 直接决定，而应由任务上下文或配置决定，例如普通移动用 `0`，带货移动或搬运任务用 `1`。

### 12.5 DimOS 任务级动作映射

在 DimOS 中，这些导航接口不作为 MCP tool，也不作为 Dax atomic skill。它们映射到任务级动作：

```text
move_to_workspace
  -> WorkspaceResolver
  -> NavigateToPose goal
  -> /navigate_to_pose
  -> /navigation_current_status feedback/result
  -> NavigationResult
```

建议标准 metadata：

```python
{
    "workspace": {
        "workspace_id": "front_workspace",
        "name": "workspace",
        "color": "front",
        "pose": {"frame_id": "map", "x": 1.8, "y": 0.0, "yaw": 0.0},
    },
    "status": "arrived",
    "nav_status_code": 1003,
    "nav_description": "导航成功",
    "uuid": "...",
    "result_pose": {...},
}
```

失败早返回规则：

- `/slam_status.status != located`：不发送 `/navigate_to_pose`。
- `/navigate_to_pose` result 为 `FAILED/CANCELED`：后续 pick/drop 不执行。
- `/navigation_current_status` 进入阻塞、终点被障碍物覆盖、全局规划失败、局部失败、ack timeout：当前 step 失败。
- 超过 DimOS 配置的导航 timeout：当前 step 失败。
