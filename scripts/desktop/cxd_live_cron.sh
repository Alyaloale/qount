#!/bin/bash
# C×D combo live orchestrator (线 C×D):60% trend (USDⓈ-M perp, x4_live.py) + 40% carry
# (spot + COIN-M dated cash-and-carry, rv_live.py), ONE cron, one total-capital split.
#
#   QOUNT_CXD_CAPITAL=2000 bash cxd_live_cron.sh dry    # split 1200/800, print, no orders
#   QOUNT_CXD_CAPITAL=2000 bash cxd_live_cron.sh live   # real orders (each leg still needs ITS arm
#                                                        # switch + key: QOUNT_X4_LIVE_ENABLE /
#                                                        # QOUNT_RV_LIVE_ENABLE in the env file)
#
# NOTE: this REPLACES the standalone com.qount.x4-live cron for the trend leg -- run only ONE of them
# (two configs trading the same USDⓈ-M account would fight). Keys/arm switches live OUTSIDE the repo
# in ~/.config/qount/x4_live.env (chmod 600). Publishes state/{x4,rv}/live -> web cxd_live.json.
set -u
REPO="${QOUNT_REPO:-/root/qount}"
PY="$REPO/.venv/bin/python"
LOG="$HOME/cxd_live.log"
WEB_DATA="/var/www/qount/data"
ENV_FILE="$HOME/.config/qount/x4_live.env"
MODE="${1:-dry}"
TOTAL="${QOUNT_CXD_CAPITAL:-1000}"
echo "=== $(date '+%F %T %Z') C×D total=$TOTAL mode=$MODE ===" >> "$LOG"
cd "$REPO" || { echo "[ALERT] cannot cd $REPO" >> "$LOG"; exit 1; }
# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

# 60/40 split of the total across the two legs (separate wallets: trend=USDⓈ-M, carry=spot+COIN-M)
export QOUNT_X4_CAPITAL=$("$PY" -c "print(round($TOTAL*0.6, 2))")
export QOUNT_RV_CAPITAL=$("$PY" -c "print(round($TOTAL*0.4, 2))")
echo "  split: trend \$$QOUNT_X4_CAPITAL (60%) + carry \$$QOUNT_RV_CAPITAL (40%)" >> "$LOG"

notify() {  # $1=title $2=body — no-op unless Server酱 key set
  [ -n "${QOUNT_SERVERCHAN_KEY:-}" ] || return 0
  curl -s --max-time 12 "https://sctapi.ftqq.com/${QOUNT_SERVERCHAN_KEY}.send" \
    --data-urlencode "title=$1" --data-urlencode "desp=$2" -o /dev/null 2>/dev/null
}

run_leg() {  # $1=script $2=success marker
  local out rc
  out=$("$PY" "scripts/desktop/$1" "$MODE" 2>&1); rc=$?
  echo "$out" >> "$LOG"
  if [ $rc -ne 0 ] || ! printf '%s' "$out" | grep -qF "$2"; then
    local last; last=$(printf '%s' "$out" | tail -1)
    echo "[ALERT] C×D '$1' FAILED rc=$rc :: $last" >> "$LOG"
    notify "C×D实盘告警·$1 失败" "$(date '+%F %T') rc=$rc%0A$last"
  fi
}

run_leg x4_live.py "[X4-LIVE"     # trend leg (60%)
run_leg rv_live.py "[RV-LIVE"     # carry leg (40%)

# publish combined snapshot for the dashboard (atomic via tmp+mv)
if [ -d "$WEB_DATA" ]; then
  if "$PY" - "$REPO/state" "$TOTAL" > /tmp/cxd_live.json.tmp <<'PYEOF'
import json, os, sys, datetime
base, total = sys.argv[1], float(sys.argv[2])
def load(p):
    try:
        with open(p) as fh: return json.load(fh)
    except Exception: return None
print(json.dumps({
    "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "total_capital": total, "weights": {"trend": 0.6, "carry": 0.4},
    "trend": load(os.path.join(base, "x4", "live", "latest.json")),
    "carry": load(os.path.join(base, "rv", "live", "latest.json")),
}, ensure_ascii=False, default=float))
PYEOF
  then
    mv /tmp/cxd_live.json.tmp "$WEB_DATA/cxd_live.json"
    echo "[web] published cxd_live.json" >> "$LOG"
  else
    echo "[ALERT] bundle cxd_live.json failed" >> "$LOG"
  fi
fi
