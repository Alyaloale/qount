#!/bin/bash
# Fetch CTA-R portfolio status JSON from WSL for the Mac desktop widget / menu bar.
# The data + engine live on WSL; the Mac is display-only. Read-only, never trades.
exec /usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=15 -o ClearAllForwardings=yes home wsl.exe bash -s <<'WSLEOF'
cd ~/Code/qount && .venv/bin/python -m qount.cta_portfolio status --json 2>/dev/null
WSLEOF
