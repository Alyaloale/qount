"""Binance public hourly trade/mark/funding inputs, reusable across lines.

Legacy cache paths remain readable; existing inputs are not rewritten.
"""
from __future__ import annotations
import hashlib
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from qount.research_data.bars import Bar
from qount.research_data.archives import archive_rows
SYMBOLS = ("SPYUSDT", "QQQUSDT")
BASE = "https://fapi.binance.com"


def load_cached_history(roots, symbols, start, end, rules_path):
    """Merge explicitly selected existing hourly caches; never download or overwrite.

    Different copies of the same observation must agree. Later listings may have
    shorter contiguous histories; their real start is retained, never padded.
    """
    rules_raw = Path(rules_path).read_bytes()
    rules = {r["symbol"]: r for r in json.loads(rules_raw)["symbols"]}
    sources = {str(rules_path): hashlib.sha256(rules_raw).hexdigest()}
    data, excluded = {}, {}
    for symbol in symbols:
        book = {"rule": rules.get(symbol)}
        for kind in ("trade", "mark", "funding"):
            merged = {}
            for root in roots:
                for path in sorted(Path(root).glob(f"{symbol}-{kind}-*-*.json")):
                    left, right = map(int, path.stem.rsplit("-", 2)[1:])
                    if right <= start or left >= end:
                        continue
                    raw = path.read_bytes()
                    sources[str(path)] = hashlib.sha256(raw).hexdigest()
                    for row in json.loads(raw):
                        timestamp = int(row["fundingTime"]) if kind == "funding" else int(row[0])
                        if not start*1000 <= timestamp < end*1000:
                            continue
                        key = (timestamp, row.get("rateType", "Regular")) if kind == "funding" else timestamp
                        if key in merged and merged[key] != row:
                            raise ValueError(f"conflicting_cached_observation:{symbol}:{kind}:{key}")
                        merged[key] = row
            rows = [merged[key] for key in sorted(merged)]
            book[kind] = rows if kind == "funding" else [Bar(int(r[0])//1000, *(float(r[i]) for i in (1,2,3,4)), float(r[5]), float(r[7])) for r in rows]
        if not book["rule"] or not book["trade"] or not book["mark"] or not book["funding"]:
            excluded[symbol] = "missing_rule_trade_mark_or_funding"
            continue
        trade, mark = book["trade"], book["mark"]
        expected = list(range(trade[0].t, end, 3600))
        if [b.t for b in trade] != expected or [b.t for b in mark] != expected:
            raise ValueError(f"hourly_gap_or_clock_mismatch:{symbol}")
        if any(not 0 < b.l <= min(b.o,b.c) <= max(b.o,b.c) <= b.h for b in trade+mark):
            raise ValueError(f"invalid_cached_ohlc:{symbol}")
        regular = [int(r["fundingTime"]) for r in book["funding"] if r.get("rateType", "Regular") == "Regular"]
        if (not regular or regular[0] > (trade[0].t+8*3600)*1000
                or regular[-1] < (end-8*3600)*1000
                or any(b-a > 8*3600000+10000 for a,b in zip(regular,regular[1:]))):
            raise ValueError(f"funding_gap:{symbol}")
        data[symbol] = book
    return data, [{"path": p, "sha256": h} for p,h in sorted(sources.items())], excluded

def public_get(endpoint, params=None):
    if endpoint not in {"/fapi/v1/klines", "/fapi/v1/markPriceKlines",
                        "/fapi/v1/fundingRate", "/fapi/v1/exchangeInfo",
                        "/fapi/v1/depth", "/fapi/v1/time"}:
        raise ValueError("public_research_endpoint_only")
    url = BASE + endpoint + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(url, timeout=25) as response:
        return json.load(response)


def load_inputs(cache: Path, start: int, end: int, download=False, symbols=SYMBOLS):
    """At most a few MB of hourly inputs; cache is separate from frozen runs."""
    cache.mkdir(parents=True, exist_ok=True)
    records = []

    def cached(name, fetch):
        path = cache / name
        if not path.exists():
            if not download:
                raise FileNotFoundError(path)
            value = fetch()
            path.write_text(json.dumps(value, separators=(",", ":")) + "\n")
        raw = path.read_bytes()
        records.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        return json.loads(raw)

    rules = cached("exchange-info.json", lambda: public_get("/fapi/v1/exchangeInfo"))
    selected = {s["symbol"]: s for s in rules["symbols"] if s["symbol"] in symbols}

    def hourly(symbol, kind):
        endpoint = "/fapi/v1/klines" if kind == "trade" else "/fapi/v1/markPriceKlines"

        def fetch():
            rows, cursor = [], start * 1000
            while cursor < end * 1000:
                page = public_get(endpoint, {"symbol": symbol, "interval": "1h", "limit": 1000,
                                            "startTime": cursor, "endTime": end*1000-1})
                if not isinstance(page, list) or not page:
                    raise ValueError(f"incomplete_public_page:{symbol}:{kind}:{cursor}")
                rows.extend(page)
                next_cursor = int(page[-1][0]) + 3600000
                if next_cursor <= cursor:
                    raise ValueError("pagination_not_advancing")
                cursor = next_cursor
            return rows

        # Reuse existing official monthly trade archives when present. REST fills
        # the remaining interval; all retained data share the same hourly clock.
        def fetch_with_reuse():
            if kind != "trade":
                return fetch()
            reused = {}
            root = Path("state/research_cache/binance_tradifi/v1/cache")
            for p in sorted(root.glob(f"um-{symbol}-1h-*.zip")):
                raw = p.read_bytes()
                records.append({"path": str(p), "sha256": hashlib.sha256(raw).hexdigest()})
                for row in archive_rows(p):
                    t = int(row[0])
                    if start*1000 <= t < end*1000:
                        reused[t] = row
            rows, cursor = [], start*1000
            while cursor < end*1000:
                if cursor in reused:
                    rows.append(reused[cursor])
                    cursor += 3600000
                    continue
                next_known = min((t for t in reused if t > cursor), default=end*1000)
                page = public_get(endpoint, {"symbol": symbol, "interval": "1h", "limit": 1000,
                                            "startTime": cursor, "endTime": min(next_known, end*1000)-1})
                if not isinstance(page, list) or not page:
                    raise ValueError(f"missing_trade_hours:{symbol}:{cursor}")
                rows.extend(page)
                cursor = int(page[-1][0]) + 3600000
            return rows

        rows = cached(f"{symbol}-{kind}-{start}-{end}.json", fetch_with_reuse)
        bars = [Bar(int(r[0])//1000, *(float(r[i]) for i in (1, 2, 3, 4)),
                    float(r[5]), float(r[7])) for r in rows]
        if [b.t for b in bars] != list(range(start, end, 3600)):
            raise ValueError(f"hourly_gap_or_duplicate:{symbol}:{kind}")
        if any(not 0 < b.l <= min(b.o, b.c) <= max(b.o, b.c) <= b.h for b in bars):
            raise ValueError("invalid_ohlc")
        return bars

    def per_symbol(s):
        trade, mark = hourly(s, "trade"), hourly(s, "mark")
        funding = cached(f"{s}-funding-{start}-{end}.json", lambda: public_get(
            "/fapi/v1/fundingRate", {"symbol": s, "startTime": start*1000,
                                    "endTime": end*1000-1, "limit": 1000}))
        if not isinstance(funding, list) or not 0 < len(funding) < 1000:
            raise ValueError("funding_missing_or_pagination_required")
        keys = [(int(r["fundingTime"]), r.get("rateType", "Regular")) for r in funding]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise ValueError("funding_order_or_duplicate")
        regular = [int(r["fundingTime"]) for r in funding if r.get("rateType", "Regular") == "Regular"]
        if regular[0] > (start+8*3600)*1000 or regular[-1] < (end-8*3600)*1000:
            raise ValueError("funding_edge_missing")
        if any(b-a > 8*3600000+10000 for a, b in zip(regular, regular[1:])):
            raise ValueError("funding_gap")
        return s, {"trade": trade, "mark": mark, "funding": funding, "rule": selected[s]}

    with ThreadPoolExecutor(max_workers=2) as pool:
        data = dict(pool.map(per_symbol, symbols))
    return data, sorted(records, key=lambda x: x["path"])
