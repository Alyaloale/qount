"""Public inverse ETF prices for the sixth discovery round."""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo
from qount.research import dual_engine_optimization as old
from qount.research.dual_engine_execution_study import verify_manifest
from qount.research.dual_engine_expansion_data import fetch

INVERSE = ("SH", "PSQ", "TBF")


def acquire_inverse(out: Path):
    """Small public acquisition; Mac files must be transferred then removed."""
    if out.exists():
        raise ValueError("immutable_inverse_input_exists")
    out.mkdir(parents=True)
    first = int(dt.datetime(2017, 9, 1, tzinfo=dt.timezone.utc).timestamp())
    last = int(dt.datetime(2026, 7, 31, tzinfo=dt.timezone.utc).timestamp())
    urls = {}
    for s in INVERSE:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1={first}"
               f"&period2={last}&interval=1d&events=div%2Csplits")
        body = fetch(url)
        if json.loads(body)["chart"]["result"][0]["meta"]["symbol"] != s:
            raise ValueError("inverse_source_identity_changed")
        (out / f"{s}.source.json").write_bytes(body)
        urls[s] = url
        print(json.dumps({"acquired_inverse": s}), flush=True)
    manifest = {"research_only": True, "orders_authorized": False,
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "source": "Yahoo public chart",
        "urls": urls, "first": "2017-09-01", "last": "2026-07-30",
        "files": {p.name: old.file_hash(p) for p in sorted(out.iterdir()) if p.is_file()}}
    old.write_json(out / "manifest.json", manifest)
    return manifest


def load_inverse(panel: old.EquityPanel, root: Path):
    files = verify_manifest(root)
    if set(files) != {f"{s}.source.json" for s in INVERSE}:
        raise ValueError("inverse_source_inventory_invalid")
    maps = [dict(panel.closes), dict(panel.total_closes), dict(panel.total_opens)]
    for s in INVERSE:
        result = json.loads((root / f"{s}.source.json").read_text())["chart"]["result"][0]
        if result["meta"]["symbol"] != s:
            raise ValueError("inverse_source_identity_changed")
        q, adj = result["indicators"]["quote"][0], result["indicators"]["adjclose"][0]["adjclose"]
        rows = {}
        for i, stamp in enumerate(result["timestamp"]):
            day = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
            if not panel.dates[0] <= day <= panel.dates[-1]:
                continue
            values = (q["close"][i], adj[i], q["open"][i])
            if day in rows or any(v is None or not math.isfinite(v) or v <= 0 for v in values):
                raise ValueError(f"inverse_invalid_row:{s}:{day}")
            rows[day] = (values[0], values[1], values[2] * values[1] / values[0])
        if set(rows) != set(panel.dates):
            raise ValueError(f"inverse_calendar_gap:{s}")
        for i, m in enumerate(maps):
            m[s] = tuple(rows[d][i] for d in panel.dates)
    return old.EquityPanel(panel.dates, *maps)
