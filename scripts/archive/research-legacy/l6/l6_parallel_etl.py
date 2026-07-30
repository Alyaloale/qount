#!/usr/bin/env python3
"""Parallel L6-daily ETL driver (research-only).

Reuses ``qount.l6_microstructure`` per-symbol functions under a
``multiprocessing.Pool`` so one trading day's 7000+ instruments are processed
across all cores (single-day-at-a-time keeps the WSL VHDX / disk peak to one
day's unpacked size). Output panel JSON is byte-identical in shape to the
``l6-daily-features`` command (same version / feature_names / counts), so the
two are interchangeable; this one just fans out across CPUs.

Usage:
    python l6_parallel_etl.py <day_dir> <out.json> [workers]

``day_dir`` must contain ``<code>.SZ|SH/`` subfolders (the unpacked day). No
network, no orders, does not touch live / run-once.
"""
from __future__ import annotations

import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from qount.l6_microstructure import DAILY_FEATURES
from qount.l6_microstructure import L6_MICROSTRUCTURE_VERSION
from qount.l6_microstructure import ORDER_FILE
from qount.l6_microstructure import TRADE_FILE
from qount.l6_microstructure import _load_instrument
from qount.l6_microstructure import daily_flow_features
from qount.l6_microstructure import parse_orders
from qount.l6_microstructure import parse_trades


def _one(args: tuple[str, str]) -> tuple[str, dict | None]:
    day_dir, sym = args
    d = Path(day_dir) / sym
    try:
        snaps, trades = _load_instrument(Path(day_dir), sym)
        _t, sz_cancels = parse_trades(d / TRADE_FILE)
        orders = parse_orders(d / ORDER_FILE)
    except FileNotFoundError:
        return sym, None
    cancels = sz_cancels + [o for o in orders if o.kind == "cancel"]
    return sym, daily_flow_features(snaps, trades, cancels)


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: l6_parallel_etl.py <day_dir> <out.json> [workers]")
    day_dir = sys.argv[1]
    out = sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else None
    syms = sorted(p.name for p in Path(day_dir).iterdir() if p.is_dir())
    t0 = time.time()
    with Pool(workers) as pool:
        results = pool.map(_one, [(day_dir, s) for s in syms], chunksize=8)
    panel = {s: f for s, f in results if f is not None}
    json.dump(
        {
            "version": L6_MICROSTRUCTURE_VERSION,
            "day_dir": day_dir,
            "feature_names": list(DAILY_FEATURES),
            "n_symbols_requested": len(syms),
            "n_symbols_scored": len(panel),
            "features": panel,
        },
        open(out, "w"),
        ensure_ascii=False,
    )
    print(f"scored {len(panel)}/{len(syms)} in {time.time()-t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
