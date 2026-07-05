#!/usr/bin/env bash
# Isolated dax-agent venv install for real robots (deploy/dax-agent branch).
#
# Uses Tsinghua PyPI mirror by default, uv-managed Python 3.12, project-local
# .venv (no system site-packages, no ROS Python).
#
# Usage (on robot):
#   cd /opt/dax-agent && bash deploy/uv-sync-robot.sh
set -euo pipefail

INSTALL_DIR="${1:-/opt/dax-agent}"
PYPI_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PATH="${HOME}/.local/bin:${PATH}"

cd "$INSTALL_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

export UV_DEFAULT_INDEX="$PYPI_INDEX"

echo "==> Isolated venv at ${INSTALL_DIR}/.venv (uv Python 3.12)"
uv venv .venv --python 3.12 --clear

echo "==> uv sync: extra dax-agent (minimal base + agent), index=${PYPI_INDEX}"
uv sync \
    --extra dax-agent \
    --no-default-groups \
    --no-dev \
    --python .venv/bin/python \
    2>&1

echo "==> Verify imports (no rclpy in venv)"
.venv/bin/python -c "import py_rosbridge; import langchain; print('py_rosbridge + langchain ok')"
.venv/bin/python -c "import rclpy" 2>&1 | grep -q ModuleNotFoundError && echo "rclpy not in venv (OK)"

echo "==> Done. Venv size: $(du -sh .venv | cut -f1)"
