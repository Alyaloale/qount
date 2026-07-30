#!/bin/bash
# Daily X4 small-cap LIVE spot run (线 D §21) — fixed TOP7 S7-mini, triggered by launchd.
# Strategy: BTC/ETH/BNB/SOL/XRP/ADA/LINK · spot · 1x · inverse-vol · BTC 200d master gate.
#
# SAFE BY DEFAULT: runs `x4_live.py live`, but order placement is self-gated by QOUNT_X4_LIVE_ENABLE.
# Secrets + the arm switch live OUTSIDE the repo in ~/.config/qount/x4_live.env (chmod 600), sourced
# only if present. Until you create that file the job logs INTENDED orders and sends NOTHING.
# To ARM: create the env file with
#     export QOUNT_BINANCE_API_KEY=...        # Binance key: SPOT TRADE only, NO withdrawal, IP-whitelisted
#     export QOUNT_BINANCE_API_SECRET=...
#     export QOUNT_X4_LIVE_ENABLE=1
# PROXY (mainland China): launchd does NOT inherit your shell's HTTP(S)_PROXY, so a job that reaches
# Binance fine from the terminal may FAIL under launchd. Put the proxy in $ENV_FILE (alongside keys),
# e.g.  export HTTPS_PROXY=http://127.0.0.1:7897  — this script normalizes it for both curl and ccxt
# (build_exchange reads QOUNT_HTTPS_PROXY/HTTPS_PROXY) and preflights api.binance.com before trading.
# Crypto trades 7d/wk -> runs daily. Alerts (macOS notification) on error. Logs to ~/Library/Logs/x4_live.log.
set -u
REPO="/Users/alyaloale/Code/qount"
LOG="$HOME/Library/Logs/x4_live.log"
ENV_FILE="$HOME/.config/qount/x4_live.env"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"
cd "$REPO" || { echo "[ALERT] cannot cd $REPO" >> "$LOG"; exit 1; }
# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

# Normalize whatever proxy var the env file set -> export all the names curl + ccxt look at.
PROXY="${QOUNT_HTTPS_PROXY:-${HTTPS_PROXY:-${HTTP_PROXY:-${ALL_PROXY:-}}}}"
if [ -n "$PROXY" ]; then
  export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" QOUNT_HTTPS_PROXY="$PROXY"
  export http_proxy="$PROXY" https_proxy="$PROXY"
  echo "[proxy] $PROXY" >> "$LOG"
else
  echo "[proxy] none (ok if Binance reachable直连; in CN you likely need one in $ENV_FILE)" >> "$LOG"
fi

# Preflight: confirm the Binance API is reachable before doing anything (catches a down proxy early
# instead of a blind/half order run). launchd-safe: no shell env assumed beyond what we exported above.
if ! curl -sf --max-time 12 https://api.binance.com/api/v3/ping -o /dev/null 2>/dev/null; then
  echo "[ALERT] api.binance.com unreachable (proxy down / GFW?) — skipping run" >> "$LOG"
  /usr/bin/osascript -e "display notification \"api.binance.com 连不上(代理断?)· 本次跳过\" with title \"X4 live daily 失败\" sound name \"Basso\"" >/dev/null 2>&1
  exit 1
fi

if [ "${QOUNT_X4_LIVE_ENABLE:-}" = "1" ]; then
  echo "[armed] QOUNT_X4_LIVE_ENABLE=1 — real spot orders may be placed" >> "$LOG"
else
  echo "[unarmed] no env file / switch off — intended orders logged, nothing sent" >> "$LOG"
fi

out=$("$REPO/.venv/bin/python" scripts/desktop/x4_live.py live 2>&1)
rc=$?
echo "$out" >> "$LOG"
if [ $rc -ne 0 ] || ! printf '%s' "$out" | grep -qF "[X4-LIVE live]"; then
  last=$(printf '%s' "$out" | tail -1)
  echo "[ALERT] x4 live FAILED rc=$rc :: $last" >> "$LOG"
  /usr/bin/osascript -e "display notification \"rc=$rc · ${last}\" with title \"X4 live daily 失败\" sound name \"Basso\"" >/dev/null 2>&1
fi
