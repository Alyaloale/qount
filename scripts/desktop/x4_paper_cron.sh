#!/bin/bash
# Linux/VPS cron version of the X4 paper-sim forward run (线 D §18 / §19.7 / §20.4) — migrated off the
# Mac so the模拟盘 forward books advance 7x24 even when the Mac is off. The 墙外 VPS reaches
# binance.vision directly, so NO proxy is needed. Pure simulation, NO real orders.
#
# Runs the 4 tracks, then bundles state/x4/paper/*.json into the dashboard web dir as x4_paper.json
# (replaces the Mac push_dashboard.sh paper step — the VPS now owns x4_paper.json).
#   forward / forward-s7 / forward-combo / holdings  -> state/x4/paper/*.json
# Counterpart of the macOS x4_paper_daily.sh (launchd). Alerts go to the log + optional Server酱.
set -u
REPO="${QOUNT_REPO:-/root/qount}"
PY="$REPO/.venv/bin/python"
LOG="$HOME/x4_paper.log"
WEB_DATA="/var/www/qount/data"
PAPER="$REPO/state/x4/paper"
ENV_FILE="$HOME/.config/qount/x4_live.env"   # reuse for optional QOUNT_SERVERCHAN_KEY
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
run_track forward-combo "[X4-PAPER forward-combo]"
run_track holdings      "[X4-PAPER holdings]"

# Publish the bundled paper snapshot to the dashboard (atomic via tmp+mv).
if [ -d "$WEB_DATA" ]; then
  if "$PY" - "$PAPER" > /tmp/x4_paper.json.tmp <<'PYEOF'
import json, os, sys, datetime
base = sys.argv[1]
def load(n):
    try:
        with open(os.path.join(base, n)) as fh: return json.load(fh)
    except Exception: return None
print(json.dumps({
    "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "holdings": load("holdings_latest.json"), "three": load("latest.json"),
    "s7": load("s7_latest.json"), "combo": load("combo_latest.json"),
}, ensure_ascii=False, default=float))
PYEOF
  then
    mv /tmp/x4_paper.json.tmp "$WEB_DATA/x4_paper.json"
    echo "[web] published x4_paper.json" >> "$LOG"
  else
    echo "[ALERT] bundle x4_paper.json failed" >> "$LOG"
  fi
fi
