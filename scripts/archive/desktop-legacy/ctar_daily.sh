#!/bin/bash
# Daily CTA-R job, triggered by launchd on the (always-on) Mac after A-share close.
# ssh -> WSL -> `cta_portfolio daily`: refresh prices, log equity snapshot, and
# auto-rebalance if a PAPER book is due (live book only prints a manual alert).
# WSL idle-teardown makes WSL-side cron unreliable, so the Mac drives the schedule.
# Alerts (macOS notification) if WSL is unreachable or the daily run errors.
LOG="$HOME/Library/Logs/ctar_daily.log"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"

OUT=$(/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=25 -o ClearAllForwardings=yes home wsl.exe bash -s 2>&1 <<'WSLEOF'
cd ~/Code/qount && .venv/bin/python -m qount.cta_portfolio daily
WSLEOF
)
rc=$?
echo "$OUT" >> "$LOG"

# Success = ssh returned 0 AND the daily command printed its "[daily ...]" marker.
if [ $rc -ne 0 ] || ! printf '%s' "$OUT" | grep -q '\[daily'; then
  last=$(printf '%s' "$OUT" | tail -1)
  echo "[ALERT] daily FAILED rc=$rc :: $last" >> "$LOG"
  /usr/bin/osascript -e "display notification \"rc=$rc · ${last}\" with title \"CTA-R daily 失败\" sound name \"Basso\"" >/dev/null 2>&1
fi
