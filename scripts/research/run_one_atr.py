#!/usr/bin/env python3
"""Offline 1ATR study using existing native caches; never requests account APIs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from qount.binance_assets import load_binance_assets
from qount.research_data.binance_history import load_cached_history
from qount.research.lines.one_atr import replay
from qount.research.engine.runs import run_identity, cached_run, save_run


def timestamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reuse", type=Path, nargs="+", default=[Path("state/research_cache")/s for s in (
        "binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730", "binance_macro_attack_20261015")])
    p.add_argument("--rules", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015/exchange-info.json"))
    p.add_argument("--data-start", default="2026-04-07")
    p.add_argument("--start", default="2026-08-07")
    p.add_argument("--end-exclusive", default="2026-10-15")
    p.add_argument("--capital", type=float, default=100)
    p.add_argument("--fraction", type=float, default=1.0)
    p.add_argument("--fee", type=float, default=.0005)
    p.add_argument("--slippage", type=float, default=.0005)
    p.add_argument("--symbols", nargs="+")
    p.add_argument("--runs-root", type=Path, default=Path("state/research_runs"))
    a = p.parse_args()
    symbols = a.symbols or [r.execution_symbol for r in load_binance_assets() if r.status=="active"]
    data, sources, excluded = load_cached_history(a.reuse,symbols,timestamp(a.data_start),timestamp(a.end_exclusive),a.rules)
    if not data:
        p.error("No complete native cached inputs; specify existing cache directories with --reuse")
    parameters = dict(start=timestamp(a.start),end=timestamp(a.end_exclusive),capital=a.capital,
                      fraction=a.fraction,fee=a.fee,slip=a.slippage)
    code = [Path(__file__),Path("config/binance-assets.json")] + [Path("src/qount")/s for s in (
        "strategies/one_atr.py", "research/lines/one_atr.py", "research/engine/linear_account.py",
        "research/engine/evaluation.py", "research/engine/perpetual.py", "research/engine/runs.py",
        "research_data/binance_history.py", "research_data/bars.py", "research_data/archives.py",
        "strategies/perpetual.py", "binance_assets.py")]
    digest, identity = run_identity("one_atr",parameters | {"symbols":symbols,"data_start":a.data_start},sources,code)
    output = a.runs_root/"one_atr"/digest[:20]
    cached = cached_run(output,digest)
    if cached:
        print(json.dumps(dict(output=str(output),reused=True,summary=cached),ensure_ascii=False))
        return
    result = replay(data,**parameters)
    baselines = {"cash":{"total_return_pct":0.0,"max_drawdown_pct":0.0}}
    for symbol in ("SPYUSDT","QQQUSDT"):
        if symbol in data:
            baselines[symbol] = replay(data,**parameters,hold_symbol=symbol)["summary"]
    result["summary"].update(symbols=list(data),excluded_symbols=excluded,baselines=baselines)
    summary = save_run(output,digest,identity,result)
    print(json.dumps(dict(output=str(output),reused=False,summary=summary),ensure_ascii=False))


if __name__ == "__main__":
    main()
