"""Public macro/network snapshots for the G20/C60 expansion discovery study."""
from __future__ import annotations

import concurrent.futures
import csv
import datetime as dt
import io
import json
import math
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from qount.research import dual_engine_optimization as old
from qount.research.dual_engine_execution_study import verify_manifest

MACRO = ("GLD", "IEF", "TLT", "TIP", "DBC", "UUP")
# Explicit native-network identity; no ERC20 fee attribution or migrated tickers.
NETWORKS = ("btc", "eth", "bch", "ltc", "etc", "doge", "ada", "bnb", "trx", "xrp",
            "avax", "sol", "atom", "dot", "xlm", "zec")
METRICS = ("AdrActCnt", "FeeTotNtv")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def acquire(out: Path) -> dict:
    from qount.research.dual_engine_expansion import require_storage
    require_storage(out)
    if (out / "manifest.json").exists():
        raise ValueError("immutable_acquisition_exists")
    out.mkdir(parents=True, exist_ok=True)
    pages, audit = out / "pages", {}
    pages.mkdir(exist_ok=True)
    first = int(dt.datetime(2017, 9, 1, tzinfo=dt.timezone.utc).timestamp())
    last = int(dt.datetime(2026, 7, 31, tzinfo=dt.timezone.utc).timestamp())

    def equity(symbol):
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={first}"
               f"&period2={last}&interval=1d&events=div%2Csplits")
        path = out / f"{symbol}.source.json"
        body = path.read_bytes() if path.exists() else fetch(url)
        if json.loads(body)["chart"]["result"][0]["meta"]["symbol"] != symbol:
            raise ValueError("equity_acquisition_identity_mismatch")
        (out / f"{symbol}.source.json").write_bytes(body)
        return symbol, len(json.loads(body)["chart"]["result"][0]["timestamp"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for symbol, bars in pool.map(equity, MACRO):
            print(json.dumps({"macro": symbol, "bars": bars}), flush=True)
    catalog_url = "https://community-api.coinmetrics.io/v4/catalog-v2/asset-metrics?assets=" + ",".join(NETWORKS)
    catalog_raw = fetch(catalog_url)
    (out / "catalog.json").write_bytes(catalog_raw)
    catalog = json.loads(catalog_raw)
    if catalog.get("next_page_url"):
        raise ValueError("filtered_catalog_unexpected_pagination")
    available = {}
    for row in catalog["data"]:
        available[row["asset"]] = {m["metric"] for m in row["metrics"]
            if any(f["frequency"] == "1d" and f.get("community") is True for f in m["frequencies"])}
    network = {}
    for asset in NETWORKS:
        if not set(METRICS).issubset(available.get(asset, set())):
            audit[asset] = {"status": "missing_free_daily_metric", "available": sorted(set(METRICS) & available.get(asset, set()))}
            continue
        url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=" + asset
               + "&metrics=" + ",".join(METRICS)
               + "&start_time=2020-01-01&end_time=2026-08-31&frequency=1d&page_size=10000")
        rows, page = {}, 0
        while url:
            if not url.startswith("https://community-api.coinmetrics.io/v4/") or page >= 10:
                raise ValueError("unexpected_network_pagination")
            body = fetch(url)
            (pages / f"{asset}-{page}.json").write_bytes(body)
            value = json.loads(body)
            for r in value["data"]:
                if r["asset"] != asset:
                    raise ValueError("network_asset_identity_mismatch")
                date = r["time"][:10]
                if date in rows:
                    raise ValueError("duplicate_network_date")
                rows[date] = {k: float(r[k]) if r.get(k) is not None else None for k in METRICS}
            url, page = value.get("next_page_url"), page + 1
        network[asset.upper() + "USDT"] = rows
        audit[asset] = {"status": "acquired", "rows": len(rows), "first": min(rows) if rows else None,
                        "last": max(rows) if rows else None}
        print(json.dumps({"network": asset, **audit[asset]}), flush=True)
    old.write_json(out / "network.json", network)
    old.write_json(out / "coverage.json", audit)
    # No vintage assertion: public historical series acquired now can be revised.
    files = {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}
    manifest = {"files": files, "research_only": True, "orders_authorized": False,
                "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "historical_vintage": "latest_retrieval_not_point_in_time_vintages"}
    old.write_json(out / "manifest.json", manifest)
    return manifest


def load_macro(panel: old.EquityPanel, root: Path) -> old.EquityPanel:
    verify_manifest(root)
    maps = [dict(panel.closes), dict(panel.total_closes), dict(panel.total_opens)]
    for s in MACRO:
        result = json.loads((root / f"{s}.source.json").read_text())["chart"]["result"][0]
        if result["meta"]["symbol"] != s:
            raise ValueError("macro_symbol_mismatch")
        q, adj = result["indicators"]["quote"][0], result["indicators"]["adjclose"][0]["adjclose"]
        rows = {}
        for i, stamp in enumerate(result["timestamp"]):
            d = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
            if panel.dates[0] <= d <= panel.dates[-1]:
                values = (q["close"][i], adj[i], q["open"][i])
                if d in rows or any(v is None or v <= 0 or not math.isfinite(v) for v in values):
                    raise ValueError(f"macro_invalid_row:{s}:{d}")
                rows[d] = (values[0], values[1], values[2] * values[1] / values[0])
        if set(rows) != set(panel.dates):
            raise ValueError(f"macro_calendar_gap:{s}")
        for j, m in enumerate(maps):
            m[s] = tuple(rows[d][j] for d in panel.dates)
    return old.EquityPanel(panel.dates, *maps)


def load_rates(root: Path, dates) -> dict:
    # Optional additional public FRED snapshot is separately hash-bound.
    verify_manifest(root)
    result = {}
    for series in ("DFII10", "T10YIE"):
        with (root / f"{series}.csv").open() as handle:
            rows = {r[0]: float(r[1]) for r in list(csv.reader(handle))[1:]
                    if len(r) == 2 and r[1] not in ("", ".")}
        aligned = []
        for t, day in enumerate(dates):
            # Two equity-session lag, and seven-calendar-day staleness limit.
            cutoff = dates[t - 2] if t >= 2 else ""
            eligible = [d for d in rows if d <= cutoff]
            d = max(eligible) if eligible else None
            aligned.append(rows[d] if d and (dt.date.fromisoformat(day) - dt.date.fromisoformat(d)).days <= 7 else None)
        result[series] = aligned
    return result


def network_growth(rows: dict, day: str, *, lag: int = 7) -> dict | None:
    end = dt.date.fromisoformat(day) - dt.timedelta(days=lag)
    values = {m: [] for m in METRICS}
    for offset in range(59, -1, -1):
        r = rows.get((end - dt.timedelta(days=offset)).isoformat())
        if r is None:
            return None
        for m in METRICS:
            v = r.get(m)
            if v is None or not math.isfinite(v) or v <= 0:
                return None
            values[m].append(v)
    return {m: math.log(sum(v[30:]) / sum(v[:30])) for m, v in values.items()}
