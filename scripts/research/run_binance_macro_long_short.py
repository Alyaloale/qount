"""Fixed small-account leverage/direction ablations; offline public cache only."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

from qount.research.binance_etf_leverage import feature_at, load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_opportunities import cost_case, fixed_fill_metrics
from qount.research_data.bars import session
from qount.research_data.archives import timestamp


PROFILES = {
    "base20": dict(risk_fraction=.20, gross_cap=3, exchange_leverage=5, liquidation_stop_multiple=3),
    "wide20": dict(risk_fraction=.20, gross_cap=20, exchange_leverage=50, liquidation_stop_multiple=3),
    "wide50": dict(risk_fraction=.50, gross_cap=20, exchange_leverage=50, liquidation_stop_multiple=3),
    "attack50": dict(risk_fraction=.50, gross_cap=20, exchange_leverage=50, liquidation_stop_multiple=1.25),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_results")
    features, sources = macro_features(args.cache, "2026-10-15")
    data, contract_sources = load_inputs(args.cache, timestamp("2026-07-30"), timestamp("2026-10-15"),
                                        symbols=tuple(CONTRACT_SIGNALS))
    args.output.mkdir(parents=True)
    runs = []
    cells = list(itertools.product(PROFILES, ("long", "short", "long_short"), (10, 100),
                                   ("base", "double_cost", "gap_2pct")))
    # Slow bearish gating is an availability control, not selected by payoff.
    cells += [("base20", "short_strict", c, s) for c in (10, 100)
              for s in ("base", "double_cost", "gap_2pct")]
    for profile, mode, capital, scenario in cells:
        params = PROFILES[profile]
        book, signals = directional_book(data, features, "short" if mode == "short_strict" else mode,
                                         params["gross_cap"]/3, "strict" if mode == "short_strict" else "tactical")
        sides = {s: rows[0].get("side", 1) for s, rows in signals.items()}
        bundle = replay(cost_case(book, scenario, sides), signals, strategy="macro_tactical",
                        capital=capital, account_controls=False, funding_policy="debit_stress",
                        fee=.001 if scenario == "double_cost" else .0005,
                        slip=.001 if scenario == "double_cost" else .0005,
                        stop_gap=.02 if scenario == "gap_2pct" else 0, **params)
        summary = bundle["summary"]
        if scenario == "base":
            fixed = [fixed_fill_metrics(t, t, book[t["symbol"]]["funding"])["fixed_path_double_cost_pnl"]
                     for t in bundle["trades"]]
            summary["fixed_fill_double_cost_return"] = sum(fixed)/capital
        summary.update(profile=profile, direction=mode, scenario=scenario,
                       long_pnl=sum(t["net_pnl"] for t in bundle["trades"] if t.get("side", 1) == 1),
                       short_pnl=sum(t["net_pnl"] for t in bundle["trades"] if t.get("side", 1) == -1),
                       short_trades=sum(t.get("side", 1) == -1 for t in bundle["trades"]),
                       maximum_entry_gross=max((t["notional_usdt"]/t["equity_before_entry"] for t in bundle["trades"]), default=0),
                       maximum_entry_leverage=max((t["leverage"] for t in bundle["trades"]), default=0),
                       stress_budget_breaches=sum(-t["net_pnl"] > t["stress_risk_usdt"]+1e-9 for t in bundle["trades"]))
        name = f"{profile}_{mode}_capital{capital}_{scenario}"
        (args.output/(name+".json")).write_text(json.dumps(bundle, allow_nan=False)+"\n")
        runs.append(summary)
    raw = {"long": 0, "short": 0, "short_strict": 0}
    for now in range(timestamp("2026-07-30"), timestamp("2026-10-15"), 3600):
        clock = session(now)
        if clock is None or clock[1] != 600:
            continue
        for rows in features.values():
            f = feature_at(rows, now)
            for key, flag in (("long", "entry_tactical"), ("short", "entry_short_tactical"), ("short_strict", "entry_short")):
                raw[key] += bool(f[flag])
    assumptions = [
        "Same consumed2026-07-30..2026-10-15 exclusive cache, signal timing and fees; no new data or independent OOS claim.",
        "All directions share ONE single-position capital book; virtual :SHORT keys are diagnostics, not exchange symbols.",
        "Long rules unchanged. Tactical shorts use mirrored31-day profile state, price<EMA20<EMA50 and negative20-day return; equity shorts require SPY<EMA20 and negative20-day return.",
        "Slow short control instead requires own price<EMA200,EMA50<EMA200,negative63-day return and matching SPY bear gate.",
        "Short signals use downward20-day breakdown/failedEMA20 bounce or upper-Bollinger red reclaim; state/ER rules mirror longs.",
        "wide profiles scale state gross and volatility targets by20/3; they are higher risk assumptions, not increased signal confidence.",
        "50x exchange setting and20x gross are REQUESTED SIMULATION CAPS, not verified exchange/account permissions; actual leverage is reduced by liquidation-distance/margin/risk constraints.",
        "Daily2ATR stops and1% gap reserve unchanged. attack50 reduces liquidation-stop cushion3 to1.25; all profiles retain stops, margin/lot/cost limits and liquidation proxy HALT.",
        "Directional regular funding debits use fixed debit_stress forecast; actual signed special dividend funding is charged, but future dividend events lack PIT reserve/eligibility forecasts.",
        "Double-cost reruns double fee/slip/adverse ordinary funding per held side; fixed-fill accounting separately freezes quantities and exit clocks, without claiming later orders remain affordable.",
        "1% maintenance/fee buffer/current filters/hourly stop-fill sequencing remain proxies; high-leverage liquidation PnL is not account-bracket certification.",
        "100USDT is a virtual scale control; no deposits, resets, services, private API calls or live orders.",
    ]
    sources += contract_sources
    code = [Path(__file__), Path("src/qount/research/binance_macro_attack.py"),
            Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"), Path("src/qount/research/engine/perpetual.py"),
            Path("src/qount/research/binance_macro_opportunities.py"), Path("src/qount/research_data/bars.py")]
    result = dict(start="2026-07-30", end_exclusive="2026-10-15", profiles=PROFILES, raw_candidates=raw,
                  runs=runs, assumptions=assumptions, sources=sources,
                  code_sources=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in code],
                  research_only=True, orders_authorized=False, independent_oos=False)
    (args.output/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    lines = ["# Small-account leverage and direction experiment", "", "2026-07-30 to2026-10-15 exclusive; consumed history.", "",
             "|Profile|Direction|Capital|Scenario|Net return|MDD|Trades|Short trades|Max entry gross|Max setting|Fixed-fill double cost|HALT|",
             "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in runs:
        fixed_label = f"{r['fixed_fill_double_cost_return']:.2%}" if "fixed_fill_double_cost_return" in r else "n/a"
        lines.append(f"|{r['profile']}|{r['direction']}|{r['initial_equity']:g}|{r['scenario']}|{r['net_return']:.2%}|{r['max_drawdown']:.2%}|{r['trade_count']}|{r['short_trades']}|{r['maximum_entry_gross']:.2f}|{r['maximum_entry_leverage']}|{fixed_label}|{r['halt'] or 'none'}|")
    lines += ["", "## Assumptions", ""]+["- "+x for x in assumptions]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output), runs=len(runs), raw_candidates=raw)))


if __name__ == "__main__":
    main()
