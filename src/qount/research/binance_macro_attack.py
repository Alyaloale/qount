"""Independent aggressive macro candidate inspired by Universal and Dual-Engine.

The frozen research/paper engines are not modified. Eight actually listed linear
contracts share ONE small-account book; GLD/CPER/USO are explicitly proxy signals
for gold/copper/oil contracts, not interchangeable execution assets.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qount.research_data.bars import Bar, NY
from qount.research.engine.runs import cached_features
from qount.strategies.macro_features import build_macro_features
from qount.binance_assets import execution_to_signal_map
from qount.research_data.regime import (
    compute_ema, compute_kaufman_er, compute_profile_state,
)

CONTRACT_SIGNALS = execution_to_signal_map(
    asset_ids={"spy", "qqq", "smh", "iwm", "xle", "xau", "copper", "cl"}
)
MACRO_TEN = ("SPY", "SMH", "IWM", "XLI", "XLB", "GLD", "CPER", "XLU", "TLT", "UUP")


def macro_features(cache: Path, end_exclusive: str, download=False, *, start_date="2025-01-01"):
    """Build unchanged causal signals; an optional start extends offline history.

    The default retains the original cache names and feature values. A different
    start uses different files, so historical research never overwrites them.
    """
    cache.mkdir(parents=True, exist_ok=True)
    tickers = sorted(set(MACRO_TEN) | set(CONTRACT_SIGNALS.values()))
    first_day = dt.date.fromisoformat(start_date)
    if first_day >= dt.date.fromisoformat(end_exclusive):
        raise ValueError("invalid_equity_history_range")
    start = int(dt.datetime.combine(first_day, dt.time(), dt.timezone.utc).timestamp())
    end = int(dt.datetime.fromisoformat(end_exclusive).replace(tzinfo=dt.timezone.utc).timestamp())

    def fetch(ticker):
        path = cache/f"yahoo-{ticker}-{first_day:%Y%m%d}-{end_exclusive}.json"
        if not path.exists():
            if not download:
                raise FileNotFoundError(path)
            url = "https://query1.finance.yahoo.com/v8/finance/chart/"+ticker+"?"+urllib.parse.urlencode(
                {"period1": start, "period2": end, "interval": "1d"})
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read()
            parsed = json.loads(raw)
            if parsed["chart"].get("error") or not parsed["chart"].get("result"):
                raise ValueError(f"equity_source_error:{ticker}")
            path.write_bytes(raw)
        raw = path.read_bytes()
        result = json.loads(raw)["chart"]["result"][0]
        quotes = result["indicators"]["quote"][0]
        adjusted = result["indicators"]["adjclose"][0]["adjclose"]
        bars, dates = [], []
        for i, t in enumerate(result["timestamp"]):
            if any(quotes[k][i] is None for k in ("open", "high", "low", "close")) or adjusted[i] is None:
                raise ValueError(f"missing_equity_bar:{ticker}:{t}")
            date = dt.datetime.fromtimestamp(t, NY).date()
            available = int(dt.datetime.combine(date, dt.time(16), NY).timestamp())
            if available >= end:
                continue
            factor = adjusted[i]/quotes["close"][i]
            b = Bar(available, *(quotes[k][i]*factor for k in ("open", "high", "low", "close")),
                    float(quotes["volume"][i] or 0))
            if not 0 < b.l <= min(b.o, b.c)+1e-7 <= max(b.o, b.c)+1e-7 <= b.h+1e-7:
                raise ValueError(f"equity_ohlc:{ticker}")
            bars.append(b)
            dates.append(date.isoformat())
        if dates != sorted(set(dates)) or len(bars) < 250:
            raise ValueError("insufficient_or_duplicate_equity_history")
        return ticker, bars, dates, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}

    with ThreadPoolExecutor(max_workers=3) as pool:
        fetched = list(pool.map(fetch, tickers))
    sources = [row[3] for row in fetched]
    base = Path(__file__).resolve().parents[1]
    values = cached_features("macro_etf_features", {"mapping": CONTRACT_SIGNALS}, sources,
        [Path(__file__), base/"strategies/macro_features.py", base/"research_data/bars.py",
         base/"research_data/regime.py", base/"research/engine/runs.py"],
        lambda: build_macro_features(fetched, CONTRACT_SIGNALS)[0], cache/"features")
    return values, sources


def directional_book(data, features, mode="long_short", exposure_scale=1.0, short_regime="strict"):
    """Virtual direction keys share ONE replay book, never two capital pools."""
    if mode not in ("long", "short", "long_short") or not math.isfinite(exposure_scale) or exposure_scale <= 0:
        raise ValueError("invalid_directional_book")
    if short_regime not in ("strict", "tactical"):
        raise ValueError("invalid_short_regime")
    suffix = "" if short_regime == "strict" else "_tactical"
    book, signals = {}, {}
    for symbol, rows in features.items():
        if mode != "short":
            book[symbol] = data[symbol]
            signals[symbol] = [{**r, "gross_target": r["gross_target"]*exposure_scale} for r in rows]
        if mode != "long":
            key = symbol+":SHORT"
            book[key] = data[symbol]
            signals[key] = [{**r, "side": -1, "entry_core": False, "hold_core": False,
                             "entry_tactical": r["entry_short"+suffix], "hold_tactical": r["hold_short"+suffix],
                             "rank_tactical": r["rank_short"], "state": r["state_short"],
                             "gross_target": r["gross_short"]*exposure_scale} for r in rows]
    return book, signals
