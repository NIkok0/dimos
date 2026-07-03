# 自然语言拆解与技能任务组合需求拆分

## 1. Summary

采用 **独立 Parser / Planner 架构**。

MVP 只支持单任务 pick，但架构预留长程任务扩展能力。

自然语言不直接驱动 VLA，也不直接暴露多个原子技能给 LLM。系统先把自然语言解析成结构化 intent，再由 planner 拆成原子技能计划，最后由 orchestrator 顺序执行。

```text
Natural Language
  -> Intent Parser
  -> Task Planner / Decomposer
  -> Skill Orchestrator
  -> Atomic Skill Adapters
```

MVP 支持：

```text
去蓝色桌子的工作区，抓取红色 cube
```

解析为：

```json
{
  "intent_type": "pick_sku",
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

规划为：

```text
go_to_workspace(table, blue)
pick_sku(table, blue, cube, red)
```

## 2. 对外任务入口

MVP 对 agent / MCP 暴露一个任务级 skill：

```python
execute_pick_task(
    workspace_name: str = "table",
    workspace_color: str = "blue",
    sku_name: str = "cube",
    sku_color: str = "red",
)
```

该 skill 是 composite skill，不是 VLA 原子动作。

内部执行：

```text
go_to_workspace
  -> pick_sku
  -> receive VLA payload
  -> basic validation
  -> forward to ROS
```

约束：

- `execute_pick_task` 是面向自然语言 agent 的任务级入口。
- `go_to_workspace` 和 `pick_sku` 第一版作为内部原子能力，不直接暴露给 LLM。
- LLM 不直接控制任务步骤顺序。
- VLA 不接收自然语言。

## 3. Intent Parser

Intent Parser 是独立模块。

职责：

- 接收自然语言。
- 输出结构化 intent。
- 不调用 sys。
- 不调用 VLA。
- 不生成 ROS action。

MVP 只支持 `pick_sku` intent。

输出格式：

```json
{
  "request_id": "req-xxx",
  "raw_instruction": "去蓝色桌子的工作区，抓取红色 cube",
  "intent_type": "pick_sku",
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

失败情况：

```text
NEED_CLARIFICATION
UNSUPPORTED_INTENT
INVALID_SLOT
```

示例：

```text
输入：去蓝色桌子的工作区，抓取红色 cube
输出：pick_sku(table, blue, cube, red)
```

```text
输入：抓取红色 cube
输出：NEED_CLARIFICATION，缺少 workspace color
```

```text
输入：去蓝色桌子擦桌面
输出：UNSUPPORTED_INTENT
```

## 4. Task Planner / Decomposer

Task Planner 是独立模块。

职责：

- 接收结构化 intent。
- 输出有序 skill plan。
- 不执行动作。
- 不调用 VLA。
- 不调用 ROS。

MVP `pick_sku` 规划结果：

```json
{
  "request_id": "req-xxx",
  "plan": [
    {
      "step_id": "step-1",
      "skill": "go_to_workspace",
      "args": {
        "workspace_name": "table",
        "workspace_color": "blue"
      }
    },
    {
      "step_id": "step-2",
      "skill": "pick_sku",
      "args": {
        "workspace_name": "table",
        "workspace_color": "blue",
        "sku_name": "cube",
        "sku_color": "red"
      }
    }
  ]
}
```

MVP 规划规则：

- `pick_sku` intent 固定拆成两个步骤：
  - `go_to_workspace`
  - `pick_sku`
- `pick_sku` 必须在 `go_to_workspace` 成功后执行。
- Planner 只生成计划，不处理执行状态。

后续长程任务可以扩展为：

```text
go_to_workspace
pick_sku
go_to_workspace
place_sku
```

但 MVP 不实现 `place_sku`。

## 5. Skill Orchestrator

职责：

- 顺序执行 planner 输出的 skill plan。
- 管理状态机。
- 处理失败、取消、超时。
- 保证 `pick_sku` 必须在 `go_to_workspace` 成功后执行。
- 负责将 VLA 输出交给 Basic Validation Gateway。
- 校验通过后，将 VLA 原始 payload 交给 ROS Action Adapter。

MVP 状态机：

```text
IDLE
  -> PARSING
  -> PLANNING
  -> EXECUTING_GO_TO_WORKSPACE
  -> EXECUTING_PICK_SKU
  -> VALIDATING_VLA_OUTPUT
  -> FORWARDING_TO_ROS
  -> SUCCEEDED
  -> FAILED
  -> TIMEOUT
  -> CANCELLED
```

失败规则：

- Parser 失败：不进入 planner。
- Planner 失败：不执行技能。
- `go_to_workspace` 失败：不调用 VLA。
- `pick_sku` / VLA 失败：不调用 ROS。
- VLA 基础校验失败：不调用 ROS。
- ROS 失败：任务失败并返回 ROS 原因。

## 6. Atomic Skill Adapters

MVP 原子技能包括两个。

### 6.1 go_to_workspace

```python
go_to_workspace(
    workspace_name: str,
    workspace_color: str,
)
```

职责：

- 调用 sys 导航到目标工作区。
- 返回 `arrived / failed / timeout / cancelled`。
- 不调用 VLA。
- 不调用 ROS action。

示例输入：

```json
{
  "workspace_name": "table",
  "workspace_color": "blue"
}
```

示例输出：

```json
{
  "status": "arrived",
  "workspace": {
    "name": "table",
    "color": "blue"
  }
}
```

### 6.2 pick_sku

```python
pick_sku(
    workspace_name: str,
    workspace_color: str,
    sku_name: str,
    sku_color: str,
)
```

职责：

- 按 `vla_pick_sku_contract.md` 调用 VLA。
- 只发送 name/color/request_id。
- 接收 VLA payload。
- 不修改 VLA payload。

dimos -> VLA 最小输入：

```json
{
  "request_id": "req-xxx",
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

VLA -> dimos 最小输出：

```json
{
  "request_id": "req-xxx",
  "target_meta": {},
  "joint_action": {},
  "joint_state": {},
  "endpose": {},
  "camera_params": {}
}
```

## 7. Basic Validation Gateway

职责：

- 校验 VLA 输出是否和用户目标一致。
- 校验通过后不修改 payload。
- 校验失败时阻断 ROS 下发。

MVP 校验规则：

```text
1. request_id 必须匹配当前任务。
2. target_meta 必须存在。
3. target_meta.object_type == sku.name。
4. target_meta.object_color == sku.color。
5. target_meta.table_color == workspace.color。
6. joint_action 必须存在。
```

强约束：

```text
validation_passed_payload == ros_submitted_payload
```

## 8. 与 VLA Contract 的关系

VLA 通信 contract 以当前目录下的 `vla_pick_sku_contract.md` 为准。

本需求文件只定义：

- 自然语言如何变成 intent。
- intent 如何变成 skill plan。
- skill plan 如何由 orchestrator 执行。
- `pick_sku` 何时调用 VLA。

`vla_pick_sku_contract.md` 定义：

- dimos -> VLA 的消息字段。
- VLA -> dimos 的动作输出字段。
- VLA error 返回格式。
- dimos -> ROS 原样转发约束。

## 9. Test Plan

### 9.1 Parser Tests

- “去蓝色桌子的工作区，抓取红色 cube”解析为 `pick_sku` intent。
- 缺少 workspace color 时返回 `NEED_CLARIFICATION`。
- 缺少 sku color 时返回 `NEED_CLARIFICATION`。
- 不支持任务如“擦桌子”返回 `UNSUPPORTED_INTENT`。

### 9.2 Planner Tests

- `pick_sku` intent 生成两个步骤：
  - `go_to_workspace`
  - `pick_sku`
- Planner 不输出 ROS action。
- Planner 不输出 VLA payload。
- 不支持 intent 返回 `UNSUPPORTED_INTENT`。

### 9.3 Orchestrator Tests

- `go_to_workspace` 成功后才调用 `pick_sku`。
- `go_to_workspace` 失败时不调用 VLA。
- VLA 返回目标一致 payload 时进入 ROS 转发。
- VLA 返回目标不一致 payload 时阻断 ROS。
- ROS 返回 rejected 时任务失败。
- 成功链路返回 `SUCCEEDED`。

### 9.4 Contract Tests

- `pick_sku` 发给 VLA 的 payload 只包含：
  - `request_id`
  - `workspace.name`
  - `workspace.color`
  - `sku.name`
  - `sku.color`
- VLA payload 校验通过后原样发给 ROS。
- `validation_passed_payload == ros_submitted_payload`。

## 10. Assumptions

- MVP 只支持 `pick_sku` 单任务。
- 暂不实现 `place_sku` / multi-step long-horizon task。
- Parser 可以先由 LLM structured output 或规则 mock 实现，但模块边界必须独立。
- Planner 第一版是确定性映射：`pick_sku intent -> go_to_workspace + pick_sku`。
- `execute_pick_task` 是对 agent 暴露的 composite skill。
- `go_to_workspace` 和 `pick_sku` 第一版作为内部原子能力，不直接暴露给 LLM。
- VLA contract 以 `vla_pick_sku_contract.md` 为准。
