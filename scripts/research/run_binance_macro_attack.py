"""Aggressive independent macro-perpetual experiment; no accounts or orders."""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

from qount.research.binance_etf_leverage import FUNDING_POLICIES, load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, MACRO_TEN, macro_features
from qount.research_data.archives import timestamp


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015"))
    p.add_argument("--start", default="2026-07-30")
    p.add_argument("--end-exclusive", default="2026-10-15")
    p.add_argument("--capital", nargs="+", type=float, default=[10, 100])
    p.add_argument("--policies", nargs="+", choices=("macro_core", "macro_tactical", "macro_hybrid"),
                   default=["macro_core", "macro_tactical", "macro_hybrid"])
    p.add_argument("--gross-caps", nargs="+", type=float, default=[1.0, 3.0])
    p.add_argument("--risk-fractions", nargs="+", type=float, default=[0.08])
    p.add_argument("--drawdown-policies", nargs="+", choices=("original", "full_loss_experiment"),
                   default=["original"])
    p.add_argument("--skip-hold-controls", action="store_true")
    p.add_argument("--funding-policies", nargs="+", choices=FUNDING_POLICIES, default=["absolute_peak"])
    p.add_argument("--download", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError("refuse_overwrite_results")
    if (any(not math.isfinite(c) or c <= 0 for c in a.capital)
            or any(not math.isfinite(r) or not 0 < r <= 1 for r in a.risk_fractions)
            or any(not math.isfinite(g) or not 0 < g <= 3 for g in a.gross_caps)
            or timestamp(a.start) >= timestamp(a.end_exclusive)):
        raise ValueError("invalid_capital_or_dates")
    features, equity_sources = macro_features(a.cache, a.end_exclusive, a.download)
    data, contract_sources = load_inputs(a.cache, timestamp(a.start), timestamp(a.end_exclusive), a.download,
                                        symbols=tuple(CONTRACT_SIGNALS))
    a.output.mkdir(parents=True)
    policies = a.policies
    assumptions = [
        "Independent new candidate; frozen Universal v1.3 and G20/C60/GC5/D15 paper contracts are untouched.",
        "Research-only consumed-history discovery, no OOS or new-listing-alpha claim; no return-target tuning.",
        "Ten macro ETF signals plusQQQ/XLE/USO; only8 listed contracts execute. XLI/XLB/XLU/TLT/UUP have no direct execution mapping.",
        "GLD->XAU, CPER->COPPER, USO->CL are economic proxy signals, not identical underlyings or inherited ETF returns.",
        "G20-inspired core: positive63-session momentum, ownEMA200/EMA50/EMA20 gates, Top1; at most1 core entry per calendar month.",
        "Universal-inspired tactical: causal profile states,20-session breakout/pullback or green lower-Bollinger reclaim; ER0.28 for trend.",
        "Hybrid gives an executable monthly core opportunity priority; otherwise tactical; one shared book, max1 position at10USD.",
        "This is mechanism adaptation, not the original GC5/D15 weights or a replica of the original engines.",
        "C60-inspired target60% annual vol cap; strong trend nominal cap3x, mixed1.5x, MR1x; actual sizing remains risk constrained.",
        "Entry pressure risk and drawdown policy are explicit run parameters; no resets or deposits.",
        "original: new-entry risk/gross halves below90% NAV high and20% drawdown HALT; full_loss_experiment removes these account DD controls only.",
        "full_loss_experiment retains per-position stops, state/time exits, liquidation proxy HALT, margin/liquidity/lot/cost constraints; it can lose the experimental capital.",
        "Core holds at most720h, tactical168h, own state-off exits at10:00 ET; no repeated forced7-day core rebuilding.",
        "Native contract ATR14 initial stop2ATR; all funding policies use only past72h regular settlements and retain the full maximum holding horizon.",
        "absolute_peak reserves absolute peak rate; debit_peak reserves positive peak only for this long-only engine.",
        "debit_stress takes max(twice72h debit intensity times full horizon,24h positive peak shock,1bp/day floor); fixed exploratory assumptions, not fitted coverage.",
        "Stops/trailing, hourly marks, signed actual regular+special funding and size rounding reuse the ETF leverage engine.",
        "Base fee5bp and slip5bp each side; double_cost doubles these and regular funding debits, never dividend credits.",
        "Current filters and1% maintenance margin/<=5x isolated setting are proxies, not historical/account bracket certification.",
        "Hourly OHLC cannot recover stop/funding order or native-stop reliability; off-session fill costs and historical books unknown.",
        "Yahoo adjusted OHLC are current-vintage proxies, not PIT-certified revisions; features available after16:00 New York.",
        "Study starts after latest included contract listing; ATR warmup delays first possible trading by14 complete UTC days.",
        "If included,100USD is a virtual scale control for minimum lots, not an authorized capital increase; cash yield0.",
        "Short sample net returns are not annualized. Multiple arms are correlated, not independent confirmations.",
    ]
    runs = []
    for policy, cap, capital, risk, dd_policy, funding_policy, scenario in itertools.product(policies, a.gross_caps, a.capital,
                                                           a.risk_fractions, a.drawdown_policies, a.funding_policies,
                                                           ("base", "double_cost", "gap_2pct")):
        adjusted = data
        if scenario == "double_cost":
            adjusted = {s: {**d, "funding": [{**r, "fundingRate": str(float(r["fundingRate"])*2)
                        if r.get("rateType", "Regular") == "Regular" and float(r["fundingRate"]) > 0
                        else r["fundingRate"]} for r in d["funding"]]} for s, d in data.items()}
        bundle = replay(adjusted, features, strategy=policy, gross_cap=cap, risk_fraction=risk,
                        account_controls=dd_policy == "original",
                        funding_policy=funding_policy,
                        capital=capital, fee=0.001 if scenario == "double_cost" else 0.0005,
                        slip=0.001 if scenario == "double_cost" else 0.0005,
                        stop_gap=0.02 if scenario == "gap_2pct" else 0, max_hold_hours=720)
        name = f"{policy}_g{cap:g}_capital{capital:g}_{scenario}"
        if risk != 0.08 or dd_policy != "original":
            name += f"_risk{risk:g}_{dd_policy}"
        if funding_policy != "absolute_peak":
            name += "_funding_"+funding_policy
        bundle["summary"].update(name=name, scenario=scenario, drawdown_policy=dd_policy,
                                 funding_policy=funding_policy)
        (a.output/(name+".json")).write_text(json.dumps(bundle, allow_nan=False)+"\n")
        runs.append(bundle["summary"])
    # Matched market-beta controls: same window, warmup, cost and account HALT.
    for symbol, cap, scenario in itertools.product(() if a.skip_hold_controls else ("SPYUSDT", "QQQUSDT"), (1.0, 3.0),
                                                   ("base", "double_cost")):
        adjusted = data
        if scenario == "double_cost":
            adjusted = {s: {**d, "funding": [{**r, "fundingRate": str(float(r["fundingRate"])*2)
                        if r.get("rateType", "Regular") == "Regular" and float(r["fundingRate"]) > 0
                        else r["fundingRate"]} for r in d["funding"]]} for s, d in data.items()}
        bundle = replay(adjusted, features, strategy="hold", hold_symbol=symbol, gross_cap=cap, capital=10,
                        fee=0.001 if scenario == "double_cost" else 0.0005,
                        slip=0.001 if scenario == "double_cost" else 0.0005)
        name = f"hold_{symbol}_g{cap:g}_capital10_{scenario}"
        bundle["summary"].update(name=name, scenario=scenario)
        (a.output/(name+".json")).write_text(json.dumps(bundle, allow_nan=False)+"\n")
        runs.append(bundle["summary"])
    sources = equity_sources+contract_sources
    code_sources = [{"path": str(f), "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for f in (
        Path(__file__), Path("src/qount/research/binance_macro_attack.py"),
        Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"), Path("src/qount/research/engine/perpetual.py"),
        Path("src/qount/research_data/bars.py"), Path("src/qount/research_data/regime.py"))]
    result = {"start": a.start, "end_exclusive": a.end_exclusive, "hypothesis":
              "Compare state-dependent leverage, entry risk and account drawdown rules on net growth; report all arms without selecting by consumed-history returns.",
              "macro_signal_universe": MACRO_TEN, "execution_mapping": CONTRACT_SIGNALS,
              "verdict": "Research candidate only; inspect net growth, costs, attribution and scale controls before promotion.",
              "parameters": {"policies": policies, "gross_caps": a.gross_caps, "capital": a.capital,
                             "risk_fractions": a.risk_fractions, "drawdown_policies": a.drawdown_policies,
                             "funding_policies": a.funding_policies},
              "assumptions": assumptions, "sources": sources, "code_sources": code_sources, "runs": runs,
              "research_only": True, "orders_authorized": False, "independent_oos": False}
    (a.output/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    report = ["# Independent aggressive macro leverage candidate", "", f"Window {a.start} to {a.end_exclusive} exclusive.",
              "", "|Policy|Capital|Gross cap|Risk budget|DD policy|Funding reserve|Scenario|Net return|MDD|Trades|Max actual gross|HALT|",
              "|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---|"]
    for r in runs:
        risk_label = f"{r['risk_fraction']:.0%}" if r["risk_fraction"] is not None else "n/a"
        report.append(f"|{r['strategy']}|{r['initial_equity']:g}|{r['gross_cap']:g}|{risk_label}|{r.get('drawdown_policy', 'original')}|{r.get('funding_policy', 'absolute_peak')}|{r['scenario']}|{r['net_return']:.2%}|{r['max_drawdown']:.2%}|{r['trade_count']}|{r['maximum_observed_gross']:.2f}|{r['halt'] or 'none'}|")
    report += ["", "## Assumptions", ""]+["- "+s for s in assumptions]
    (a.output/"report.md").write_text("\n".join(report)+"\n")
    print(json.dumps({"output": str(a.output), "runs": len(runs), "source_files": len(sources)}))


if __name__ == "__main__":
    main()
