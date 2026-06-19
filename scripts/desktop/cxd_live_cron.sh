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
# in ~/.config/qount/x4_live.env (chmod 600). Publishes state/{x4,rv}/live -> web cxd_live.json.
set -u
REPO="${QOUNT_REPO:-/root/qount}"
PY="$REPO/.venv/bin/python"
LOG="$HOME/cxd_live.log"
WEB_DATA="/var/www/qount/data"
ENV_FILE="$HOME/.config/qount/x4_live.env"
MODE="${1:-dry}"
echo "=== $(date '+%F %T %Z') C×D mode=$MODE ===" >> "$LOG"
cd "$REPO" || { echo "[ALERT] cannot cd $REPO" >> "$LOG"; exit 1; }
# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

# --- total capital: fixed or auto-detect from UMFUTURE wallet ---
# QOUNT_CXD_CAPITAL=auto → read the live UMFUTURE USDT wallet balance (trend leg's home).
# This is the correct dynamic total: the trend wallet IS the capital pool; carry gets autofunded
# from it. Fixed QOUNT_CXD_CAPITAL=2000 → override for dry/tuning.
CXD_TOTAL="$QOUNT_CXD_CAPITAL"
if [ "$CXD_TOTAL" = "auto" ] || [ -z "$CXD_TOTAL" ]; then
  # read the live wallet balance; fall back to a safe default on failure
  WALLET=$("$PY" -c "
import sys; sys.path.insert(0, 'src')
from qount.settings import Settings; from qount.exchange_utils import build_exchange
import dataclasses
s = Settings.from_env(); ex = build_exchange(dataclasses.replace(s, market_type='future'), private=True)
ex.load_markets(); bal = ex.fetch_balance()
from qount.x4.live import usdt_wallet_balance
w = usdt_wallet_balance(bal)
print(f'{w:.2f}' if w else '0')
" 2>/dev/null) || WALLET=""
  # NOTE: carry sizes off the UMFUTURE WALLET (~40% of it), NOT the combined wallet+carry. The combined
  # base would target a true 40% of the book but at this account size (~$420, ETH-only since BTCUSD's
  # $100 contract is unfundable) it over-pushes the ETH short past what whole-contract COIN-M margin can
  # track -> the last 1-2 contracts fail (-2019) while the spot grows -> the carry DRIFTS off delta-neutral.
  # The wallet base lands carry ~27% of the book but holds Δ≈0 cleanly. A true 40% needs a deposit (so the
  # short has margin granularity headroom / BTC becomes fundable). 2026-06-19.
  if [ -n "$WALLET" ] && [ "$WALLET" != "0" ] && [ "$WALLET" != "0.00" ]; then
    CXD_TOTAL="$WALLET"
    echo "  [auto] UMFUTURE wallet balance: \$${CXD_TOTAL}" >> "$LOG"
  else
    CXD_TOTAL="${QOUNT_CXD_CAPITAL_FALLBACK:-500}"
    echo "  [auto] wallet read failed, using fallback: \$${CXD_TOTAL}" >> "$LOG"
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

# ensure carry arm switches are set (the env file may not have these)
export QOUNT_RV_LIVE_ENABLE="${QOUNT_RV_LIVE_ENABLE:-1}"
export QOUNT_RV_AUTOFUND="${QOUNT_RV_AUTOFUND:-1}"

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
  fi
}

run_leg x4_live.py "[X4-LIVE"     # trend leg (60%)
run_leg rv_live.py "[RV-LIVE"     # carry leg (40%)

# publish combined snapshot for the dashboard (atomic via tmp+mv)
if [ -d "$WEB_DATA" ]; then
  if "$PY" - "$REPO/state" "$CXD_TOTAL" > /tmp/cxd_live.json.tmp <<'PYEOF'
import json, os, sys, datetime
base, total = sys.argv[1], float(sys.argv[2])
def load(p):
    try:
        with open(p) as fh: return json.load(fh)
    except Exception: return None
# SINGLE source of truth for carry: the reconciled state/cxd/live/latest.json (cxd_publish.py), which
# counts the COIN-M margin coin as long -> TRUE capital (actually deployed) + TRUE net Δ (≈0). The raw
# rv/live/latest.json under-counts the long (spot only) -> misleading −Δ; used only as a transient
# fallback if cxd_publish hasn't run yet. trend uses the rich x4 latest for the trend-leg row.
cxd = load(os.path.join(base, "cxd", "live", "latest.json")) or {}
trend = load(os.path.join(base, "x4", "live", "latest.json"))
carry = cxd.get("carry") or load(os.path.join(base, "rv", "live", "latest.json"))
weights = cxd.get("weights") or {"trend": 0.6, "carry": 0.4}   # ACTUAL (deployed) split
total_cap = cxd.get("total_capital") or total
print(json.dumps({
    "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "total_capital": total_cap, "weights": weights,
    "target_weights": {"trend": 0.6, "carry": 0.4},   # design intent, shown alongside actual
    "trend": trend,
    "carry": carry,
}, ensure_ascii=False, default=float))
PYEOF
  then
    mv /tmp/cxd_live.json.tmp "$WEB_DATA/cxd_live.json"
    echo "[web] published cxd_live.json" >> "$LOG"
  else
    echo "[ALERT] bundle cxd_live.json failed" >> "$LOG"
  fi
  # ALSO publish the trend leg's own snapshot -> the 加密实盘 page reads data/x4_live.json directly (hero /
  # holdings / gates / 更新时间). The standalone x4_live_cron that used to publish it is no longer in cron
  # (replaced by THIS orchestrator) -> without this copy x4_live.json froze at its last standalone run and
  # the page showed a stale "更新 N 小时前". Atomic copy of the fresh state snapshot. 2026-06-19.
  if [ -f "$REPO/state/x4/live/latest.json" ]; then
    cp "$REPO/state/x4/live/latest.json" /tmp/x4_live.json.tmp && mv /tmp/x4_live.json.tmp "$WEB_DATA/x4_live.json" \
      && echo "[web] published x4_live.json" >> "$LOG"
  fi
fi
