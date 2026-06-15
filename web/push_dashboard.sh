#!/bin/bash
# Push the dashboard data (线 A A股 CTA-R + 线 D X4 paper) up to the VPS web data dir.
#
# Runs on the Mac (the only host that can reach BOTH WSL `home` and the 墙外 VPS):
#   1. A股 CTA-R 模拟盘 状态  ← ssh home → WSL `cta_portfolio status --json`   -> cta.json
#   2. 加密 X4 paper 三本 book ← 本地 state/x4/paper/*latest.json 打包          -> x4_paper.json
#   3. scp 两个文件到 VPS:/var/www/qount/data/
#
# The 加密 X4 live (实盘) 数据 already lives ON the VPS (x4_live_cron.sh writes it);
# x4_live_cron.sh 自己把它 cp 进 /var/www/qount/data/x4_live.json,本脚本不管。
#
# Read-only on all sources. Never places an order. Driven by launchd (com.qount.dashboard.plist).
set -u

REPO="${QOUNT_REPO:-/Users/alyaloale/Code/qount}"
VPS="${QOUNT_VPS:-root@8.220.130.35}"
WEB_DATA="/var/www/qount/data"
PAPER="$REPO/state/x4/paper"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log() { echo "$(date '+%F %T') $*"; }

# --- 1. A股 CTA-R status from WSL ---
# On a transient WSL/network hiccup we DON'T push (would blank the last-good A股 data on the
# site). Only a valid status (must contain "equity") gets added to the push set.
PUSH=("$TMP/x4_paper.json")   # paper is always local, always pushable
ssh -o BatchMode=yes -o ConnectTimeout=15 -o ClearAllForwardings=yes home wsl.exe bash -s <<'EOF' 2>/dev/null \
  | grep '^{' | tail -1 > "$TMP/cta.json"
cd ~/Code/qount && .venv/bin/python -m qount.cta_portfolio status --json 2>/dev/null
EOF
if grep -q '"equity"' "$TMP/cta.json" 2>/dev/null; then
  PUSH=("$TMP/cta.json" "${PUSH[@]}")
else
  log "[warn] A股取数失败,跳过 cta.json(保留服务器上最后一份)"
fi

# --- 2. bundle X4 paper books into one file ---
/usr/bin/python3 - "$PAPER" > "$TMP/x4_paper.json" <<'PY'
import json, os, sys
base = sys.argv[1]
def load(name):
    try:
        with open(os.path.join(base, name)) as fh:
            return json.load(fh)
    except Exception:
        return None
out = {
    "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
    "holdings": load("holdings_latest.json"),
    "three": load("latest.json"),
    "s7": load("s7_latest.json"),
    "combo": load("combo_latest.json"),
}
print(json.dumps(out, ensure_ascii=False, default=float))
PY

# --- 3. push to VPS (retry once on transient ssh failure) ---
names="$(for f in "${PUSH[@]}"; do basename "$f"; done | tr '\n' ' ')"
for attempt in 1 2; do
  if scp -o BatchMode=yes -o ConnectTimeout=10 -q "${PUSH[@]}" "$VPS:$WEB_DATA/"; then
    log "[ok] pushed $names-> $VPS:$WEB_DATA"
    exit 0
  fi
  log "[warn] scp attempt $attempt failed"
  sleep 3
done
log "[error] scp to VPS failed after retries"
exit 1
