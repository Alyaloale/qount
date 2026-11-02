"""Daily G20 low-leverage sizing/exit mechanism comparison; research only."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import numpy as np

from study_crypto_g20_rotation import load
from qount.research.crypto_g20_rotation import Rule, features, replay


def paired_log_growth(curves, candidate, control, scenario):
    a = curves[candidate + ":" + scenario]["curve"]
    b = curves[control + ":" + scenario]["curve"]
    assert [r["date"] for r in a] == [r["date"] for r in b]
    delta = np.log1p([r["returns"] for r in a]) - np.log1p([r["returns"] for r in b])
    rng = np.random.default_rng(20)
    ci = {}
    for block in (30, 90):
        starts = rng.integers(0, len(delta), (4000, (len(delta) + block - 1) // block))
        ix = ((starts[..., None] + np.arange(block)) % len(delta)).reshape(4000, -1)[:, :len(delta)]
        ci[str(block)] = (np.quantile(delta[ix].mean(axis=1) * 365.25 * 100, [.025, .975])).tolist()
    return dict(annual_log_growth_difference_pct=float(delta.mean() * 365.25 * 100),
                moving_block95_pct=ci, samples=4000, seed=20,
                note="Paired account comparison includes exposure, timing, selection and rounding; not an alpha estimate. Post-selection, unadjusted intervals.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json"))
    parser.add_argument("--mark-input", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/mark_daily.json"))
    parser.add_argument("--filters", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/exchange_filters.json"))
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/crypto_g20_daily_low_leverage_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    p = load(args.input, args.mark_input)
    f = features(p)
    filters = {r["symbol"]: r for r in json.loads(args.filters.read_text())["symbols"]}
    # Fixed mechanism contrasts: not a leverage / ATR / vol-target grid.
    rules = {"weekly_1x": Rule(gross=1),
             "weekly_1p5x": Rule(gross=1.5),
             "weekly_2x": Rule(gross=2),
             "daily_1x": Rule(cadence="daily", gross=1),
             "daily_1p5x": Rule(cadence="daily", gross=1.5),
             "daily_2x": Rule(cadence="daily", gross=2),
             "daily_vol60_cap2": Rule(cadence="daily", gross=2, volatility_target=.6),
             "daily_vol60_cap2_stop3": Rule(cadence="daily", gross=2, volatility_target=.6, stop_atr=3),
             "weekly_vol60_cap2_stop3": Rule(gross=2, volatility_target=.6, stop_atr=3),
             # Added after the first nine contrasts showed persistent deep
             # drawdowns. Explicit post-result mechanism experiment, not OOS.
             "daily_vol60_cap2_btc": Rule(cadence="daily", gross=2, volatility_target=.6, market_trend=True),
             "daily_vol60_cap2_stop3_btc": Rule(cadence="daily", gross=2, volatility_target=.6, stop_atr=3, market_trend=True),
             "weekly_vol60_cap2_stop3_btc": Rule(gross=2, volatility_target=.6, stop_atr=3, market_trend=True)}
    windows = {"2021_2023": ("2021-05-03", "2024-01-01"),
               "2024": ("2024-01-01", "2025-01-01"),
               "2025": ("2025-01-01", "2026-01-01"),
               "2026": ("2026-01-01", "2026-10-26"),
               "2024_2026": ("2024-01-01", "2026-10-26")}
    scenarios = {"small21": dict(capital=21.25, filters=filters),
                 "small21_cost30": dict(capital=21.25, filters=filters, cost_bp=30),
                 "small21_delay3": dict(capital=21.25, filters=filters),
                 "unit1000": dict(capital=1000, filters=None)}
    results, curves = {}, {}
    for name, rule in rules.items():
        results[name] = {}
        for label, (start, end) in windows.items():
            results[name][label] = {}
            for scenario, kw in scenarios.items():
                r = replace(rule, delay=3) if scenario == "small21_delay3" else rule
                run = replay(p, f, r, start=start, end=end, **kw)
                results[name][label][scenario] = run["summary"]
                if label == "2024_2026":
                    curves[name + ":" + scenario] = run
        print(name, {w: round(results[name][w]["small21"]["return_pct"], 2)
                     for w in ("2021_2023", "2024", "2025", "2026")},
              "recent cagr/mdd", round(results[name]["2024_2026"]["small21"]["cagr_pct"], 2),
              round(results[name]["2024_2026"]["small21"]["mdd_pct"], 2), flush=True)
    old = json.loads(Path("state/research_runs/crypto_g20_rotation_20261102/results.json").read_text())
    control_count = 0
    for w in windows:
        if w in old["small_accounts"]["weekly_trend_1x"]["21.25"]:
            assert results["weekly_1x"][w]["small21"] == old["small_accounts"]["weekly_trend_1x"]["21.25"][w]
            control_count += 1
        assert results["weekly_1x"][w]["unit1000"] == old["results"]["weekly_trend_1x"][w]
        control_count += 1
    payload = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Can small actual leverage, daily rotation and volatility sizing improve G20's net growth/drawdown without multiplying the prior losses?",
        universe=p["symbols"], rules={k: asdict(v) for k, v in rules.items()}, windows=windows,
        base_cost_one_way_bp=10, stress_cost_one_way_bp=30, cash_interest=0,
        volatility="Trailing 30 daily log-return sample standard deviation * sqrt(365.25); fixed 60% annual target.",
        actual_gross="Position notional / total wallet equity. Target <=2 at rebalance, not a continuously enforced intraday cap.",
        stop="3 ATR14 simple average, updated from delayed available close; trade OHLC trigger, gap fill and costs included.",
        execution="Signal d close, wait full next day, execute d+2 open. Extra-day stress d+3. Existing trends checked daily for every cadence.",
        market_gate="BTC close > MA120 and 63-day momentum >0; when off, exit held coin at the same delayed daily execution, even for weekly selection.",
        current_filters_observed_at=json.loads(args.filters.read_text())["observed_at"],
        prior_control_summaries_exact=control_count,
        source_hashes={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (args.input, args.mark_input, args.filters)}, results=results,
        paired_log_growth={control + ":" + scenario: paired_log_growth(curves,
            "daily_vol60_cap2_btc", control, scenario)
            for control in ("daily_vol60_cap2", "weekly_1x") for scenario in ("small21", "unit1000")},
        limitations=["Nine initial mechanism configurations, then three BTC-gate ablations after observing deep drawdowns; all on consumed history, no independent OOS or optimized target claim.",
            "Seven surviving contracts chosen retrospectively; current quantity/minimum filters applied historically.",
            "Daily stop/liquidation ordering pessimistic, fixed 0.5% maintenance and 1% liquidation fee; not exact historical venue reconstruction.",
            "Drawdown is open-to-open. Intraday bound uses adverse mark extreme against previous open highwater, not complete intraday MDD.",
            "Daily decisions may trade each day; skipped subminimum delta orders can make small accounts materially different from continuous units.",
            "More favorable 2021-2023 tests retain pre-2024 approximate funding marks. Annual books restart and cannot be multiplied to rebuild the continuous book."])
    (args.output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (args.output / "curves.json").write_text(json.dumps(curves, ensure_ascii=False, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
