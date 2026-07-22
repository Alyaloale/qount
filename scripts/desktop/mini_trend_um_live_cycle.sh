#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${QOUNT_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
PYTHON="${QOUNT_PYTHON_BIN:-$REPO/.venv/bin/python}"
STATE_ROOT="${QOUNT_MINI_TREND_STATE_ROOT:-$REPO/state/mini_trend}"
FORWARD_ROOT="$STATE_ROOT/forward"
ARM_PATH="${QOUNT_MINI_TREND_ARM_PATH:-$STATE_ROOT/arm/manual-final-arm.json}"
LIVE_ENV_PATH="${QOUNT_MINI_TREND_LIVE_ENV_PATH:-/root/.config/qount/mini-trend-live.env}"
LIVE_ROOT="$STATE_ROOT/live"
AUTHORITY_ROOT="${QOUNT_DASHBOARD_AUTHORITY_ROOT:-/var/lib/qount/dashboard-authority}"
AUTHORITY_RUNTIME_ROOT="${QOUNT_DASHBOARD_RUNTIME_ROOT:-/var/lib/qount/dashboard-runtime}"
AUTHORITY_BACKUP_ROOT="${QOUNT_DASHBOARD_BACKUP_ROOT:-/var/lib/qount/dashboard-backups}"
DASHBOARD_ROOT="${QOUNT_DASHBOARD_ROOT:-/var/www/qount/data}"
AUTHORITY_LOCK_PATH="${QOUNT_DASHBOARD_LOCK_PATH:-/run/qount-dashboard/publisher.lock}"
NOTIFICATION_STORE="${QOUNT_NOTIFICATION_STORE:-/var/lib/qount/notifications/store.sqlite3}"
LOCK_PATH="$STATE_ROOT/forward-cycle.lock"

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
    printf '%s\n' "mini_trend_live_cycle=blocked_legacy_live_switch"
    exit 76
  fi
done

if ! is_true "${QOUNT_MINI_TREND_LIVE_ENABLE:-false}"; then
  printf '%s\n' "mini_trend_live_cycle=blocked_live_switch"
  exit 77
fi
if [[ -z "${QOUNT_MINI_TREND_LIVE_CONFIRMATION:-}" ]]; then
  printf '%s\n' "mini_trend_live_cycle=blocked_live_confirmation"
  exit 78
fi
if [[ -z "${QOUNT_MINI_TREND_ARM_TOKEN:-}" ]]; then
  printf '%s\n' "mini_trend_live_cycle=blocked_arm_token"
  exit 79
fi
if [[ ! -f "$LIVE_ENV_PATH" || -L "$LIVE_ENV_PATH" ]]; then
  printf '%s\n' "mini_trend_live_cycle=blocked_live_env_file"
  exit 80
fi
env_mode_owner="$(stat -c '%a:%u' "$LIVE_ENV_PATH")"
if [[ "$env_mode_owner" != "600:$(id -u)" ]]; then
  printf '%s\n' "mini_trend_live_cycle=blocked_live_env_permissions"
  exit 80
fi
env_parent_mode="$(stat -c '%a' "$(dirname "$LIVE_ENV_PATH")")"
if (( (8#$env_parent_mode & 8#022) != 0 )); then
  printf '%s\n' "mini_trend_live_cycle=blocked_live_env_parent_permissions"
  exit 80
fi
if [[ ! -f "$ARM_PATH" || -L "$ARM_PATH" ]]; then
  printf '%s\n' "mini_trend_live_cycle=blocked_arm_file"
  exit 80
fi
arm_mode_owner="$(stat -c '%a:%u' "$ARM_PATH")"
if [[ "$arm_mode_owner" != "600:$(id -u)" ]]; then
  printf '%s\n' "mini_trend_live_cycle=blocked_arm_permissions"
  exit 80
fi
if [[ -e "$STATE_ROOT/HALT" ]]; then
  printf '%s\n' "mini_trend_live_cycle=blocked_halt_file"
  exit 75
fi
if [[ ! -x "$PYTHON" ]]; then
  printf 'python_not_executable=%s\n' "$PYTHON" >&2
  exit 81
fi

mkdir -p "$LIVE_ROOT"
exec 9>"$LOCK_PATH"
if ! flock -n 9; then
  printf '%s\n' "mini_trend_live_cycle=skipped_locked"
  exit 0
fi

arm_id="$($PYTHON -c 'import json,sys; p=json.load(open(sys.argv[1])); print(p.get("arm_id", ""))' "$ARM_PATH")"
if [[ -z "$arm_id" || "$arm_id" != "$QOUNT_MINI_TREND_LIVE_CONFIRMATION" ]]; then
  printf '%s\n' "mini_trend_live_cycle=blocked_arm_confirmation_mismatch"
  exit 82
fi

DISPATCH_CONTRACT_HASH="$(
  PYTHONPATH="$REPO/src" "$PYTHON" -c \
    'from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT; print(LIVE_PILOT_CONTRACT.contract_hash)'
)"
if [[ ! "$DISPATCH_CONTRACT_HASH" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'dispatch_contract_hash_invalid=%s\n' "$DISPATCH_CONTRACT_HASH" >&2
  exit 86
fi

DISPATCH_JOURNAL_PATH="$STATE_ROOT/dry/contracts/$DISPATCH_CONTRACT_HASH/dispatcher.jsonl"
executed_count="$(
  PYTHONPATH="$REPO/src" "$PYTHON" -c \
    'import sys; from qount.mini_trend.pilot_dispatcher import verify_dispatch_journal; print(len(verify_dispatch_journal(sys.argv[1])["executed_decision_ids"]))' \
    "$DISPATCH_JOURNAL_PATH"
)"

if (( executed_count > 0 )); then
  # After the arm has been consumed once, refresh every input and the standard
  # authority under an explicitly order-free environment. The refresh script
  # owns the same cycle lock, so release it only for that subprocess.
  flock -u 9
  env \
    QOUNT_MINI_TREND_LIVE_ENABLE=false \
    QOUNT_MINI_TREND_LIVE_CONFIRMATION= \
    QOUNT_MINI_TREND_ARM_TOKEN= \
    "$REPO/scripts/desktop/mini_trend_um_forward_cycle.sh"
  if ! flock -n 9; then
    printf '%s\n' "mini_trend_live_cycle=blocked_lock_reacquire"
    exit 83
  fi
fi

RUN_DIR="$(readlink -f "$FORWARD_ROOT/latest")"
case "$RUN_DIR" in
  "$FORWARD_ROOT"/runs/*) ;;
  *)
    printf 'mini_trend_live_cycle=blocked_latest_run_path\n' >&2
    exit 84
    ;;
esac

for name in \
  account_preflight.json \
  latest_projection.json \
  live_readiness.json \
  exchange_rules.json \
  authority_result.json
do
  if [[ ! -f "$RUN_DIR/$name" ]]; then
    printf 'mini_trend_live_cycle=blocked_missing_artifact:%s\n' "$name" >&2
    exit 85
  fi
done

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LIVE_DISPATCH_PATH="$RUN_DIR/live_dispatch-$STAMP.json"

decision_status="$($PYTHON - "$RUN_DIR/latest_projection.json" "$DISPATCH_JOURNAL_PATH" <<'PY'
import json
import sys
from pathlib import Path

projection = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
decision_id = str((projection.get("decision") or {}).get("decision_id") or "")
executed = set()
locked = set()
journal = Path(sys.argv[2])
if journal.exists():
    for raw in journal.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        row_decision = str(row.get("decision_id") or "")
        event_type = str(row.get("event_type") or "")
        if event_type == "live_intent_locked":
            locked.add(row_decision)
        elif event_type == "live_completed":
            executed.add(row_decision)
            locked.discard(row_decision)
if not decision_id:
    print("missing")
elif decision_id in locked:
    print("locked")
elif decision_id in executed:
    print("executed")
else:
    print("new")
PY
)"
case "$decision_status" in
  executed)
    printf 'mini_trend_live_cycle=duplicate_decision_noop\nrun_dir=%s\n' "$RUN_DIR"
    exit 0
    ;;
  locked)
    printf '%s\n' "mini_trend_live_cycle=blocked_unresolved_live_intent"
    exit 87
    ;;
  new) ;;
  *)
    printf '%s\n' "mini_trend_live_cycle=blocked_missing_decision"
    exit 88
    ;;
esac

export QOUNT_EXCHANGE_BYPASS_PROXY=true
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
cd "$REPO"

"$PYTHON" scripts/desktop/mini_trend_um_dispatch.py \
  --mode live \
  --preflight-path "$RUN_DIR/account_preflight.json" \
  --projection-path "$RUN_DIR/latest_projection.json" \
  --readiness-path "$RUN_DIR/live_readiness.json" \
  --exchange-rules-path "$RUN_DIR/exchange_rules.json" \
  --journal-path "$DISPATCH_JOURNAL_PATH" \
  --arm-path "$ARM_PATH" \
  --authority-root "$AUTHORITY_ROOT" \
  --authority-source-root "$FORWARD_ROOT/latest" \
  --runtime-root "$AUTHORITY_RUNTIME_ROOT" \
  --backup-root "$AUTHORITY_BACKUP_ROOT" \
  --dashboard-root "$DASHBOARD_ROOT" \
  --authority-lock-path "$AUTHORITY_LOCK_PATH" \
  --notification-store "$NOTIFICATION_STORE" \
  --halt-path "$STATE_ROOT/HALT" \
  --output-path "$LIVE_DISPATCH_PATH"

ln -sfn "$LIVE_DISPATCH_PATH" "$LIVE_ROOT/latest.json"
printf 'mini_trend_live_cycle=complete\nrun_dir=%s\nlive_dispatch=%s\n' \
  "$RUN_DIR" "$LIVE_DISPATCH_PATH"
