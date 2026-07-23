#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${QOUNT_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
PYTHON="${QOUNT_PYTHON_BIN:-$REPO/.venv/bin/python}"
STATE_ROOT="${QOUNT_MINI_TREND_STATE_ROOT:-$REPO/state/mini_trend}"
RUNTIME_LEDGER="${QOUNT_DASHBOARD_RUNTIME_ROOT:-/var/lib/qount/dashboard-runtime}/runtime.sqlite3"
HALT_PATH="$STATE_ROOT/HALT"
STATE_DIR="${QOUNT_PHASE_B_STATE_DIR:-$REPO/state/phase_b}"
LIVE_COMPLETED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

cd "$REPO"
exec "$PYTHON" scripts/operations/phase_b_readonly_run.py \
  --mode all \
  --symbols BTCUSDT ETHUSDT BNBUSDT \
  --runtime-ledger-path "$RUNTIME_LEDGER" \
  --halt-path "$HALT_PATH" \
  --state-dir "$STATE_DIR" \
  --live-cycle-completed-at "$LIVE_COMPLETED_AT"
