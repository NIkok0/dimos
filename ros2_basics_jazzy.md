# ROS2 Jazzy 系统学习路线 v2（面向 VLA / 机器人学习集成）

> 面向：Ubuntu 24.04 + ROS2 Jazzy，计划结合 [VLA 学习路线](./vla_basics_learning.md) 做 **ROS2 系统 + VLA 策略** 全面学习的工程师  
> 定位：ROS2 **不是** 算法课，而是 **机器人软件的通信、编排、控制与安全底座**  
> 默认语言：Python（`rclpy`），机械臂 / 移动底盘场景兼顾

---

## 0. 双轨学习地图：ROS2 与 VLA 如何并行

VLA 文档假设你「已有 ROS2 基础」；本文档负责把 ROS2 学到 **能接 policy、能采数据、能联调 Isaac**。两条线应在 **阶段 3 之后汇合**。

```text
时间轴（建议 8–12 周）

Week 1–2   ROS2 心智模型 + talker/listener + 调试命令
Week 2–3   ROS2 写节点 + launch + 参数 + TF/RViz
           ║  并行：VLA 阶段 0–1（读 episode、Diffusion Policy 概念）
Week 3–4   ros2_control + 标准消息（Image / JointState / TF）
           ║  并行：VLA 阶段 2（RT-2 / OXE 论文）
Week 4–6   MoveIt2 或 Nav2（按方向二选一）+ rosbag2 录数据
           ║  并行：VLA 阶段 3（OpenVLA / LeRobot inference）
Week 6–8   Policy ROS2 node + safety filter + Isaac ROS2 Bridge
           ║  并行：VLA 阶段 4–5（benchmark + Isaac）
Week 8+    dimos 编排 / 真机前 checklist
           ║  并行：VLA 阶段 6（finetune + sim-to-real）
```

**汇合点（必须打通的一条链）：**

```text
/camera/image + /joint_states + /task_instruction
        ↓
  vla_policy_node（或 dimos → HTTP VLA）
        ↓
  safety_filter
        ↓
  /joint_trajectory 或 FollowJointTrajectory Action
        ↓
  ros2_control → 仿真 / 真机
```

详细 VLA 论文、项目链接见：[vla_basics_learning.md](./vla_basics_learning.md)  
dimos 编排与 HTTP contract 见：[vla_pick_architecture_v1.md](./vla_pick_architecture_v1.md)

---

## 1. ROS2 在 VLA 栈里的角色

| 层次 | 谁负责 | ROS2 做什么 | VLA 做什么 |
|------|--------|-------------|------------|
| 感知 | 相机驱动、深度、TF | 发布 `sensor_msgs/Image`、`/tf` | 消费图像 tensor |
| 状态 | 关节编码器、夹爪 | 发布 `sensor_msgs/JointState` | 消费 proprio |
| 任务 | 人机界面、LLM agent | 发布 `std_msgs/String` 或 custom msg | 消费 language |
| 策略 | — | **Policy Node** 订阅 obs，发布 action | GPU 上 inference |
| 安全 | — | 限幅、workspace、急停 node | 不替代 |
| 控制 | `ros2_control`、控制器 | 执行 trajectory / velocity | 不直接碰硬件 |
| 规划 | MoveIt2 / Nav2 | 大范围导航 / 避障轨迹 | 通常不替代细粒度抓取 |

**原则：**

```text
ROS2 管「系统怎么连、怎么跑、怎么录、怎么停」
VLA 管「看到什么、听到什么、下一步动作向量是什么」
控制器管「动作怎么变成力矩/位置指令」
```

---

## 2. ROS2 心智模型（Jazzy）

### 2.1 分布式进程 + 标准通信

机器人软件 = 多个 **Node** 并行运行，通过 **Topic / Service / Action** 交换数据。

```text
camera_node  ──/camera/image──►  vla_policy_node  ──►  safety_node  ──►  controller
joint_state  ──/joint_states───►       ▲
instruction  ──/task_instruction───────┘
```

与普通程序的区别：

| 普通程序 | ROS2 系统 |
|----------|-----------|
| 单进程、函数调用 | 多进程、异步消息 |
| 跑完即退出 | 长期运行、事件驱动 |
| 调试靠 print | 调试靠 `ros2 topic` / `rosbag` / RViz |

### 2.2 核心概念速查

| 概念 | 作用 | VLA 场景示例 |
|------|------|--------------|
| **Workspace** | 放多个 package，`colcon build` | `~/ros2_ws` |
| **Package** | 最小工程单元 | `vla_bringup`, `robot_control` |
| **Node** | 运行中的进程 | `vla_policy_node` |
| **Topic** | 连续数据流，Pub/Sub | `/camera/image`, `/joint_states` |
| **Service** | 同步请求-响应 | 查询夹爪状态、reset sim |
| **Action** | 长时间任务 + feedback | `FollowJointTrajectory`, Nav2 `NavigateToPose` |
| **Parameter** | 运行时配置 | `control_frequency`, `camera_topic` |
| **Launch** | 多节点编排启动 | 一键起 sim + camera + policy |
| **TF2** | 坐标系树 | `base_link` → `camera_link` → `tool0` |
| **rosbag2** | 录播数据 | **VLA 训练数据采集** |

### 2.3 通信方式怎么选

```text
持续传感器流     → Topic（Image, JointState, LaserScan）
一次性配置/查询   → Service（save_map, get_parameters）
移动/抓取等任务   → Action（NavigateToPose, FollowJointTrajectory）
```

**VLA policy node 典型用法：**

- 订阅：**Topic**（image, joint_states, instruction）
- 发布：**Topic**（高频 action command）或 **Action Client**（提交一段 trajectory）

dimos MVP 当前用 **HTTP** 调 VLA 而非 ROS2 topic 直连模型——工程上 policy 可在独立 GPU 机器，ROS2 只跑轻量 client node。

---

## 3. 环境：Jazzy on Ubuntu 24.04

### 3.1 官方资源（直接访问）

| 资源 | 链接 |
|------|------|
| Jazzy 发行说明 | [docs.ros.org/jazzy/Releases.html](https://docs.ros.org/en/jazzy/Releases/Release-Jazzy-Jalisco.html) |
| Jazzy 教程索引 | [docs.ros.org/jazzy/Tutorials.html](https://docs.ros.org/en/jazzy/Tutorials.html) |
| rclpy 文档 | [docs.ros.org/jazzy/p/rclpy](https://docs.ros.org/en/jazzy/p/rclpy/) |
| 安装（deb） | [Ubuntu Install Jazzy](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html) |

### 3.2 每个终端必做

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash   # 若有自研 workspace
```

验证：

```bash
ros2 doctor
echo $ROS_DISTRO   # 应输出 jazzy
```

---

## 4. Jazzy 命令速查（调试优先）

### 4.1 系统观测

```bash
ros2 node list
ros2 node info /node_name
ros2 topic list
ros2 topic info /topic_name
ros2 topic echo /topic_name
ros2 topic hz /topic_name
ros2 service list
ros2 action list
ros2 param list
```

### 4.2 构建与运行

```bash
cd ~/ros2_ws && colcon build --symlink-install
source install/setup.bash
ros2 run pkg_name executable_name
ros2 launch pkg_name launch_file.py
```

### 4.3 VLA 联调常用 topic 名（约定俗成，以实际 launch 为准）

| Topic | 消息类型 | 方向 |
|-------|----------|------|
| `/camera/image_raw` | `sensor_msgs/msg/Image` | 相机 → policy |
| `/camera/camera_info` | `sensor_msgs/msg/CameraInfo` | 标定 |
| `/joint_states` | `sensor_msgs/msg/JointState` | 机器人 → policy |
| `/tf`, `/tf_static` | `tf2_msgs/msg/TFMessage` | 坐标变换 |
| `/task_instruction` | `std_msgs/msg/String` | 任务 → policy |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | 移动底盘 |
| `/joint_trajectory_controller/...` | `trajectory_msgs/msg/JointTrajectory` | policy → 控制 |

查看消息定义：

```bash
ros2 interface show sensor_msgs/msg/Image
ros2 interface show sensor_msgs/msg/JointState
```

---

## 5. 分阶段学习路线（ROS2 专轨）

每阶段标注：**目标 / 练习 / 与 VLA 的衔接 / 通过标准**。

---

### 阶段 R0：心智模型 + 官方 Demo（3–5 天）

**目标：** 理解 Node / Topic，会用 CLI 观察系统。

**练习：**

```bash
# 终端 1
ros2 run demo_nodes_py talker
# 终端 2
ros2 run demo_nodes_py listener
# 终端 3
ros2 topic echo /chatter
ros2 topic hz /chatter
rqt_graph
```

**官方教程：**

- [Writing a Simple Publisher and Subscriber (Python)](https://docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Writing-A-Simple-Py-Publisher-And-Subscriber.html)
- [Understanding ROS2 Topics](https://docs.ros.org/en/jazzy/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Topics/Understanding-ROS2-Topics.html)

**VLA 衔接：** 把 `/chatter` 想象成 `/task_instruction`——policy 也是「订阅输入、发布输出」。

**通过标准：** 能口述 Pub/Sub 模型，并用 `rqt_graph` 指出 talker → listener。

---

### 阶段 R1：自写 Python 包 + Launch（1 周）

**目标：** 掌握 workspace、package、`colcon build`、entry_points。

**练习：** 完成 talker/listener 自建包（见 §12 附录 A），再加：

1. **Launch** 同时启动 talker + listener  
   - 教程：[Launching Multiple Nodes](https://docs.ros.org/en/jazzy/Tutorials/Intermediate/Launch/Launch-Multiple-Nodes.html)
2. **Parameter** 把发布频率做成参数  
   - 教程：[Using Parameters in a Class (Python)](https://docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Using-Parameters-In-A-Class-CPP.html)（概念通用）

**VLA 衔接：** policy node 就是一个 package 里的 node；`control_hz`、`model_path` 都是 parameter。

**通过标准：** 修改参数后不改代码即可改频率；一个 launch 拉起整个 mini 系统。

---

### 阶段 R2：TF2 + RViz2（1 周）

**目标：** 理解为什么 VLA 必须关心坐标系。

**必读：**

- [Introducing TF2](https://docs.ros.org/en/jazzy/Tutorials/Intermediate/Tf2/Introduction-To-Tf2.html)
- [Using RViz2](https://docs.ros.org/en/jazzy/Tutorials/Intermediate/RViz/RViz-Main.html)

**关键坐标系（ manipulation ）：**

```text
world / map
  └── base_link          （机器人基座）
        └── camera_link  （相机）
        └── tool0        （末端执行器）
```

**VLA 衔接：**

- 模型在 **相机系** 预测 grasp → 必须 TF 变换到 **base_link / tool0** 才能发给控制器
- dimos contract 里 `target_meta.object_position` 必须声明是哪个 frame

**练习：**

```bash
ros2 run tf2_tools view_frames   # 生成 frames.pdf
rviz2                            # Fixed Frame 选 base_link，看 TF 树
```

**通过标准：** 能解释「为什么 policy 输出 EEF delta 时必须知道 base_link → camera 的变换」。

---

### 阶段 R3：标准消息 + QoS + rosbag2（1 周）

**目标：** 掌握 VLA 数据在 ROS2 里的载体。

#### 3.1 必会消息类型

| 消息 | 用途 |
|------|------|
| `sensor_msgs/Image` | RGB / 压缩图像 |
| `sensor_msgs/JointState` | 关节名 + position/velocity/effort |
| `geometry_msgs/PoseStamped` | 带 frame 的位姿 |
| `trajectory_msgs/JointTrajectory` | 关节轨迹 |
| `control_msgs/action/FollowJointTrajectory` | 机械臂 Action |

#### 3.2 QoS（相机必读）

相机 publisher 常用 `sensor_data` QoS；subscriber 不匹配会导致 **echo 不到图像**。

```bash
ros2 topic info /camera/image -v    # 看 reliability / durability
```

教程：[About Quality of Service Settings](https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Quality-of-Service-Settings.html)

#### 3.3 rosbag2 — 连接 VLA 数据采集

```bash
ros2 bag record /camera/image /joint_states /tf /task_instruction
ros2 bag info ./rosbag_folder
ros2 bag play ./rosbag_folder
```

教程：[Recording and Playing Back Data](https://docs.ros.org/en/jazzy/Tutorials/Advanced/Recording-A-Bag-From-Your-Own-Node-CPP.html)

**VLA 衔接：** teleop 录 bag → 离线转 LeRobot dataset → 训练 / finetune（见 [vla_basics_learning.md §阶段 1–3](./vla_basics_learning.md)）。

**通过标准：** 录一段 30s bag 并 play 回，`ros2 topic hz` 恢复。

---

### 阶段 R4：ros2_control + 控制器（1–2 周）

**目标：** 理解「policy 输出的 action 最终发给谁」。

**架构：**

```text
joint_trajectory_controller (ros2_control)
  ↑  commands
hardware_interface / Gazebo / Isaac bridge
  ↓  states
/joint_states
```

**必读：**

- [ros2_control 文档](https://control.ros.org/jazzy/index.html)
- [ROS2 Control Demos](https://github.com/ros-controls/ros2_control_demos)

**Gazebo / 仿真：**

- [Gazebo + ROS2 Integration (Jazzy)](https://gazebosim.org/docs/latest/ros2_integration/)

**VLA 衔接：**

- policy 通常发布 **JointTrajectory** 或 **Float64MultiArray** 到 controller 的 command interface
- dimos contract 的 `joint_action` 应对齐 controller 期望的 joint 名与顺序

**通过标准：** 在仿真中用 `ros2 action send_goal` 让机械臂动一下，同时 `/joint_states` 有反馈。

---

### 阶段 R5：MoveIt2（机械臂）或 Nav2（移动底盘）（2 周，二选一）

#### 路径 A：Manipulator + VLA 抓取

| 资源 | 链接 |
|------|------|
| MoveIt2 文档 | [moveit.picknik.ai (Jazzy)](https://moveit.picknik.ai/main/index.html) |
| MoveIt2 Tutorials | [GitHub: moveit2_tutorials](https://github.com/ros-planning/moveit2_tutorials) |

MoveIt2 负责：**规划** 无碰撞轨迹。VLA 负责：**感知-语言-动作**。二者关系：

```text
粗粒度：Nav / MoveIt 到 pre-grasp 附近（可选）
细粒度：VLA 输出 joint_action / EEF delta 完成抓取
```

#### 路径 B：Mobile + VLA

| 资源 | 链接 |
|------|------|
| Nav2 文档 | [nav2.org](https://docs.nav2.org/) |
| Nav2 Tutorials | [Getting Started](https://docs.nav2.org/getting_started/index.html) |

**VLA 衔接：** dimos MVP 的 `go_to_workspace` 对应 Nav2 / 语义导航；`pick_sku` 对应 manipulation VLA。

---

### 阶段 R6：Policy Node + Safety + 外部 VLA 服务（2 周）

**目标：** 实现 VLA 文档 [阶段 5](./vla_basics_learning.md) 的 ROS2 部分。

#### 6.1 Policy Node 架构

```text
┌─────────────────────────────────────┐
│ vla_policy_node                      │
│  Sub: Image, JointState, String      │
│  Timer: control_loop @ 10–50 Hz      │
│  Infer: local GPU | HTTP | gRPC      │
│  Pub: JointTrajectory / Twist        │
└─────────────────────────────────────┘
          ↓
┌─────────────────────────────────────┐
│ safety_filter_node                   │
│  joint limits, workspace AABB,       │
│  velocity clamp, e-stop topic        │
└─────────────────────────────────────┘
          ↓
     ros2_control
```

#### 6.2 两种 VLA 部署模式

| 模式 | 优点 | 典型场景 |
|------|------|----------|
| **ROS2 内嵌 policy** | 低延迟，topic 直连 | 边缘 GPU、小模型 SmolVLA |
| **HTTP / gRPC policy server** | GPU 隔离、易扩缩 | OpenVLA / π0、dimos `POST /pick_sku` |

dimos 当前路线：

```text
dimos agent → HTTP VLA → 校验 joint_action → RosActionAdapter → (未来) ROS2 Action
```

#### 6.3 Safety Checklist（上真机前）

```text
[ ] joint 限位
[ ] 工作空间 AABB
[ ] 最大速度 / 加速度
[ ] 夹爪力矩上限
[ ] watchdog（policy 超时 → hold）
[ ] 物理急停按钮可用
[ ] rosbag 录制 obs + action
```

**通过标准：** 仿真中 policy node 以 ≥10Hz 发布 command，kill policy 后 robot 进入 safe hold。

---

### 阶段 R7：Isaac Sim + ROS2 Bridge（1–2 周）

与 [vla_basics_learning.md §阶段 5](./vla_basics_learning.md) 对齐。

| 资源 | 链接 |
|------|------|
| Isaac Sim | [developer.nvidia.com/isaac/sim](https://developer.nvidia.com/isaac/sim) |
| Isaac Sim Docs | [docs.isaacsim.omniverse.nvidia.com](https://docs.isaacsim.omniverse.nvidia.com/) |
| ROS2 Bridge 安装 | [Install ROS2 Bridge](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html) |
| Isaac Lab | [Isaac Lab Docs](https://isaac-sim.github.io/IsaacLab/main/index.html) |

**推荐顺序：**

```text
Isaac Sim demo
  → 相机 + /joint_states 在 ROS2 可见
  → ros2 topic echo /clock /tf
  → 手动 pub trajectory
  → policy node 闭环
  →（可选）对接 dimos HTTP VLA
```

---

## 6. 统一学习路径：ROS2 × VLA 对照表

| 周 | ROS2（本文档） | VLA（[vla_basics_learning.md](./vla_basics_learning.md)） | 联合产出 |
|----|----------------|-----------------------------------------------------------|----------|
| 1–2 | R0–R1：Topic、自写包 | 阶段 0–1：episode、Diffusion Policy | 理解 data flow |
| 3 | R2–R3：TF、rosbag | 阶段 2：RT-2、OXE | 录第一个 rosbag |
| 4–5 | R4：ros2_control | 阶段 3：OpenVLA inference | 仿真中动关节 |
| 5–6 | R5：MoveIt2/Nav2 | 阶段 4：LIBERO eval | 理解 plan vs policy |
| 7–8 | R6：policy node | 阶段 5：Isaac + policy | **闭环 demo** |
| 9+ | R7 + 真机 safety | 阶段 6：finetune | sim-to-real |

---

## 7. dimos 项目中的 ROS2 位置

当前 dimos VLA MVP **不强制依赖 ROS2 runtime**，但 contract 设计面向 ROS 转发：

```text
execute_pick_instruction
  → go_to_workspace (MockSysNavigationAdapter)   # 未来 → Nav2 / 语义导航 ROS2
  → pick_sku (HTTP VLA)                          # 未来 → 或 ROS2 service
  → validated_payload                            # joint_action 原样
  → MockRosActionAdapter                         # 未来 → FollowJointTrajectory
```

相关文档：

- [vla_pick_architecture_v1.md](./vla_pick_architecture_v1.md)
- [vla_pick_sku_contract.md](./vla_pick_sku_contract.md)
- [vla_pick_demo_runbook.md](./vla_pick_demo_runbook.md)

**学习建议：** 用 dimos 理解 **任务编排 + 校验**；用 ROS2 理解 **动作如何到电机**；用 VLA 文档理解 **模型如何产出 action**。

---

## 8. 调试手册（ROS2 + VLA 联调）

### 8.1 启动后四问

```bash
ros2 node list          # 节点齐了吗？
ros2 topic info ... -v  # 谁 pub/sub？QoS 匹配吗？
ros2 topic hz ...       # 频率够吗？（相机 ≥15Hz，控制 ≥10Hz）
ros2 topic echo ...     # 数据合理吗？
```

### 8.2 常见问题

| 现象 | 可能原因 | 排查 |
|------|----------|------|
| `ros2 run` 找不到包 | 未 build / 未 source | `colcon build && source install/setup.bash` |
| echo 不到图像 | QoS 不匹配 | `topic info -v`，subscriber 用 `sensor_data` |
| TF 断链 | 缺 static transform | `view_frames`，查 launch |
| policy 有输出机器人不动 | 关节名/order 不对 | 对比 `JointState.name` 与 trajectory |
| VLA 延迟过大 | 模型在远程 HTTP | 本地 GPU 或 action chunk |

### 8.3 可视化工具

```bash
rqt_graph    # 通信拓扑
rviz2        # 空间 + 传感器
rqt_image_view   # 快速看相机
```

---

## 9. 推荐官方与社区资源

### 9.1 ROS2 Jazzy 核心

| 名称 | 链接 |
|------|------|
| Jazzy 文档首页 | [docs.ros.org/en/jazzy](https://docs.ros.org/en/jazzy/index.html) |
| 初学者教程 | [Beginner Tutorials](https://docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Beginner-Client-Libraries.html) |
| Launch | [Launch Tutorials](https://docs.ros.org/en/jazzy/Tutorials/Intermediate/Launch/Launch-Main.html) |
| TF2 | [Tf2 Tutorials](https://docs.ros.org/en/jazzy/Tutorials/Intermediate/Tf2/Tf2-Main.html) |
| rosbag2 | [Rosbag2](https://docs.ros.org/en/jazzy/Tutorials/Advanced/Recording-A-Bag-From-Your-Own-Node-CPP.html) |

### 9.2 机器人栈

| 名称 | 链接 |
|------|------|
| ros2_control | [control.ros.org/jazzy](https://control.ros.org/jazzy/index.html) |
| MoveIt2 | [moveit.picknik.ai](https://moveit.picknik.ai/main/index.html) |
| Nav2 | [docs.nav2.org](https://docs.nav2.org/) |
| Gazebo ROS | [gazebosim.org ROS integration](https://gazebosim.org/docs/latest/ros2_integration/) |

### 9.3 VLA / 学习（交叉引用）

| 名称 | 链接 |
|------|------|
| VLA 学习路线 v2 | [vla_basics_learning.md](./vla_basics_learning.md) |
| LeRobot | [GitHub](https://github.com/huggingface/lerobot) · [Docs](https://huggingface.co/docs/lerobot) |
| OpenPI | [GitHub](https://github.com/Physical-Intelligence/openpi) |
| Isaac ROS2 | [Isaac Sim ROS2](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html) |

---

## 10. 一句话总结

```text
ROS2 Jazzy 学的是：节点、通信、坐标系、控制接口、录包、调试
VLA 学的是：数据、模型、action 空间、推理、评估
两者在 policy node + ros2_control 处汇合
```

最稳的全栈路线：

```text
ROS2 R0–R3（会写 node、会录 bag）
  + VLA 阶段 0–1（会读 episode）
  → ROS2 R4–R6（会发 trajectory、会写 policy node）
  + VLA 阶段 3–5（会跑 inference、会接 Isaac）
  → dimos 编排 / 真机 safety
```

---

## 附录 A：最小 talker/listener 包（Jazzy）

```bash
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src
source /opt/ros/jazzy/setup.bash
ros2 pkg create my_first_ros2_pkg --build-type ament_python --dependencies rclpy std_msgs
```

`talker.py` / `listener.py` 代码与原版相同，见 Jazzy 官方教程：  
[Writing a Simple Publisher and Subscriber (Python)](https://docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Writing-A-Simple-Py-Publisher-And-Subscriber.html)

```bash
cd ~/ros2_ws
colcon build --symlink-install --packages-select my_first_ros2_pkg
source install/setup.bash
ros2 run my_first_ros2_pkg talker    # 终端 1
ros2 run my_first_ros2_pkg listener  # 终端 2
```

---

## 附录 B：Policy Node 骨架（伪代码）

```python
class VlaPolicyNode(Node):
    def __init__(self):
        super().__init__('vla_policy_node')
        self.declare_parameter('control_hz', 20.0)
        self.create_subscription(Image, '/camera/image', self.on_image, 10)
        self.create_subscription(JointState, '/joint_states', self.on_joint, 10)
        self.create_subscription(String, '/task_instruction', self.on_instruction, 10)
        self.traj_pub = self.create_publisher(JointTrajectory, '/joint_trajectory', 10)
        hz = self.get_parameter('control_hz').value
        self.create_timer(1.0 / hz, self.control_loop)

    def control_loop(self):
        if not self.obs_ready():
            return
        action = self.infer_policy()          # 本地 or HTTP VLA
        safe = self.apply_safety(action)
        self.traj_pub.publish(self.to_trajectory(safe))
```

完整实现需对齐：消息同步、TF、action space、controller joint names——在 R4–R6 逐条填满。

---

## 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v1 | — | Jazzy 基础概念 + talker/listener |
| v2 | 2026-06-12 | 专家路线：R0–R7 分阶段、与 VLA 双轨对照、policy node、Isaac、dimos 衔接、官方链接索引 |
