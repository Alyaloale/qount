"""Minute-price and exogenous-gap validation of eight frozen small-account orders."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from qount.research.binance_etf_leverage import load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_validation import available_atr, frozen_trade, minute_windows
from qount.research_data.bars import aggregate
from qount.research_data.archives import timestamp


SCENARIOS = {
    "minute_base": {},
    "mark_trigger": dict(trigger="mark"),
    "delay_1m": dict(entry_delay=1, exit_delay=1),
    "delay_5m": dict(entry_delay=5, exit_delay=5),
    "double_cost": dict(fee=.001, slip=.001),
    "slip_25bp": dict(slip=.0025),
    "slip_50bp": dict(slip=.005),
    "isolated_funding_debit": dict(funding_collateral="isolated_debit"),
    "maintenance_2_5pct": dict(maintenance=.025),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, default=Path("state/research_runs/binance_macro_long_short_20261015"))
    p.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015"))
    p.add_argument("--minute-cache", type=Path, default=Path("state/research_cache/binance_macro_minutes_20261015"))
    p.add_argument("--download", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_validation")
    baseline = json.loads((args.baseline/"summary.json").read_text())
    for source in baseline["sources"]:
        if hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("original_input_changed")
    books = {}
    for profile in ("base20", "wide20", "attack50"):
        for capital in (10, 100):
            books[profile, capital] = json.loads((args.baseline/f"{profile}_long_capital{capital}_base.json").read_text())
    primary = books["wide20", 10]["trades"]
    minute_data, minute_sources = minute_windows(primary, args.minute_cache, timestamp("2026-10-15"), args.download)
    data, _ = load_inputs(args.cache, timestamp("2026-07-30"), timestamp("2026-10-15"), symbols=tuple(CONTRACT_SIGNALS))
    atrs = {s: available_atr(d["trade"]) for s, d in data.items()}
    hourly_comparison = {"checked": 0, "mismatched": 0, "by_kind": {}, "max_absolute_price_difference": 0, "examples": []}
    for (symbol, start), window in minute_data.items():
        for kind in ("trade", "mark"):
            old = {b.t: b for b in data[symbol][kind]}
            for b in aggregate(window[kind], 3600, 60):
                err = max(abs(getattr(b, k)-getattr(old[b.t], k)) for k in ("o", "h", "l", "c"))
                hourly_comparison["checked"] += 1
                hourly_comparison["max_absolute_price_difference"] = max(err, hourly_comparison["max_absolute_price_difference"])
                if err > 1e-7:
                    hourly_comparison["mismatched"] += 1
                    hourly_comparison["by_kind"][kind] = hourly_comparison["by_kind"].get(kind, 0)+1
                    hourly_comparison["examples"].append(dict(symbol=symbol, kind=kind, time=b.t, difference=err))
    runs, stress = [], []
    for (profile, capital), original in books.items():
        assert [(t["symbol"], t["entry_time"], t["exit_time"]) for t in original["trades"]] == [(t["symbol"], t["entry_time"], t["exit_time"]) for t in primary]
        for scenario, params in SCENARIOS.items():
            equity = peak = capital
            mdd = adverse_mdd = 0
            trades = []
            margin_violations = risk_violations = 0
            for t in original["trades"]:
                s = t["symbol"]
                window = minute_data[s, t["entry_time"]]
                funding = data[s]["funding"]
                if scenario == "double_cost":
                    funding = [{**r, "fundingRate": str(float(r["fundingRate"])*2)}
                               if r.get("rateType", "Regular") == "Regular" and float(r["fundingRate"]) > 0
                               else r for r in funding]
                order = {**t, "equity_before_entry": equity,
                         "risk_budget_usdt": baseline["profiles"][profile]["risk_fraction"]*equity}
                result = frozen_trade(order, window["trade"], window["mark"], funding, atrs[s], data[s]["rule"], **params)
                curve = result.pop("curve")
                if result["status"] == "executed":
                    margin_violations += result["entry_margin_fraction"] > .8+1e-9
                    risk_violations += result["entry_stress_risk_usdt"] > order["risk_budget_usdt"]+1e-9
                for row in curve:
                    mdd = max(mdd, 1-row["equity"]/peak)
                    adverse_mdd = max(adverse_mdd, 1-row["adverse_equity"]/peak)
                    peak = max(peak, row["equity"])
                equity += result["net_pnl"]
                result.update(symbol=s, original_net_pnl=t["net_pnl"])
                trades.append(result)
            assert math.isclose(capital+sum(t["net_pnl"] for t in trades), equity, abs_tol=1e-8)
            if scenario == "minute_base":
                assert all(math.isclose(t["net_pnl"], t["original_net_pnl"], abs_tol=1e-8) for t in trades)
            runs.append(dict(profile=profile, capital=capital, scenario=scenario, net_return=equity/capital-1,
                             minute_close_mdd=mdd, adverse_minute_bound=adverse_mdd,
                             stops=sum(t["exit_reason"] == "stop" for t in trades),
                             liquidations=sum(t["exit_reason"] == "liquidation_proxy" for t in trades),
                             changed_exit_times=sum(t["exit_time"] != o["exit_time"] for t, o in zip(trades, original["trades"])),
                             margin_cap_violations=margin_violations, risk_cap_violations=risk_violations,
                             cancellations=sum(t["status"] != "executed" for t in trades), trades=trades))
        for overshoot in (.01, .03, .10):
            results = []
            for t in original["trades"]:
                s = t["symbol"]
                window = minute_data[s, t["entry_time"]]
                r = frozen_trade(t, window["trade"], window["mark"], data[s]["funding"], atrs[s], data[s]["rule"],
                                 stop_overshoot=overshoot)
                r.pop("curve")
                results.append(dict(symbol=s, original_entry_time=t["entry_time"], **r))
            stress.append(dict(profile=profile, capital=capital, overshoot_beyond_stop=overshoot,
                               min_loss_fraction=min(r["risk_fraction_loss"] for r in results),
                               max_loss_fraction=max(r["risk_fraction_loss"] for r in results),
                               budget_breaches=sum(r["risk_budget_exceeded"] for r in results),
                               stress_estimate_breaches=sum(r["stress_estimate_exceeded"] for r in results),
                               liquidations=sum(r["exit_reason"] == "liquidation_proxy" for r in results), trades=results))
    # Frozen-size cost paths can violate the original budget. Compare actual
    # causal re-admission/resizing instead of calling them executable accounts.
    features, _ = macro_features(args.cache, "2026-10-15")
    book, signals = directional_book(data, features, "long", 20/3)
    full_strategy = []
    for capital in (10, 100):
        for slip in (.0005, .0025, .005):
            bundle = replay(book, signals, strategy="macro_tactical", capital=capital,
                            account_controls=False, funding_policy="debit_stress", slip=slip,
                            **baseline["profiles"]["wide20"])
            full_strategy.append(dict(capital=capital, slip_per_side=slip, **bundle["summary"], trades=bundle["trades"]))
    args.output.mkdir(parents=True)
    code = [Path(__file__), Path("src/qount/research/binance_macro_validation.py")]
    result = dict(start=baseline["start"], end_exclusive=baseline["end_exclusive"],
                  baseline_summary_sha256=hashlib.sha256((args.baseline/"summary.json").read_bytes()).hexdigest(),
                  original_input_files_verified=len(baseline["sources"]), minute_sources=minute_sources,
                  minute_bars=sum(len(v[k]) for v in minute_data.values() for k in v),
                  hourly_comparison=hourly_comparison, runs=runs, synthetic_stress=stress,
                  full_strategy_slippage_controls=full_strategy,
                  code_sources=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in code],
                  assumptions=[
                      "Frozen signal/quantity/order schedule; delay/cost paths do not reselect signals or resize orders. Margin/risk-cap violations are disclosed, not silently repaired.",
                      "Sample-end exits stay at sample end; right-censored trades are not extended for exit delays.",
                      "Hourly-close trailing and causal prior-day ATR retained; no within-minute favourable trailing.",
                      "Contract or mark stop triggers compared; mark-trigger fills use adverse contract-minute extreme. No historical order book or queue proof.",
                      "Funding follows settled timestamps; ambiguous touched-stop minute charges debits and omits credits. Wallet-first funding and isolated-debit stress bound are separate.",
                      "Liquidation uses mark extremes, dynamic isolated collateral, hypothetical1%/2.5% maintenance, current clearance fee and isolated-bankruptcy clipping; real brackets/insurance handling unverified.",
                      "Synthetic persistent gap occurs one minute after each independent frozen entry and goes1/3/10% beyond its existing stop. These are loss scenarios, not probabilities or account returns.",
                      "Minute volume participation is an after-the-fact liquidity diagnostic, never an entry filter using future volume.",
                      "Same consumed historical dates, no fresh OOS, private account access, service changes or live orders."],
                  research_only=True, orders_authorized=False, independent_oos=False)
    (args.output/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    lines = ["# Frozen-order minute execution validation", "", "|Profile|Capital|Scenario|Net return|Minute-close MDD|Stops|Liquidations|Cancelled|Margin/risk violations|", "|---|---:|---|---:|---:|---:|---:|---:|---|"]
    for r in runs:
        lines.append(f"|{r['profile']}|{r['capital']}|{r['scenario']}|{r['net_return']:.2%}|{r['minute_close_mdd']:.2%}|{r['stops']}|{r['liquidations']}|{r['cancellations']}|{r['margin_cap_violations']}/{r['risk_cap_violations']}|")
    lines += ["", "## Full strategy with causal cost admission and sizing", "", "|Capital|Slip per side|Net return|Hourly-close MDD|Trades|", "|---|---:|---:|---:|---:|"]
    for r in full_strategy:
        lines.append(f"|{r['capital']}|{r['slip_per_side']*10000:.0f}bp|{r['net_return']:.2%}|{r['max_drawdown']:.2%}|{r['trade_count']}|")
    lines += ["", "## Independent synthetic gap losses", "", "|Profile|Capital|Gap past stop|Min loss|Max loss|Budget breaches|Liquidations|", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in stress:
        lines.append(f"|{r['profile']}|{r['capital']}|{r['overshoot_beyond_stop']:.0%}|{r['min_loss_fraction']:.2%}|{r['max_loss_fraction']:.2%}|{r['budget_breaches']}/8|{r['liquidations']}/8|")
    lines += ["", "## Assumptions", ""]+["- "+x for x in result["assumptions"]]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output), minute_bars=result["minute_bars"],
                         frozen_books=len(runs), synthetic_trade_paths=sum(len(r["trades"]) for r in stress),
                         hourly_comparison={k:v for k,v in hourly_comparison.items() if k!='examples'})))


if __name__ == "__main__":
    main()
