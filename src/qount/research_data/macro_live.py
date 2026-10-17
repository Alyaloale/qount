"""Bounded public live inputs. Completed hourly cache is reusable by research."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qount.research_data.bars import Bar, NY, session
from qount.strategies.macro_1atr import SIGNAL_MAPPING, scaled_features
from qount.strategies.macro_features import MACRO_TEN, build_macro_features
from qount.strategies.macro_liquidity import capacity_snapshot

HISTORY_START = int(dt.datetime(2026, 4, 7, tzinfo=dt.timezone.utc).timestamp())
# Preserve the selected study's actual input windows when rebuilding a cache.
# A different ATR seed or episode prefix must never silently change live rules.
NATIVE_HISTORY_START = {s: HISTORY_START for s in SIGNAL_MAPPING}
NATIVE_HISTORY_START.update(IWMUSDT=1781136000, XLEUSDT=1781136000, SMHUSDT=1785369600)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False)+"\n")
    os.replace(temporary, path)


def expected_feature_date(now):
    local = dt.datetime.fromtimestamp(now, NY)
    day = local.date()
    # Preserve the original conservative 16:00 availability even on early closes.
    if local.hour < 16:
        day -= dt.timedelta(days=1)
    for _ in range(10):
        stamp = int(dt.datetime.combine(day, dt.time(16), NY).timestamp())
        if session(stamp) is not None:
            return day
        day -= dt.timedelta(days=1)
    raise ValueError("proxy_calendar_unknown")


def parse_proxy(ticker, payload, now):
    result = payload["chart"]["result"][0]
    quotes = result["indicators"]["quote"][0]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    bars, dates = [], []
    for i, stamp in enumerate(result["timestamp"]):
        day = dt.datetime.fromtimestamp(stamp, NY).date()
        available = int(dt.datetime.combine(day, dt.time(16), NY).timestamp())
        if available > now:
            continue
        values = [quotes[k][i] for k in ("open", "high", "low", "close")]+[adjusted[i]]
        if any(v is None or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("proxy_invalid_prices")
        factor = adjusted[i]/quotes["close"][i]
        b = Bar(available, *(quotes[k][i]*factor for k in ("open", "high", "low", "close")),
                float(quotes["volume"][i] or 0))
        if not 0 < b.l <= min(b.o, b.c)+1e-7 <= max(b.o, b.c)+1e-7 <= b.h+1e-7:
            raise ValueError("proxy_invalid_ohlc")
        bars.append(b)
        dates.append(day.isoformat())
    if len(bars) < 250 or dates != sorted(set(dates)):
        raise ValueError("proxy_history_short_or_duplicate")
    return ticker, bars, dates, {"ticker": ticker, "last_date": dates[-1]}


def native_bar(row):
    bar = Bar(int(row[0])//1000, *(float(row[i]) for i in (1, 2, 3, 4)),
              float(row[5]), float(row[7]))
    if (any(not math.isfinite(v) for v in (bar.o, bar.h, bar.l, bar.c, bar.v, bar.q))
            or not 0 < bar.l <= min(bar.o, bar.c) <= max(bar.o, bar.c) <= bar.h or bar.v < 0):
        raise ValueError("native_invalid_bar")
    return bar


class MacroLiveInputs:
    def __init__(self, exchange, cache):
        self.exchange, self.cache = exchange, Path(cache)

    def features(self, now):
        expected = expected_feature_date(now).isoformat()
        tickers = sorted(set(MACRO_TEN) | set(SIGNAL_MAPPING.values()))
        def fetch(ticker):
            path = self.cache/f"yahoo-{ticker}-{expected}.json"
            if path.exists():
                payload = json.loads(path.read_text())
            else:
                params = {"period1": 1735689600, "period2": now+1, "interval": "1d"}
                url = "https://query1.finance.yahoo.com/v8/finance/chart/"+ticker+"?"+urllib.parse.urlencode(params)
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=20) as response:
                    payload = json.load(response)
            parsed = parse_proxy(ticker, payload, now)
            if parsed[2][-1] != expected:
                raise ValueError("proxy_latest_completed_session_missing")
            if not path.exists():
                write_json(path, payload)
                # Keep just the two latest snapshots per ticker on the runtime host.
                for old in sorted(self.cache.glob(f"yahoo-{ticker}-*.json"))[:-2]:
                    old.unlink()
            return parsed
        with ThreadPoolExecutor(max_workers=3) as pool:
            fetched = list(pool.map(fetch, tickers))
        features, _ = build_macro_features(fetched, SIGNAL_MAPPING)
        return scaled_features(features)

    def _hours(self, symbol, now):
        path = self.cache/f"{symbol}-hours.json"
        rows = json.loads(path.read_text()) if path.exists() else []
        cursor = int(rows[-1][0])+3600000 if rows else NATIVE_HISTORY_START[symbol]*1000
        while cursor < (now+3600)*1000:
            page = self.exchange.fapiPublicGetKlines(dict(symbol=symbol, interval="1h", limit=1000,
                       startTime=cursor, endTime=(now+3600)*1000-1))
            if not page:
                break
            if int(page[0][0]) < cursor:
                raise ValueError("native_history_pagination_invalid")
            rows.extend(page)
            next_cursor = int(page[-1][0])+3600000
            if next_cursor <= cursor:
                raise ValueError("native_history_not_advancing")
            cursor = next_cursor
        bars = [native_bar(r) for r in rows if int(r[0])//1000 < now]
        if not bars or bars[0].t != NATIVE_HISTORY_START[symbol]:
            raise ValueError("native_history_seed_mismatch")
        if bars and [b.t for b in bars] != list(range(bars[0].t, now, 3600)):
            raise ValueError("native_hourly_gap")
        write_json(path, [r for r in rows if int(r[0])//1000 < now])
        current = [r for r in rows if int(r[0])//1000 == now]
        if len(current) > 1:
            raise ValueError("native_duplicate_current_open")
        if current:
            # Deliberately discard all current-hour fields except its open.
            price = float(current[0][1])
            if not math.isfinite(price) or price <= 0:
                raise ValueError("native_open_invalid")
            bars.append(Bar(now, price, price, price, price))
        return bars

    def snapshot(self, now, *, entry=False, held=None):
        symbols = tuple(SIGNAL_MAPPING) if entry else (held,) if held else ()
        rules = {r["symbol"]: r for r in self.exchange.fapiPublicGetExchangeInfo({})["symbols"]}
        data, caps = {}, {}
        for s in symbols:
            rule = rules[s]
            if (rule["status"] != "TRADING" or rule["marginAsset"] != "USDT"
                    or rule["contractType"] not in ("PERPETUAL", "TRADIFI_PERPETUAL")):
                raise ValueError("native_contract_unavailable")
            bars = self._hours(s, now)
            funding = self.exchange.fapiPublicGetFundingRate(dict(symbol=s, startTime=(now-96*3600)*1000,
                                                                 endTime=now*1000-1, limit=1000))
            times = sorted(int(r["fundingTime"]) for r in funding if r.get("rateType", "Regular") == "Regular")
            if (not times or times[-1] < (now-8*3600)*1000
                    or any(b-a > 8*3600000+10000 for a, b in zip(times, times[1:]))):
                raise ValueError("native_funding_history_stale_or_gap")
            data[s] = {"trade": bars, "funding": funding, "rule": rule}
            if entry:
                minutes = self.exchange.fapiPublicGetKlines(dict(symbol=s, interval="1m", limit=20,
                            startTime=(now-960)*1000, endTime=now*1000-1))
                cap = capacity_snapshot([native_bar(r) for r in minutes], now)
                if cap is not None:
                    caps[s, now] = cap
        return data, caps
