#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${QOUNT_VPS_HOST:-qount-vps}"
REMOTE_DIR="${QOUNT_VPS_DIR:-/root/qount}"
PYTHON_BIN="${QOUNT_VPS_PYTHON:-./.venv/bin/python}"
TEST_TARGET="${1:-discover}"

ssh "$REMOTE_HOST" 'bash -s' -- "$REMOTE_DIR" "$PYTHON_BIN" "$TEST_TARGET" <<'EOF'
set -euo pipefail
REMOTE_DIR="$1"
PYTHON_BIN="$2"
TEST_TARGET="$3"

cd "$REMOTE_DIR"
if [[ "$TEST_TARGET" == "discover" ]]; then
  PYTHONPATH=src "$PYTHON_BIN" -m unittest discover -s tests -p 'test*.py'
else
  PYTHONPATH=src "$PYTHON_BIN" -m unittest "$TEST_TARGET"
fi
EOF
