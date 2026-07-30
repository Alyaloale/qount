#!/bin/bash
# Daily X4 paper-sim forward run (线 D §18 / B2 + §19.7), triggered by launchd on the always-on Mac.
# Runs the forward paper tracks + the holdings book, each NO real orders -- pure simulation:
#   1) forward       : the 3-sleeve (S1+S3+S4; S2 excluded) BTC portfolio   -> snapshots.jsonl + latest.json
#   2) forward-s7    : the S7-TREND-PORT 14-coin trend portfolio (§19.7)     -> s7_snapshots.jsonl + s7_latest.json
#   2b) forward-s7-vt3: S7 at vol_target=3% (小资金搏盈利档,真前向 since-deploy) -> s7_vt3_snapshots.jsonl + s7_vt3_latest.json
#   3) forward-combo : the §20 C×D combo (60/40 S7-trend / RV-C-carry)       -> combo_snapshots.jsonl + combo_latest.json
#                      (carry leg now uses §20.4 dated day-dump fallback -> refreshes DAILY like the others)
#   4) holdings      : as-of-today forward book (§20.5) -- actual positions  -> holdings_latest.json
#                      (price/qty/value of the combo's carry legs + trend coins + cash; forward P&L from deploy)
# Crypto trades 7d/wk, so this runs every day (unlike the weekday-only ctar_daily job).
# Alerts (macOS notification) if EITHER run errors. Logs to ~/Library/Logs/x4_paper.log.
set -u
REPO="/Users/alyaloale/Code/qount"
LOG="$HOME/Library/Logs/x4_paper.log"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"
cd "$REPO" || { echo "[ALERT] cannot cd $REPO" >> "$LOG"; exit 1; }

run_track() {
  # $1 = mode, $2 = success marker to grep for
  local out rc
  out=$("$REPO/.venv/bin/python" scripts/research/x4_paper.py "$1" 2>&1)
  rc=$?
  echo "$out" >> "$LOG"
  if [ $rc -ne 0 ] || ! printf '%s' "$out" | grep -qF "$2"; then
    local last; last=$(printf '%s' "$out" | tail -1)
    echo "[ALERT] x4 paper '$1' FAILED rc=$rc :: $last" >> "$LOG"
    /usr/bin/osascript -e "display notification \"$1 rc=$rc · ${last}\" with title \"X4 paper daily 失败\" sound name \"Basso\"" >/dev/null 2>&1
  fi
}

run_track forward       "[X4-PAPER forward]"
run_track forward-s7    "[X4-PAPER forward-s7]"
run_track forward-s7-vt3 "[X4-PAPER forward-s7-vt3]"
run_track forward-combo "[X4-PAPER forward-combo]"
run_track holdings      "[X4-PAPER holdings]"
