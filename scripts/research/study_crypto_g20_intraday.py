"""Hourly full-account rotation against daily-horizon G20 research.

Reuse continuous BTC/ETH/SOL futures caches, not event-selected candles.
Disjoint windows are evaluated separately and never joined into a fake NAV.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import numpy as np

from qount.research.crypto_g20_rotation import Rule, features, replay

HOUR = 3600000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
WINDOWS = {
    "2025q1": ("hourly_2025q1.json", "2025-01-01", "2025-04-01"),
    "2025q4": ("hourly_2025q4.json", "2025-10-01", "2026-01-01"),
    "2026tail": ("hourly.json", "2026-08-01", "2026-10-27"),
}


def load_hour_panel(path, mark_data, daily):
    raw = json.loads(path.read_text())["data"]
    bars = [np.asarray(raw[s + "_futures"], dtype=float) for s in SYMBOLS]
    times = bars[0][:, 0].astype(np.int64)
    for b in bars:
        assert np.array_equal(b[:, 0], times) and np.all(np.diff(times) == HOUR)
        assert np.all(b[:, 6] == times + HOUR - 1)
        assert np.all(np.isfinite(b)) and np.all(b[:, 1:5] > 0)
        assert np.all(b[:, 3] <= np.minimum(b[:, 1], b[:, 4]))
        assert np.all(b[:, 2] >= np.maximum(b[:, 1], b[:, 4]))
    marks = [np.asarray(mark_data[s], dtype=float) for s in SYMBOLS]
    for b in marks:
        assert np.array_equal(b[:, 0], times), "hourly_mark_calendar_mismatch"
        assert np.all(b[:, 3] <= np.minimum(b[:, 1], b[:, 4]))
        assert np.all(b[:, 2] >= np.maximum(b[:, 1], b[:, 4]))
    funding, debit, credit = (np.zeros((len(times), 3)) for _ in range(3))
    for j, s in enumerate(SYMBOLS):
        rows = daily[s + "_funding"]
        relevant = [r for r in rows if times[0] <= int(r["fundingTime"]) <= times[-1]]
        stamps = [int(r["fundingTime"]) for r in relevant]
        assert stamps[0] <= times[0] + 8 * HOUR and stamps[-1] >= times[-1] - 8 * HOUR
        assert len(set(stamps)) == len(stamps) and np.max(np.diff(stamps)) < 8.01 * HOUR
        for r in relevant:
            k = int(np.searchsorted(times, int(r["fundingTime"]), side="left") - 1)
            if k >= 0:
                assert r.get("markPrice"), "missing_hourly_funding_mark"
                value = float(r["fundingRate"]) * float(r["markPrice"])
                funding[k, j] += value
                debit[k, j] += max(value, 0.)
                credit[k, j] += max(-value, 0.)
    cube, mark_cube = np.stack(bars, axis=2), np.stack(marks, axis=2)
    return dict(symbols=SYMBOLS, times=times,
        dates=times.astype("datetime64[ms]").astype("datetime64[m]").astype(str),
        open=cube[:, 1], high=cube[:, 2], low=cube[:, 3], close=cube[:, 4],
        mark_low=mark_cube[:, 3], mark_high=mark_cube[:, 2],
        funding_value=funding, funding_debit=debit, funding_credit=credit, periods_per_year=8766.)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capital", type=float, default=21.25)
    parser.add_argument("--hour-root", type=Path, default=Path("state/research_cache/position_flow_20261027"))
    parser.add_argument("--mark-input", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/mark_hourly_windows.json"))
    parser.add_argument("--funding-input", type=Path, default=Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json"))
    parser.add_argument("--filters", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/exchange_filters.json"))
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/crypto_g20_intraday_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    mark_data = json.loads(args.mark_input.read_text())["data"]
    daily = json.loads(args.funding_input.read_text())["data"]
    filter_raw = json.loads(args.filters.read_text())
    filters = {r["symbol"]: r for r in filter_raw["symbols"]}
    base = Rule(cadence="6h", lookback=72, gross=3, stop_atr=2.,
                risk_adjusted_rank=True, max_hold_bars=48)
    rules = {
        "long1": replace(base, gross=1), "long3": base,
        "long5": replace(base, gross=5), "long10": replace(base, gross=10),
        "both3": replace(base, direction="both"),
        "both5": replace(base, direction="both", gross=5),
        "both10": replace(base, direction="both", gross=10),
    }
    results, curves = {}, {}
    for window, (filename, start, end) in WINDOWS.items():
        panel = load_hour_panel(args.hour_root / filename, mark_data[window], daily)
        f = features(panel)
        results[window] = {}
        for name, rule in rules.items():
            runs = {}
            for scenario, cost, ff, rr, path in (
                ("small0bp", 0, filters, rule, "liquidation_first"),
                ("continuous10bp", 10, None, rule, "liquidation_first"),
                ("small10bp", 10, filters, rule, "liquidation_first"),
                ("small30bp", 30, filters, rule, "liquidation_first"),
                ("small_delay3", 10, filters, replace(rule, delay=3), "liquidation_first"),
                ("small_stop_first", 10, filters, rule, "stop_first")):
                run = replay(panel, f, rr, start=start, end=end, capital=args.capital,
                             cost_bp=cost, filters=ff, ambiguous_path=path)
                runs[scenario] = run["summary"]
                if scenario == "small10bp":
                    curves[f"{window}_{name}"] = run
            results[window][name] = runs
            a = runs["small10bp"]
            print(window, name, "return/MDD/final", round(a["return_pct"], 2), round(a["mdd_pct"], 2),
                  round(a["final_usdt"], 4), a["counts"])
    sources = [args.mark_input, args.funding_input, args.filters,
               *(args.hour_root / v[0] for v in WINDOWS.values())]
    payload = dict(research_only=True, orders_authorized=False, independent_oos=False,
        initial_capital_usdt=args.capital, universe=SYMBOLS,
        rules={n: asdict(r) for n, r in rules.items()}, windows=WINDOWS,
        source_hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        signal="72 completed hours momentum / trailing30h volatility; 120h trend; 6h rotation; 2ATR14h trailing stop; 48h max hold",
        clock="close hour h; execute open hour h+2; one full extra hour; funding (entry,exit]",
        costs_one_way_bp=[0, 10, 30], filters_observed_at=filter_raw["observed_at"],
        liquidation_assumptions=dict(maintenance_fraction=.005, fee_fraction=.01, collateral="whole wallet"),
        limitations=["Only three retrospectively selected surviving coins, and three disjoint historical windows.",
            "No concatenated continuous equity curve, no stable-CAGR claim from a quarter.",
            "Current exchange filters applied retrospectively; historical tiers and stop execution unverified.",
            "Actual hourly mark highs/lows used, with both stop/liquidation order assumptions.",
            "Hourly stop fills and funding timing conservative, order-book fill/latency not reconstructed.",
            "Consumed historical samples, no independent OOS or live profitability certification."],
        results=results)
    (args.output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    (args.output / "curves.json").write_text(json.dumps(curves, ensure_ascii=False, allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
