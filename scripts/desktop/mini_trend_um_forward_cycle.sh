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
DISPATCH_JOURNAL_PATH="$DRY_ROOT/dispatcher.jsonl"
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

export QOUNT_EXCHANGE_BYPASS_PROXY=true
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

RULES_PATH="$RUN_DIR/exchange_rules.json"
INPUT_PATH="$RUN_DIR/shadow_inputs.json"
PREFLIGHT_PATH="$RUN_DIR/account_preflight.json"
PAPER_PATH="$RUN_DIR/paper_runtime.json"
PROJECTION_PATH="$RUN_DIR/latest_projection.json"
READINESS_PATH="$RUN_DIR/live_readiness.json"
DISPATCH_PATH="$RUN_DIR/dry_dispatch.json"
RUNTIME_PROOF_PATH="$RUN_DIR/runtime_proof.json"

cd "$REPO"

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

CAPITAL_USDT="$("$PYTHON" -c 'import json,sys; p=json.load(open(sys.argv[1])); v=float(p["evidence"]["available_balance_usdt"]); assert 0 < v <= 1000; print(format(v, ".8f"))' "$PREFLIGHT_PATH")"

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

readiness_args=(
  --owner-requested \
  --capital-usdt "$CAPITAL_USDT" \
  --start-date 2026-07-19 \
  --preflight-path "$PREFLIGHT_PATH" \
  --paper-path "$PAPER_PATH" \
  --shadow-input-path "$INPUT_PATH" \
  --dry-journal-path "$DISPATCH_JOURNAL_PATH" \
  --runtime-proof-path "$RUNTIME_PROOF_PATH" \
  --legacy-live-guard-disarmed \
  --output-path "$READINESS_PATH"
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

"$PYTHON" scripts/research/mini_trend_live_pilot_readiness.py "${readiness_args[@]}"

"$PYTHON" scripts/desktop/mini_trend_um_dispatch.py \
  --mode dry \
  --preflight-path "$PREFLIGHT_PATH" \
  --projection-path "$PROJECTION_PATH" \
  --readiness-path "$READINESS_PATH" \
  --exchange-rules-path "$RULES_PATH" \
  --journal-path "$DISPATCH_JOURNAL_PATH" \
  --halt-path "$STATE_ROOT/HALT" \
  --output-path "$DISPATCH_PATH"

# A newly validated completed-bar decision must count in this run's final readiness.
"$PYTHON" scripts/research/mini_trend_live_pilot_readiness.py "${readiness_args[@]}"
ln -sfn "runs/$STAMP" "$FORWARD_ROOT/latest"
printf 'mini_trend_forward_cycle=complete\nrun_dir=%s\n' "$RUN_DIR"
