#!/bin/bash
# C×D combo live orchestrator (线 C×D):60% trend (USDⓈ-M perp, x4_live.py) + 40% carry
# (spot + COIN-M dated cash-and-carry, rv_live.py), ONE cron, one total-capital split.
#
#   QOUNT_CXD_CAPITAL=2000 bash cxd_live_cron.sh dry    # split 1200/800, print, no orders
#   QOUNT_CXD_CAPITAL=2000 bash cxd_live_cron.sh live   # real orders (each leg still needs ITS arm
#                                                        # switch + key: QOUNT_X4_LIVE_ENABLE /
#                                                        # QOUNT_RV_LIVE_ENABLE in the env file)
#   QOUNT_CXD_CAPITAL=auto bash cxd_live_cron.sh live   # auto-detect total from UMFUTURE wallet
#
# NOTE: this REPLACES the standalone com.qount.x4-live cron for the trend leg -- run only ONE of them
# (two configs trading the same USDⓈ-M account would fight). Keys/arm switches live OUTSIDE the repo
# in ~/.config/qount/x4_live.env (chmod 600). Dashboard publication is handled separately.
set -u
REPO="${QOUNT_REPO:-/root/qount}"
PY="$REPO/.venv/bin/python"
LOG="$HOME/cxd_live.log"
ENV_FILE="$HOME/.config/qount/x4_live.env"
MODE="${1:-dry}"

# shellcheck disable=SC1091
source "$REPO/scripts/desktop/cron_guard.sh"
qount_cron_guard "$0" "cxd-live" "${QOUNT_CXD_RUN_TIMEOUT_SECONDS:-110}" "$LOG" "$@"

rotate_log_if_needed() {
  local log_file="$1"
  local max_bytes="${QOUNT_LOG_MAX_BYTES:-5242880}"
  [ -f "$log_file" ] || return 0
  case "$max_bytes" in
    ''|*[!0-9]*) max_bytes=5242880 ;;
  esac
  local size
  size=$(wc -c < "$log_file" 2>/dev/null || echo 0)
  [ "$size" -lt "$max_bytes" ] && return 0
  local ts archive_dir base
  ts=$(date -u '+%Y%m%dT%H%M%SZ')
  archive_dir="$REPO/state/logs/archive/$ts"
  base=$(basename "$log_file")
  mkdir -p "$archive_dir"
  cp -p "$log_file" "$archive_dir/$base"
  gzip -9 "$archive_dir/$base"
  : > "$log_file"
  chmod 0644 "$log_file"
}

rotate_log_if_needed "$LOG"
echo "=== $(date '+%F %T %Z') C×D mode=$MODE ===" >> "$LOG"
cd "$REPO" || { echo "[ALERT] cannot cd $REPO" >> "$LOG"; exit 1; }
# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

# --- total capital display: fixed or last known X4 wallet snapshot ---
# x4_live.py already reads the live UMFUTURE balance for order sizing. Do not repeat load_markets +
# fetch_balance here: that duplicate private request was one of the incident's hang surfaces. For the
# dashboard bundle, use the last successful local snapshot before the run and refresh it after the leg.
read_x4_capital() {
  "$PY" - "$REPO/state/x4/live/latest.json" <<'PYEOF' 2>/dev/null
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    value = float(data.get("capital") or data.get("trend_wallet") or 0.0)
    print(f"{value:.2f}" if value > 0 else "")
except Exception:
    print("")
PYEOF
}

CXD_REQUESTED="${QOUNT_CXD_CAPITAL:-auto}"
CXD_TOTAL="$CXD_REQUESTED"
if [ "$CXD_REQUESTED" = "auto" ] || [ -z "$CXD_REQUESTED" ]; then
  CXD_TOTAL=$(read_x4_capital)
  if [ -n "$CXD_TOTAL" ]; then
    echo "  [auto] last successful X4 wallet snapshot: \$${CXD_TOTAL}" >> "$LOG"
  else
    CXD_TOTAL="${QOUNT_CXD_CAPITAL_FALLBACK:-500}"
    echo "  [auto] no X4 wallet snapshot, dashboard fallback: \$${CXD_TOTAL}" >> "$LOG"
  fi
fi

# Capital split: trend uses auto (reads UMFUTURE wallet, sizes against full balance so all 7 coins
# are tradeable at ~$410). Carry gets ~40% notional via autofund — not a rigid 60/40 of the sizing
# capital, because at $246 (60%) the trend loses BTC/ETH/LINK min-order. Instead, the trend sizes
# against the full wallet, and carry autofund pulls idle USDT with a reduced buffer ($100 not $200),
# leaving enough free margin for trend while funding the carry wallets.
export QOUNT_X4_CAPITAL="${QOUNT_X4_CAPITAL:-auto}"
# Carry capital is PINNED to a fixed $ (not 40% of the wallet). At this account size carry can only run
# ETH-only (BTC unfundable) and whole-contract COIN-M margin can't track a moving target -> a %-of-wallet
# target chases the wallet up/down and over-pushes the ETH short past its margin granularity (-2019) +
# breaks delta-neutral. A fixed pin (~$133 -> N=$100 -> 10 whole ETHUSD contracts, delta-neutral) keeps
# carry stable and lets idle cash be swept to the trend wallet without re-triggering carry growth.
# Override with QOUNT_CXD_CARRY_CAPITAL (e.g. raise it after a deposit when BTC becomes fundable). 2026-06-19.
RV_CAP="${QOUNT_CXD_CARRY_CAPITAL:-133}"
export QOUNT_RV_CAPITAL="$RV_CAP"
# reduced buffer: trend at 2x uses ~$160 margin of $410 wallet → free ~$250. With $100 buffer,
# carry can pull ~$150 (enough for ETH-only carry at ~$82/pair). Default $200 is too conservative.
export QOUNT_RV_UM_BUFFER_USDT="${QOUNT_RV_UM_BUFFER_USDT:-100}"
echo "  split: total=\$$CXD_TOTAL | trend=auto (full wallet) | carry=\$$RV_CAP (pinned) | um_buffer=\$$QOUNT_RV_UM_BUFFER_USDT" >> "$LOG"

# CARRY PAUSED (2026-06-29, owner 决策「暂停 carry 集中趋势腿」). 复盘结论:在 ~$500 账户 / ETH-only /
# COIN-M 整张($10/张)颗粒度下,carry 是噪声级收益(EV≈0)+ 运营复杂度(taker 中和 / quarterly roll /
# 双场所非原子),且 delta 在大波动期易失控(见 6/17-25 流水)。趋势腿才是会计干净的真盈利引擎。
# 单一总开关 QOUNT_CXD_CARRY_ENABLE(默认 0=暂停);注资到 ~$5k 或改用 USDⓈ-M linear 季度合约重建后,
# 设 =1 即重新武装。暂停 = 不再开新 carry 仓 / 不 autofund / 不 taker 中和;既有持仓需另行 unwind 撤回。
CARRY_ENABLE="${QOUNT_CXD_CARRY_ENABLE:-0}"
export QOUNT_RV_LIVE_ENABLE="${QOUNT_RV_LIVE_ENABLE:-$CARRY_ENABLE}"
export QOUNT_RV_AUTOFUND="${QOUNT_RV_AUTOFUND:-$CARRY_ENABLE}"

notify() {  # $1=title $2=body — no-op unless Server酱 key set
  [ -n "${QOUNT_SERVERCHAN_KEY:-}" ] || return 0
  curl -s --max-time 12 "https://sctapi.ftqq.com/${QOUNT_SERVERCHAN_KEY}.send" \
    --data-urlencode "title=$1" --data-urlencode "desp=$2" -o /dev/null 2>/dev/null
}

run_leg() {  # $1=script $2=success marker
  local out rc
  out=$("$PY" "scripts/desktop/$1" "$MODE" 2>&1); rc=$?
  echo "$out" >> "$LOG"
  if [ $rc -ne 0 ] || ! printf '%s' "$out" | grep -qF "$2"; then
    local last; last=$(printf '%s' "$out" | tail -1)
    echo "[ALERT] C×D '$1' FAILED rc=$rc :: $last" >> "$LOG"
    notify "C×D实盘告警·$1 失败" "$(date '+%F %T') rc=$rc%0A$last"
    return 1
  fi
  return 0
}

RUN_OK=1
if ! run_leg x4_live.py "logged ->"; then
  RUN_OK=0
fi
if [ "$CXD_REQUESTED" = "auto" ] || [ -z "$CXD_REQUESTED" ]; then
  FRESH_TOTAL=$(read_x4_capital)
  if [ -n "$FRESH_TOTAL" ]; then
    CXD_TOTAL="$FRESH_TOTAL"
    echo "  [auto] refreshed X4 wallet snapshot: \$${CXD_TOTAL}" >> "$LOG"
  fi
fi
# carry leg: only reconcile when armed. PAUSED by default (2026-06-29) → no new carry orders / no autofund.
# cxd_publish.py still reports any RESIDUAL carry positions until they are unwound, so the dashboard stays
# honest during the wind-down. Re-arm with QOUNT_CXD_CARRY_ENABLE=1.
if [ "$CARRY_ENABLE" = "1" ]; then
  if ! run_leg rv_live.py "logged ->"; then
    RUN_OK=0
  fi
else
  echo "  carry leg PAUSED (QOUNT_CXD_CARRY_ENABLE=0) — trend-only" >> "$LOG"
fi

# carry delta-neutral guard: rv_live.py writes delta_breach=true when |net_delta| exceeds its threshold
# (default 10% of deployed long). Notify ONCE per breach episode (a flag file de-dups the every-2-min cron;
# cleared when the book comes back to neutral -> re-arms). Only live mode produces a trustworthy unified Δ.
# Skipped while carry is paused (nothing to guard once unwound; avoids stale rv-state false alarms).
if [ "$MODE" = "live" ] && [ "$CARRY_ENABLE" = "1" ]; then
  DELTA_FLAG="$HOME/.cache/qount/rv_delta_alerted"
  mkdir -p "$(dirname "$DELTA_FLAG")"
  RV_STATE="$REPO/state/rv/live/latest.json"
  if [ -f "$RV_STATE" ]; then
    BREACH=$("$PY" -c "import json;d=json.load(open('$RV_STATE'));print('1' if (d.get('delta_breach') and d.get('delta_unified')) else '0')" 2>/dev/null || echo 0)
    if [ "$BREACH" = "1" ]; then
      if [ ! -f "$DELTA_FLAG" ]; then
        ND=$("$PY" -c "import json;d=json.load(open('$RV_STATE'));print(d.get('net_delta'),round(d.get('delta_long_usd') or 0,0))" 2>/dev/null)
        echo "[ALERT] carry Δ breach: net_delta/deployed=$ND -> off delta-neutral" >> "$LOG"
        notify "C×D carry Δ 漂移告警" "$(date '+%F %T') carry net_delta=${ND%% *} USD,偏离 delta 中性(空腿可能差合约 / -2019)。deployed long=${ND##* }"
        touch "$DELTA_FLAG"
      fi
    else
      rm -f "$DELTA_FLAG"   # back to neutral -> re-arm for the next episode
    fi
  fi
fi

[ "$RUN_OK" -eq 1 ] || exit 1
