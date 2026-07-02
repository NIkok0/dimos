import json
import time
from pathlib import Path

from tool.test_request_joint import DaxJointRequestClient


JSON_PATH = Path(__file__).with_name("dax_hi_ani(1).json")
START_INDEX = 150
SEND_COUNT = 200
SEND_INTERVAL = 0.01

client = DaxJointRequestClient()

# HOME
left_arm_positions = [
    0.49968776484597655,
    0.34976398209966364,
    0.0,
    -1.4997614262387273,
    0.0,
    -0.4497713482389387,
    0.2,
]

right_arm_positions = [-1.11065948, -0.9408707, 0.0107924733, -2.14151549, -1.30853546, 0.09318465, -0.119986169]

client.move_dual_joints(left_arm_positions,right_arm_positions,dt=0.01)

with JSON_PATH.open("r", encoding="utf-8") as f:
    data = json.load(f)

positions = data["positions"]
selected_positions = positions[START_INDEX : START_INDEX + SEND_COUNT]

print("Position frame count:", len(positions))
print(f"Send range: {START_INDEX}-{START_INDEX + len(selected_positions) - 1}")
print("Send frame count:", len(selected_positions))

for index, right_arm_positions in enumerate(selected_positions, start=START_INDEX):
    print(f"send index {index}:", right_arm_positions)
    client.servo_dual_joints(left_arm_positions, right_arm_positions)
    time.sleep(SEND_INTERVAL)


left_arm_positions = [
    0.49968776484597655,
    0.34976398209966364,
    0.0,
    -1.4997614262387273,
    0.0,
    -0.4497713482389387,
    0.2,
]

right_arm_positions = [
    0.49968776484597655,
    -0.34976398209966364,
    0.0,
    -1.4997614262387273,
    0.0,
    -0.4497713482389387,
    0.2,]

client.move_dual_joints(left_arm_positions,right_arm_positions,dt=0.01)
