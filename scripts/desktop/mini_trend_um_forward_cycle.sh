#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${QOUNT_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
PYTHON="${QOUNT_PYTHON_BIN:-$REPO/.venv/bin/python}"
STATE_ROOT="${QOUNT_MINI_TREND_STATE_ROOT:-$REPO/state/mini_trend}"
FORWARD_ROOT="$STATE_ROOT/forward"
CACHE_DIR="$FORWARD_ROOT/cache"
FUNDING_ROOT="$FORWARD_ROOT/funding"
PAPER_ROOT="$STATE_ROOT/paper"
JOURNAL_PATH="$PAPER_ROOT/pilot.jsonl"
DRY_ROOT="$STATE_ROOT/dry"
AUTHORITY_ROOT="${QOUNT_DASHBOARD_AUTHORITY_ROOT:-/var/lib/qount/dashboard-authority}"
AUTHORITY_RUNTIME_ROOT="${QOUNT_DASHBOARD_RUNTIME_ROOT:-/var/lib/qount/dashboard-runtime}"
AUTHORITY_BACKUP_ROOT="${QOUNT_DASHBOARD_BACKUP_ROOT:-/var/lib/qount/dashboard-backups}"
DASHBOARD_ROOT="${QOUNT_DASHBOARD_ROOT:-/var/www/qount/data}"
AUTHORITY_LOCK_PATH="${QOUNT_DASHBOARD_LOCK_PATH:-/run/qount-dashboard/publisher.lock}"
NOTIFICATION_STORE="${QOUNT_NOTIFICATION_STORE:-/var/lib/qount/notifications/store.sqlite3}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$FORWARD_ROOT/runs/$STAMP"
LOCK_PATH="$STATE_ROOT/forward-cycle.lock"

mkdir -p "$RUN_DIR" "$CACHE_DIR" "$FUNDING_ROOT" "$PAPER_ROOT" "$DRY_ROOT"
exec 9>"$LOCK_PATH"
if ! flock -n 9; then
  printf '%s\n' "mini_trend_forward_cycle=skipped_locked"
  exit 0
fi

if [[ -e "$STATE_ROOT/HALT" ]]; then
  printf '%s\n' "mini_trend_forward_cycle=blocked_halt_file"
  exit 75
fi

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

for flag in \
  "${QOUNT_LIVE_ENABLE:-false}" \
  "${QOUNT_X4_LIVE_ENABLE:-false}" \
  "${QOUNT_RV_LIVE_ENABLE:-false}" \
  "${QOUNT_CXD_CARRY_ENABLE:-false}"
do
  if is_true "$flag"; then
    printf '%s\n' "mini_trend_forward_cycle=blocked_live_switch"
    exit 76
  fi
done

unset QOUNT_LIVE_CONFIRMATION
unset QOUNT_MINI_TREND_LIVE_CONFIRMATION
unset QOUNT_MINI_TREND_ARM_TOKEN

if [[ ! -x "$PYTHON" ]]; then
  printf 'python_not_executable=%s\n' "$PYTHON" >&2
  exit 77
fi

DISPATCH_CONTRACT_HASH="$(
  PYTHONPATH="$REPO/src" "$PYTHON" -c \
    'from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT; print(LIVE_PILOT_CONTRACT.contract_hash)'
)"
if [[ ! "$DISPATCH_CONTRACT_HASH" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'dispatch_contract_hash_invalid=%s\n' "$DISPATCH_CONTRACT_HASH" >&2
  exit 78
fi
DISPATCH_JOURNAL_PATH="$DRY_ROOT/contracts/$DISPATCH_CONTRACT_HASH/dispatcher.jsonl"
mkdir -p "$(dirname "$DISPATCH_JOURNAL_PATH")"

export QOUNT_EXCHANGE_BYPASS_PROXY=true
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

RULES_PATH="$RUN_DIR/exchange_rules.json"
INPUT_PATH="$RUN_DIR/shadow_inputs.json"
PREFLIGHT_PATH="$RUN_DIR/account_preflight.json"
PAPER_PATH="$RUN_DIR/paper_runtime.json"
PROJECTION_PATH="$RUN_DIR/latest_projection.json"
DISPATCH_READINESS_PATH="$RUN_DIR/dispatch_readiness.json"
READINESS_PATH="$RUN_DIR/live_readiness.json"
DISPATCH_PATH="$RUN_DIR/dry_dispatch.json"
RUNTIME_PROOF_PATH="$RUN_DIR/runtime_proof.json"
AUTHORITY_RESULT_PATH="$RUN_DIR/authority_result.json"
RELEASE_PROVENANCE_PATH="$REPO/.qount-release-provenance.json"
RELEASE_PROVENANCE_VERIFY_PATH="$RUN_DIR/release_provenance.json"

cd "$REPO"

"$PYTHON" scripts/operations/verify_release_provenance.py \
  --repo-root "$REPO" \
  --provenance-path "$RELEASE_PROVENANCE_PATH" \
  --output-path "$RELEASE_PROVENANCE_VERIFY_PATH"

"$PYTHON" scripts/desktop/mini_trend_um_runtime_proof.py \
  --cycle-path "$REPO/scripts/desktop/mini_trend_um_forward_cycle.sh" \
  --service-unit-path /etc/systemd/system/qount-mini-trend-forward.service \
  --output-path "$RUNTIME_PROOF_PATH"

"$PYTHON" scripts/research/alpha_agent_exchange_rules.py \
  --market um \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT \
  --output-path "$RULES_PATH"

input_args=(
  --cache-dir "$CACHE_DIR"
  --funding-snapshot-root "$FUNDING_ROOT"
  --start-month 2025-12
  --transport-label direct_vps
  --output-path "$INPUT_PATH"
)
if [[ -d "$REPO/state/grid_b/klines" ]]; then
  input_args+=(--seed-cache-dir "$REPO/state/grid_b/klines")
fi
"$PYTHON" scripts/research/mini_trend_futures_shadow_inputs.py "${input_args[@]}"

"$PYTHON" scripts/desktop/mini_trend_um_preflight.py \
  --output-path "$PREFLIGHT_PATH"

# The order-free projection stays on the fixed canary budget. Account balance
# sufficiency remains a fail-closed readiness gate in the preflight artifact.
CAPITAL_USDT="100.00000000"

"$PYTHON" scripts/desktop/mini_trend_um_paper.py \
  --exchange-rules-path "$RULES_PATH" \
  --journal-path "$JOURNAL_PATH" \
  --cache-dir "$CACHE_DIR" \
  --funding-snapshot-root "$FUNDING_ROOT" \
  --start-month 2025-12 \
  --capital-usdt "$CAPITAL_USDT" \
  --output-path "$PAPER_PATH"

"$PYTHON" scripts/desktop/mini_trend_um_project.py \
  --exchange-rules-path "$RULES_PATH" \
  --cache-dir "$CACHE_DIR" \
  --funding-snapshot-root "$FUNDING_ROOT" \
  --start-month 2025-12 \
  --capital-usdt "$CAPITAL_USDT" \
  --output-path "$PROJECTION_PATH"

projection_verdict="$("$PYTHON" - "$PROJECTION_PATH" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print((payload.get("diagnostics") or {}).get("verdict") or "")
PY
)"
case "$projection_verdict" in
  await_latest_completed_pilot_bar)
    # Preserve the diagnostic run, but do not publish incomplete authority or
    # pass an absent decision to either dispatcher.
    ln -sfn "runs/$STAMP" "$FORWARD_ROOT/latest"
    printf 'mini_trend_forward_cycle=await_latest_completed_pilot_bar\nrun_dir=%s\n' \
      "$RUN_DIR"
    exit 0
    ;;
  latest_causal_decision_projected) ;;
  *)
    printf 'mini_trend_forward_cycle=blocked_projection_verdict:%s\n' \
      "$projection_verdict" >&2
    exit 79
    ;;
esac

readiness_args=(
  --owner-requested \
  --capital-usdt "$CAPITAL_USDT" \
  --start-date 2026-07-19 \
  --preflight-path "$PREFLIGHT_PATH" \
  --paper-path "$PAPER_PATH" \
  --shadow-input-path "$INPUT_PATH" \
  --release-provenance-path "$RELEASE_PROVENANCE_VERIFY_PATH" \
  --dry-journal-path "$DISPATCH_JOURNAL_PATH" \
  --runtime-proof-path "$RUNTIME_PROOF_PATH" \
  --legacy-live-guard-disarmed
)
if [[ -x "$REPO/scripts/desktop/mini_trend_um_rollback.sh" ]]; then
  readiness_args+=(--rollback-documented)
fi

legacy_runtime_disabled=false
if command -v crontab >/dev/null 2>&1; then
  if ! (crontab -l 2>/dev/null || true) \
    | sed '/^[[:space:]]*#/d;/^[[:space:]]*$/d' \
    | grep -q .
  then
    legacy_runtime_disabled=true
  fi
fi
if [[ "$legacy_runtime_disabled" == true ]] && command -v systemctl >/dev/null 2>&1; then
  for unit in \
    qount-mini-trend.service \
    qount-mini-trend.timer \
    qount-runner.service \
    qount-runner.timer \
    qount-alpha-collector.service
  do
    if systemctl is-active --quiet "$unit"; then
      legacy_runtime_disabled=false
      break
    fi
  done
fi
if [[ "$legacy_runtime_disabled" == true ]]; then
  readiness_args+=(--legacy-production-cron-disabled)
fi

"$PYTHON" scripts/research/mini_trend_live_pilot_readiness.py \
  "${readiness_args[@]}" \
  --output-path "$DISPATCH_READINESS_PATH"

"$PYTHON" scripts/desktop/mini_trend_um_dispatch.py \
  --mode dry \
  --preflight-path "$PREFLIGHT_PATH" \
  --projection-path "$PROJECTION_PATH" \
  --readiness-path "$DISPATCH_READINESS_PATH" \
  --exchange-rules-path "$RULES_PATH" \
  --journal-path "$DISPATCH_JOURNAL_PATH" \
  --halt-path "$STATE_ROOT/HALT" \
  --output-path "$DISPATCH_PATH"

# Publish this completed order-free run through the standard Phase B/C authority
# before final readiness is evaluated. A failed writer leaves the prior authority
# intact and stops this cycle.
ln -sfn "runs/$STAMP" "$FORWARD_ROOT/latest"
env -u BINANCE_API_KEY -u BINANCE_SECRET \
  -u QOUNT_BINANCE_API_KEY -u QOUNT_BINANCE_API_SECRET \
  "$PYTHON" scripts/operations/write_authority_bundle.py \
  --repo-root "$REPO" \
  --source-root "$FORWARD_ROOT/latest" \
  --authority-root "$AUTHORITY_ROOT" \
  --runtime-root "$AUTHORITY_RUNTIME_ROOT" \
  --backup-root "$AUTHORITY_BACKUP_ROOT" \
  --dashboard-root "$DASHBOARD_ROOT" \
  --lock-path "$AUTHORITY_LOCK_PATH" \
  --notification-store "$NOTIFICATION_STORE" \
  --result-path "$AUTHORITY_RESULT_PATH"

# A newly validated decision and the matching standard authority must count in
# this run's final readiness. Elapsed-day targets remain visible observations.
"$PYTHON" scripts/research/mini_trend_live_pilot_readiness.py \
  "${readiness_args[@]}" \
  --authority-root "$AUTHORITY_ROOT" \
  --authority-result-path "$AUTHORITY_RESULT_PATH" \
  --output-path "$READINESS_PATH"
printf 'mini_trend_forward_cycle=complete\nrun_dir=%s\n' "$RUN_DIR"
