#!/usr/bin/env bash
# Quick launcher for local offline LLM
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="/mnt/data_vault/Documents/BigFish-cli/venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

exec "$VENV_PYTHON" "$SCRIPT_DIR/chat.py" "$@"
