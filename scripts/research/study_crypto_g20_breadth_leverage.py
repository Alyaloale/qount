"""Test a trend-breadth leverage overlay for small-account daily G20."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from study_crypto_g20_rotation import load
from qount.research.crypto_g20_rotation import Rule, features, replay


WINDOWS = {
    "2021_2023": ("2021-05-03", "2024-01-01"),
    "2024": ("2024-01-01", "2025-01-01"),
    "2025": ("2025-01-01", "2026-01-01"),
    "2026": ("2026-01-01", "2026-10-26"),
    "2024_2026": ("2024-01-01", "2026-10-26"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json"))
    parser.add_argument("--mark-input", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/mark_daily.json"))
    parser.add_argument("--filters", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/exchange_filters.json"))
    parser.add_argument("--prior-results", type=Path, default=Path("state/research_runs/crypto_g20_daily_low_leverage_20261102/results.json"))
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/crypto_g20_breadth_leverage_20261102"))
    parser.add_argument("--capital", type=float, default=21.25)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    panel = load(args.input, args.mark_input)
    f = features(panel)
    filter_data = json.loads(args.filters.read_text())
    filters = {row["symbol"]: row for row in filter_data["symbols"]}
    rules = {
        "current_budget": Rule(cadence="daily", gross=2, volatility_target=.6, market_trend=True),
        "high_budget_always": Rule(cadence="daily", gross=3, volatility_target=1.5, market_trend=True),
        "high_budget_breadth_5_of_7": Rule(
            cadence="daily", gross=2, volatility_target=.6, market_trend=True,
            risk_on_breadth=5 / 7, risk_on_gross=3, risk_on_volatility_target=1.5),
        "high_budget_only_at_breadth_5_of_7": Rule(
            cadence="daily", gross=3, volatility_target=1.5, market_trend=True,
            risk_off_breadth=5 / 7),
    }
    scenarios = {
        "base_cost": dict(cost_bp=10, delay=2),
        "high_cost": dict(cost_bp=30, delay=2),
        "one_more_day": dict(cost_bp=10, delay=3),
    }
    results = {}
    for name, rule in rules.items():
        results[name] = {}
        for window, (start, end) in WINDOWS.items():
            results[name][window] = {}
            for scenario, config in scenarios.items():
                changed = replace(rule, delay=config["delay"])
                run = replay(panel, f, changed, start=start, end=end,
                    capital=args.capital, filters=filters, cost_bp=config["cost_bp"])
                results[name][window][scenario] = run["summary"]
                if window == "2024_2026" and scenario == "base_cost":
                    results.setdefault("curves", {})[name] = run
            base = results[name][window]["base_cost"]
            print(name, window, "final/CAGR/MDD/Calmar/mean-gross",
                  round(base["final_usdt"], 4), round(base["cagr_pct"], 2),
                  round(base["mdd_pct"], 2), round(base["calmar"], 3),
                  round(base["mean_gross"], 3), base["counts"], flush=True)

    prior = json.loads(args.prior_results.read_text())
    for window in WINDOWS:
        old = prior["results"]["daily_vol60_cap2_btc"][window]["small21"]
        current = results["current_budget"][window]["base_cost"]
        assert current == old, ("published_control_changed", window)
    for scenario, old_key in (("high_cost", "small21_cost30"), ("one_more_day", "small21_delay3")):
        for window in WINDOWS:
            old = prior["results"]["daily_vol60_cap2_btc"][window][old_key]
            current = results["current_budget"][window][scenario]
            assert current == old, ("published_stress_control_changed", scenario, window)

    payload = dict(
        research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Does cross-sectional trend breadth justify concentrating higher leverage in broad risk-on periods, improving the small account's net compounding versus using high risk budget continuously?",
        initial_capital_usdt=args.capital, universe=panel["symbols"],
        rules={name: asdict(rule) for name, rule in rules.items()}, windows=WINDOWS,
        risk_on_definition="At signal close, at least five of seven fixed contracts close above trailing SMA120 and have positive trailing 63-day momentum.",
        risk_budget_definition="Current budget is 60% annualized trailing 30-day volatility target capped at 2x. High budget is 150% target capped at 3x; overlay uses it only in breadth-confirmed periods.",
        breadth_cash_definition="The cash-only variant requires the same five-of-seven trend breadth as well as the BTC trend gate; otherwise it exits to cash.",
        costs_one_way_bp={"base_cost": 10, "high_cost": 30}, execution="signal d close; execute at d+2 open; delay stress executes at d+3 open",
        quantity_filters_observed_at=filter_data["observed_at"],
        published_baseline_summaries_exact=True,
        source_hashes={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in (args.input, args.mark_input, args.filters, args.prior_results)},
        results={key: value for key, value in results.items() if key != "curves"},
        limitations=[
            "All history has been consumed by prior research; windows are diagnostics, not independent OOS.",
            "Seven retrospectively selected surviving contracts and current quantity filters applied historically.",
            "High volatility target describes desired annualized exposure risk, not guaranteed leverage or return; mark gaps, quantity skips and liquidation can change realized exposure.",
            "Daily equity drawdown is open-to-open; liquidation uses fixed 0.5% maintenance and 1% fee approximation, not historical account tiers.",
            "No order-book, queue, latency, funding-tier or live execution validation; no production change or account query.",
        ],
    )
    (args.output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (args.output / "curves.json").write_text(json.dumps(results["curves"], ensure_ascii=False, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
