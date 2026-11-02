"""MR thesis invalidation at the frozen entry rejection candle's low."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import cost_case
from qount.research.macro_depth_execution import DepthExitStress
from qount.research.macro_mechanism_value import daily_replay
from qount.research.macro_mr_exit import RejectionLowHolding
from continue_macro_fixed_candidates import CASES, append_inputs
from study_macro_admission_and_simplicity import headline, verify
from study_macro_mechanism_value import cluster_interval, paired_blocks
from study_macro_mr_failure import RUNS, long_inputs, native_profiles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; retain old results")
    book, rows, _, sources = long_inputs()
    rules = dict(control=None, own_low=RejectionLowHolding(book),
                 own_and_market_low=RejectionLowHolding(book, systemic=True))
    previous = json.loads((RUNS/"macro_mr_failure_20261026/comparison.json").read_text())
    daily, daily_pairs, shadows, checks = [], [], [], []
    count = 0
    for target in (None, .15):
        for profile, rule in rules.items():
            r = daily_replay(book, rows["control"], "original_mr", vol_target=target, mr_holding_rule=rule)
            r["exit_profile"] = profile
            daily.append(r)
            count += 1
            if profile == "control":
                old = next(v for v in previous["daily"] if v["exit_profile"] == profile and v["vol_target"] == target)
                assert r["trades"] == old["trades"] and r["curve"] == old["curve"]
                checks.append(dict(sample="ETF", vol_target=target, exact=True))
            print("ETF", target, profile, r["summary"]["cagr_pct"], r["summary"]["max_drawdown_pct"], flush=True)
        control = next(r for r in daily if r["exit_profile"] == "control" and r["vol_target"] == target)
        for r in daily:
            if r["vol_target"] == target and r["exit_profile"] != "control":
                daily_pairs.append(dict(profile=r["exit_profile"], vol_target=target, **paired_blocks(r, control)))
    primary = next(r for r in daily if r["exit_profile"] == "control" and r["vol_target"] is None)
    for t in primary["trades"]:
        if t["exit_reason"] == "end_of_sample":
            continue
        start = dt.datetime.fromtimestamp(t["entry_time"]).date()
        pair = {}
        for profile, rule in rules.items():
            r = daily_replay(book, rows["control"], "original_mr", start=start.isoformat(),
                end=(start+dt.timedelta(days=50)).isoformat(), capital=t["equity_at_entry"],
                mr_holding_rule=rule, entry_times={t["entry_time"]})
            count += 1
            assert len(r["trades"]) == 1
            v = r["trades"][0]
            assert abs(v["quantity"]-t["quantity"]) < 1e-8 and v["entry_price"] == t["entry_price"]
            pair[profile] = v
        assert pair["control"] == t
        for profile in rules:
            if profile == "control" or pair[profile]["exit_reason"] == "end_of_sample":
                continue
            shadows.append(dict(profile=profile, symbol=t["symbol"], signal_date=start.isoformat(),
                control=t, candidate=pair[profile], delta=(pair[profile]["net_pnl"]-t["net_pnl"])/(
                    t["quantity"]*t["entry_price"])))
    (native, features, gates, caps), native_sources, _ = append_inputs("2026-10-26", False)
    sources += native_sources
    proxy = native_profiles(features, return_bars=True)
    rules = dict(control=None, own_low=RejectionLowHolding(proxy),
                 own_and_market_low=RejectionLowHolding(proxy, systemic=True))
    prior = json.loads((RUNS/"macro_mr_holding_20261026/comparison.json").read_text())
    native_results = []
    for capital in (prior["parameters"]["capital"], 30., 100.):
        for scenario, fee, slip, shock in CASES:
            p = dict(prior["parameters"], capital=capital, fee=fee, slip=slip)
            data = cost_case(native, scenario)
            for profile, rule in rules.items():
                r = replay(data, features, mr_holding_rule=rule, entry_confirmations=gates,
                    entry_liquidity_caps=caps, exit_execution_model=DepthExitStress({}, use_depth=False,
                        unknown_extra_slip=0, all_extra_slip=shock) if shock else None, **p)
                verify(r, data, p)
                count += 1
                if profile == "control":
                    old = next(v for v in prior["portfolios"] if v["profile"] == "control" and
                               v["capital"] == capital and v["scenario"] == scenario)
                    assert r["trades"] == old["trades"] and r["curve"] == old["curve"]
                    checks.append(dict(sample="native", capital=capital, scenario=scenario, exact=True))
                native_results.append(dict(profile=profile, capital=capital, scenario=scenario,
                    headline=headline(r), trades=r["trades"], curve=r["curve"]))
                print("native", capital, scenario, profile, r["summary"]["net_return"], flush=True)
    native_shadows = []
    baseline = next(r for r in native_results if r["profile"] == "control" and r["scenario"] == "base"
                    and r["capital"] == prior["parameters"]["capital"])
    for t in baseline["trades"]:
        if t["tactical_setup"] != "mean_reversion":
            continue
        only = {k: dict(g, eligible=g["eligible"] and k == (t["symbol"], t["entry_time"])) for k, g in gates.items()}
        pair = {}
        for profile, rule in rules.items():
            p = dict(prior["parameters"], capital=t["equity_before_entry"])
            r = replay(native, features, mr_holding_rule=rule, entry_confirmations=only,
                entry_liquidity_caps=caps, **p)
            count += 1
            verify(r, native, p)
            assert len(r["trades"]) == 1
            pair[profile] = r["trades"][0]
            assert pair[profile]["quantity"] == t["quantity"]
        assert pair["control"] == t
        native_shadows.append(pair)
    unique = {r["path"]: r for r in sources}
    for r in unique.values():
        assert hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"]
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Freeze entry signal candle low as MR failure level, close-confirmed, preserving initial entries, original stop/trail,21-day limit and financial funding/cash caps. Equity SPY entry-day low is evaluated separately.",
        daily=daily, daily_pairs=daily_pairs, daily_shadows=shadows,
        daily_shadow_statistics={p: cluster_interval([r for r in shadows if r["profile"] == p], "delta")
                                 for p in ("own_low", "own_and_market_low")},
        native=native_results, native_shadows=native_shadows, control_checks=checks,
        replay_count=count, sources=list(unique.values()))
    args.output.mkdir(parents=True)
    (args.output/"comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False)+"\n")
    lines = ["# MR反弹信号低点：修复假设失效", "",
        "顺序追加于双收盘/EMA200均未改善原生结果之后：固定入场信号K线低点，后续已完成收盘跌破则次一决策退出，未跌破则不因原趋势资格失效退出。权益的SPY同日低点另做组件消融。",
        "初始入场、21自然日期限、原2ATR/移动止损及财务风险/资金费/现金保护不变；财务续期使用新持仓资格，但不会刷新终身预算。价格锚点随持仓冻结，不随新信号重置。",
        "ETF2017–2025、单仓无杠杆、10000美元等值、下一开盘；原生2026-04-07至10-26前、25%预算、原容量/档位；基础单边5bp/25bp、真实原生资金费，现金0%。ETF为调整价格单位、并非原生合约收益。", "",
        "|ETF仓位上限|规则|CAGR|日MDD|交易数|2022|", "|---|---|---:|---:|---:|---:|"]
    for r in daily:
        h = r["summary"]
        lines.append(f"|{r['vol_target']}|{r['exit_profile']}|{h['cagr_pct']:.2f}%|{h['max_drawdown_pct']:.2f}%|{h['trades']}|{h['years']['2022']:.2%}|")
    lines += ["", "## 固定ETF入场的增量", "", json.dumps(out["daily_shadow_statistics"], ensure_ascii=False), "",
        "原71个入场固定实际数量及价格，独立退出影子；扩展区间可重叠，不作可实现组合收益。", "",
        "## 原生账户", "", "|本金|成本|规则|收益|小时MDD|交易数|", "|---:|---|---|---:|---:|---:|"]
    for r in native_results:
        h = r["headline"]
        lines.append(f"|{r['capital']:.4f}|{r['scenario']}|{r['profile']}|{h['net_return']:.2%}|{h['max_drawdown']:.2%}|{h['trade_count']}|")
    lines += ["", "## 同一原生MR入场", ""]
    for pair in native_shadows:
        for profile in ("own_low", "own_and_market_low"):
            a, b = pair["control"], pair[profile]
            lines.append(f"- {a['symbol']} / {profile}：数量{a['quantity']}，原净损益{a['net_pnl']:+.6f}→{b['net_pnl']:+.6f}，原退出{a['exit_reason']}→{b['exit_reason']}。")
    lines += ["", f"{count}次回放；{len(checks)}组旧控制逐值复现；{len(unique)}份输入hash一致。", "",
        "全部为已消费历史的顺序研究，ETF当前复权/资产池及原生当前档位历史套用、小时成交/止损近似仍在；不认证独立OOS、真实IOC或生产替换。未改实盘源码、参数、权限、服务。", "",
        "复现：`PYTHONPATH=src ./.venv/bin/python scripts/research/study_macro_mr_rejection_low.py --output <新目录>`", ""]
    (args.output/"report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
