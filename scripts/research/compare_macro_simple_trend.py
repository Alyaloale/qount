"""Compare a fixed simple trend and selected macro rules with equal execution constraints."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case
from qount.research.engine.evaluation import nav_metrics
from qount.research.engine.runs import cached_run, run_identity, save_run
from qount.research.lines.macro_1atr import inputs
from qount.research.lines.simple_trend import candidate_clocks, simple_features


def minute_path(cache, key):
    symbol, now = key
    return cache/f"{symbol}-trade-1m-{now-16*60}-{now+60}.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-missing", action="store_true", help="Fetch only absent public 17-minute windows; never rewrite retained files.")
    parser.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015"))
    parser.add_argument("--liquidity", type=Path, default=Path("state/research_cache/binance_macro_liquidity_20261015"))
    parser.add_argument("--new-minutes", type=Path, default=Path("state/research_cache/macro_simple_trend_minutes_20261017"))
    parser.add_argument("--review", type=Path, default=Path("state/research_runs/binance_macro_account_review_20261016/review.json"))
    parser.add_argument("--runs-root", type=Path, default=Path("state/research_runs"))
    args = parser.parse_args()
    raw = args.review.read_bytes()
    review = json.loads(raw)
    roots = [Path("state/research_cache")/name for name in (
        "binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730", "binance_macro_attack_20261015")]
    start, end = "2026-04-07", "2026-10-15"
    book, macro, gates, macro_caps, sources = inputs(args.cache, roots, args.liquidity, start, end)
    simple, simple_sources = simple_features(args.cache, CONTRACT_SIGNALS, end)
    needed = candidate_clocks(book, simple)
    old_keys = [key for key in needed if minute_path(args.liquidity, key).exists()]
    old_key_set = set(old_keys)
    new_keys = [key for key in needed if key not in old_key_set]
    missing = [key for key in new_keys if not minute_path(args.new_minutes, key).exists()]
    print(json.dumps(dict(simple_candidate_clocks=len(needed), retained_minute_clocks=len(old_keys),
                          missing_minute_clocks=len(missing))), flush=True)
    if missing and not args.download_missing:
        raise FileNotFoundError(f"missing_public_minute_windows:{len(missing)}; use --download-missing")
    # Small batches keep downloads bounded if a public source rejects a request.
    for offset in range(0, len(missing), 16):
        load_capacity_contexts(missing[offset:offset+16], args.new_minutes, download=True)
        print(json.dumps(dict(downloaded=min(offset+16, len(missing)), total_missing=len(missing))), flush=True)
    old_caps, old_sources, _ = load_capacity_contexts(old_keys, args.liquidity)
    new_caps, new_sources, _ = load_capacity_contexts(new_keys, args.new_minutes)
    caps = {**macro_caps, **old_caps, **new_caps}
    if any(caps[key] != value for key, value in macro_caps.items()):
        raise AssertionError("retained_macro_capacity_changed")
    if any(key not in caps for key in needed):
        raise ValueError("simple_candidate_capacity_unknown")
    sources += simple_sources+old_sources+new_sources+[dict(path=str(args.review), sha256=hashlib.sha256(raw).hexdigest())]
    root = Path("src/qount")
    code = [Path(__file__), Path("config/binance-assets.json")]+[root/name for name in (
        "research/lines/simple_trend.py", "research/lines/macro_1atr.py", "research/engine/runs.py",
        "research/engine/evaluation.py", "research/engine/perpetual.py", "research/binance_etf_leverage.py",
        "research/binance_macro_attack.py", "research/binance_macro_liquidity.py", "research/binance_macro_opportunities.py",
        "research/binance_macro_funding_lease.py", "research_data/binance_history.py", "research_data/archives.py",
        "research_data/bars.py", "research_data/regime.py", "binance_assets.py", "strategies/perpetual.py")]
    code += sorted((root/"strategies").glob("macro_*.py"))
    retained = {(risk, cost): path for risk, cost, path in (
        (.5, "base", "1f01a9af9a80396377bd"), (.5, "double_cost", "875d9ca2861621ee4529"),
        (.25, "base", "f813a3e5d98a7fe30039"), (.25, "double_cost", "1f88d62da2add6012db9"))}
    for risk in (.5, .25):
        controls = {**review["parameters"], "risk_fraction": risk}
        for cost, fee, slip in (("base", .0005, .0025), ("double_cost", .001, .005)):
            for name, signals, confirmations in (("macro", macro, gates), ("simple_sma120_mom20", simple, None)):
                parameters = dict(strategy=name, controls=controls, capital=review["replay_capital"],
                    start=start, end_exclusive=end, scenario=cost, fee=fee, slip=slip,
                    capacity="same_prior_15_completed_minutes_with_1_minute_publication_buffer",
                    simple_rule="close>SMA120 and momentum20>0; rank=momentum20; fixed_20x_gross_cap; 7day_horizon")
                digest, identity = run_identity("macro_simple_baseline", parameters, sources, code)
                output = args.runs_root/"macro_simple_baseline"/digest[:20]
                summary = cached_run(output, digest)
                reused = summary is not None
                if summary is None:
                    result = replay(cost_case(book, cost), signals, capital=review["replay_capital"], fee=fee, slip=slip,
                        entry_liquidity_caps=caps, entry_confirmations=confirmations, **controls)
                    if name == "macro":
                        original = Path("state/research_runs/macro_1atr")/retained[risk, cost]
                        saved = json.loads((original/"summary.json").read_text())
                        cached_run(original, saved["run_id"])
                        if result["trades"] != json.loads((original/"trades.json").read_text()) or result["summary"] != saved["retained_replay_summary"]:
                            raise AssertionError("common_capacity_changed_retained_macro_replay")
                    nav = [dict(t=r["time"], nav=r["equity"]/review["replay_capital"], equity=r["equity"]) for r in result["curve"]]
                    trades = result["trades"]
                    detail = result["summary"]
                    summary = dict(**nav_metrics(nav), initial_capital=review["replay_capital"], final_equity=detail["final_equity"],
                        trade_count=len(trades), closed_trades=sum(t["exit_reason"] != "end_of_sample" for t in trades),
                        censored_trades=sum(t["exit_reason"] == "end_of_sample" for t in trades),
                        closed_pnl=sum(t["net_pnl"] for t in trades if t["exit_reason"] != "end_of_sample"),
                        censored_pnl=sum(t["net_pnl"] for t in trades if t["exit_reason"] == "end_of_sample"),
                        entry_notional_usdt=sum(t["quantity"]*t["entry_price"] for t in trades),
                        two_sided_turnover_usdt=sum(t["quantity"]*(t["entry_price"]+t["exit_price"]) for t in trades),
                        fees_usdt=detail["fees"], funding_usdt=detail["funding"], maximum_observed_gross=detail["maximum_observed_gross"],
                        cash_fraction=detail["cash_fraction"], intrahour_drawdown_proxy=detail["intrahour_drawdown_bound"],
                        halt=detail["halt"], rejections=detail["rejections"], sample_kind="consumed_historical_exploration",
                        independent_oos=False, symbols=list(book), simple_candidate_clocks=len(needed),
                        retained_minute_clocks=len(old_keys), added_minute_clocks=len(new_keys),
                        baselines={"cash": {"total_return_pct": 0.0}},
                        hypothesis="在相同成本、压力预算和分钟容量规则下，复杂宏观规则是否比固定简单趋势有净增量。",
                        limitations=["同风险预算上限不等于同实际暴露或相同尾部损失。",
                            "比较完整规则组合：简单趋势不使用宏观状态/系统门/禁止追涨/MR门，统一7天期限；不归因单个模块。",
                            "ETF信号代理与原生合约分开；当前交易filters历史套用，资金费历史版本限制保持。",
                            "分钟成交量只是容量代理，不代表盘口深度或实际成交保证；小时止损/清算与退出继续近似。",
                            "所有结果为已消费历史；原宏观方案经过历史选择，本次简单规则固定且不搜索参数，不能认定OOS优势。"])
                    summary = save_run(output, digest, identity, dict(summary=summary, nav=nav, trades=trades))
                print(json.dumps(dict(output=str(output), reused=reused, strategy=name, risk=risk, scenario=cost,
                    return_pct=summary["total_return_pct"], mdd_pct=summary["max_drawdown_pct"], trades=summary["trade_count"],
                    closed_pnl=summary["closed_pnl"], censored_pnl=summary["censored_pnl"])), flush=True)


if __name__ == "__main__":
    main()
