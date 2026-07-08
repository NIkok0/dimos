#!/usr/bin/env bash
# Invoke execute_atomic_skill in the ROS + dax_planner_ws Python environment.
# Used by DimOS DaxAtomicSkillClient when DAX_ATOMIC_SKILL_EXECUTOR=subprocess.
#
# Usage:
#   bash deploy/run_atomic_skill_invoke.sh joint_move '{"group":"body_dual","target":[...],"dt":0.01}'
set -eo pipefail

DAX_PLANNER_WS="${DAX_ATOMIC_SKILL_WS:-${DAX_SKILL_SDK_WS:-/home/nvidia/dax_planner_ws}}"
ROS_SETUP="${DAX_ATOMIC_SKILL_ROS_SETUP:-${DAX_SKILL_ROS_SETUP:-/opt/ros/humble/setup.bash}}"

if [ ! -f "$ROS_SETUP" ]; then
    echo "ERROR: ROS setup not found: $ROS_SETUP" >&2
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

exec python3 - "$1" "$2" <<'PY'
import json
import sys

from dax_skill_sdk.atomic_skill_executor_helper import execute_atomic_skill

skill_name = sys.argv[1]
params = json.loads(sys.argv[2])
rc, result = execute_atomic_skill(skill_name, params)
if not isinstance(result, dict):
    result = {"success": False, "message": f"unexpected result type: {type(result)!r}", "data": {}}
print(json.dumps({"rc": rc, "result": result}, ensure_ascii=False))
PY
