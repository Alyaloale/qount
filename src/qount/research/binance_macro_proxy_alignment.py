"""Synchronized proxy attribution and one fixed causal mean-reversion gap cap."""
import bisect
import datetime as dt
import math
import statistics

from qount.research.binance_etf_leverage import feature_at
from qount.research.binance_macro_validation import available_atr
from qount.research_data.bars import NY


def etf_closes(payload):
    r = payload["chart"]["result"][0]
    raw = r["indicators"]["quote"][0]["close"]
    adjusted = r["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i, stamp in enumerate(r["timestamp"]):
        day = dt.datetime.fromtimestamp(stamp, NY).date()
        available = int(dt.datetime.combine(day, dt.time(16), NY).timestamp())
        if any(v is None or not math.isfinite(v) or v <= 0 for v in (raw[i], adjusted[i])):
            raise ValueError("invalid_proxy_close")
        rows.append(dict(date=day.isoformat(), available=available,
                         etf_raw=raw[i], etf_adjusted=adjusted[i]))
    if [r["available"] for r in rows] != sorted({r["available"] for r in rows}):
        raise ValueError("unordered_or_duplicate_proxy_closes")
    return rows


def paired_closes(etf, data):
    """Use the native hourly close ending at the ETF's16:00 NY clock.

    Current experiments end before any2026 early-close session. Missing native
    endpoints are omitted explicitly, never filled from the future.
    """
    trade = {b.t+3600: b.c for b in data["trade"]}
    mark = {b.t+3600: b.c for b in data["mark"]}
    return [dict(r, session_index=i, native_trade=trade[r["available"]], native_mark=mark[r["available"]])
            for i,r in enumerate(etf) if r["available"] in trade and r["available"] in mark]


def pair_statistics(rows):
    result = dict(paired_closes=len(rows), first_date=rows[0]["date"] if rows else None,
                  last_date=rows[-1]["date"] if rows else None)
    transitions = [(a,b) for a,b in zip(rows,rows[1:])
                   if "session_index" not in a or b["session_index"] == a["session_index"]+1]
    result["omitted_nonconsecutive_transitions"] = max(0,len(rows)-1)-len(transitions)
    premiums = [abs(r["native_trade"]/r["native_mark"]-1)*10000 for r in rows if "native_mark" in r]
    result["mean_abs_trade_mark_premium_bps"] = statistics.mean(premiums) if premiums else None
    for proxy in ("etf_raw", "etf_adjusted"):
        x = [math.log(b[proxy]/a[proxy]) for a,b in transitions]
        y = [math.log(b["native_trade"]/a["native_trade"]) for a,b in transitions]
        nonzero = [(a,b) for a,b in zip(x,y) if a != 0 and b != 0]
        result[proxy] = dict(return_pairs=len(x),
            correlation=statistics.correlation(x,y) if len(x)>1 and statistics.pstdev(x)>0 and statistics.pstdev(y)>0 else None,
            mean_abs_daily_log_return_difference_bps=statistics.mean(abs(a-b) for a,b in zip(x,y))*10000 if x else None,
            opposite_sign_days=sum(a*b<0 for a,b in nonzero), nonzero_pairs=len(nonzero),
            zero_native_nonzero_proxy_days=sum(b==0 and a!=0 for a,b in zip(x,y)))
    return result


def causal_proxy_snapshot(rows, now):
    i = bisect.bisect_right([r["available"] for r in rows],now)-1
    if i < 0:
        return None
    last = rows[i]
    result = dict(available=last["available"], date=last["date"], native_close=last["native_trade"],
                  etf_adjusted_close=last["etf_adjusted"])
    for n in (1,5,20,63):
        continuous = ("session_index" not in last or (i>=n and
            all(rows[j]["session_index"]==last["session_index"]-i+j for j in range(i-n,i+1))))
        if i >= n and continuous:
            prior = rows[i-n]
            result[f"proxy_return_{n}"] = last["etf_adjusted"]/prior["etf_adjusted"]-1
            result[f"native_return_{n}"] = last["native_trade"]/prior["native_trade"]-1
    return result


from qount.strategies.macro_gates import mean_reversion_gap_confirmations


def mean_reversion_daily_confirmations(features, closes, clocks):
    """Require MR's ETF signal close above its prior actual session close.

    This adds one zero-threshold condition to the existing intraday-green setup.
    Use the exact original signal timestamp and adjusted prices, never a later
    available bar or a calendar-day subtraction across holidays/weekends.
    """
    times = {s:[r["available"] for r in rows] for s,rows in closes.items()}
    result = {}
    for s,now in clocks:
        f = feature_at(features[s],now)
        if f is None or not 0 < now-f["available"] <= 4*86400:
            continue
        context = dict(asof=now, feature_available=f["available"], setup=f["tactical_setup"],
                       eligible=True, reason="mean_reversion_no_daily_reversal")
        if f["tactical_setup"] == "mean_reversion":
            rows = closes.get(s,[])
            i = bisect.bisect_left(times.get(s,[]),f["available"])
            if i < 1 or i >= len(rows) or rows[i]["available"] != f["available"]:
                context.update(eligible=False,reason="mean_reversion_daily_close_unknown")
            else:
                current,prior = rows[i],rows[i-1]
                context.update(signal_close=current["etf_adjusted"], prior_close=prior["etf_adjusted"],
                    prior_available=prior["available"], daily_return=current["etf_adjusted"]/prior["etf_adjusted"]-1,
                    eligible=current["etf_adjusted"]>prior["etf_adjusted"])
        result[s,now] = context
    return result
