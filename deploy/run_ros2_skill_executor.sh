#!/usr/bin/env bash
# Run dax_skill_sdk skill_executor in the ROS + dax_planner_ws environment.
# Used by DimOS DaxSkillSdkAdapter when DAX_SKILL_EXECUTOR=subprocess (uv venv
# cannot load dax_rf_planner / rclpy native modules).
#
# Usage:
#   bash deploy/run_ros2_skill_executor.sh /path/to/go_home.yaml --no-confirm
#   bash deploy/run_ros2_skill_executor.sh /path/to/place.yaml --no-confirm \
#     --input arm_name=left --input target_name=FODR0000000046
set -eo pipefail

DAX_PLANNER_WS="${DAX_SKILL_SDK_WS:-/home/nvidia/dax_planner_ws}"
ROS_SETUP="${DAX_SKILL_ROS_SETUP:-/opt/ros/humble/setup.bash}"

if [ ! -f "$ROS_SETUP" ]; then
    echo "ERROR: ROS setup not found: $ROS_SETUP (set DAX_SKILL_ROS_SETUP)" >&2
    exit 127
fi

set +u
# shellcheck disable=SC1090
source "$ROS_SETUP"
if [ -f "$DAX_PLANNER_WS/install/setup.bash" ]; then
    # shellcheck disable=SC1090
    source "$DAX_PLANNER_WS/install/setup.bash"
else
    echo "ERROR: $DAX_PLANNER_WS/install/setup.bash missing" >&2
    exit 127
fi
set -u

exec ros2 run dax_skill_sdk skill_executor "$@"
