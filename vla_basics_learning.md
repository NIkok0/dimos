# VLA 学习路线 v2：概念、论文、项目与实验

> 面向：准备系统进入 VLA / 机器人学习 的工程师（ROS2 基础见 [ros2_basics_jazzy.md](./ros2_basics_jazzy.md)）  
> 目标：不是第一天就训练 7B 模型，而是建立 **可验证、可复现、可集成** 的知识栈  
> 阅读时间：概念 2–3 天 → 数据与工具 1 周 → 轻量实验 2 周 → 仿真/ROS 集成 2–4 周

---

## 0. 先建立「地图」：你在学什么

VLA（Vision-Language-Action）不是单一模型，而是一类 **把感知 + 语言 + 控制统一建模** 的机器人策略范式。

```text
Observation (images, proprio, language)
        ↓
   Policy / VLA
        ↓
   Action (joint / EEF / gripper / action chunk)
        ↓
   Controller + Safety Layer + Robot / Sim
```

**和 dimos 项目的关系（工程视角）：**

| 层 | dimos MVP 现状 | 典型 VLA 栈 |
|----|----------------|-------------|
| NL → 结构化任务 | dimos parse + catalog | 可用 LLM，也可规则层 |
| 导航到工作区 | Mock adapter | 真实 motion planning / nav stack |
| V→A 推理 | HTTP `POST /pick_sku` | GPU policy server（OpenVLA / π0 等） |
| 输出校验 | `target_meta` + `joint_action` | 同上，或 action space 校验 |
| 执行 | Mock ROS adapter | `joint_trajectory` / custom action |

dimos 当前是 **系统编排 + contract 校验** 路线；VLA 模型训练是另一条深线——两者最终在 ROS / 控制器处汇合。

---

## 1. VLA 是什么（精确定义）

### 1.1 输入 / 输出

**输入（Observation）：**

- **Vision**：RGB、多相机、有时 depth / point cloud
- **Language**：任务指令（"pick the red cube"）或 goal image
- **Proprioception**：关节角、夹爪、末端位姿、历史帧

**输出（Action）：**

- 单步动作，或 **action chunk**（一次预测 H 步，如 50Hz×0.5s）
- 常见空间：关节位置/速度、末端 delta pose、离散 token 化的 action

### 1.2 一句话

```text
VLA = 看见 + 听懂 + 输出可执行动作（不是输出文字计划）
```

### 1.3 必须时刻追问的四个工程问题

```text
1. 输入是什么？（几路相机？state 维度？指令是否每步固定？）
2. 输出是什么？（joint 还是 EEF？绝对还是 delta？是否 chunk？）
3. 数据从哪来？（teleop / sim / OXE / 自采？）
4. 动作发给谁？（ROS topic？SDK？频率？安全层？）
```

答不清这四个问题，不要开始训练。

---

## 2. 领域坐标：VLA 在机器人学习中的位置

```text
                    需要 reward 设计
                          ↑
                     RL / RLHF
                          |
    CV/VLM 预训练 --------+-------- Imitation Learning (BC)
         |                |                |
         v                v                v
      语义理解        Generalist         小任务 specialist
      (RT-2等)        Policy (Octo)      (Diffusion Policy)
         |                |                |
         └─────── VLA / Robot Foundation Model ───────┘
                          |
                    部署：policy server + ROS + safety
```

| 范式 | 核心思想 | 代表 | 新手友好度 |
|------|----------|------|------------|
| **Behavior Cloning (BC)** | 模仿专家轨迹 | ACT, Diffusion Policy | ⭐⭐⭐⭐⭐ |
| **Generalist Robot Policy** | 大数据预训练 + 微调 | Octo, OpenVLA | ⭐⭐⭐ |
| **VLA（VLM + Action）** | 复用互联网 VLM 语义 | RT-2, OpenVLA, π0 | ⭐⭐ |
| **Flow / Diffusion Action** | 连续动作生成 | Diffusion Policy, π0, Octo | ⭐⭐⭐ |

**推荐学习顺序：**

```text
BC / Diffusion Policy（懂 data & action）
  → Open X-Embodiment（懂 cross-embodiment 数据）
  → Octo / OpenVLA（懂 generalist + finetune）
  → π0 / LingBot-VLA（懂现代 VLA 架构与部署）
  → Isaac + ROS2 集成（懂 sim-to-real 工程）
```

---

## 3. 核心概念速查

### 3.1 Episode / Timestep / Dataset

```text
Dataset
  └── Episode（一次完整任务）
        └── Timestep t
              ├── image(s)
              ├── proprio state
              ├── language instruction
              └── action（专家或 policy 输出）
```

机器人数据集 **不是** ImageNet。它是时序、多模态、带 embodiment 元数据的。

### 3.2 Action space（最容易踩坑）

| 类型 | 含义 | 典型项目 |
|------|------|----------|
| Joint position | 目标关节角 | RT-1, many sim benchmarks |
| EEF delta pose | 末端增量 6D + gripper | Diffusion Policy, many teleop |
| Action tokens | 离散化后当 text token 预测 | RT-2, OpenVLA |
| Flow-matched continuous | 连续向量场回归 | π0 |

**同一任务在不同项目里 action 格式可能完全不兼容。**

### 3.3 Policy 推理循环

```python
while task_running:
    obs = read_cameras_and_state()
    action = policy.infer(obs, instruction)  # 可能返回 chunk
    for step in action_chunk:
        send_to_controller(step)  # 经过 safety filter
        sleep(control_period)
```

---

## 4. 专家推荐学习路线（6 阶段）

每阶段给出：**目标 / 必读 / 必做实验 / 通过标准**。

---

### 阶段 0：机器人学习最小前置（3–5 天）

**目标：** 理解模仿学习闭环，不碰大模型。

| 类型 | 资源 |
|------|------|
| 课程 | [CS285 Deep RL（Berkeley）](https://rail.eecs.berkeley.edu/deeprlcourse/) — 重点 Lec 1–5 imitation / BC |
| 论文 | [End-to-End Training of Deep Visuomotor Policies（Sergey Levine 经典）](https://arxiv.org/abs/1504.00702) |
| 工具 | [Robomimic 文档](https://robomimic.github.io/docs/introduction/overview.html) |

**实验：** 用 Robomimic 或 LeRobot 打开一个 hdf5 episode，打印 `obs/action` shape。

**通过标准：** 能画出一条 episode 的时间轴，标出 grasp 发生时刻。

---

### 阶段 1：模仿学习与 Action 生成（1–2 周）

**目标：** 理解「不用 VLM 也能做 manipulation」的 strong baseline。

| 优先级 | 论文 | 链接 |
|--------|------|------|
| ⭐⭐⭐ | Diffusion Policy | [arXiv:2303.04137](https://arxiv.org/abs/2303.04137) · [Project](https://diffusion-policy.cs.columbia.edu/) · [GitHub](https://github.com/real-stanford/diffusion_policy) |
| ⭐⭐⭐ | ACT (Action Chunking Transformer) | [arXiv:2304.00279](https://arxiv.org/abs/2304.00279) · [Project](https://act-plus-plus.github.io/) |
| ⭐⭐ | RoboMimic | [arXiv:2108.03265](https://arxiv.org/abs/2108.03265) · [GitHub](https://github.com/ARISE-Initiative/robomimic) |

**工具：**

- [LeRobot GitHub](https://github.com/huggingface/lerobot)
- [LeRobot 文档](https://huggingface.co/docs/lerobot)
- [LeRobot Diffusion Policy 示例](https://huggingface.co/docs/lerobot/en/policy_diffusion)

**实验：**

1. LeRobot 加载公开 dataset（如 `lerobot/aloha_sim_insertion_human`）
2. 跑通 **eval only**（不训练）：观察 action 维度和频率
3. 在 ManiSkill / robosuite 回放 scripted policy

**通过标准：** 能解释 Diffusion Policy 与 ACT 在「单步 vs chunk」上的区别。

---

### 阶段 2：VLA 范式与 Cross-Embodiment 数据（1 周）

**目标：** 理解为什么 VLA 需要 VLM 预训练 + 大规模机器人数据。

| 优先级 | 工作 | 链接 |
|--------|------|------|
| ⭐⭐⭐ | RT-1 | [arXiv:2212.06817](https://arxiv.org/abs/2212.06817) · [Robotics at Google](https://github.com/google-research/robotics_transformer) |
| ⭐⭐⭐ | RT-2 | [arXiv:2307.15818](https://arxiv.org/abs/2307.15818) · [Project](https://rt2-anon.github.io/) |
| ⭐⭐⭐ | Open X-Embodiment / RT-X | [arXiv:2310.08864](https://arxiv.org/abs/2310.08864) · [Dataset](https://robotics-transformer-x.github.io/) |
| ⭐⭐ | PaLM-E | [arXiv:2303.03378](https://arxiv.org/abs/2303.03378) — 理解 embodied VLM 脉络 |

**阅读顺序：** RT-1（系统）→ OXE（数据）→ RT-2（VLA 叙事）→ 再读 OpenVLA

**实验：** 浏览 [Open X-Embodiment on Hugging Face](https://huggingface.co/datasets/openx-embodiment) 的 schema，看 `steps/observation/action` 字段。

**通过标准：** 能解释 action tokenization vs continuous action 两条技术路线。

---

### 阶段 3：开源 VLA 可动手项目（2–3 周）

**目标：** 跑通 inference / 小规模 finetune，建立工程直觉。

#### 3.1 入门首选：OpenVLA

| 资源 | 链接 |
|------|------|
| 论文 | [OpenVLA: An Open-Source Vision-Language-Action Model](https://arxiv.org/abs/2406.09246) |
| 项目页 | [openvla.github.io](https://openvla.github.io/) |
| GitHub | [openvla/openvla](https://github.com/openvla/openvla) |
| 模型 | [Hugging Face: openvla/openvla-7b](https://huggingface.co/openvla/openvla-7b) |

**学什么：** action discretization、LoRA finetune、LIBERO / Bridge 评估协议。

#### 3.2 轻量部署：SmolVLA

| 资源 | 链接 |
|------|------|
| 论文 | [SmolVLA](https://arxiv.org/abs/2506.01844) |
| LeRobot 集成 | [SmolVLA 文档](https://huggingface.co/docs/lerobot/en/smolvla) |

**学什么：** 小模型 + 低延迟推理，适合边缘 GPU / 快速迭代。

#### 3.3 Generalist + Diffusion head：Octo

| 资源 | 链接 |
|------|------|
| 论文 | [Octo (RSS 2024)](https://arxiv.org/abs/2405.12213) |
| 项目页 | [octo-models.github.io](https://octo-models.github.io/) |
| GitHub | [octo-models/octo](https://github.com/octo-models/octo) |

**学什么：** 800k OXE 预训练、goal image / language 条件、finetune 到新 embodiment。

#### 3.4 现代 VLA Foundation：π 系列（OpenPI）

| 资源 | 链接 |
|------|------|
| π0 论文 | [π0: VLA Flow Model](https://arxiv.org/abs/2410.24164) |
| π0 博客 | [Physical Intelligence: π0](https://www.physicalintelligence.company/blog/pi0) |
| OpenPI GitHub | [Physical-Intelligence/openpi](https://github.com/Physical-Intelligence/openpi) |
| LeRobot π0 文档 | [LeRobot Pi0](https://huggingface.co/docs/lerobot/main/en/pi0) |

**学什么：** flow matching action head、VLM backbone、remote policy server 部署模式。

#### 3.5 国内开源：LingBot-VLA

| 资源 | 链接 |
|------|------|
| 论文 | [A Pragmatic VLA Foundation Model](https://arxiv.org/abs/2601.18692) |
| GitHub | [Robbyant/lingbot-vla](https://github.com/Robbyant/lingbot-vla) |

**学什么：** 数据管线 + 训练 + 推理 + 真机部署的工程拆分方式。

**阶段实验清单：**

```text
[ ] OpenVLA：单帧 inference，打印 action token / denormalized action
[ ] Octo 或 SmolVLA：在 sim benchmark 上 eval（LIBERO / ManiSkill）
[ ] OpenPI：读 websocket policy server 示例，理解 client-server 分工
```

**通过标准：** 能在本机或 Colab 完成一次 **不训练** 的 policy inference，并说明 action 如何映射到控制器。

---

### 阶段 4：Benchmark 与仿真（2 周）

**目标：** 在标准 benchmark 上理解「什么叫泛化」。

| 工具 | 用途 | 链接 |
|------|------|------|
| **LIBERO** |  lifelong / multitask IL benchmark | [Project](https://libero-project.github.io/main) · [GitHub](https://github.com/Lifelong-Robot-Learning/LIBERO) |
| **ManiSkill** | 高效 manipulation sim + benchmark | [Docs](https://maniskill.readthedocs.io/en/latest/) · [GitHub](https://github.com/haosulab/ManiSkill) |
| **robosuite** | MuJoCo 操作任务 | [Site](https://robosuite.ai/) · [Docs](https://robosuite.ai/docs/index.html) |
| **MuJoCo** | 轻量物理引擎 | [mujoco.org](https://mujoco.org/) |

**仿真器选型（结合你的 ROS2 + VLA 目标）：**

```text
快速理解 IL/VLA 算法  → ManiSkill / LIBERO / robosuite
控制与 RL 研究          → MuJoCo
高保真视觉 + ROS2 集成  → Isaac Sim
大规模并行 RL/IL 训练   → Isaac Lab
```

**通过标准：** 在 LIBERO 或 ManiSkill 跑通一个 baseline policy 的 success rate 评估。

---

### 阶段 5：Isaac + ROS2 + Policy Node（2–4 周）

**目标：** 打通「仿真传感器 → ROS2 → policy → 控制」闭环——与 dimos / 真机路线对齐。

| 资源 | 链接 |
|------|------|
| Isaac Sim | [Developer](https://developer.nvidia.com/isaac/sim) · [Docs](https://docs.isaacsim.omniverse.nvidia.com/) |
| Isaac Lab | [Developer](https://developer.nvidia.com/isaac/lab) · [Docs](https://isaac-sim.github.io/IsaacLab/main/index.html) |
| ROS2 Bridge | [Isaac Sim ROS2 安装](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html) |
| Isaac Lab Tasks | [Isaac Lab Tasks Docs](https://isaac-sim.github.io/IsaacLab/main/source/overview/environments.html) |

**推荐动手顺序：**

```text
1. Isaac Sim 自带 demo（相机 + 关节可见）
2. 加载机械臂场景，确认 /camera、/joint_states
3. 开启 ROS2 Bridge，ros2 topic echo
4. 从 ROS2 发 joint trajectory（不用 VLA）
5. 包装 policy 为 ROS2 node（sub obs → pub action）
6. 加 safety filter（限幅、workspace、急停）
7. 再接 VLA HTTP / gRPC policy server
```

**架构示意（与 dimos MVP 类似）：**

```text
Isaac Sim / 真机
  → /camera/image, /joint_states
        ↓
  [可选] dimos 编排 / 任务规划
        ↓
  VLA Policy Server (GPU)
        ↓
  validation + safety filter
        ↓
  ROS2 controller → robot
```

**通过标准：** ROS2 里能看到图像和 joint_states，policy node 以 ≥10Hz 发布 command（仿真中不回退）。

---

### 阶段 6：微调与 Sim-to-Real（持续）

**目标：** 在小数据上 finetune，并理解部署差距。

| 主题 | 资源 |
|------|------|
| OpenVLA finetune | [OpenVLA Fine-Tuning README](https://github.com/openvla/openvla/blob/main/README.md) |
| Octo finetune | [Octo GitHub finetuning](https://github.com/octo-models/octo) |
| Sim-to-real survey | [Closing the Sim-to-Real Gap (DeepMind, 2020)](https://arxiv.org/abs/1812.07278) |
| Domain randomization | [Domain Randomization for Transferring NN (Tobin et al.)](https://arxiv.org/abs/1610.02188) |

**原则：**

```text
先复现官方 eval 数字
→ 只改一个变量（数据 / 相机 / action space）
→ 仿真验证
→ 真机前加 safety + 低速
```

---

## 5. 论文阅读路线图（按周）

### Week 1–2：基础

1. [Diffusion Policy](https://arxiv.org/abs/2303.04137) — 连续 action 生成
2. [ACT](https://arxiv.org/abs/2304.00279) — action chunking
3. [RoboMimic](https://arxiv.org/abs/2108.03265) — 数据集与 benchmark 规范

### Week 3：VLA 起源

4. [RT-1](https://arxiv.org/abs/2212.06817) — Transformer policy at scale
5. [Open X-Embodiment](https://arxiv.org/abs/2310.08864) — 跨本体数据
6. [RT-2](https://arxiv.org/abs/2307.15818) — VLM → action tokens

### Week 4–5：开源可复现

7. [Octo](https://arxiv.org/abs/2405.12213) — generalist + finetune
8. [OpenVLA](https://arxiv.org/abs/2406.09246) — 开源 7B VLA
9. [π0](https://arxiv.org/abs/2410.24164) — flow matching VLA

### Week 6+：扩展

10. [SmolVLA](https://arxiv.org/abs/2506.01844) — 轻量 VLA
11. [LingBot-VLA](https://arxiv.org/abs/2601.18692) — 工程化 foundation model
12. [Mobile ALOHA / ACT++](https://arxiv.org/abs/2304.13705) — 全身 teleop 数据（可选）

---

## 6. 轻量实验手册（不动大 GPU）

| # | 实验 | 工具 | 产出 |
|---|------|------|------|
| 1 | 读一个 episode | LeRobot / Robomimic | 数据 schema 笔记 |
| 2 | 单帧 inference | OpenVLA / SmolVLA | action shape + 数值范围 |
| 3 | 离线 replay | 自写脚本 / Rerun |  grasp 时间点标注 |
| 4 | Sim 闭环 | ManiSkill / robosuite | success/fail 视频 |
| 5 | ROS2 echo | Isaac Sim Bridge | topic 列表截图 |
| 6 | Policy node 骨架 | rclpy | sub/pub 延迟测量 |

**不要第一天做的事：**

- 从零预训练 7B VLA
- 同时改模型结构 + 数据集 + 仿真 + 控制器
- 跳过 safety 层直接上真机

---

## 7. VLA 与 ROS2 集成（工程 checklist）

```text
[ ] 明确 action space（joint / EEF / delta / chunk）
[ ] 明确控制频率（10Hz? 50Hz?）
[ ] 明确坐标系（base_link / tool0 / camera optical frame）
[ ] denormalize action（stats 来自训练集）
[ ] safety：限幅 / workspace / velocity / e-stop
[ ] 超时与 watchdog（policy 卡住时 hold / freeze）
[ ] 日志：obs + action + latency 落盘
```

**ROS2 node 示意：**

```text
Subscriptions:  /camera/image, /joint_states, /task_instruction
Publications:   /joint_trajectory or /eef_delta (after filter)
```

dimos MVP 走的是 **结构化 HTTP contract**（`pick_sku` + `target_meta` + `joint_action`），与端到端 VLA 的关系：

```text
dimos：NL → 结构化 pick 请求 → VLA 服务 → 校验 → ROS
纯 VLA：图像 + 语言 → policy → action → ROS
```

长期可合并：dimos 负责 task-level 编排，VLA 负责 visuomotor policy。

---

## 8. 常见误区（专家视角）

| 误区 | 实际情况 |
|------|----------|
| 「VLA = 聊天机器人 + 机械臂」 | 输出必须是 **控制器可执行** 的 action，且有严格时空对齐 |
| 「下载 checkpoint 就能用」 | embodiment、相机位姿、action space 必须 match，否则要 finetune |
| 「Isaac 第一天就上 VLA 训练」 | 先 Sim + ROS2 通信稳定，再接 policy |
| 「OpenVLA 和 π0 可以互换」 | 架构、action 表示、推理 API 完全不同 |
| 「有 language 就是 VLA」 | 仅有 high-level planner + 传统 motion planner 不算 VLA policy |

---

## 9. 完整链接索引

### 9.1 奠基与 VLA 范式

| 名称 | 论文 | 项目 / 代码 |
|------|------|-------------|
| RT-1 | [arXiv:2212.06817](https://arxiv.org/abs/2212.06817) | [robotics_transformer](https://github.com/google-research/robotics_transformer) |
| RT-2 | [arXiv:2307.15818](https://arxiv.org/abs/2307.15818) | [Project](https://rt2-anon.github.io/) |
| Open X-Embodiment | [arXiv:2310.08864](https://arxiv.org/abs/2310.08864) | [robotics-transformer-x.github.io](https://robotics-transformer-x.github.io/) |
| PaLM-E | [arXiv:2303.03378](https://arxiv.org/abs/2303.03378) | — |

### 9.2 模仿学习 Baseline

| 名称 | 论文 | 项目 / 代码 |
|------|------|-------------|
| Diffusion Policy | [arXiv:2303.04137](https://arxiv.org/abs/2303.04137) | [GitHub](https://github.com/real-stanford/diffusion_policy) · [Site](https://diffusion-policy.cs.columbia.edu/) |
| ACT | [arXiv:2304.00279](https://arxiv.org/abs/2304.00279) | [act-plus-plus.github.io](https://act-plus-plus.github.io/) |
| RoboMimic | [arXiv:2108.03265](https://arxiv.org/abs/2108.03265) | [GitHub](https://github.com/ARISE-Initiative/robomimic) · [Docs](https://robomimic.github.io/docs/introduction/overview.html) |

### 9.3 开源 VLA / Foundation Model

| 名称 | 论文 | 项目 / 代码 |
|------|------|-------------|
| OpenVLA | [arXiv:2406.09246](https://arxiv.org/abs/2406.09246) | [GitHub](https://github.com/openvla/openvla) · [Site](https://openvla.github.io/) · [HF Model](https://huggingface.co/openvla/openvla-7b) |
| Octo | [arXiv:2405.12213](https://arxiv.org/abs/2405.12213) | [GitHub](https://github.com/octo-models/octo) · [Site](https://octo-models.github.io/) |
| SmolVLA | [arXiv:2506.01844](https://arxiv.org/abs/2506.01844) | [LeRobot Docs](https://huggingface.co/docs/lerobot/en/smolvla) |
| π0 | [arXiv:2410.24164](https://arxiv.org/abs/2410.24164) | [OpenPI](https://github.com/Physical-Intelligence/openpi) · [Blog](https://www.physicalintelligence.company/blog/pi0) |
| LingBot-VLA | [arXiv:2601.18692](https://arxiv.org/abs/2601.18692) | [GitHub](https://github.com/Robbyant/lingbot-vla) |

### 9.4 工具链

| 名称 | 链接 |
|------|------|
| LeRobot | [GitHub](https://github.com/huggingface/lerobot) · [Docs](https://huggingface.co/docs/lerobot) |
| Open X-Embodiment Dataset | [Hugging Face](https://huggingface.co/datasets/openx-embodiment) |
| CS285 | [Berkeley Deep RL](https://rail.eecs.berkeley.edu/deeprlcourse/) |

### 9.5 仿真与 Benchmark

| 名称 | 链接 |
|------|------|
| Isaac Sim | [Developer](https://developer.nvidia.com/isaac/sim) · [Docs](https://docs.isaacsim.omniverse.nvidia.com/) |
| Isaac Lab | [Developer](https://developer.nvidia.com/isaac/lab) · [Docs](https://isaac-sim.github.io/IsaacLab/main/index.html) |
| Isaac ROS2 | [Install Guide](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html) |
| ManiSkill | [Docs](https://maniskill.readthedocs.io/en/latest/) · [GitHub](https://github.com/haosulab/ManiSkill) |
| robosuite | [Site](https://robosuite.ai/) · [Docs](https://robosuite.ai/docs/index.html) |
| LIBERO | [Project](https://libero-project.github.io/main) · [GitHub](https://github.com/Lifelong-Robot-Learning/LIBERO) |
| MuJoCo | [mujoco.org](https://mujoco.org/) |

### 9.6 Sim-to-Real

| 名称 | 链接 |
|------|------|
| Sim-to-Real Gap Survey | [arXiv:1812.07278](https://arxiv.org/abs/1812.07278) |
| Domain Randomization | [arXiv:1610.02188](https://arxiv.org/abs/1610.02188) |

---

## 10. 与 dimos / ROS2 文档的衔接

| 文档 | 内容 |
|------|------|
| [ros2_basics_jazzy.md](./ros2_basics_jazzy.md) | **ROS2 Jazzy 系统路线 v2**，与本文双轨对照（R0–R7 × VLA 阶段） |
| [vla_pick_architecture_v1.md](./vla_pick_architecture_v1.md) | dimos 当前 NL→VLA→ROS 编排架构 |
| [vla_pick_sku_contract.md](./vla_pick_sku_contract.md) | VLA HTTP 接口 contract |
| [vla_execution_mvp_plan.md](Planner%20and%20Orchestrator.md) | dimos MVP 阶段计划 |
| [vla_pick_demo_runbook.md](./vla_pick_demo_runbook.md) | 联调运行手册 |

**建议并行阅读：**

```text
学 VLA 概念（本文档阶段 1–3）
  +
读 dimos architecture v1（理解系统编排层）
  +
在 Isaac / robotwin 上观察 VLA 实际返回格式
```

---

## 11. 一句话总结

VLA 的核心不是「机器人会聊天」，而是 **在特定 embodiment 下，把视觉、语言和本体状态映射为可执行、可评估、可安全落地的动作序列**。

最稳路线：

```text
BC/Diffusion（懂 data & action）
  → OXE + RT-2（懂 VLA 为什么出现）
  → OpenVLA / Octo / π0（动手 inference & finetune）
  → LIBERO / ManiSkill（懂评估）
  → Isaac + ROS2 + safety（懂部署）
  → dimos 编排层（懂系统边界）
```

慢即是快。先把 **一个 episode、一次 inference、一个 benchmark 数字、一条 ROS 闭环** 做扎实，再谈训练大模型。

---

## 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1 | — | 初版概念与项目速览 |
| v2 | 2026-06-12 | 专家路线：6 阶段、论文阅读序、完整链接索引、dimos 衔接 |
