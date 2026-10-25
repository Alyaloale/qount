"""Public daily inputs for order-free paper runners; cache actual fetch times."""
from __future__ import annotations

import datetime as dt
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from qount.contracts import canonical_hash
from qount.research_data.macro_live import write_json

NY = ZoneInfo("America/New_York")
SH = ZoneInfo("Asia/Shanghai")


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Qount-Paper"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=12) as response:
        return json.load(response)


def yahoo_rows(symbol, observed, cache_root, *, start=None, interval="1d"):
    """Return only bars available by the actual observation; never synthesize gaps."""
    cache_root = Path(cache_root)
    from qount.research_data.macro_live import expected_feature_date
    expected=expected_feature_date(int(observed.timestamp())-900).isoformat()
    path = cache_root / (symbol + "-" + interval + ".json")
    if path.exists():
        cached = json.loads(path.read_text())
        age = (observed-dt.datetime.fromisoformat(cached["fetched_at"])).total_seconds()
        if (interval!="1d" and 0 <= age < 3600) or (interval=="1d" and age>=0 and cached["rows"][-1]["date"]==expected):
            return cached["rows"], cached["source_hash"]
    start = start or observed-dt.timedelta(days=800)
    query = urllib.parse.urlencode(dict(period1=int(start.timestamp()), period2=int(observed.timestamp()),
                                       interval=interval, events="div,splits"))
    last = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            payload = get_json(f"https://{host}/v8/finance/chart/{symbol}?{query}")
            node = payload["chart"]["result"][0]
            if interval=="1d":
                q=node["indicators"]["quote"][0]
                a=node["indicators"].get("adjclose",[{}])[0].get("adjclose",q["close"])
                # Some Yahoo nodes publish the completed last bar with null
                # close/adjclose while their regular-market closing quote is
                # already timestamped exactly at the session close. Accept that
                # explicit quote only, never an after-hours price or stale mark.
                for i,t in enumerate(node.get("timestamp",[])):
                    day=dt.datetime.fromtimestamp(t,NY).date()
                    close_at=dt.datetime.combine(day,dt.time(16),NY)
                    meta=node.get("meta",{});price=meta.get("regularMarketPrice")
                    quote_at=meta.get("regularMarketTime",0)
                    events=[e for group in node.get("events",{}).values() for e in group.values()]
                    action_today=any(dt.datetime.fromtimestamp(e.get("date",0),NY).date()==day for e in events)
                    if (day.isoformat()==expected and i>0 and not action_today and price and
                        close_at+dt.timedelta(minutes=15)<=observed and
                        abs(quote_at-int(close_at.timestamp()))<=1 and
                        q["close"][i-1] and a[i-1] and
                        all(q[k][i] is not None for k in ("open","high","low"))):
                        if q["close"][i] is None:
                            q["close"][i]=float(price)
                            node.setdefault("qount_close_basis",{})[str(i)]="timestamped_regular_market_close"
                        if a[i] is None:
                            a[i]=q["close"][i]*(a[i-1]/q["close"][i-1])
                            node.setdefault("qount_adjustment_basis",{})[str(i)]="unchanged_previous_factor_no_action"
                usable=[i for i,t in enumerate(node.get("timestamp",[]))
                        if dt.datetime.fromtimestamp(t,NY).date().isoformat()==expected
                        and all(q[k][i] is not None for k in ("open","high","low","close")) and a[i] is not None]
                if not usable:raise ValueError("expected_daily_bar_missing")
            quote = node["indicators"]["quote"][0]
            adjusted = node["indicators"].get("adjclose", [{}])[0].get("adjclose", quote["close"])
            rows = []
            for i, stamp in enumerate(node.get("timestamp", [])):
                local = dt.datetime.fromtimestamp(stamp, NY)
                available = (dt.datetime.combine(local.date(), dt.time(16, 15), NY) if interval == "1d"
                             else dt.datetime.fromtimestamp(stamp+60, dt.timezone.utc))
                if available > observed:
                    continue
                values = [quote[k][i] for k in ("open", "high", "low", "close")]+[adjusted[i]]
                if any(v is None or not math.isfinite(float(v)) or float(v) <= 0 for v in values):
                    continue
                o,h,l,c,a = map(float, values)
                # Metadata quotes use decimal cents; OHLC arrays use float32. Normalize
                # only float encoding differences, not substantive invalid price ranges.
                rounding=max(o,c,h,l)*2e-7
                if l-rounding<=min(o,c) and max(o,c)<=h+rounding:
                    h=max(h,o,c);l=min(l,o,c)
                if not 0 < l <= min(o,c) <= max(o,c) <= h:
                    raise ValueError(f"invalid_yahoo_ohlc:{symbol}")
                rows.append(dict(date=local.date().isoformat(), timestamp=stamp, open=o, high=h, low=l,
                                 close=c, adjClose=a, volume=float(quote["volume"][i] or 0),
                                 close_basis=node.get("qount_close_basis",{}).get(str(i),"daily_close"),
                                 adjustment_basis=node.get("qount_adjustment_basis",{}).get(str(i),"provider_adjclose")))
            if not rows or (interval=="1d" and rows[-1]["date"]!=expected):
                raise ValueError(f"stale_yahoo_daily:{symbol}")
            break
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            last = exc
    else:
        raise ValueError(f"yahoo_unavailable:{symbol}:{type(last).__name__}") from None
    digest = canonical_hash(payload)
    write_json(path, dict(source="yahoo_public", fetched_at=observed.isoformat(), rows=rows,
                          source_hash=digest, events=node.get("events", {})))
    return rows, digest


def yahoo_dual_getter(cache_root, observed, binance_getter):
    """Adapt public Yahoo OHLC to the existing collector's equity row shape.

    No Tiingo credential is sent, read or required. Binance requests retain their
    original public implementation. The caller labels hashes yahoo_public.
    """
    def get(url, headers, timeout):
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname != "api.tiingo.com":
            return binance_getter(url, headers, timeout)
        parts = parsed.path.split("/")
        symbol = parts[3] if parts[1] == "tiingo" else parts[2]
        intraday = parts[1] == "iex"
        start = dt.datetime.combine(observed.astimezone(NY).date(), dt.time(9,30), NY) if intraday else None
        rows, digest = yahoo_rows(symbol, observed, cache_root, start=start,
                                  interval="1m" if intraday else "1d")
        if intraday:
            rows = [dict(date=dt.datetime.fromtimestamp(r["timestamp"], dt.timezone.utc).isoformat(),
                         open=r["open"], close=r["close"]) for r in rows]
        return rows, digest
    return get


def tencent_etf_rows(observed, cache_root):
    path = Path(cache_root)/"513100.json"
    cutoff = observed.astimezone(SH)
    cutoff_day = cutoff.date() if cutoff.hour >= 17 else cutoff.date()-dt.timedelta(days=1)
    if path.exists():
        cached = json.loads(path.read_text())
        age = (observed-dt.datetime.fromisoformat(cached["fetched_at"])).total_seconds()
        if 0 <= age < 3600 and cached.get("request_end") == cutoff_day.isoformat():
            return cached["rows"], cached["source_hash"]
    last = None
    # Keep raw and adjusted responses on the same node. A bad response must
    # neither poison the cache nor prevent trying the other public endpoint.
    for host in ("web.ifzq.gtimg.cn", "proxy.finance.qq.com/ifzqgtimg"):
        try:
            output, hashes = {}, []
            for adjustment in ("qfq", ""):
                # An open-ended query may append a two-decimal quote to qfqday
                # while raw day retains three decimals. Ask for settled history
                # explicitly; do not mistake that quote for an adjustment factor.
                url = f"https://{host}/appstock/app/fqkline/get?param=sh513100,day,,{cutoff_day.isoformat()},500,{adjustment}"
                payload = get_json(url)
                node = payload["data"]["sh513100"]
                rows = node.get("qfqday" if adjustment else "day")
                if not rows:
                    raise ValueError("etf_source_adjustment_missing")
                output[adjustment] = {r[0]:r for r in rows if r[0] <= cutoff_day.isoformat()}
                hashes.append(canonical_hash(payload))
            rows=[]
            for day in sorted(set(output[""]) & set(output["qfq"])):
                r,a = output[""][day],output["qfq"][day]
                o,c,h,l = map(float,r[1:5]); adj=float(a[2])
                if not 0 < l <= min(o,c) <= max(o,c) <= h or adj <= 0:
                    raise ValueError("etf_source_invalid_ohlc")
                rows.append(dict(date=day,open=o,close=c,high=h,low=l,adjClose=adj,volume=float(r[5])))
            if len(rows)<200 or (cutoff_day-dt.date.fromisoformat(rows[-1]["date"])).days>4:
                raise ValueError("etf_source_stale_or_short")
            break
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            last = exc
    else:
        raise ValueError(f"tencent_etf_unavailable:{type(last).__name__}") from None
    digest=canonical_hash(hashes)
    write_json(path,dict(source="tencent_public_raw_and_qfq",fetched_at=observed.isoformat(),
                         request_end=cutoff_day.isoformat(),rows=rows,source_hash=digest))
    return rows,digest
