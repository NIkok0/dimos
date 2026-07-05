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
| [`uv.lock.dax-agent`](uv.lock.dax-agent) | pin 过的依赖 lock，真机安装前应复制为 `uv.lock` |

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

## 联调检查

```bash
cd /opt/dax-agent

# 1. gRPC 连通（venv 内，无需 ROS）
.venv/bin/python -c "
from py_rosbridge import RosbridgeClient
c = RosbridgeClient('10.69.6.144:9091', ready_timeout_s=10)  # 改为你的 IP
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

```bash
cd /opt/dax-agent
git fetch origin
git checkout deploy/dax-agent   # 或 tag：git checkout dax-agent-v1
git pull

cp deploy/uv.lock.dax-agent uv.lock
uv sync --frozen --extra dax-agent

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
