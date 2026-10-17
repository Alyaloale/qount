"""Fixed SMA120/20-session momentum benchmark on retained ETF signal inputs."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path

from qount.research_data.bars import NY, session
from qount.strategies.macro_funding import feature_at


def trend_rows(daily, gross_cap=20.0):
    """A close is used only from its supplied availability time onward."""
    times = [r["available"] for r in daily]
    if times != sorted(set(times)) or len(daily) < 120:
        raise ValueError("ordered_120_daily_observations_required")
    if not math.isfinite(gross_cap) or gross_cap <= 0:
        raise ValueError("invalid_gross_cap")
    closes = [float(r["close"]) for r in daily]
    if any(not math.isfinite(c) or c <= 0 for c in closes):
        raise ValueError("invalid_daily_close")
    rows = []
    for i in range(119, len(daily)):
        average = statistics.mean(closes[i-119:i+1])
        momentum = closes[i]/closes[i-20]-1
        eligible = closes[i] > average and momentum > 0
        rows.append(dict(available=daily[i]["available"], date=daily[i]["date"],
            close=closes[i], sma120=average, momentum20=momentum,
            entry_core=False, hold_core=False, entry_tactical=eligible,
            hold_tactical=eligible, hold_structural=eligible,
            rank_core=momentum, rank_tactical=momentum, state="SIMPLE_TREND",
            tactical_setup="breakout", gross_target=gross_cap))
    return rows


def simple_features(cache, mapping, end_exclusive, gross_cap=20.0):
    end = dt.datetime.fromisoformat(end_exclusive).replace(tzinfo=dt.timezone.utc).timestamp()
    features, sources = {}, []
    for symbol, ticker in mapping.items():
        path = Path(cache)/f"yahoo-{ticker}-20250101-{end_exclusive}.json"
        raw = path.read_bytes()
        data = json.loads(raw)["chart"]["result"][0]
        closes = data["indicators"]["adjclose"][0]["adjclose"]
        if len(closes) != len(data["timestamp"]):
            raise ValueError("daily_price_time_length_mismatch")
        daily = []
        for t, close in zip(data["timestamp"], closes):
            date = dt.datetime.fromtimestamp(t, NY).date()
            available = int(dt.datetime.combine(date, dt.time(16), NY).timestamp())
            if available < end:
                daily.append(dict(available=available, date=date.isoformat(), close=close))
        features[symbol] = trend_rows(daily, gross_cap)
        sources.append(dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()))
    return features, sources


def candidate_clocks(book, signals):
    """Use the union of native histories; never invent pre-listing opportunities."""
    present = {s: {b.t for b in d["trade"]} for s, d in book.items()}
    clocks = sorted({t for times in present.values() for t in times})
    result = []
    for now in clocks:
        clock = session(now)
        if clock is None or clock[1] != 600:
            continue
        fs = {s: feature_at(rows, now) for s, rows in signals.items()}
        if not all(f is not None and 0 < now-f["available"] <= 4*86400 for f in fs.values()):
            continue
        result.extend((s, now) for s, f in fs.items() if f["entry_tactical"] and now in present[s])
    return result
