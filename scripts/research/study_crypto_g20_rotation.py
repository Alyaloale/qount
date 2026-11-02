"""Bounded G20-inspired full-wallet crypto rotation experiment, no orders."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import numpy as np

from study_independent_crypto_factors import load_panel, SYMBOLS, DAY
from qount.research.crypto_g20_rotation import Rule, features, replay


def load(path, mark_path):
    panel = load_panel(path)
    raw = json.loads(path.read_text())["data"]
    panel["symbols"] = SYMBOLS
    panel["high"] = np.array([[float(r[2]) for r in raw[s + "_klines"]] for s in SYMBOLS]).T
    panel["low"] = np.array([[float(r[3]) for r in raw[s + "_klines"]] for s in SYMBOLS]).T
    marks = json.loads(mark_path.read_text())["data"]
    lows, highs = [], []
    for s in SYMBOLS:
        rows = marks[s]
        assert [int(r[0]) for r in rows] == panel["times"].tolist(), "mark_calendar_mismatch"
        assert all(float(r[3]) <= min(float(r[1]), float(r[4])) <= float(r[2]) for r in rows)
        lows.append([float(r[3]) for r in rows])
        highs.append([float(r[2]) for r in rows])
    panel["mark_low"] = np.asarray(lows).T
    panel["mark_high"] = np.asarray(highs).T
    debit = np.zeros_like(panel["funding_value"])
    credit = np.zeros_like(debit)
    for j, s in enumerate(SYMBOLS):
        for r in raw[s + "_funding"]:
            stamp = int(r["fundingTime"])
            k = int(np.searchsorted(panel["times"], stamp, side="left") - 1)
            if 0 <= k < len(debit) - 1:
                d = int((stamp - panel["times"][0]) // DAY)
                mark = float(r["markPrice"]) if r.get("markPrice") else panel["open"][d, j]
                debit[k, j] += max(0., float(r["fundingRate"])) * mark
                credit[k, j] += max(0., -float(r["fundingRate"])) * mark
    panel["funding_debit"] = debit
    panel["funding_credit"] = credit
    return panel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json"))
    parser.add_argument("--mark-input", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/mark_daily.json"))
    parser.add_argument("--filters", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/exchange_filters.json"))
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/crypto_g20_rotation_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    panel = load(args.input, args.mark_input)
    f = features(panel)
    filters_raw = json.loads(args.filters.read_text())
    filters = {r["symbol"]: r for r in filters_raw["symbols"]}
    # Rules declared before evaluating this experiment. All history is consumed,
    # so chronological windows are diagnostics, never independent OOS claims.
    rules = {"monthly_raw_1x": Rule(cadence="monthly", trend=False, gross=1),
             "weekly_raw_1x": Rule(trend=False, gross=1),
             "weekly_trend_1x": Rule(gross=1),
             "weekly_trend_3x": Rule(gross=3),
             "weekly_trend_5x": Rule(gross=5),
             "weekly_trend_10x": Rule(gross=10),
             "weekly_trend_3x_stop": Rule(gross=3, stop_atr=3),
             "weekly_trend_5x_stop": Rule(gross=5, stop_atr=3),
             "weekly_trend_10x_stop": Rule(gross=10, stop_atr=3),
             "weekly_vol200_cap5_stop": Rule(gross=5, volatility_target=2., stop_atr=3),
             "weekly_fast_long3_stop": Rule(lookback=21, gross=3, stop_atr=1.5, risk_adjusted_rank=True),
             "weekly_fast_both3_stop": Rule(lookback=21, gross=3, stop_atr=1.5, risk_adjusted_rank=True, direction="both"),
             "weekly_fast_both5_stop": Rule(lookback=21, gross=5, stop_atr=1.5, risk_adjusted_rank=True, direction="both")}
    windows = {"2021_2023": ("2021-05-03", "2024-01-01"),
               "2024": ("2024-01-01", "2025-01-01"),
               "2025": ("2025-01-01", "2026-01-01"),
               "2026": ("2026-01-01", "2026-10-26"),
               "2024_2026": ("2024-01-01", "2026-10-26"),
               "2025_2026": ("2025-01-01", "2026-10-26")}
    results, curves = {}, {}
    for name, rule in rules.items():
        results[name] = {}
        for window, (start, end) in windows.items():
            run = replay(panel, f, rule, start=start, end=end, capital=1000)
            results[name][window] = run["summary"]
            if window == "2024_2026":
                curves[name] = run
    # Separate current-filter application from friction-only signal economics.
    small, stresses = {}, {}
    for name in ("monthly_raw_1x", "weekly_raw_1x", "weekly_trend_1x", "weekly_trend_3x",
                 "weekly_trend_3x_stop", "weekly_trend_5x_stop", "weekly_vol200_cap5_stop",
                 "weekly_fast_long3_stop", "weekly_fast_both3_stop", "weekly_fast_both5_stop"):
        rule = rules[name]
        small[name] = {}
        for capital in (21.25, 100., 1000.):
            small[name][str(capital)] = {}
            for window in ("2024", "2025", "2026", "2024_2026", "2025_2026"):
                start, end = windows[window]
                small[name][str(capital)][window] = replay(panel, f, rule,
                    start=start, end=end, capital=capital, filters=filters)["summary"]
        stresses[name] = {}
        for label, changed, cost, path in (
            ("cost30bp", rule, 30, "liquidation_first"),
            ("extra_day_delay", replace(rule, delay=3), 10, "liquidation_first"),
            ("stop_first_bound", rule, 10, "stop_first"),
            ("lookback42", replace(rule, lookback=42), 10, "liquidation_first"),
            ("lookback84", replace(rule, lookback=84), 10, "liquidation_first")):
            stresses[name][label] = replay(panel, f, changed,
                start="2024-01-01", end="2026-10-26", capital=1000,
                cost_bp=cost, ambiguous_path=path)["summary"]
    # BTC buy-and-hold is an additional long-only funding-inclusive control.
    # A fixed-quantity 1x BTC account does not need a rotation rule.
    benchmarks = {}
    for name, (start, end) in windows.items():
        a = int(np.flatnonzero(panel["dates"] >= start)[0])
        b = min(int(np.flatnonzero(panel["dates"] < end)[-1]) + 1, len(panel["dates"]) - 1)
        price = panel["open"][a, 0]
        q = 1000 / (price * 1.001)
        nav = [1.]
        equity = 1000 - q * price * .001
        for t in range(a, b):
            equity += q * (panel["open"][t+1, 0] - panel["open"][t, 0] - panel["funding_value"][t, 0])
            nav.append(equity / 1000)
        equity -= q * panel["open"][b, 0] * .001
        nav[-1] = equity / 1000
        nav = np.asarray(nav)
        benchmarks[name] = dict(return_pct=(equity/1000-1)*100,
            cagr_pct=((equity/1000)**(365.25/(b-a))-1)*100,
            mdd_pct=float(np.max(1-nav/np.maximum.accumulate(nav))*100))
    payload = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="G20-style winner rotation, full account available, fixed actual exposure versus trend/stop/volatility controls.",
        universe=SYMBOLS, bar_count=len(panel["times"]), first_bar=str(panel["dates"][0]),
        last_bar=str(panel["dates"][-1]), source_hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (args.input, args.mark_input, args.filters)},
        filters_observed_at=filters_raw["observed_at"], rules={n: asdict(r) for n,r in rules.items()},
        windows=windows, costs_one_way_bp=10, cash_interest=0,
        liquidation_assumptions=dict(maintenance_fraction=.005, fee_fraction=.01,
                                    collateral="whole wallet", default_path="liquidation_first"),
        funding_approximate_marks=panel["approximate_marks"],
        limitations=["Seven surviving contracts selected retrospectively; not a PIT whole-market universe.",
            "Before 2024 missing funding marks use daily trade open; 2024+ settlement marks complete.",
            "Current minimum quantities/notionals applied retrospectively only in small-account scenarios.",
            "Liquidation uses actual daily mark lows, fixed maintenance and full-wallet collateral proxy; no historical tiers, intraday funding or liquidation matching reconstruction.",
            "Stops use trade OHLC, extra execution cost, and pessimistic funding debit; daily order ambiguity has a stop-first bound.",
            "Per-day mark-low drawdown bound does not include intraday high-water marks or certify fills.",
            "Existing history consumed by prior research; no untouched holdout or live profitability claim."],
        results=results, small_accounts=small, stresses=stresses, btc_hold_control=benchmarks)
    (args.output/"results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    (args.output/"curves.json").write_text(json.dumps(curves, ensure_ascii=False, allow_nan=False)+"\n")
    for name in rules:
        a=results[name]
        print(name, {y: round(a[y]["return_pct"], 2) for y in ("2024", "2025", "2026")},
              "recent CAGR/MDD", round(a["2024_2026"]["cagr_pct"],2), round(a["2024_2026"]["mdd_pct"],2),
              a["2024_2026"]["counts"])


if __name__ == "__main__":
    main()
