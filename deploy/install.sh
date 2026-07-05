#!/usr/bin/env bash
# Real-robot one-shot install for the dax-agent thin entrypoint.
# Run on the robot after cloning the deploy/dax-agent branch:
#   git clone -b deploy/dax-agent <dimos-repo> /opt/dax-agent
#   cd /opt/dax-agent && bash deploy/install.sh
set -euo pipefail

INSTALL_DIR="${1:-/opt/dax-agent}"
LOG_DIR="/var/log/dax-agent"
SERVICE="dax-agent.service"

cd "$INSTALL_DIR"

echo "==> Installing Python deps via uv (minimal dax-agent, isolated venv)"
if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv not installed. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi
bash deploy/uv-sync-robot.sh "$INSTALL_DIR"

echo "==> Placing .env from template (skip if already present)"
if [ ! -f .env ]; then
    cp deploy/dax-agent.env.example .env
    echo "  Created .env from template. EDIT IT NOW: vim .env"
else
    echo "  .env already exists, leaving as-is"
fi

echo "==> Creating data dir for wave animation"
mkdir -p data
if [ -f scripts/dax_hi_ani.json ] && [ ! -f data/dax_hi_ani.json ]; then
    cp scripts/dax_hi_ani.json data/dax_hi_ani.json
fi

echo "==> Creating log dir"
sudo mkdir -p "$LOG_DIR"
sudo chown "$(whoami)" "$LOG_DIR"

echo "==> Installing systemd unit"
sudo cp deploy/dax-agent.service /etc/systemd/system/$SERVICE
sudo systemctl daemon-reload

echo
echo "Done. Next steps:"
echo "  1. Edit .env: vim $INSTALL_DIR/.env  (set DEEPSEEK_API_KEY, DAX_JOINT_SERVER_URL, ROSBRIDGE_GRPC_TARGET)"
echo "  2. Adjust py-rosbridge path in pyproject.toml if not at /home/miaoli/Projects/py_rosbridge"
echo "  3. Start: sudo systemctl start dax-agent"
echo "  4. Status: sudo systemctl status dax-agent"
echo "  5. Logs: tail -f $LOG_DIR/dax-agent.log"
echo "  6. Enable boot start: sudo systemctl enable dax-agent"
