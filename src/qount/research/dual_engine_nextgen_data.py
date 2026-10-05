"""Public issued-supply and volatility-futures inputs; no account interfaces."""
from __future__ import annotations
import concurrent.futures
import datetime as dt
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo
from qount.research import dual_engine_optimization as old
from qount.research.dual_engine_execution_study import verify_manifest, load_cache
from qount.research.dual_engine_expansion_data import fetch


def acquire_supply(out, pit_cache):
    from qount.research.dual_engine_expansion import require_storage
    require_storage(out)
    if (out / "manifest.json").exists():
        raise ValueError("immutable_supply_snapshot_exists")
    out.mkdir(parents=True, exist_ok=True)
    (out / "pages").mkdir(exist_ok=True)
    raw, _ = load_cache(pit_cache)
    body = fetch("https://community-api.coinmetrics.io/v4/catalog-v2/asset-metrics?page_size=10000")
    (out / "catalog.json").write_bytes(body)
    catalog = json.loads(body)
    if catalog.get("next_page_url"):
        raise ValueError("incomplete_metric_catalog")
    available = {}
    for row in catalog["data"]:
        asset = row["asset"]
        # Exact native/token identity only. Chain suffixes, wrappers and migrations
        # require an explicit identity decision and are excluded from this study.
        if not asset.isalnum() or asset.upper() + "USDT" not in raw:
            continue
        fields = {m["metric"] for m in row["metrics"] if any(
            f["frequency"] == "1d" and f.get("community") is True for f in m["frequencies"])}
        if "SplyCur" in fields:
            available[asset] = [m for m in ("SplyCur", "FeeTotNtv") if m in fields]

    def one(item):
        asset, metrics = item
        url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=" + asset
               + "&metrics=" + ",".join(metrics)
               + "&start_time=2020-01-01&end_time=2026-08-31&frequency=1d&page_size=10000")
        rows, page = {}, 0
        while url:
            if not url.startswith("https://community-api.coinmetrics.io/v4/") or page >= 10:
                raise ValueError("unexpected_supply_pagination")
            path = out / "pages" / f"{asset}-{page}.json"
            content = path.read_bytes() if path.exists() else fetch(url)
            path.write_bytes(content)
            value = json.loads(content)
            for r in value["data"]:
                day = r["time"][:10]
                if r["asset"] != asset or day in rows or not "2020-01-01" <= day <= "2026-08-31":
                    raise ValueError("supply_row_identity_or_date")
                rows[day] = {m: float(r[m]) if r.get(m) is not None else None for m in metrics}
            url, page = value.get("next_page_url"), page + 1
        print(json.dumps({"supply_asset": asset, "rows": len(rows), "metrics": metrics}), flush=True)
        return asset.upper() + "USDT", rows
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        supply = dict(pool.map(one, sorted(available.items())))
    old.write_json(out / "supply.json", supply)
    old.write_json(out / "coverage.json", {"available": available, "symbols": len(supply),
        "interpretation": "SplyCur is ledger issued supply, not circulating/free float or vesting unlocks; fees do not equal holder cash flow"})
    files = {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}
    manifest = {"files": files, "research_only": True, "orders_authorized": False,
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "historical_vintage": "latest_retrieval_not_point_in_time_vintages"}
    old.write_json(out / "manifest.json", manifest)
    return manifest


def supply_features(rows, day, *, lag=7):
    end = dt.date.fromisoformat(day) - dt.timedelta(days=lag)
    values = []
    for offset in range(59, -1, -1):
        r = rows.get((end - dt.timedelta(days=offset)).isoformat())
        v = r.get("SplyCur") if r else None
        if v is None or not math.isfinite(v) or v <= 0:
            return None
        values.append(r)
    growth = math.log(values[-1]["SplyCur"] / values[-31]["SplyCur"])
    density = None
    fees = [r.get("FeeTotNtv") for r in values]
    if all(v is not None and math.isfinite(v) and v > 0 for v in fees):
        per_unit = [v / r["SplyCur"] for v, r in zip(fees, values, strict=True)]
        density = math.log(sum(per_unit[30:]) / sum(per_unit[:30]))
    return {"issued_growth30": growth, "fee_density_growth": density, "feature_end": end.isoformat()}


def load_tail(panel, root):
    verify_manifest(root)
    result = json.loads((root / "VIXY.source.json").read_text())["chart"]["result"][0]
    if result["meta"]["symbol"] != "VIXY":
        raise ValueError("tail_symbol_mismatch")
    quote = result["indicators"]["quote"][0]
    adj = result["indicators"]["adjclose"][0]["adjclose"]
    rows = {}
    for i, timestamp in enumerate(result["timestamp"]):
        day = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if panel.dates[0] <= day <= panel.dates[-1]:
            vals = (quote["close"][i], adj[i], quote["open"][i])
            if day in rows or any(v is None or not math.isfinite(v) or v <= 0 for v in vals):
                raise ValueError("invalid_tail_row")
            rows[day] = (vals[0], vals[1], vals[2] * vals[1] / vals[0])
    if set(rows) != set(panel.dates):
        raise ValueError("tail_calendar_gap")
    maps = [dict(panel.closes), dict(panel.total_closes), dict(panel.total_opens)]
    for j, mapping in enumerate(maps):
        mapping["VIXY"] = tuple(rows[d][j] for d in panel.dates)
    return old.EquityPanel(panel.dates, *maps)
