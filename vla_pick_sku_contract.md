# dimos <-> VLA Pick SKU Contract v1

## 1. 边界说明

dimos 不向 VLA 模型发送自然语言。

dimos 负责把自然语言解析为结构化任务，并在 sys 导航到工作区后，向 VLA 发送 `pick_sku.request`。

当前仿真环境使用 VLA 侧 Isaac Sim 真值。dimos 不给 VLA 赋值 position、pose、object id 或 workspace id；dimos 只告诉 VLA 工作区和 SKU 的名称与颜色，VLA 侧根据仿真真值解析具体 position 和对象标识。

VLA 负责 Isaac Sim 仿真和 V-A 推理，返回 `pick_sku.action`。

dimos 只做基础语义校验；校验通过后，不修改 VLA payload，直接原样转发给 ROS action。

```text
validation_passed_payload == ros_submitted_payload
```

MVP 执行动作入口固定使用 `joint_action`。

`joint_state`、`endpose`、`camera_params` 保留用于审计、调试和后续扩展。

---

## 2. VLA 服务入口

VLA 侧需要提供一个可调用入口，接收 pick request，返回 action payload 或 error payload。

MVP 推荐入口：

```text
POST /v1/pick_sku
```

后续真机联调可升级为 ROS2 Action server，但业务 payload 保持本 contract 不变。

VLA 侧自行决定 Isaac Sim 生命周期：

- 可以预先启动 Isaac Sim，并让服务连接已有仿真。
- 也可以由服务在收到请求后启动或 reset Isaac scene。
- dimos 不关心仿真启动方式，只关心请求是否返回 action 或 error。
- 如果仿真未就绪，VLA 返回 `SIMULATION_NOT_READY`。

---

## 3. dimos -> VLA: pick_sku.request

### Message Type

```text
pick_sku.request
```

### 最小输入字段

```text
workspace.name
workspace.color
sku.name
sku.color
request_id
```

### JSON 示例

```json
{
  "request_id": "req-20260610-0001",
  "workspace": {
    "name": "table",
    "color": "blue"
  },
  "sku": {
    "name": "cube",
    "color": "red"
  }
}
```

### 字段约定

| 字段 | 必填 | 说明 |
|---|---:|---|
| `request_id` | 是 | dimos 生成，全链路追踪 |
| `workspace.name` | 是 | 工作区类型，如 `table` |
| `workspace.color` | 是 | 工作区颜色，如 `blue` |
| `sku.name` | 是 | 目标类型，如 `cube` |
| `sku.color` | 是 | 目标颜色，如 `red` |

### 函数形态约定

对齐双方口头 contract，dimos 侧任务入口可以映射为：

```python
execute_pick_task(
    workspace_name: str = "table",
    workspace_color: str = "blue",
    sku_name: str = "cube",
    sku_color: str = "red",
)
```

内部拆分：

```python
go_to_workspace(
    workspace_name: str = "table",
    workspace_color: str = "blue",
)

pick_sku(
    workspace_name: str = "table",
    workspace_color: str = "blue",
    sku_name: str = "cube",
    sku_color: str = "red",
)
```

说明：

- `go_to_workspace` 是 dimos/sys 内部导航步骤。
- `pick_sku` 是 dimos 发给 VLA 的结构化技能指令。
- `execute_pick_task` 是面向自然语言 agent 的任务级入口。

---

## 4. VLA -> dimos: pick_sku.action

### Message Type

```text
pick_sku.action
```

### 最小输出字段

```text
target_meta
joint_action
joint_state
endpose
camera_params
```

### JSON 示例

```json
{
  "request_id": "req-20260610-0001",
  "frame_idx": 0,
  "target_meta": {
    "target_object_id": "cube_red_on_blue_table",
    "object_type": "cube",
    "object_color": "red",
    "object_position": [0.42, -0.18, 0.83],
    "table_id": "table_blue",
    "table_color": "blue",
    "workspace_position": [1.20, 0.50, 0.00]
  },
  "joint_state": {
    "left_arm": [-1.5673, 1.0418, -1.5671, -1.0489, -0.0019, 0.00005, -0.0370],
    "left_gripper": 1.0,
    "right_arm": [-1.5708, -1.0471, 1.5708, -1.0478, -0.00007, -0.0047, 0.0219],
    "right_gripper": 1.0
  },
  "joint_action": {
    "left_arm": [-1.5675, 1.0425, -1.5670, -1.0477, -0.0019, 0.0050, -0.0122],
    "left_gripper": 1.0,
    "right_arm": [-1.5708, -1.0471, 1.5708, -1.0478, -0.00007, -0.0047, 0.0219],
    "right_gripper": 1.0
  },
  "endpose": {
    "left_endpose": [-0.5270, 0.1711, 1.2342, 0.0134, 0.7094, 0.7044, -0.0135],
    "left_gripper": 1.0,
    "right_endpose": [0.5302, 0.1690, 1.2371, -0.7051, 0.0080, -0.0080, -0.7089],
    "right_gripper": 1.0
  },
  "camera_params": {
    "head_camera": {
      "intrinsic": [[415.6921, 0.0, 320.0], [0.0, 415.6921, 240.0], [0.0, 0.0, 1.0]],
      "extrinsic": [],
      "cam2world": []
    }
  }
}
```

### VLA 必填字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `request_id` | 是 | 必须与 dimos request 一致 |
| `frame_idx` | 建议 | 动作帧序号 |
| `target_meta` | 是 | dimos 基础语义校验使用 |
| `target_meta.target_object_id` | 建议 | VLA 基于仿真真值解析出的目标对象唯一 ID |
| `target_meta.object_type` | 是 | 如 `cube` |
| `target_meta.object_color` | 是 | 如 `red` |
| `target_meta.object_position` | 建议 | VLA 基于仿真真值解析出的目标对象 position |
| `target_meta.table_id` | 建议 | VLA 基于仿真真值解析出的目标所在工作区 ID |
| `target_meta.table_color` | 是 | 如 `blue` |
| `target_meta.workspace_position` | 建议 | VLA 基于仿真真值解析出的工作区 position |
| `joint_action` | 是 | MVP ROS 执行动作入口 |
| `joint_state` | 建议 | 审计/调试 |
| `endpose` | 建议 | 审计/未来扩展 |
| `camera_params` | 建议 | 审计/未来扩展 |

---

## 5. VLA -> dimos: pick_sku.error

### Message Type

```text
pick_sku.error
```

### JSON 示例

```json
{
  "request_id": "req-20260610-0001",
  "error_code": "TARGET_NOT_FOUND",
  "message": "No red cube found on the blue table."
}
```

### 最小失败字段

```text
error_code
message
```

### 建议错误码

```text
TARGET_NOT_FOUND
WORKSPACE_NOT_FOUND
SIMULATION_NOT_READY
MODEL_INFERENCE_FAILED
ACTION_GENERATION_FAILED
INVALID_REQUEST
TIMEOUT
```

---

## 6. dimos 基础校验

dimos 收到 `pick_sku.action` 后校验：

```text
1. request_id 必须匹配当前任务。
2. target_meta 必须存在。
3. target_meta.object_type == sku.name。
4. target_meta.object_color == sku.color。
5. target_meta.table_color == workspace.color。
6. joint_action 必须存在。
```

通过后：

```text
dimos 不修改 VLA payload，直接原样发给 ROS action。
```

失败时：

```text
dimos 阻断 ROS action 下发，并返回 VLA_TARGET_MISMATCH 或 VLA_OUTPUT_INVALID。
```

---

## 7. dimos -> ROS 转发约束

dimos 转发给 ROS 的业务 payload 必须与 VLA 原始输出保持深度一致：

```text
validation_passed_payload == ros_submitted_payload
```

允许：

- 在 ROS action 外层 envelope 添加 `ros_goal_id`、`timeout_s`、`trace_id` 等传输字段。
- 记录日志和审计副本。

不允许：

- 改写 `target_meta`。
- 改写 `joint_action`。
- 改写 `joint_state`。
- 改写 `endpose`。
- 改写 `camera_params`。
- 在 dimos 内重新生成动作。

ROS action goal 外层示例：

```json
{
  "ros_goal_id": "ros-goal-id",
  "request_id": "req-20260610-0001",
  "timeout_s": 30.0,
  "payload": {
    "request_id": "req-20260610-0001",
    "frame_idx": 0,
    "target_meta": {},
    "joint_state": {},
    "joint_action": {},
    "endpose": {},
    "camera_params": {}
  }
}
```

其中 `payload` 必须是 VLA 原始输出。

