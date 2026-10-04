#!/usr/bin/env bash
# Freeze and evaluate an explicitly declared checkpoint set in one artifact.
# Pass --checkpoint repeatedly, plus --data-root, --start, --end and --out.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
exec "${QOUNT_PYTHON_BIN:-python3}" scripts/research/etf_trader_backtest.py "$@"
