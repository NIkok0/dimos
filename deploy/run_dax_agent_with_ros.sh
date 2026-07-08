#!/usr/bin/env bash
# Start dax-agent with ROS + dax_planner_ws sourced (required for go_home/place YAML).
# Usage on robot:
#   bash deploy/run_dax_agent_with_ros.sh
#   bash deploy/run_dax_agent_with_ros.sh /opt/dax-agent
set -eo pipefail

INSTALL_DIR="${1:-/opt/dax-agent}"
DAX_PLANNER_WS="${DAX_PLANNER_WS:-/home/nvidia/dax_planner_ws}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/humble/setup.bash}"

cd "$INSTALL_DIR"

if [ ! -f "$ROS_SETUP" ]; then
    echo "ERROR: ROS setup not found: $ROS_SETUP" >&2
    exit 1
fi

# ROS setup.bash may reference unset vars (e.g. AMENT_TRACE_SETUP_FILES); disable nounset while sourcing.
set +u
# shellcheck disable=SC1090
source "$ROS_SETUP"
if [ -f "$DAX_PLANNER_WS/install/setup.bash" ]; then
    # shellcheck disable=SC1090
    source "$DAX_PLANNER_WS/install/setup.bash"
else
    echo "WARN: $DAX_PLANNER_WS/install/setup.bash missing — YAML skills may fail" >&2
fi
set -u

# Writable logs when /opt/dax-agent/logs is root-owned (systemd).
export DIMOS_RUN_LOG_DIR="${DIMOS_RUN_LOG_DIR:-${HOME}/.local/state/dimos/logs}"
mkdir -p "$DIMOS_RUN_LOG_DIR"

exec "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/scripts/run_dax_agent.py"
