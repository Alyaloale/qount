#!/bin/bash
# Daily X4 paper-sim forward run (线 D §18 / B2 + §19.7), triggered by launchd on the always-on Mac.
# Runs TWO forward paper tracks, each NO real orders -- pure simulation:
#   1) forward     : the 3-sleeve (S1+S3+S4; S2 excluded) BTC portfolio  -> snapshots.jsonl + latest.json
#   2) forward-s7  : the S7-TREND-PORT 14-coin trend portfolio (§19.7)    -> s7_snapshots.jsonl + s7_latest.json
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

run_track forward     "[X4-PAPER forward]"
run_track forward-s7  "[X4-PAPER forward-s7]"
