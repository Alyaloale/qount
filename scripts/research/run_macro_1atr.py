#!/usr/bin/env python3
"""Offline selected macro replay with shared inputs/features and isolated results."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from qount.research.lines.macro_1atr import inputs, run
from qount.research.engine.runs import run_identity, cached_run, save_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("base", "double_cost"), default="base")
    parser.add_argument("--review", type=Path, default=Path("state/research_runs/binance_macro_account_review_20261016/review.json"))
    parser.add_argument("--capital", type=float)
    parser.add_argument("--mr-hold-days", type=int, choices=(7, 21),
                        help="Offline fixed holding-period comparison; live rules are unchanged")
    parser.add_argument("--runs-root", type=Path, default=Path("state/research_runs"))
    parser.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015"))
    parser.add_argument("--liquidity", type=Path, default=Path("state/research_cache/binance_macro_liquidity_20261015"))
    parser.add_argument("--reuse", type=Path, nargs="+", default=[Path("state/research_cache")/p for p in (
        "binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730", "binance_macro_attack_20261015")])
    args = parser.parse_args()
    raw = args.review.read_bytes()
    review = json.loads(raw)
    if args.mr_hold_days is not None:
        review["parameters"]["tactical_setup_policies"]["mean_reversion"]["max_hold_hours"] = args.mr_hold_days*24
    capital = args.capital if args.capital is not None else review["replay_capital"]
    fee, slip = ((.0005, .0025) if args.scenario == "base" else (.001, .005))
    book, signals, gates, caps, sources = inputs(args.cache, args.reuse, args.liquidity, "2026-04-07", "2026-10-15")
    sources.append(dict(path=str(args.review), sha256=hashlib.sha256(raw).hexdigest()))
    parameters = dict(capital=capital, fee=fee, slip=slip, controls=review["parameters"], scenario=args.scenario,
                      start="2026-04-07", end_exclusive="2026-10-15")
    if args.mr_hold_days is not None:
        parameters["mr_hold_days"] = args.mr_hold_days
    root = Path("src/qount")
    code = [Path(__file__), Path("config/binance-assets.json")] + [root/p for p in (
        "research/lines/macro_1atr.py", "research/engine/runs.py", "research/engine/evaluation.py",
        "research/engine/perpetual.py", "research/binance_etf_leverage.py", "research/binance_macro_attack.py",
        "research/binance_macro_liquidity.py", "research/binance_macro_opportunities.py",
        "research/binance_macro_funding_lease.py", "research_data/binance_history.py", "research_data/archives.py",
        "research_data/bars.py", "research_data/regime.py", "strategies/perpetual.py", "binance_assets.py")]
    code += sorted((root/"strategies").glob("macro_*.py"))
    digest, identity = run_identity("macro_1atr", parameters, sources, code)
    output = args.runs_root/"macro_1atr"/digest[:20]
    existing = cached_run(output, digest)
    if existing is None:
        result = run(book, signals, gates, caps, capital=capital, fee=fee, slip=slip,
                     controls=review["parameters"], scenario=args.scenario)
        if args.mr_hold_days is not None:
            result["summary"].update(mr_hold_days=args.mr_hold_days,
                hypothesis=f"固定其他原配置，比较均值回归{args.mr_hold_days}天期限的净收益与截尾贡献。",
                conclusion="固定持有期限对照，全部为已消费历史；不改变实盘，不证明独立OOS。")
            result["summary"]["limitations"][0] = "仅调整均值回归持有期限；其余沿用原配置及保留公开输入，不进行参数搜索"
        existing = save_run(output, digest, identity, result)
        reused = False
    else:
        reused = True
    print(json.dumps(dict(output=str(output), run_id=digest, reused=reused,
        total_return_pct=existing["total_return_pct"], max_drawdown_pct=existing["max_drawdown_pct"],
        trade_count=existing["trade_count"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
