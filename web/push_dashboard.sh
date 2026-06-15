#!/bin/bash
# Push the A股 CTA-R dashboard data up to the VPS web data dir.
#
# Runs on the Mac (the only host that can reach BOTH WSL `home` and the 墙外 VPS):
#   A股 CTA-R 模拟盘 状态  ← ssh home → WSL `cta_portfolio status --json`  -> cta.json  -> VPS
#
# 加密数据都在 VPS 上自产自发,本脚本不管:
#   - X4 live (实盘)  : x4_live_cron.sh   写 /var/www/qount/data/x4_live.json
#   - X4 paper (模拟盘): x4_paper_cron.sh  写 /var/www/qount/data/x4_paper.json  (2026-06-15 迁离 Mac)
# A股(线 A)引擎/数据仍在 WSL,VPS 在墙外取不到境内行情,故 A股仍由 Mac 中继。
#
# Read-only. Never places an order. Driven by launchd (com.qount.dashboard.plist).
set -u

VPS="${QOUNT_VPS:-root@8.220.130.35}"
WEB_DATA="/var/www/qount/data"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
log() { echo "$(date '+%F %T') $*"; }

# --- A股 CTA-R status from WSL ---
# On a transient WSL/network hiccup we DON'T push (would blank the last-good A股 data on the site).
ssh -o BatchMode=yes -o ConnectTimeout=15 -o ClearAllForwardings=yes home wsl.exe bash -s <<'EOF' 2>/dev/null \
  | grep '^{' | tail -1 > "$TMP/cta.json"
cd ~/Code/qount && .venv/bin/python -m qount.cta_portfolio status --json 2>/dev/null
EOF
if ! grep -q '"equity"' "$TMP/cta.json" 2>/dev/null; then
  log "[warn] A股取数失败,跳过(保留服务器上最后一份)"
  exit 0
fi

# --- push to VPS (retry once on transient ssh failure) ---
for attempt in 1 2; do
  if scp -o BatchMode=yes -o ConnectTimeout=10 -q "$TMP/cta.json" "$VPS:$WEB_DATA/"; then
    log "[ok] pushed cta.json -> $VPS:$WEB_DATA"
    exit 0
  fi
  log "[warn] scp attempt $attempt failed"
  sleep 3
done
log "[error] scp to VPS failed after retries"
exit 1
