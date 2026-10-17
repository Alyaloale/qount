"""Fixed SPY/QQQ small-account leverage experiment; no private APIs or orders."""
import argparse
import datetime as dt
import hashlib
import itertools
import json
from pathlib import Path

from qount.research.binance_etf_leverage import equity_features, load_inputs, replay
from qount.research_data.archives import timestamp


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_etf_leverage_20261015"))
    p.add_argument("--equity-data", type=Path, default=Path("state/research_cache/etf_trader_p2"))
    p.add_argument("--start", default="2026-04-07")
    p.add_argument("--end-exclusive", default="2026-10-02")
    p.add_argument("--capital", type=float, default=10)
    p.add_argument("--download", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_results")
    if args.capital <= 0 or timestamp(args.start) >= timestamp(args.end_exclusive):
        raise ValueError("invalid_experiment_range_or_capital")
    features, sources = equity_features(args.equity_data)
    if any(rows[-1]["date"] < (dt.date.fromisoformat(args.end_exclusive)-dt.timedelta(days=1)).isoformat()
           for rows in features.values()):
        raise ValueError("equity_source_does_not_cover_end")
    data, public_sources = load_inputs(args.cache, timestamp(args.start), timestamp(args.end_exclusive), args.download)
    args.output.mkdir(parents=True)
    assumptions = [
        "Consumed-history exploration, not independent OOS; parameters not optimized on this run.",
        "10:00 America/New_York decisions use strictly earlier ETF adjusted closes; no incomplete daily candle.",
        "Primary momentum120: positive 120-session return and above SMA120, SPY gate, choose strongest eligible ETF.",
        "No ranking replacement while holding; trend-off at10:00 ET; hard expiry exactly168h even on a holiday.",
        "Stop 2x prior-completed UTC contract-day Wilder ATR14; 2R activates 2ATR trailing effective next hour.",
        "Pressure sizing includes 1% stop gap, ordinary costs, seven-day funding reserve from past72h regular rates.",
        "Funding interval forecast reuses prior regular settlement gap with8h fallback; not PIT-certified interval snapshots.",
        "Separate gross caps1/2/2.5/3x and account risk budgets3%/6%; isolated setting<=5x, margin<=80%.",
        "Fee5bp and slippage5bp each side are assumptions; double_cost doubles those and regular funding debits, not dividend cashflows.",
        "Current filters applied historically; historical account brackets/fees/order books not authenticated.",
        "1% maintenance margin and isolated liquidation formula are research proxies, not actual liquidation certification.",
        "Hourly OHLC cannot identify intrabar stop/funding order; adverse funding charged and favorable credit omitted in stop hours.",
        "20% high-water drawdown HALT, no automatic reset, cash yield0; transfers absent.",
        "First entry needs14 complete UTC contract days; baselines share warmup, clock and20% HALT.",
        "Historical ETF adjusted closes are current-vintage total-return proxies, not PIT-certified revisions.",
        "Hourly close MDD and an intrahour bound are reported separately; stop fills and native protection unverified.",
        "The same fee/slippage assumption applies to all-hour stops/expiry; off-session historical spread is unknown.",
    ]
    runs = []
    for scenario in ("base", "double_cost", "gap_2pct"):
        for gross, risk in itertools.product((1.0, 2.0, 2.5, 3.0), (0.03, 0.06)):
            # Double ordinary adverse funding only; retain special dividend events.
            if scenario == "double_cost":
                adjusted = {s: {**d, "funding": [{**r, "fundingRate": str(float(r["fundingRate"])*2)
                             if r.get("rateType", "Regular") == "Regular" and float(r["fundingRate"]) > 0
                             else r["fundingRate"]} for r in d["funding"]]} for s, d in data.items()}
            else:
                adjusted = data
            bundle = replay(adjusted, features, gross_cap=gross, risk_fraction=risk,
                            fee=0.001 if scenario == "double_cost" else 0.0005,
                            slip=0.001 if scenario == "double_cost" else 0.0005,
                            stop_gap=0.02 if scenario == "gap_2pct" else 0, capital=args.capital)
            name = f"momentum120_g{gross:g}_r{risk:g}_{scenario}"
            bundle["summary"].update(name=name, scenario=scenario)
            (args.output/(name+".json")).write_text(json.dumps(bundle, allow_nan=False)+"\n")
            runs.append(bundle["summary"])
    for symbol, gross, scenario in itertools.product(("SPYUSDT", "QQQUSDT"),
                                                    (1.0, 2.0, 2.5, 3.0), ("base", "double_cost")):
        adjusted = data
        if scenario == "double_cost":
            adjusted = {s: {**d, "funding": [{**r, "fundingRate": str(float(r["fundingRate"])*2)
                        if r.get("rateType", "Regular") == "Regular" and float(r["fundingRate"]) > 0
                        else r["fundingRate"]} for r in d["funding"]]} for s, d in data.items()}
        bundle = replay(adjusted, features, strategy="hold", hold_symbol=symbol, gross_cap=gross,
                        fee=0.001 if scenario == "double_cost" else 0.0005,
                        slip=0.001 if scenario == "double_cost" else 0.0005, capital=args.capital)
        name = f"hold_{symbol}_g{gross:g}_{scenario}"
        bundle["summary"].update(name=name, scenario=scenario)
        (args.output/(name+".json")).write_text(json.dumps(bundle, allow_nan=False)+"\n")
        runs.append(bundle["summary"])
    code_sources = [{"path": str(pth), "sha256": hashlib.sha256(pth.read_bytes()).hexdigest()}
                    for pth in (Path(__file__), Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"),
                                Path("src/qount/research/engine/perpetual.py"),
                                Path("src/qount/research_data/bars.py"))]
    result = {"start": args.start, "end_exclusive": args.end_exclusive, "capital": args.capital,
              "hypothesis": "ETF momentum retains net value on actual perpetual prices; leverage benefit survives risk and costs.",
              "assumptions": assumptions, "sources": sources+public_sources, "code_sources": code_sources, "runs": runs,
              "research_only": True, "orders_authorized": False, "independent_oos": False}
    (args.output/"summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    report = ["# SPY/QQQ 10 USDT leverage experiment", "", f"Window {args.start} to {args.end_exclusive} exclusive; research only.",
              "", "|Strategy|Gross cap|Risk budget|Scenario|Net return|MDD|Trades|Max actual gross|HALT|",
              "|---|---:|---:|---|---:|---:|---:|---:|---|"]
    for r in runs:
        risk = f"{r['risk_fraction']:.0%}" if r["risk_fraction"] is not None else "—"
        report.append(f"|{r['strategy']}|{r['gross_cap']:g}|{risk}|{r['scenario']}|{r['net_return']:.2%}|{r['max_drawdown']:.2%}|{r['trade_count']}|{r['maximum_observed_gross']:.2f}|{r['halt'] or 'none'}|")
    report += ["", "## Assumptions", ""] + ["- "+a for a in assumptions]
    (args.output/"report.md").write_text("\n".join(report)+"\n")
    print(json.dumps({"output": str(args.output), "runs": len(runs), "public_sources": len(public_sources)}))


if __name__ == "__main__":
    main()
