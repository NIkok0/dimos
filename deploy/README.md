# dax-agent 真机部署指南

本文档说明如何在机器人上部署 `deploy/dax-agent` 分支，以及 **uv（Python）与 ROS 2 如何隔离**。

## 架构：两层进程，互不混用

dax-agent **不需要**、也 **不应该** 在启动前 `source /opt/ros/.../setup.bash`。

```text
┌─────────────────────────────────────┐     gRPC :9091      ┌──────────────────────────────────┐
│  dax-agent 进程（uv .venv）          │ ──────────────────► │  rosbridge_grpc_server（ROS 环境） │
│  scripts/run_dax_agent.py           │   ROSBRIDGE_GRPC_   │  source /opt/ros/jazzy/setup.bash │
│  py_rosbridge 客户端（无 rclpy）     │   TARGET            │  rclpy / nav / pick 节点          │
└─────────────────────────────────────┘                     └──────────────────────────────────┘
         │ HTTP :5000
         ▼
   dax_server（关节/头部/挥手）
```

| 层 | 隔离方式 | 真机路径 |
|----|----------|----------|
| Python 依赖 | `uv sync --extra dax-agent` → 项目内 `.venv/` | `/opt/dax-agent/.venv` |
| DimOS 配置 | `.env`（pydantic-settings + dotenv） | `/opt/dax-agent/.env` |
| ROS 2 | 仅在 rosbridge server 进程内 source | 机器人现有 ROS 工作空间 |
| 代码版本 | `deploy/dax-agent` 分支 + `deploy/uv.lock.dax-agent` | `/opt/dax-agent` |

**要点：** dax-agent 只安装 `py-rosbridge`（gRPC 客户端），不安装 `rclpy`。导航/抓取通过 gRPC 调用远端 rosbridge server，ROS topic/service 名称写在 `.env` 里即可。

---

## 本目录文件

| 文件 | 用途 |
|------|------|
| [`dax-agent.env.example`](dax-agent.env.example) | 配置模板，复制为 `/opt/dax-agent/.env` |
| [`dax-agent.service`](dax-agent.service) | systemd 单元（自动重启、日志到 `/var/log/dax-agent/`） |
| [`install.sh`](install.sh) | 一键安装：uv sync + `.env` 模板 + systemd |
| [`run_dax_agent_with_ros.sh`](run_dax_agent_with_ros.sh) | 启动 agent 前 source ROS + dax_planner_ws（go_home/place YAML 必需） |
| [`uv.lock.dax-agent`](uv.lock.dax-agent) | pin 过的依赖 lock，真机安装前应复制为 `uv.lock` |

仓库根目录还有 **独立测试脚本**（不接入 `dimos` CLI）：

| 脚本 | 用途 |
|------|------|
| [`scripts/vis_bridge_probe.py`](../scripts/vis_bridge_probe.py) | 模拟一轮 `/vis/*` POST，**不经过 agent/LLM**，tool 不可用也能测前端 |
| [`scripts/mock_vis_frontend.py`](../scripts/mock_vis_frontend.py) | 本地 mock 前端，收 `/vis/input`、`/vis/thoughts`、`/vis/outputs` |

---

## 前置条件

- 机器人或部署机可访问 GitHub（SSH 或 HTTPS）
- 已安装 [uv](https://docs.astral.sh/uv/)（`install.sh` 会检查）
- **rosbridge gRPC server** 已在 ROS 环境中运行，监听 `9091`（或与 `.env` 中 `ROSBRIDGE_GRPC_TARGET` 一致）
- **dax_server** 已运行，HTTP 关节控制可访问（`DAX_JOINT_SERVER_URL`）
- 网络可达：`ROSBRIDGE_GRPC_TARGET`、`DAX_JOINT_SERVER_URL` 所指向的 IP

---

## 真机部署步骤

### 1. 克隆 deploy 分支

```bash
git clone -b deploy/dax-agent git@github.com:NIkok0/dimos.git /opt/dax-agent
cd /opt/dax-agent
```

使用 `deploy/dax-agent` 而非 `main`：已去掉个人笔记类 `.md`，含 deploy 专用 lockfile。

### 2. 处理 py-rosbridge 依赖（部署前必做）

[`pyproject.toml`](../pyproject.toml) 的 `[dax-agent]` extra 可能仍指向开发机路径：

```toml
"py-rosbridge @ file:///home/miaoli/Projects/py_rosbridge"
```

真机需改为可用来源，**任选其一**：

```toml
# 方案 A：git 依赖（推荐，可 pin tag/commit）
"py-rosbridge @ git+ssh://git@github.com/you/py_rosbridge.git@v0.1.1"

# 方案 B：真机本地 clone
"py-rosbridge @ file:///opt/py_rosbridge"
```

或在 `uv sync` 之后手动补装：

```bash
uv pip install -e /opt/py_rosbridge
```

修改后重新 lock 并更新 `deploy/uv.lock.dax-agent`（在开发机 `dimos-deploy` worktree 完成，push 后再在真机 pull）。

### 3. 用 uv 创建独立 Python 环境（逻辑最小集）

`deploy/dax-agent` 分支已将 `[project.dependencies]` 瘦身为 dax-agent 运行时最小核心；opencv / open3d / rerun / CLI 等移至 optional extra `heavy-base`（真机不装）。

```bash
cd /opt/dax-agent

# 推荐：清华源 + 隔离 .venv + 仅 dax-agent extra
bash deploy/uv-sync-robot.sh /opt/dax-agent

# 或 install.sh（内部调用 uv-sync-robot.sh）
# bash deploy/install.sh /opt/dax-agent
```

自定义 PyPI 镜像：`UV_DEFAULT_INDEX=https://pypi.org/simple bash deploy/uv-sync-robot.sh`

验证 **ROS 未混入 venv**：

```bash
.venv/bin/python -c "import py_rosbridge; print('py_rosbridge ok')"
.venv/bin/python -c "import rclpy" 2>&1 | grep -q ModuleNotFoundError && echo "rclpy 未安装 ✓"
```

### 4. 配置 `.env`

```bash
cp deploy/dax-agent.env.example .env
vim .env
```

**必填项：**

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | LLM API 密钥 |
| `DAX_JOINT_SERVER_URL` | dax_server HTTP 地址，如 `http://10.69.6.144:5000` |
| `ROSBRIDGE_GRPC_TARGET` | rosbridge gRPC 地址，如 `10.69.6.144:9091` |

**适配器（保持 gRPC 隔离）：**

```bash
VLA_PICK_ADAPTER=py_rosbridge
VLA_ROS_ADAPTER=py_rosbridge
VLA_SYS_NAV_ADAPTER=ros_topic
```

其余 `ROS_NAV_*`、`ROS_*_SERVICE` 为 topic/service **名称字符串**，不需要本机安装对应 ROS 包。

挥手动画 JSON（可选）：

```bash
DAX_WAVE_ANIMATION_PATH=/opt/dax-agent/data/dax_hi_ani.json
```

`install.sh` 会把 `scripts/dax_hi_ani.json` 复制到 `data/`（若不存在）。

### 5. 启动顺序

**先 ROS 侧（独立进程，需 source ROS）：**

```bash
source /opt/ros/jazzy/setup.bash
source ~/your_ws/install/setup.bash   # 含 robot_interfaces / dax_dimos_interfaces

# 启动 rosbridge_grpc_server（具体命令以机器人文档为准）
# 例：ros2 run rosbridge_grpc_server ...
```

**再 dax-agent（不要 source ROS）：**

```bash
cd /opt/dax-agent
.venv/bin/python scripts/run_dax_agent.py
```

### 6. systemd 自启动（可选）

```bash
bash deploy/install.sh /opt/dax-agent
sudo vim /opt/dax-agent/.env          # 确认配置
sudo systemctl enable --now dax-agent
sudo systemctl status dax-agent
tail -f /var/log/dax-agent/dax-agent.log
```

[`dax-agent.service`](dax-agent.service) 仅加载 `EnvironmentFile=/opt/dax-agent/.env`，**不含** `source /opt/ros/...`。若 rosbridge server 与 agent 同机，建议为 server 单独写 systemd unit。

---

## uv 与 ROS 对照表

| 操作 | dax-agent（`.venv`） | rosbridge server（ROS 环境） |
|------|----------------------|------------------------------|
| `source /opt/ros/jazzy/setup.bash` | 不需要 | **必须** |
| `uv sync --extra dax-agent` | **必须** | 不需要 |
| 安装 py-rosbridge | 是（gRPC 客户端） | server 由 ROS 栈提供 |
| 配置 `ROSBRIDGE_GRPC_TARGET` | 是 | server 监听对应端口 |
| 运行 `run_dax_agent.py` | 是 | 否 |
| 运行 rosbridge gRPC server | 否 | 是 |

---

## VisBridge / 前端测试（独立脚本）

真机 tool（wave、dax_server、rosbridge）暂时不可用时，仍可用下面脚本验证 **113 前端** 是否收到 `thoughts`（content）和 `outputs`（tool_calls）。脚本与 `dimos` CLI 无关，直接 `python scripts/...` 运行。

### 1. 探针：模拟一轮 VisBridge（推荐）

**在开发机或 136 上**（需能访问 `VIS_BRIDGE_URL`，默认 113:8765）：

```bash
cd /opt/dax-agent   # 或 dimos-deploy 源码目录

# 默认：input + 2 条 thoughts + wave tool_call（legacy 格式，113 前端当前 schema）
.venv/bin/python scripts/vis_bridge_probe.py \
  --url http://10.69.6.113:8765

# 自定义用户输入与 tool
.venv/bin/python scripts/vis_bridge_probe.py \
  --url http://10.69.6.113:8765 \
  --text "帮我挥挥手" \
  --tool wave

# 多个 tool：每个 tool 单独一轮 session（各自 /vis/input → thoughts → outputs）
.venv/bin/python scripts/vis_bridge_probe.py \
  --tool wave --tool execute_nl_task

# 仅文本，不发 /vis/outputs
.venv/bin/python scripts/vis_bridge_probe.py --no-tools

# 新 schema（顶层 tool_calls，113 升级后使用）
.venv/bin/python scripts/vis_bridge_probe.py --outputs-format flat
```

无 venv 时（需已装 `requests`）：

```bash
python3 scripts/vis_bridge_probe.py --url http://10.69.6.113:8765
```

**不会**调用 136/144 的 joint server，**不会**走 LLM。

### 2. 本地 mock 前端

在无 113 机器时，本机起一个 mock 收 POST：

```bash
# 终端 1
python scripts/mock_vis_frontend.py --port 8765

# 终端 2（另开目录或同一 repo）
python scripts/vis_bridge_probe.py --url http://127.0.0.1:8765
```

### 3. 走真 agent（会触发 LLM，可能调 tool）

在 **136** 上向 LCM `/human_input` 发消息，VisBridge 会推送到 113；若 LLM 选了 `wave` 等 tool，会打到 `DAX_JOINT_SERVER_URL`（`.env` 里配置，当前为 136:5000）。

```bash
ssh daxbot-136
mkdir -p /tmp/dimos-cli
cd /tmp
DIMOS_RUN_LOG_DIR=/tmp/dimos-cli /opt/dax-agent/.venv/bin/python -c "
from dimos.core.transport import pLCMTransport
t = pLCMTransport('/human_input')
t.start()
t.publish('你好，请介绍一下你自己')
t.stop()
print('ok')
"

# 查看 VisBridge 是否推送到 113
grep -i VisBridge /var/log/dax-agent/dax-agent.log | tail -10
```

仅测前端、不想动 joint server 时，用 **§1 探针**，不要用 §3。

---

## go_home / place YAML（dax_skill_sdk）

`deploy/dax-agent` 已接入 NL `go_home` → `GoHomeTemplate` → `DaxSkillSdkAdapter.go_home()` → `go_home.yaml`。
**YAML 真机必须在 ROS 环境中执行**（与 gRPC rosbridge 隔离层不同）。

**YAML 真机还需 venv 内 `scipy`**（`dax_skill_sdk` 加载 composite skill 时会 import 全部 atomic skill）。若报 `No module named 'scipy'`：

```bash
cd /opt/dax-agent
uv pip install --python .venv/bin/python 'scipy>=1.11.0'
# 或重新 sync：bash deploy/uv-sync-robot.sh /opt/dax-agent
```

**uv `.venv` 无法加载 `dax_rf_planner` / `rclpy`（Python 3.12 与 ROS 原生模块隔离）**。若报：

```text
DAX_SDK_UNAVAILABLE: ... No module named 'rf_collision_world.pyCollisionWorld'
```

在 `.env` 使用 **subprocess** 模式（经 `ros2 run`，与 CLI 真机一致）：

```env
DAX_SKILL_EXECUTOR=subprocess
DAX_SKILL_ROS_SETUP=/opt/ros/humble/setup.bash
```

并确保 `deploy/run_ros2_skill_executor.sh` 可执行。MCP/后台调用时建议 `DAX_SKILL_STEP_CONFIRM=false`（逐步确认需要 TTY）。

### 1. 真机 `.env`（136 示例）

```bash
vim /opt/dax-agent/.env
```

```env
DAX_SKILL_ADAPTER=dax
DAX_SKILL_DRY_RUN=false
DAX_SKILL_STEP_CONFIRM=true
DAX_SKILL_SDK_WS=/home/nvidia/dax_planner_ws
DAX_SKILL_COMPOSITE_DIR=/home/nvidia/dax_planner_ws/src/dax_skill_sdk/dax_skill_sdk/composite_skill
DAX_SKILL_EXECUTOR=subprocess
DAX_SKILL_ROS_SETUP=/opt/ros/humble/setup.bash
DAX_SKILL_STEP_CONFIRM=false
```

### 2. 开发机改 deploy 分支 → 同步到 136

```bash
# 开发机 dimos-deploy worktree
cd ~/Projects/dimos-deploy
git add dimos/agents/task_action_plan.py dimos/agents/vla_pick_adapter_factory.py \
  dimos/agents/nl/ config/nl_semantics.yaml deploy/
git commit -m "feat(deploy): wire NL go_home to DaxSkillSdkAdapter"
git push origin deploy/dax-agent

# 136 真机
cd /opt/dax-agent
git pull --ff-only origin deploy/dax-agent
# 或 rsync（无 git 时）:
# rsync -avz ~/Projects/dimos-deploy/dimos/ nvidia@10.69.6.136:/opt/dax-agent/dimos/
# rsync -avz ~/Projects/dimos-deploy/config/ nvidia@10.69.6.136:/opt/dax-agent/config/
```

验证代码已到位：

```bash
grep GoHomeTemplate /opt/dax-agent/dimos/agents/task_action_plan.py
grep go_home /opt/dax-agent/config/nl_semantics.yaml
```

### 3. 带 ROS 启动 agent

```bash
chmod +x /opt/dax-agent/deploy/run_dax_agent_with_ros.sh
bash /opt/dax-agent/deploy/run_dax_agent_with_ros.sh
```

### 4. 发回零

**步骤 A — subprocess dry-run**（验证 ROS + YAML，不 motion）：

```bash
bash /opt/dax-agent/deploy/run_ros2_skill_executor.sh \
  /home/nvidia/dax_planner_ws/src/dax_skill_sdk/dax_skill_sdk/composite_skill/go_home.yaml \
  --dry-run
```

**步骤 B — NL 回零**（需 agent 已启动，`DAX_SKILL_EXECUTOR=subprocess`）：

```bash
cd /opt/dax-agent
dimos mcp call execute_nl_task --arg text="回零"
# 或
dimos agent-send "回零"
# 无 dimos 在 PATH 时：
.venv/bin/python scripts/mcp_client.py call execute_nl_task --arg text="回零"
```

日志：`grep -E 'go_home|composite_skill|dax_' /var/log/dax-agent/dax-agent.log | tail -20`

详见 [`docs/coding-agents/dax-skill-sdk-yaml-path.md`](../docs/coding-agents/dax-skill-sdk-yaml-path.md)。

---

## 联调检查

```bash
cd /opt/dax-agent

# 1. gRPC 连通（venv 内，无需 ROS）
.venv/bin/python -c "
from py_rosbridge import RosbridgeClient
c = RosbridgeClient('10.69.6.136:9091', ready_timeout_s=10)
c.connect(); print('gRPC ok'); c.close()
"

# 2. 前台启动 agent
.venv/bin/python scripts/run_dax_agent.py

# 3. MCP 探活（另开终端）
.venv/bin/python scripts/mcp_client.py list
# 或：curl http://localhost:9990/mcp  （视 MCP 配置而定）
```

**常见故障：**

| 现象 | 排查 |
|------|------|
| gRPC 超时 / 连接失败 | VPN/网段、`ROSBRIDGE_GRPC_TARGET`、server 是否在 ROS 环境中已启动 |
| `import py_rosbridge` 失败 | py-rosbridge 路径未改、`uv sync` 未成功 |
| 导航/抓取无响应 | `.env` 中 topic/service 名与真机不一致 |
| MCP 9990 不可达 | `LISTEN_HOST=0.0.0.0`、防火墙 |

---

## 升级

**方式 A — rsync 部署转 git（首次）：**

若 `/opt/dax-agent` 是 rsync 拷贝、没有 `.git`：

```bash
cd /opt/dax-agent
.venv/bin/dimos deploy init-git
# 自定义 remote：dimos deploy init-git --remote git@github.com:you/dimos.git
```

**方式 B — 日常拉代码并重启：**

```bash
cd /opt/dax-agent
.venv/bin/dimos deploy pull --restart --sudo
```

等价于：

```bash
git pull --ff-only origin deploy/dax-agent
sudo systemctl restart dax-agent
```

依赖变更时重新 sync venv：

```bash
bash deploy/uv-sync-robot.sh /opt/dax-agent
.venv/bin/dimos deploy pull --restart --sudo
```

**方式 C — 纯 git（手动）：**

```bash
cd /opt/dax-agent
git fetch origin
git checkout deploy/dax-agent   # 或 tag：git checkout dax-agent-v1
git pull

bash deploy/uv-sync-robot.sh /opt/dax-agent
sudo systemctl restart dax-agent
```

---

## 开发机与真机的关系

开发机可用 git worktree 并排维护两个目录（共享同一 `.git`）：

| 目录 | 分支 | 用途 |
|------|------|------|
| `~/Projects/dimos` | `main` | 完整开发、个人笔记 |
| `~/Projects/dimos-deploy` | `deploy/dax-agent` | 与真机同分支，改 deploy 脚本 / lock / `.env.example` |

流程：在 `dimos-deploy` 改完 → push `deploy/dax-agent` → 真机 `git pull` → `uv sync --frozen` → `systemctl restart dax-agent`。

**逐步说明（git/rsync、依赖 lock、冒烟、`.env` 规则）见 [`docs/coding-agents/deploy-to-robot.md`](../docs/coding-agents/deploy-to-robot.md)。**

---

## Voyager 架构设计（Minecraft LLM Agent 参考）

Voyager（[MineDojo/Voyager](https://github.com/MineDojo/Voyager)）是论文 *Voyager: An Open-Ended Embodied Agent with Large Language Models* 的开源实现：在 **Minecraft** 里用 **GPT-4 黑盒调用**（无微调）做开放-ended 终身学习。本地安装与启动见 `~/Projects/Voyager/deploy/README.md`。

### 总体分层

Voyager 与 dax-agent 一样采用 **「Python 编排 + 独立运行时」** 两层，但运行时不是 ROS，而是 **Node mineflayer + Minecraft 游戏进程**：

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  Python：Voyager 主类（voyager/voyager.py）                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │CurriculumAgent│ │ ActionAgent  │ │ CriticAgent  │ │  SkillManager    │  │
│  │ 自动课程      │ │ 代码生成+迭代 │ │ 任务成败判定  │ │ 技能库 Chroma DB │  │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘  │
│         │    LangChain ChatOpenAI / OpenAIEmbeddings（OpenAI API）           │
│         └──────────────────┬───────────────────────────────────────────────┘  │
│                            │ HTTP POST（gym step）                            │
│  ┌─────────────────────────▼───────────────────────────────────────────────┐  │
│  │  VoyagerEnv（voyager/env/bridge.py）                                     │  │
│  │  SubprocessMonitor: node mineflayer/index.js :3000                       │  │
│  │  MinecraftInstance（可选 Azure Login 自动拉起 MC + LAN）                  │  │
│  └─────────────────────────┬───────────────────────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────────────────────┘
                             │ mineflayer 协议
                             ▼
                    ┌─────────────────┐
                    │ Minecraft 1.19  │
                    │ + Fabric mods   │
                    └─────────────────┘
```

| 层 | 技术 | 隔离方式 |
|----|------|----------|
| Python 依赖 | `uv venv` + `langchain==0.0.354` | 项目内 `.venv/` |
| LLM | OpenAI GPT-4 / GPT-3.5（API Key） | 无本地模型 |
| 环境桥接 | `VoyagerEnv` HTTP → mineflayer | Node 子进程 `:3000` |
| 游戏 | Minecraft Java + Fabric | 独立进程 / Azure 拉起 |
| 持久化 | `ckpt/`（JSON + Chroma vectordb） | 本地目录 |

### 四大 Agent 组件（论文对应关系）

| 组件 | 类 | 论文概念 | 职责 |
|------|-----|----------|------|
| 自动课程 | `CurriculumAgent` | Automatic Curriculum | 根据背包/生物群系/已完成任务等观测，**提出下一子任务**；维护 completed/failed 列表；Chroma 缓存 QA |
| 动作执行 | `ActionAgent` | Iterative Prompting | 调用 GPT-4 生成 **JavaScript 控制代码**（基于 `control_primitives`）；多轮迭代直到 Critic 通过或达 retry 上限 |
| 自我验证 | `CriticAgent` | Self-Verification | 读环境 observation（物品栏、血量、错误日志等），**判定当前子任务是否成功** |
| 技能库 | `SkillManager` | Skill Library | 成功 rollout 后 **add_new_skill**；向量检索 top-k 技能注入 ActionAgent prompt；技能为可复用 JS 函数 |

底层动作原语在 `voyager/control_primitives/*.js`（如 `mineBlock`、`craftItem`、`exploreUntil`），由 mineflayer bot 在 MC 内执行。

### 核心循环

**1. 终身学习 `learn()`**

```text
env.reset(hard/soft)
  └─ while iteration < max_iterations:
       curriculum.propose_next_task(last_events)  → task, context
       rollout(task):
         reset → while not done:
           ActionAgent.llm → 解析 program_code
           env.step(code)  → mineflayer 执行 JS，返回 events
           CriticAgent.check_task_success(events)
           失败则把 critique 写回 prompt，重试（最多 task_max_retries）
       成功 → skill_manager.add_new_skill(info)
       curriculum.update_exploration_progress(info)
       last_events = events
```

**2. 指定任务推理 `inference(sub_goals)`**

加载已有 `skill_library_dir`（如 `skill_library/trial3`），`decompose_task` 拆分子目标后，对每个 sub_goal 跑同样的 `rollout`，**不再写入新技能**（`resume=False`）。

### 观测与执行路径

```text
ActionAgent 生成 JS
    → VoyagerEnv.step(code, programs=skill_manager.programs)
    → HTTP POST mineflayer server
    → bot 在 MC 中执行（chat / dig / craft …）
    → 回调 observation：inventory, voxels, status, onError, onChat …
    → 拼进 HumanMessage 反馈给 ActionAgent
```

`env_request_timeout`（默认 600s）防止 GPT 生成死循环；Azure Login 模式下超时后可 **自动 resume** MC 进程。

### 与 dax-agent 架构对照

| 维度 | Voyager | dax-agent（本仓库 deploy 分支） |
|------|---------|-----------------------------------|
| 物理世界 | Minecraft 仿真 | 真机（Unitree / xArm 等） |
| 运行时隔离 | Python ↔ Node mineflayer | Python ↔ gRPC rosbridge（ROS 在 server 进程） |
| LLM 用法 | LangChain 多 Agent，生成 **JS 代码** | LangGraph + MCP，调用 **@skill 工具** |
| 技能存储 | Chroma + `skills.json`（JS 函数） | MCP tool registry + skill containers |
| 前端展示 | 无（CLI 日志） | VisBridge → `/vis/*` REST（113 前端） |
| 配置 | 代码参数 + `OPENAI_API_KEY` | `.env` + GlobalConfig |
| 部署 | 开发机 + MC 客户端 | `/opt/dax-agent` + systemd |

两者共同点：**Python 侧只做编排与 LLM，重运行时（MC / ROS）在独立进程，通过 RPC/HTTP 通信，venv 不混入运行时依赖。**

### 目录速查（Voyager 源码）

| 路径 | 作用 |
|------|------|
| `voyager/voyager.py` | 主类：`learn` / `rollout` / `inference` |
| `voyager/agents/` | 四个 Agent |
| `voyager/env/bridge.py` | Gym 环境 + mineflayer 子进程 |
| `voyager/env/mineflayer/` | Node mineflayer 服务 |
| `voyager/control_primitives/` | 基础 JS 原语 |
| `voyager/prompts/*.txt` | 各 Agent 的 prompt 模板 |
| `skill_library/` | 预训练技能库（trial1–3） |
| `ckpt/` | 运行时 checkpoint（默认） |
| `deploy/` | uv 安装、`.env` 模板、`run_learn.py` |

---

## 维护：重新生成 lockfile

在开发机 `dimos-deploy` worktree 中（改完 `pyproject.toml` 后）：

```bash
uv lock --extra dax-agent
cp uv.lock deploy/uv.lock.dax-agent
git add deploy/uv.lock.dax-agent pyproject.toml
git commit -m "chore(deploy): relock dax-agent deps"
git push origin deploy/dax-agent
```

---

## Tag 参考

| Tag | 说明 |
|-----|------|
| `dax-agent-v1` | 首个真机 deploy 发布 |

```bash
git clone -b deploy/dax-agent ... /opt/dax-agent
cd /opt/dax-agent && git checkout dax-agent-v1
```
