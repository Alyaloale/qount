"""Replay fixed macro opportunities and three predeclared routing mechanisms."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

from qount.research.binance_etf_leverage import load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, macro_features
from qount.research.binance_macro_opportunities import cost_case, diagnose, fractional_rules
from qount.research_data.archives import timestamp


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, default=Path("state/research_runs/binance_macro_attack_20261015_final"))
    p.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError("refuse_overwrite_diagnosis")
    original = json.loads((a.baseline/"summary.json").read_text())
    for row in original["sources"]:
        if hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("original_input_changed:"+row["path"])
    features, _ = macro_features(a.cache, original["end_exclusive"])
    data, _ = load_inputs(a.cache, timestamp(original["start"]), timestamp(original["end_exclusive"]),
                          symbols=tuple(CONTRACT_SIGNALS))
    baseline = replay(data, features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08,
                      capital=10, trace=True)
    saved = json.loads((a.baseline/"macro_hybrid_g3_capital10_base.json").read_text())
    assert saved["trades"] == baseline["trades"]
    for key in baseline["summary"]:
        assert baseline["summary"][key] == saved["summary"][key], key
    events, attribution = diagnose(data, features, baseline)
    a.output.mkdir(parents=True)
    (a.output/"opportunities.json").write_text(json.dumps(events, ensure_ascii=False, allow_nan=False)+"\n")
    controls = [("exact10", 10, data), ("fractional10_untradable", 10, fractional_rules(data)), ("exact100_virtual", 100, data)]
    accounts = []
    for routing, (scale, capital, d), scenario in itertools.product(
            ("core_first", "tactical_first", "tactical_preempt", "exit_handover"), controls,
            ("base", "double_cost", "gap_2pct")):
        bundle = replay(cost_case(d, scenario), features, strategy="macro_hybrid", gross_cap=3,
                        risk_fraction=0.08, capital=capital, routing=routing, trace=True,
                        fee=0.001 if scenario == "double_cost" else 0.0005,
                        slip=0.001 if scenario == "double_cost" else 0.0005,
                        stop_gap=0.02 if scenario == "gap_2pct" else 0)
        bundle["summary"].update(routing=routing, scale=scale, scenario=scenario)
        name = routing+"_"+scale+"_"+scenario
        (a.output/(name+".json")).write_text(json.dumps(bundle, allow_nan=False)+"\n")
        accounts.append(bundle["summary"])
    # Split the joint fractional control into its two mechanical components.
    for scale, d in (("no_notional_floor10", fractional_rules(data, relax_grid=False)),
                     ("no_quantity_grid10", fractional_rules(data, relax_minimum=False))):
        for scenario in ("base", "double_cost", "gap_2pct"):
            bundle = replay(cost_case(d, scenario), features, strategy="macro_hybrid", gross_cap=3,
                            risk_fraction=0.08, capital=10, routing="core_first", trace=True,
                            fee=0.001 if scenario == "double_cost" else 0.0005,
                            slip=0.001 if scenario == "double_cost" else 0.0005,
                            stop_gap=0.02 if scenario == "gap_2pct" else 0)
            bundle["summary"].update(routing="core_first", scale=scale, scenario=scenario)
            (a.output/("core_first_"+scale+"_"+scenario+".json")).write_text(json.dumps(bundle, allow_nan=False)+"\n")
            accounts.append(bundle["summary"])
    assumptions = [
        "All original38 input hashes checked; no downloads, new dates, new signals or parameter search.",
        "Raw candidate flags ignore monthly quota/account occupancy for attribution; they are not all legal portfolio entries.",
        "Every event starts from fixed10 or100 equity, no compounding, no account HALT/downshift; native stop/liquidation/state/time exits retained.",
        "Signal-only fractional paths bypass forecast friction admission, but pay actual modeled fees/slippage/signed funding.",
        "Quantity-only counterfactuals reuse identical entry/exit paths; exit mechanisms and isolated leverage must match.",
        "Fractional control relaxes only LOT_SIZE/MARKET_LOT_SIZE grids/minQty and MIN_NOTIONAL; price ticks and all other rules unchanged.",
        "Core-first component controls separately remove MIN_NOTIONAL only or quantity grid/minQty only; both remain untradable diagnostics.",
        "Fixed-path double cost changes fees/slippage/adverse regular funding on original exit clocks; separate from full account reruns.",
        "End-of-sample paths are right-censored and excluded from closed-event expectancy; all events still retained.",
        "Consecutive signal episodes are grouped; first observable event per episode is a correlation diagnostic, not independent evidence.",
        "Event PnL totals cannot be added as account returns because events overlap and use separate virtual capital.",
        "Core occupancy groups use original continuous account decision trace; no causally randomized treatment claim.",
        "Coordination: original core-first, tactical-first only when flat, executable tactical preemption, and natural-exit same-clock tactical handover.",
        "Handover never interrupts valid holdings and never repurchases the just-exited asset; both planned exit and entry pay costs.",
        "Preemption checks replacement feasibility using actual post-exit equity before selling core; both fills pay costs, same-hour latency approximate.",
        "All prior hourly fill/mark, current-filter, funding-vintage, maintenance and historical-book limitations remain.",
        "This consumed-history diagnosis cannot establish OOS alpha or authorize production/parameter promotion.",
    ]
    code_paths = [Path(__file__), Path("src/qount/research/binance_macro_opportunities.py"),
                  Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"), Path("src/qount/research/binance_macro_attack.py"),
                  Path("src/qount/research/engine/perpetual.py"), Path("src/qount/research_data/bars.py")]
    result = {"start": original["start"], "end_exclusive": original["end_exclusive"],
              "baseline_sha256": hashlib.sha256((a.baseline/"summary.json").read_bytes()).hexdigest(),
              "baseline_trades_and_summary_reproduced": True, "source_hashes_verified": len(original["sources"]),
              "code_sources": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in code_paths],
              "attribution": attribution, "accounts": accounts, "assumptions": assumptions,
              "research_only": True, "orders_authorized": False, "independent_oos": False}
    (a.output/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    lines = ["# 固定机会重放与入口协调诊断", "", f"{original['start']} 至 {original['end_exclusive']}（结束日不含），已消费历史。", "",
             "## 逐机会质量（事件重叠，不能相加为账户收益）", "",
             "|入口|口径|候选|可评估/可执行|闭合|截尾|平均净压力R|固定路径双倍成本R|", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for engine in ("core", "tactical"):
        for label, s in attribution[engine].items():
            val = "—" if s["mean_net_stress_r"] is None else f"{s['mean_net_stress_r']:.4f}"
            dbl = "—" if s["mean_fixed_path_double_cost_r"] is None else f"{s['mean_fixed_path_double_cost_r']:.4f}"
            lines.append(f"|{engine}|{label}|{s['signals']}|{s['accepted']}|{s['closed']}|{s['censored']}|{val}|{dbl}|")
    lines += ["", "## 连续账户对照", "", "|协调方式|规模|情景|净收益|最大回撤|交易数|", "|---|---|---|---:|---:|---:|"]
    for s in accounts:
        lines.append(f"|{s['routing']}|{s['scale']}|{s['scenario']}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['trade_count']}|")
    lines += ["", "## 假设与限制", ""]+["- "+s for s in assumptions]
    (a.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps({"opportunities": len(events), "account_runs": len(accounts), "output": str(a.output)}))


if __name__ == "__main__":
    main()
