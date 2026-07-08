# 开发机 → 真机部署流程

本文说明 **dax-agent** 从开发机打包/同步到真机（如 136）的标准流程。真机安装路径默认 `/opt/dax-agent`，分支 **`deploy/dax-agent`**。

更完整的安装、架构与故障排查见 [`deploy/README.md`](../../deploy/README.md)。YAML 上半身（go_home/place）联调见 [`dax-skill-sdk-yaml-path.md`](./dax-skill-sdk-yaml-path.md)。

---

## 目录对照

| 开发机 | 分支 | 真机（136 示例） |
|--------|------|------------------|
| `~/Projects/dimos` | `main` | **不直接部署**（完整开发、笔记） |
| `~/Projects/dimos-deploy` | `deploy/dax-agent` | `/opt/dax-agent` |
| `~/Projects/dax_planner_ws-main` | — | `/home/nvidia/dax_planner_ws` |

**两条栈分开同步：**

- **DimOS agent**（`/opt/dax-agent`）：NL、MCP、adapter、`.env`
- **dax_planner_ws**（真机 `~/dax_planner_ws`）：`go_home.yaml` / `place.yaml`、ROS 包；改 YAML 时单独 `rsync` + `colcon build`

---

## 架构要点（部署时别混）

```text
┌─────────────────────────┐     gRPC      ┌──────────────────────────┐
│ dax-agent（uv .venv）    │ ────────────► │ rosbridge_grpc_server    │
│ 无 rclpy                │               │ source ROS + rclpy       │
└─────────────────────────┘               └──────────────────────────┘
         │ HTTP
         ▼
   dax_server（wave/head）
         │
         │ go_home/place（DAX_SKILL_EXECUTOR=subprocess）
         ▼
   ros2 run skill_executor（ROS 环境，非 venv 内 import dax_rf_planner）
```

- 真机 **不要** 在 `uv sync` 前 `source ROS`（会破坏 venv 隔离）。
- YAML 真机执行用 **`DAX_SKILL_EXECUTOR=subprocess`** + `deploy/run_ros2_skill_executor.sh`。

---

## 日常迭代（只改代码，依赖不变）

### 1. 开发机

```bash
cd ~/Projects/dimos-deploy    # 必须在 deploy/dax-agent 分支
# 开发、pytest …
git add …
git commit -m "feat(deploy): …"
git push origin deploy/dax-agent
```

若在 `~/Projects/dimos`（`main`）开发，需 **cherry-pick 或手动同步** 到 `dimos-deploy` 再 push。真机只跟踪 `deploy/dax-agent`。

### 2. 真机拉代码

**方式 A — git（推荐）**

```bash
ssh nvidia@10.69.6.136
cd /opt/dax-agent
git pull --ff-only origin deploy/dax-agent
```

**方式 B — rsync（无 git / 快速调试）**

```bash
# 开发机执行
rsync -avz ~/Projects/dimos-deploy/dimos/ \
  nvidia@10.69.6.136:/opt/dax-agent/dimos/
rsync -avz ~/Projects/dimos-deploy/config/ \
  nvidia@10.69.6.136:/opt/dax-agent/config/
rsync -avz ~/Projects/dimos-deploy/deploy/run_*.sh \
  nvidia@10.69.6.136:/opt/dax-agent/deploy/
chmod +x nvidia@10.69.6.136:/opt/dax-agent/deploy/run_*.sh
```

**不要 rsync：** 开发机 `.env`、开发机完整 `.venv`。

### 3. 重启 agent

**systemd：**

```bash
sudo systemctl restart dax-agent
```

或（真机已装 dimos CLI）：

```bash
cd /opt/dax-agent
.venv/bin/dimos deploy pull --restart --sudo
```

**前台调试（go_home/place 需要 ROS）：**

```bash
bash /opt/dax-agent/deploy/run_dax_agent_with_ros.sh
```

### 4. 冒烟

```bash
# A. subprocess dry-run（不 motion）
bash /opt/dax-agent/deploy/run_ros2_skill_executor.sh \
  /home/nvidia/dax_planner_ws/src/dax_skill_sdk/dax_skill_sdk/composite_skill/go_home.yaml \
  --dry-run

# B. MCP 回零（agent 必须在跑）
cd /opt/dax-agent
dimos mcp call execute_nl_task --arg text="回零"
# 或
.venv/bin/python scripts/mcp_client.py call execute_nl_task --arg text="回零"
```

日志：

```bash
grep -E 'go_home|composite_skill|dax_' ~/.local/state/dimos/logs/*/main.jsonl | tail -20
# systemd：tail -f /var/log/dax-agent/dax-agent.log
```

---

## 依赖变更（改了 `pyproject.toml`）

### 开发机

```bash
cd ~/Projects/dimos-deploy
uv lock --extra dax-agent
cp uv.lock deploy/uv.lock.dax-agent
git add pyproject.toml deploy/uv.lock.dax-agent
git commit -m "chore(deploy): relock dax-agent deps"
git push origin deploy/dax-agent
```

若 `[dax-agent]` 里 `py-rosbridge` 仍指向开发机路径，先改为 git 或真机本地路径再 lock（见 [`deploy/README.md`](../../deploy/README.md) §2）。

### 真机

```bash
cd /opt/dax-agent
git pull --ff-only origin deploy/dax-agent
cp deploy/uv.lock.dax-agent uv.lock    # 若仓库用 deploy lock 作真机源
bash deploy/uv-sync-robot.sh /opt/dax-agent
sudo systemctl restart dax-agent
```

---

## 首次部署（真机尚无 `/opt/dax-agent`）

```bash
# 真机
git clone -b deploy/dax-agent git@github.com:NIkok0/dimos.git /opt/dax-agent
cd /opt/dax-agent
cp deploy/dax-agent.env.example .env
vim .env    # DEEPSEEK_API_KEY、ROSBRIDGE_GRPC_TARGET、DAX_JOINT_*、DAX_SKILL_* …
bash deploy/uv-sync-robot.sh /opt/dax-agent
bash deploy/install.sh /opt/dax-agent   # 可选：systemd
```

### rsync 拷贝转 git（一次性）

若目录是 rsync 来的、没有 `.git`：

```bash
cd /opt/dax-agent
.venv/bin/dimos deploy init-git
# 之后用 git pull 升级
```

---

## 真机 `.env` 维护

| 规则 | 说明 |
|------|------|
| 模板在仓库 | `deploy/dax-agent.env.example` |
| 真机私有 | `/opt/dax-agent/.env` **不提交、不 rsync 覆盖** |
| 模板更新后 | 在真机 `.env` **手动合并** 新变量 |

136 go_home 常用片段：

```env
DAX_SKILL_ADAPTER=dax
DAX_SKILL_DRY_RUN=false
DAX_SKILL_EXECUTOR=subprocess
DAX_SKILL_ROS_SETUP=/opt/ros/humble/setup.bash
DAX_SKILL_SDK_WS=/home/nvidia/dax_planner_ws
DAX_SKILL_COMPOSITE_DIR=/home/nvidia/dax_planner_ws/src/dax_skill_sdk/dax_skill_sdk/composite_skill
DAX_SKILL_STEP_CONFIRM=false
LISTEN_HOST=0.0.0.0
DAX_JOINT_SERVER_URL=http://127.0.0.1:5000
DAX_ROBOT_JOINT_CONFIG_PATH=config/dax_robot_joint.yaml
MCP_TOOL_ALLOWLIST=execute_nl_task,wave,head_accept,head_reject
```

### 多机部署：按机器人区分的参数

| 配置方式 | 变量 / 文件 | 用途 |
|----------|-------------|------|
| `.env` | `DAX_JOINT_SERVER_URL` | dax_server HTTP 地址（同机常用 `127.0.0.1:5000`） |
| `.env` | `DAX_WAVE_ANIMATION_PATH` | 挥手动画 JSON 路径 |
| `.env` | `DAX_ROBOT_JOINT_CONFIG_PATH` | 每台机器人的 wave/head 关节 YAML |
| `.env` | `ROSBRIDGE_GRPC_TARGET` | rosbridge gRPC 地址 |
| `.env` | `DAX_SKILL_SDK_WS` / `DAX_SKILL_COMPOSITE_DIR` | YAML 复合技能 workspace |
| `.env` | `MCP_TOOL_ALLOWLIST` | 对外暴露的 MCP 工具列表 |
| YAML | `config/dax_robot_joint.yaml` | 默认模板；可复制为 `config/robots/<id>.yaml` 后改 `DAX_ROBOT_JOINT_CONFIG_PATH` |

每台新机器人：复制 `deploy/dax-agent.env.example` → `.env`，改 IP/路径；若关节零位不同，复制并编辑 `config/dax_robot_joint.yaml`（或单独 YAML），rsync 时带上 `config/`。

---

## dax_planner_ws 同步（YAML / SDK 变更）

仅当 `go_home.yaml`、`place.yaml` 或 SDK 代码变更时：

```bash
# 开发机 → 136
rsync -avz ~/Projects/dax_planner_ws-main/src/ \
  nvidia@10.69.6.136:~/dax_planner_ws/src/

# 136 上 build
ssh nvidia@10.69.6.136
source /opt/ros/humble/setup.bash
cd ~/dax_planner_ws
colcon build --packages-select dax_planner_executor dax_skill_sdk --symlink-install
```

DimOS agent 代码与 `dax_planner_ws` **独立版本**；只改 adapter 时不必 rebuild workspace。

---

## 外部 MCP / 语音触发回零

dax-agent **无内置 ASR**。外部语音系统：ASR → 文本 → MCP HTTP。

- **无** atomic MCP tool `go_home`；用 **`execute_nl_task(text="回零")`**
- MCP 白名单：`.env` 中 `MCP_TOOL_ALLOWLIST`（默认 `execute_nl_task,wave,head_accept,head_reject`）
- 外部调用示例：`http://10.69.6.136:9990/mcp`（需 `LISTEN_HOST=0.0.0.0`）

---

## 不要做的事

| ❌ | 原因 |
|----|------|
| 真机部署 `main` 分支 | 含非 deploy 内容，与真机约定不一致 |
| rsync 开发机 `.venv` | Python 版本/路径与真机 uv 隔离策略冲突 |
| 真机 `source ROS` 后 `uv sync` | ROS Python 混入 venv |
| 覆盖真机 `.env` | API key、IP 与开发机不同 |
| in-process YAML 真机（无 subprocess） | uv 3.12 无法 load `dax_rf_planner` / `rclpy` |

---

## 流程总览

```text
dimos-deploy 开发（deploy/dax-agent）
    │
    ├─ 仅代码 ──► push ──► 真机 git pull ──► restart agent ──► 冒烟
    │
    ├─ 依赖变更 ──► lock + push ──► 真机 pull + uv-sync-robot.sh ──► restart
    │
    └─ YAML/SDK ──► rsync dax_planner_ws ──► colcon build ──► dry-run go_home.yaml
```

---

## 相关命令速查

| 操作 | 命令 |
|------|------|
| 真机拉代码 | `git pull --ff-only origin deploy/dax-agent` |
| 重装 venv | `bash deploy/uv-sync-robot.sh /opt/dax-agent` |
| 带 ROS 启动 | `bash deploy/run_dax_agent_with_ros.sh` |
| YAML subprocess | `bash deploy/run_ros2_skill_executor.sh …/go_home.yaml --dry-run` |
| init-git | `dimos deploy init-git` |
| pull + restart | `dimos deploy pull --restart --sudo` |

---

## 延伸阅读

- [`deploy/README.md`](../../deploy/README.md) — 架构、install、VisBridge、升级 tag
- [`dax-skill-sdk-yaml-path.md`](./dax-skill-sdk-yaml-path.md) — go_home/place 测试阶梯
- [`blueprint-call-path.md`](./blueprint-call-path.md) — MCP → worker 调用链
