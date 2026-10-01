"""C60 v2 survivorship check on a point-in-time Binance spot universe (not a trial).

research_only=true / orders_authorized=false. Public archive only; no credentials used.
Preregistration: docs/c60-pit-universe-survivorship-2026-09.md
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qount.contracts import canonical_hash
from qount.research.c60_cost_study import build_panel, simulate, target_path
from qount.research.c60_pit_universe import (
    EVAL_END, FIRST_DECISION, eligible_symbol, fetch_symbol, list_spot_symbols, run, summarize,
)

DEFAULT_CLOSES = Path("state/research_runs/c60_cost_expectancy_v1/7495a6fbc649fd2d/closes.json")


def _get(url: str) -> bytes:
    url = urllib.parse.quote(url, safe=":/?&=%")  # some listed symbols are non-ASCII
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "qount-research"}),
                                        timeout=60) as response:
                return response.read()
        except OSError:
            if attempt == 7:
                raise
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError("unreachable")


def _write_private(path: Path, text: str) -> None:
    path.write_text(text)
    os.chmod(path, 0o600)


def _cached(cache: Path, symbol: str) -> dict[str, object]:
    path = cache / f"{symbol}.json"
    if path.exists():
        return json.loads(path.read_text())
    data = fetch_symbol(symbol, _get)
    _write_private(path, json.dumps(data, sort_keys=True))
    return data


def _frozen_panel_check(closes: Path) -> dict[str, object]:
    """Trial 150 on the frozen cost-study panel, truncated to the same evaluation end."""

    series = {s: {d: v for d, v in values.items() if d <= EVAL_END} for s, values in json.loads(closes.read_text()).items()}
    panel, audit = build_panel(series)
    result = simulate(panel, target_path(panel, mode="research_monthly"), cost_bps=25.0, start_date=FIRST_DECISION)
    return {"data_hash": audit["data_hash"], "summary": summarize(
        {"dates": list(result.dates), "returns": list(result.returns), "turnover": result.turnover,
         "average_gross": result.average_gross})}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, default=Path("state/research_runs/c60_pit_universe_v1"))
    parser.add_argument("--closes", type=Path, default=DEFAULT_CLOSES)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args(argv)

    cache = args.out_root / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.chmod(args.out_root, 0o700)
    os.chmod(cache, 0o700)
    everything = list_spot_symbols(_get)
    symbols = sorted(s for s in everything if eligible_symbol(s, everything))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fetched = dict(zip(symbols, pool.map(lambda s: _cached(cache, s), symbols)))
    raw = {s: {d: tuple(v) for d, v in data["rows"].items()} for s, data in fetched.items() if data["rows"]}
    manifest = {s: data["files"] for s, data in fetched.items() if data["files"]}
    manifest_hash = canonical_hash(manifest)
    _write_private(args.out_root / f"manifest-{manifest_hash[:16]}.json", json.dumps(manifest, indent=1, sort_keys=True))

    result = run(raw) | {
        "spot_symbols_listed": len(everything), "eligible_usdt_symbols": len(symbols), "symbols_with_data": len(raw),
        "archive_files": sum(len(v) for v in manifest.values()), "manifest_hash": manifest_hash,
        "frozen_panel_trial_150_same_window": _frozen_panel_check(args.closes),
    }
    out = args.out_root / f"{canonical_hash(result)[:16]}.json"
    _write_private(out, json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"out": str(out)} | result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
