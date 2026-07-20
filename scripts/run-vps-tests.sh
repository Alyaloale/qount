#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${QOUNT_VPS_HOST:-qount-vps}"
REMOTE_DIR="${QOUNT_VPS_DIR:-/root/qount}"
PYTHON_BIN="${QOUNT_VPS_PYTHON:-./.venv/bin/python}"
TEST_TARGET="${1:-production}"

ssh "$REMOTE_HOST" 'bash -s' -- "$REMOTE_DIR" "$PYTHON_BIN" "$TEST_TARGET" <<'EOF'
set -euo pipefail
REMOTE_DIR="$1"
PYTHON_BIN="$2"
TEST_TARGET="$3"

cd "$REMOTE_DIR"
if [[ "$TEST_TARGET" == "production" ]]; then
  PYTHONPATH=src "$PYTHON_BIN" -m unittest \
    tests.test_architecture_boundaries \
    tests.test_runtime_contracts \
    tests.test_dispatch_contract_adapters \
    tests.test_governance_registry \
    tests.test_immutable_contract_artifacts \
    tests.test_decision_batch_artifacts \
    tests.test_legacy_dispatch_replay \
    tests.test_runtime_ledger \
    tests.test_ledger_dashboard_bridge \
    tests.test_notification_producers \
    tests.test_notification_transport \
    tests.test_notifications \
    tests.test_daily_brief \
    tests.test_dashboard_read_models \
    tests.test_authority_importer \
    tests.test_authority_writer \
    tests.test_system_health \
    tests.test_operations_publisher \
    tests.test_publisher_path_audit \
    tests.test_cron_guard \
    tests.test_exchange_throttling \
    tests.test_x4_live \
    tests.test_x4_funding \
    tests.test_grid_data
elif [[ "$TEST_TARGET" == "discover" ]]; then
  PYTHONPATH=src "$PYTHON_BIN" -m unittest discover -s tests -p 'test*.py'
else
  PYTHONPATH=src "$PYTHON_BIN" -m unittest "$TEST_TARGET"
fi
EOF
