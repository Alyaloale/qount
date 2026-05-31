#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${QOUNT_WSL_HOST:-home}"
REMOTE_DIR="${QOUNT_WSL_DIR:-/home/alyaloale/Code/qount}"
TEST_TARGET="${1:-discover}"

if [[ "$TEST_TARGET" == "discover" ]]; then
  ssh -o ClearAllForwardings=yes "$REMOTE_HOST" 'wsl.exe bash -s' <<EOF
set -euo pipefail
cd "$REMOTE_DIR"
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
EOF
else
  ssh -o ClearAllForwardings=yes "$REMOTE_HOST" 'wsl.exe bash -s' <<EOF
set -euo pipefail
cd "$REMOTE_DIR"
PYTHONPATH=src ./.venv/bin/python -m unittest "$TEST_TARGET"
EOF
fi
