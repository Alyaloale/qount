#!/bin/bash
# Linux/VPS cron version of the X4 fixed-TOP7 LIVE spot run (线 D §21) — for a 墙外 VPS with a
# STATIC IP (no proxy, direct to Binance). Counterpart of the macOS x4_live_daily.sh (launchd).
#
# Strategy: BTC/ETH/BNB/SOL/XRP/ADA/LINK · spot · 1x · inverse-vol · BTC 200d master gate.
# Secrets + arm switch in ~/.config/qount/x4_live.env (chmod 600), sourced if present. The VPS reaches
# Binance directly, so NO proxy line is needed in that file. Order placement is self-gated by
# QOUNT_X4_LIVE_ENABLE. Alerts are written to the log (no desktop notifier on a headless VPS).
set -u
REPO="${QOUNT_REPO:-$HOME/qount}"
LOG="$HOME/x4_live.log"
ENV_FILE="$HOME/.config/qount/x4_live.env"
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ===" >> "$LOG"
cd "$REPO" || { echo "[ALERT] cannot cd $REPO" >> "$LOG"; exit 1; }
# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

# WeChat push via Server酱 (set QOUNT_SERVERCHAN_KEY in the env file; no-op if unset).
notify() {  # $1=title  $2=body
  [ -n "${QOUNT_SERVERCHAN_KEY:-}" ] || return 0
  curl -s --max-time 12 "https://sctapi.ftqq.com/${QOUNT_SERVERCHAN_KEY}.send" \
    --data-urlencode "title=$1" --data-urlencode "desp=$2" -o /dev/null 2>/dev/null
}

# Optional proxy normalization (a VPS usually needs none; harmless if unset).
PROXY="${QOUNT_HTTPS_PROXY:-${HTTPS_PROXY:-${HTTP_PROXY:-}}}"
if [ -n "$PROXY" ]; then
  export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" QOUNT_HTTPS_PROXY="$PROXY"
  echo "[proxy] $PROXY" >> "$LOG"
fi

# Preflight: Binance API reachable? (catches a network/region outage before trading)
if ! curl -sf --max-time 12 https://api.binance.com/api/v3/ping -o /dev/null 2>/dev/null; then
  echo "[ALERT] api.binance.com unreachable — skipping run" >> "$LOG"
  notify "X4实盘告警·连不上币安" "$(date '+%F %T') api.binance.com 不可达,本次跳过。检查 VPS 网络。"
  exit 1
fi

if [ "${QOUNT_X4_LIVE_ENABLE:-}" = "1" ]; then
  echo "[armed] real spot orders may be placed" >> "$LOG"
else
  echo "[unarmed] intended orders logged, nothing sent" >> "$LOG"
fi

out=$("$REPO/.venv/bin/python" scripts/desktop/x4_live.py live 2>&1)
rc=$?
echo "$out" >> "$LOG"
if [ $rc -ne 0 ] || ! printf '%s' "$out" | grep -qF "[X4-LIVE live]"; then
  last=$(printf '%s' "$out" | tail -1)
  echo "[ALERT] x4 live FAILED rc=$rc :: $last" >> "$LOG"
  notify "X4实盘告警·运行失败" "$(date '+%F %T') rc=$rc%0A$last"
fi

# Publish the live snapshot to the dashboard web dir (站点 qount.alyaloale.com, web/site).
# Caddy serves /var/www/qount/data/x4_live.json; harmless no-op if the web dir doesn't exist.
WEB_DATA="/var/www/qount/data"
[ -d "$WEB_DATA" ] && cp -f "$REPO/state/x4/live/latest.json" "$WEB_DATA/x4_live.json" 2>/dev/null \
  && echo "[web] published x4_live.json" >> "$LOG"
