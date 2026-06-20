# read-only: publish C×D dashboard json from live trend latest + live carry position. No trading.
import json, dataclasses, datetime as dt, ccxt
from pathlib import Path
from qount.settings import Settings
from qount.exchange_utils import build_exchange
REPO=Path("/root/qount"); s=Settings.from_env()
trend=json.load(open(REPO/"state/x4/live/latest.json"))
sx=build_exchange(dataclasses.replace(s,market_type="spot"),private=True); sx.load_markets()
cm=ccxt.binance({"enableRateLimit":True,"options":{"defaultType":"delivery","adjustForTimeDifference":True},
    "apiKey":s.binance_api_key,"secret":s.binance_api_secret}); cm.load_markets()
px_eth=float(sx.fetch_ticker("ETH/USDT")["last"])
px_btc=float(sx.fetch_ticker("BTC/USDT")["last"])
_sb=sx.fetch_balance()
seth=float((_sb.get("total") or {}).get("ETH",0) or 0)
sbtc=float((_sb.get("total") or {}).get("BTC",0) or 0)
# idle USDT sitting in the SPOT wallet (carry's funding venue) — real account capital that lives in
# neither the trend UMFUTURE wallet nor the carry ETH legs, so it must be added to equity explicitly or
# the curve/总盈亏 sag by its amount whenever cash moves wallet->spot but isn't deployed into ETH.
sidle=float((_sb.get("free") or {}).get("USDT",0) or 0)
# Simple Earn (flexible savings) holdings live OUTSIDE spot.total: Binance reports them as separate LD*
# tokens (token units at an exchange rate, not the underlying), so reading only spot total.ETH / free.USDT
# silently omits any ETH/USDT subscribed into Earn for yield. That omission = the 2026-06-20 -$66 equity
# "cliff" (ETH moved wallet->spot->Earn vanished from carry long_usd). Pull the TRUE underlying amounts
# from the Simple Earn endpoint and fold each into its real bucket (ETH/BTC -> long, USDT -> idle).
try:
    for _p in (sx.sapiGetSimpleEarnFlexiblePosition().get("rows") or []):
        _a=_p.get("asset"); _amt=float(_p.get("totalAmount") or 0)
        if _a=="ETH": seth+=_amt
        elif _a=="BTC": sbtc+=_amt
        elif _a in ("USDT","USDC","FDUSD"): sidle+=_amt
except Exception:
    pass
ceth=float((cm.fetch_balance().get("total") or {}).get("ETH",0) or 0)
cbtc=float((cm.fetch_balance().get("total") or {}).get("BTC",0) or 0)
CONTRACT_USD={"BTCUSD": 100.0, "ETHUSD": 10.0}
short_usd=0.0; short_upnl=0.0; active=[]
for r in cm.dapiPrivateGetPositionRisk():
    amt=float(r.get("positionAmt") or 0)
    sym=r.get("symbol") or ""
    if "_" in sym and amt!=0:
        base=sym.split("USD_")[0]+"USD" if "USD_" in sym else ""
        mult=CONTRACT_USD.get(base, 10.0)
        short_usd += abs(amt)*mult
        short_upnl += float(r.get("unrealisedProfit") or r.get("unrealizedProfit") or 0)
        active.append(sym)
long_usd=(seth+ceth)*px_eth + (sbtc+cbtc)*px_btc
carry_equity=round(long_usd+short_upnl,2)
carry_cap=round(long_usd,2)
net_delta=round(long_usd-short_usd,2)
tcap=trend.get("capital",0)
cxd={
  "trend":{"armed":trend.get("armed"),"capital":tcap,"max_leverage":trend.get("max_leverage"),
           "gate_open":trend.get("gate_open"),"short_gate":trend.get("short_gate"),
           "shorting":trend.get("shorting"),"ts":trend.get("ts")},
  "carry":{"armed":bool(active),"capital":carry_cap,"equity":carry_equity,"active_dated":active,
           "net_delta":net_delta,"ts":dt.datetime.now(dt.UTC).isoformat()},
  "weights":{"trend":round(tcap/(tcap+carry_cap),3) if (tcap+carry_cap) else 0.6,
             "carry":round(carry_cap/(tcap+carry_cap),3) if (tcap+carry_cap) else 0.4},
  "idle_usdt":round(sidle,2),                       # spot dry powder (counted in equity, not a leg)
  "total_capital":round(tcap+carry_cap+sidle,2),
}
out=REPO/"state/cxd/live"; out.mkdir(parents=True,exist_ok=True)
(out/"latest.json").write_text(json.dumps(cxd,indent=2,default=float))
# NOTE: this writes ONLY the reconciled carry truth to state/. It does NOT write the web file —
# cxd_live_cron.sh's bundle is the SINGLE writer of /var/www/qount/data/cxd_live.json, and it reads
# this state file for the carry leg. (Before 2026-06-19 both wrote the web file with incompatible
# schemas -> the dashboard flickered between $62/+Δ2 and $148/−Δ23 every few minutes.)
print(json.dumps({"carry":cxd["carry"],"total":cxd["total_capital"],"weights":cxd["weights"]},default=float))