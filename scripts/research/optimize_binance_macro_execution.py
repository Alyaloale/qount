"""Fixed capacity/cost/gap-reserve ablations on the existing tactical signals."""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

from qount.research.binance_etf_leverage import load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_liquidity import candidate_clocks, load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case
from qount.research.binance_macro_validation import available_atr, frozen_trade, minute_windows
from qount.research_data.archives import timestamp


ARMS = {
    "legacy5": dict(capacity=False, slip=.0005, gap=.01),
    "volume5": dict(capacity=True, slip=.0005, gap=.01),
    "cost25": dict(capacity=False, slip=.0025, gap=.01),
    "volume25": dict(capacity=True, slip=.0025, gap=.01),
    "volume25_gap3": dict(capacity=True, slip=.0025, gap=.03),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015"))
    p.add_argument("--capacity-cache", type=Path, default=Path("state/research_cache/binance_macro_liquidity_20261015"))
    p.add_argument("--minute-cache", type=Path, default=Path("state/research_cache/binance_macro_minutes_20261015"))
    p.add_argument("--download", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_optimization")
    features, sources = macro_features(args.cache, "2026-10-15")
    data, contract_sources = load_inputs(args.cache, timestamp("2026-07-30"), timestamp("2026-10-15"), symbols=tuple(CONTRACT_SIGNALS))
    clocks = candidate_clocks(data, features)
    contexts, context_sources, observed_volume = load_capacity_contexts(clocks, args.capacity_cache, args.download)
    book, signals = directional_book(data, features, "long", 20/3)
    bundles, summaries = {}, []
    for arm, capital, scenario in itertools.product(ARMS, (10, 100), ("base", "double_cost")):
        spec = ARMS[arm]
        bundle = replay(cost_case(book, scenario), signals, strategy="macro_tactical", capital=capital,
                        gross_cap=20, risk_fraction=.20, exchange_leverage=50, liquidation_stop_multiple=3,
                        account_controls=False, funding_policy="debit_stress",
                        entry_liquidity_caps=contexts if spec["capacity"] else None,
                        sizing_gap_reserve=spec["gap"],
                        fee=.001 if scenario == "double_cost" else .0005,
                        slip=spec["slip"]*(2 if scenario == "double_cost" else 1))
        bundle["summary"].update(arm=arm, capital=capital, scenario=scenario)
        bundles[arm, capital, scenario] = bundle
    # Reproduce the pre-optimization controls before interpreting new arms.
    for capital in (10, 100):
        old = json.loads(Path(f"state/research_runs/binance_macro_long_short_20261015/wide20_long_capital{capital}_base.json").read_text())
        assert old["trades"] == bundles["legacy5", capital, "base"]["trades"]
    all_trades = [t for (arm, capital, scenario), b in bundles.items() if scenario == "base" for t in b["trades"]]
    longest = {}
    for t in all_trades:
        key = t["symbol"], t["entry_time"]
        if key not in longest or t["exit_time"] > longest[key]["exit_time"]:
            longest[key] = t
    minute_data, minute_sources = minute_windows(list(longest.values()), args.minute_cache, timestamp("2026-10-15"), args.download)
    atrs = {s: available_atr(d["trade"]) for s, d in data.items()}
    stress = []
    args.output.mkdir(parents=True)
    for (arm, capital, scenario), bundle in bundles.items():
        spec = ARMS[arm]
        if scenario == "base":
            equity = peak = capital
            mdd = 0
            checks = []
            for t in bundle["trades"]:
                window = minute_data[t["symbol"], t["entry_time"]]
                result = frozen_trade({**t, "equity_before_entry": equity}, window["trade"], window["mark"],
                                      data[t["symbol"]]["funding"], atrs[t["symbol"]], data[t["symbol"]]["rule"], slip=spec["slip"])
                for row in result.pop("curve"):
                    mdd = max(mdd, 1-row["equity"]/peak)
                    peak = max(peak, row["equity"])
                assert math.isclose(t["net_pnl"], result["net_pnl"], abs_tol=1e-8)
                assert result["entry_stress_risk_usdt"] <= t["risk_budget_usdt"]+1e-9
                equity += result["net_pnl"]
                v = observed_volume[t["symbol"], t["entry_time"]]
                result.update(symbol=t["symbol"], observed_entry_volume_fraction=t["quantity"]/v if v > 0 else None)
                checks.append(result)
                if spec["capacity"]:
                    context = t["entry_liquidity"]
                    assert t["quantity"] <= context["quantity_cap"]+1e-9
                    assert context["asof"] <= t["entry_time"]-60
                    if t["entry_time"]-120 < context["asof"] < t["entry_time"]-60:
                        raise AssertionError("unexpected_context_timestamp")
            bundle["minute_checks"] = checks
            bundle["summary"].update(minute_close_mdd=mdd, minute_pnl_reproduced=True,
                                     observed_volume_over_10pct=sum(t["observed_entry_volume_fraction"] is not None and t["observed_entry_volume_fraction"] > .1 for t in checks))
            for overshoot in (.01, .03, .10):
                rows = []
                for t in bundle["trades"]:
                    window = minute_data[t["symbol"], t["entry_time"]]
                    result = frozen_trade(t, window["trade"], window["mark"], data[t["symbol"]]["funding"],
                                          atrs[t["symbol"]], data[t["symbol"]]["rule"], slip=spec["slip"], stop_overshoot=overshoot)
                    result.pop("curve")
                    rows.append(result)
                stress.append(dict(arm=arm, capital=capital, overshoot=overshoot,
                                   max_loss=max((t["risk_fraction_loss"] for t in rows), default=0),
                                   budget_breaches=sum(t["risk_budget_exceeded"] for t in rows),
                                   liquidation_count=sum(t["exit_reason"] == "liquidation_proxy" for t in rows), trades=rows))
        name = f"{arm}_capital{capital}_{scenario}"
        (args.output/(name+".json")).write_text(json.dumps(bundle, allow_nan=False)+"\n")
        summaries.append(bundle["summary"])
    code = [Path(__file__), Path("src/qount/research/binance_macro_liquidity.py"),
            Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"), Path("src/qount/research/binance_macro_validation.py"),
            Path("src/qount/research/engine/perpetual.py"), Path("src/qount/research/binance_macro_attack.py")]
    result = dict(start="2026-07-30", end_exclusive="2026-10-15", arms=ARMS, runs=summaries,
                  synthetic_stress=stress, raw_candidates=len(clocks), capacity_sources=context_sources,
                  minute_sources=minute_sources, sources=sources+contract_sources,
                  code_sources=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in code],
                  assumptions=[
                      "Fixed five arms before payoff; same consumed history and signals, no threshold sweep or independent OOS.",
                      "Capacity caps use10% of min(past5m mean volume,past15m mean volume), with a one-minute publication buffer; current/future minute volume is diagnosis only.",
                      "25bp per-side slip is an explicit conservative scenario, not estimated spread or certified fill. Exit liquidity remains a modeling limitation.",
                      "The gap3 arm reserves3% overshoot beyond stop for sizing, retaining20% risk and3x liquidation-stop cushion; it cannot bound larger jumps.",
                      "Minimum orders are never inflated to defeat capacity limits. Missing/stale capacity fails closed.",
                      "Minute checks preserve hourly-close trailing and verify every new base trade; hypothetical50x setting remains unverified exchange/account capacity.",
                      "No private account, services, production strategy changes or real orders."],
                  research_only=True, orders_authorized=False, independent_oos=False)
    (args.output/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    lines = ["# Causal capacity and execution optimization", "", "|Arm|Capital|Scenario|Net return|Hourly MDD|Minute MDD|Trades|Volume>10% ex post|", "|---|---:|---|---:|---:|---:|---:|---:|"]
    for r in summaries:
        minute = f"{r['minute_close_mdd']:.2%}" if "minute_close_mdd" in r else "n/a"
        lines.append(f"|{r['arm']}|{r['capital']}|{r['scenario']}|{r['net_return']:.2%}|{r['max_drawdown']:.2%}|{minute}|{r['trade_count']}|{r.get('observed_volume_over_10pct', 'n/a')}|")
    lines += ["", "## Independent gap stress", "", "|Arm|Capital|Overshoot past stop|Max loss|Budget breaches|Liquidations|", "|---|---:|---:|---:|---:|---:|"]
    for r in stress:
        lines.append(f"|{r['arm']}|{r['capital']}|{r['overshoot']:.0%}|{r['max_loss']:.2%}|{r['budget_breaches']}|{r['liquidation_count']}|")
    lines += ["", "## Assumptions", ""]+["- "+x for x in result["assumptions"]]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output), arms=len(ARMS), accounts=len(summaries), raw_candidates=len(clocks))))


if __name__ == "__main__":
    main()
