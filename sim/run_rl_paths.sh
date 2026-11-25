#!/usr/bin/env bash
# Repeatable entry point for the sim-RL paths (see run_rl_paths.py).
# Usage: bash sim/run_rl_paths.sh {4|5|6|all} [options]
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VENV="$DIR/../lerobot-env"
if [[ ! -x "$VENV/bin/python" ]]; then
    VENV="$DIR/../venv"
fi
if [[ ! -x "$VENV/bin/python" ]]; then
    echo "[ERROR] 未找到 lerobot-env；先按仓库 install.sh 安装依赖" >&2
    exit 1
fi

export PYTHONPATH="$DIR/../lerobot/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" "$DIR/run_rl_paths.py" "$@"