#!/bin/bash
# Fetch the X4 fixed-TOP7 LIVE status from the VPS (线 D §21) as one compact JSON line for the
# Übersicht widget (x4live.jsx). The bot runs on the 墙外 VPS now, so this ssh's in (key-based) and
# emits its state/x4/live/latest.json compacted. Mirrors line A's ctar_fetch.sh (ssh -> WSL).
VPS="root@8.220.130.35"
ssh -o ConnectTimeout=8 -o BatchMode=yes -o StrictHostKeyChecking=no "$VPS" \
  'python3 -c "import json; print(json.dumps(json.load(open(\"/root/qount/state/x4/live/latest.json\"))))"' \
  2>/dev/null || echo '{"error":"VPS 连不上"}'
