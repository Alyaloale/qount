#!/bin/bash
# Daily CTA-R job, triggered by launchd on the (always-on) Mac after A-share close.
# ssh -> WSL -> `cta_portfolio daily`: refresh prices, log equity snapshot, and
# auto-rebalance if a PAPER book is due (live book only prints a manual alert).
# WSL idle-teardown makes WSL-side cron unreliable, so the Mac drives the schedule.
LOG="$HOME/Library/Logs/ctar_daily.log"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"
/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=25 -o ClearAllForwardings=yes home wsl.exe bash -s >> "$LOG" 2>&1 <<'WSLEOF'
cd ~/Code/qount && .venv/bin/python -m qount.cta_portfolio daily
WSLEOF
