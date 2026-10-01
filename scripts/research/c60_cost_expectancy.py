"""Run the preregistered C60 cost-expectancy study (Trials 149/150).

research_only=true / orders_authorized=false. Public Binance spot klines only; no credentials,
no paper state, no orders. Preregistration: docs/c60-cost-expectancy-preregistration-2026-09.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from qount.contracts import canonical_hash
from qount.dual_engine.contracts import C60_SYMBOLS
from qount.research.c60_cost_study import PREREGISTRATION, build_panel, fetch_daily_closes, run_study


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, default=Path("state/research_runs/c60_cost_expectancy_v1"))
    parser.add_argument("--cache", type=Path, default=None, help="reuse a cached closes JSON instead of fetching")
    args = parser.parse_args(argv)

    observed = dt.datetime.now(dt.timezone.utc)
    if args.cache:
        series = json.loads(args.cache.read_text())
    else:
        observed_ms = int(observed.timestamp() * 1000)
        series = {symbol: fetch_daily_closes(symbol, observed_ms=observed_ms) for symbol in C60_SYMBOLS}
    panel, audit = build_panel(series)
    results = run_study(panel, audit)
    results["observed_at"] = observed.isoformat()

    bundle = args.out_root / canonical_hash({"data": audit["data_hash"], "prereg": results["preregistration_hash"]})[:16]
    bundle.mkdir(parents=True, exist_ok=True)
    os.chmod(bundle, 0o700)
    _write(bundle / "closes.json", series)
    _write(bundle / "preregistration.json", PREREGISTRATION)
    _write(bundle / "results.json", results)
    _write(bundle / "manifest.json", {
        "files": {name: canonical_hash(json.loads((bundle / name).read_text()))
                  for name in ("closes.json", "preregistration.json", "results.json")},
        "research_only": True, "orders_authorized": False,
    })
    print(json.dumps({"bundle": str(bundle), "verdicts": {k: v["verdict"] for k, v in results["trials"].items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
