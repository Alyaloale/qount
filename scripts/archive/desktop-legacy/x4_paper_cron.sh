#!/bin/bash
# Linux/VPS cron version of the X4 paper-sim forward run (线 D §18 / §19.7 / §20.4) — migrated off the
# Mac so the模拟盘 forward books advance 7x24 even when the Mac is off. The 墙外 VPS reaches
# binance.vision directly, so NO proxy is needed. Pure simulation, NO real orders.
#
# Runs the 4 tracks and retains their state artifacts. Dashboard v1 has a separate publisher.
#   forward / forward-s7 / forward-s7-vt3 / forward-combo / holdings  -> state/x4/paper/*.json
#   (forward-s7-vt3 = S7 at vol_target=3% 小资金搏盈利档,真前向 since-deploy -> s7_vt3_latest.json)
# Counterpart of the macOS x4_paper_daily.sh (launchd). Alerts go to the log + optional Server酱.
set -u
REPO="${QOUNT_REPO:-/root/qount}"
PY="$REPO/.venv/bin/python"
LOG="$HOME/x4_paper.log"
ENV_FILE="$HOME/.config/qount/x4_live.env"   # reuse for optional QOUNT_SERVERCHAN_KEY

# shellcheck disable=SC1091
source "$REPO/scripts/desktop/cron_guard.sh"
qount_cron_guard "$0" "x4-paper" "${QOUNT_X4_PAPER_TIMEOUT_SECONDS:-1800}" "$LOG" "$@"

echo "=== $(date '+%F %T %Z') ===" >> "$LOG"
cd "$REPO" || { echo "[ALERT] cannot cd $REPO" >> "$LOG"; exit 1; }
# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

notify() {  # $1=title $2=body — no-op unless Server酱 key set
  [ -n "${QOUNT_SERVERCHAN_KEY:-}" ] || return 0
  curl -s --max-time 12 "https://sctapi.ftqq.com/${QOUNT_SERVERCHAN_KEY}.send" \
    --data-urlencode "title=$1" --data-urlencode "desp=$2" -o /dev/null 2>/dev/null
}

run_track() {  # $1=mode $2=success marker
  local out rc
  out=$("$PY" scripts/research/x4_paper.py "$1" 2>&1); rc=$?
  echo "$out" >> "$LOG"
  if [ $rc -ne 0 ] || ! printf '%s' "$out" | grep -qF "$2"; then
    local last; last=$(printf '%s' "$out" | tail -1)
    echo "[ALERT] x4 paper '$1' FAILED rc=$rc :: $last" >> "$LOG"
    notify "X4模拟盘告警·$1 失败" "$(date '+%F %T') rc=$rc%0A$last"
  fi
}

run_track forward       "[X4-PAPER forward]"
run_track forward-s7    "[X4-PAPER forward-s7]"
run_track forward-s7-vt3 "[X4-PAPER forward-s7-vt3]"
run_track forward-combo "[X4-PAPER forward-combo]"
run_track holdings      "[X4-PAPER holdings]"
