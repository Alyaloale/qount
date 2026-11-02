"""Hourly G20-style entry ranking with multi-week trend persistence."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from qount.research.crypto_g20_hourly_swing import SwingRule, features, replay
from qount.research.crypto_g20_rotation import rounded_quantity
from qount.research_data.binance_history import public_get


SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
START = int(datetime(2021, 9, 1, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 10, 28, tzinfo=timezone.utc).timestamp())
WINDOWS = {
    "2022": ("2022-01-01", "2023-01-01"),
    "2023": ("2023-01-01", "2024-01-01"),
    "2024": ("2024-01-01", "2025-01-01"),
    "2025": ("2025-01-01", "2026-01-01"),
    "2026": ("2026-01-01", "2026-10-27"),
    "2022_2026": ("2022-01-01", "2026-10-27"),
}


def fetch_hourly(cache, symbol, kind, *, download):
    path = cache / f"{symbol}-{kind}-{START}-{END}.json"
    if not path.exists():
        if not download:
            raise FileNotFoundError(f"{path}; rerun with --download")
        endpoint = "/fapi/v1/klines" if kind == "trade" else "/fapi/v1/markPriceKlines"
        rows, cursor, pages = [], START * 1000, 0
        while cursor < END * 1000:
            pages += 1
            if pages > 40:
                raise ValueError("bounded_hourly_page_limit")
            page = public_get(endpoint, dict(symbol=symbol, interval="1h", startTime=cursor,
                                             endTime=END * 1000 - 1, limit=1500))
            if not isinstance(page, list) or not page:
                raise ValueError(f"empty_public_hourly_page:{symbol}:{kind}:{cursor}")
            page = [r for r in page if START * 1000 <= int(r[0]) < END * 1000]
            if not page or int(page[0][0]) != cursor:
                raise ValueError(f"public_hourly_page_gap:{symbol}:{kind}:{cursor}")
            rows.extend(page)
            next_cursor = int(page[-1][0]) + 3600000
            if next_cursor <= cursor:
                raise ValueError("hourly_pagination_not_advancing")
            cursor = next_cursor
            if pages % 8 == 0:
                print("download", symbol, kind, "pages", pages, "bars", len(rows), flush=True)
            time.sleep(.08)
        expected = list(range(START * 1000, END * 1000, 3600000))
        if [int(r[0]) for r in rows] != expected:
            raise ValueError(f"public_hourly_calendar_mismatch:{symbol}:{kind}")
        with path.open("x") as stream:
            json.dump(rows, stream, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
    raw = path.read_bytes()
    rows = json.loads(raw)
    expected = list(range(START * 1000, END * 1000, 3600000))
    if [int(r[0]) for r in rows] != expected:
        raise ValueError(f"cached_hourly_calendar_mismatch:{symbol}:{kind}")
    for r in rows:
        o, h, low, close = (float(r[i]) for i in (1, 2, 3, 4))
        if not 0 < low <= min(o, close) <= max(o, close) <= h:
            raise ValueError(f"invalid_cached_ohlc:{symbol}:{kind}")
    return rows, dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())


def verify_existing_windows(cache_rows, mark_rows):
    root = Path("state/research_cache/position_flow_20261027")
    marks = json.loads(Path("state/research_cache/crypto_g20_rotation_20261102/mark_hourly_windows.json").read_text())["data"]
    pairs = (("2025q1", "hourly_2025q1.json"), ("2025q4", "hourly_2025q4.json"),
             ("2026tail", "hourly.json"))
    checks = 0
    for window, filename in pairs:
        raw = json.loads((root / filename).read_text())["data"]
        for symbol in SYMBOLS:
            start = int(raw[symbol + "_futures"][0][0])
            stop = int(raw[symbol + "_futures"][-1][0]) + 3600000
            i, j = (start - START * 1000) // 3600000, (stop - START * 1000) // 3600000
            for kind, rows, key in (("trade", cache_rows[symbol], symbol + "_futures"),
                                    ("mark", mark_rows[symbol], symbol)):
                old = raw[key] if kind == "trade" else marks[window][key]
                new = rows[i:j]
                if len(new) != len(old):
                    raise ValueError(f"existing_hourly_overlap_length:{window}:{symbol}:{kind}")
                for a, b in zip(old, new):
                    if int(a[0]) != int(b[0]) or not np.allclose(
                            [float(a[k]) for k in (1, 2, 3, 4)],
                            [float(b[k]) for k in (1, 2, 3, 4)], rtol=0, atol=1e-7):
                        raise ValueError(f"existing_hourly_overlap_mismatch:{window}:{symbol}:{kind}")
                checks += len(old)
    return checks


def build_panel(trade_rows, mark_rows, daily_data):
    times = np.asarray([int(r[0]) // 1000 for r in trade_rows[SYMBOLS[0]]], dtype=np.int64)
    arrays = {}
    for kind, rows_by_symbol in (("trade", trade_rows), ("mark", mark_rows)):
        for symbol in SYMBOLS:
            rows = rows_by_symbol[symbol]
            stamps = np.asarray([int(r[0]) // 1000 for r in rows], dtype=np.int64)
            if not np.array_equal(stamps, times):
                raise ValueError(f"hourly_symbol_calendar_mismatch:{symbol}:{kind}")
            for name, column in (("open", 1), ("high", 2), ("low", 3), ("close", 4)):
                arrays.setdefault(kind + "_" + name, []).append(
                    np.asarray([float(r[column]) for r in rows]))
    trade = {k: np.stack(v, axis=1) for k, v in arrays.items() if k.startswith("trade_")}
    marks = {k: np.stack(v, axis=1) for k, v in arrays.items() if k.startswith("mark_")}
    funding_value = np.zeros_like(trade["trade_open"])
    funding_debit = np.zeros_like(funding_value)
    approximate_events = 0
    daily_open = {}
    for symbol in SYMBOLS:
        for row in daily_data[symbol + "_klines"]:
            daily_open[(int(row[0]) // 1000)] = {}
        break
    for j, symbol in enumerate(SYMBOLS):
        # Exchange daily opens are used only when historical settlement rows
        # lack their markPrice field.
        by_day = {int(r[0]) // 1000: float(r[1])
                  for r in daily_data[symbol + "_klines"]}
        for row in daily_data[symbol + "_funding"]:
            stamp = int(row["fundingTime"]) // 1000
            if not times[0] < stamp <= times[-1]:
                continue
            k = int(np.searchsorted(times, stamp, side="left") - 1)
            if k < 0 or k >= len(times) - 1:
                continue
            if row.get("markPrice"):
                mark = float(row["markPrice"])
            else:
                day = stamp // 86400 * 86400
                if day not in by_day:
                    raise ValueError(f"missing_daily_funding_mark_fallback:{symbol}:{stamp}")
                mark = by_day[day]
                approximate_events += 1
            value = float(row["fundingRate"]) * mark
            funding_value[k, j] += value
            funding_debit[k, j] += max(value, 0.0)
    return dict(symbols=SYMBOLS, times=times, open=trade["trade_open"],
        high=trade["trade_high"], low=trade["trade_low"], close=trade["trade_close"],
        mark_low=marks["mark_low"], mark_high=marks["mark_high"],
        funding_value=funding_value, funding_debit=funding_debit,
        periods_per_year=8766.0), approximate_events


def buy_and_hold(panel, *, start, end, capital=1000., cost_bp=10.):
    left = int(np.searchsorted(panel["times"], start, side="left"))
    right = int(np.searchsorted(panel["times"], end, side="left"))
    fee = cost_bp / 10000
    q = np.full(len(SYMBOLS), capital / len(SYMBOLS) / panel["open"][left])
    costs = float(np.sum(q * panel["open"][left] * fee))
    equity = capital - costs
    values, highwater, mdd, funding, price_pnl = [], capital, 0., 0., 0.
    for t in range(left, right):
        pnl = float(np.sum(q * (panel["open"][t + 1] - panel["open"][t])))
        fund = float(-np.sum(q * panel["funding_value"][t]))
        equity += pnl + fund
        funding += fund
        price_pnl += pnl
        values.append(equity)
        highwater = max(highwater, equity)
        mdd = max(mdd, 1 - equity / highwater)
    close_cost = float(np.sum(q * panel["open"][right] * fee))
    equity -= close_cost
    costs += close_cost
    nav = np.asarray([capital, *values, equity]) / capital
    mdd = max(mdd, float(np.max(1 - nav / np.maximum.accumulate(nav))))
    years = (right - left) / 8766
    cagr = (nav[-1] ** (1 / years) - 1) if nav[-1] > 0 else -1.
    return dict(initial_usdt=capital, final_usdt=float(equity),
        return_pct=float((nav[-1] - 1) * 100), cagr_pct=float(cagr * 100),
        mdd_pct=float(mdd * 100), price_pnl=price_pnl, funding_pnl=funding,
        costs=costs, note="Equal initial fixed quantities of BTC/ETH/SOL; no rebalancing.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("state/research_cache/crypto_g20_hourly_swing_20261102"))
    parser.add_argument("--daily-input", type=Path, default=Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json"))
    parser.add_argument("--filters", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/exchange_filters.json"))
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/crypto_g20_hourly_swing_20261102"))
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)

    jobs = [(s, kind) for s in SYMBOLS for kind in ("trade", "mark")]
    fetched = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(fetch_hourly, args.cache, s, kind,
                               download=args.download): (s, kind) for s, kind in jobs}
        for future in futures:
            s, kind = futures[future]
            rows, source = future.result()
            fetched[(s, kind)] = rows
            print("loaded", s, kind, len(rows), flush=True)
    trade_rows = {s: fetched[(s, "trade")] for s in SYMBOLS}
    mark_rows = {s: fetched[(s, "mark")] for s in SYMBOLS}
    overlap_checks = verify_existing_windows(trade_rows, mark_rows)

    daily_raw = json.loads(args.daily_input.read_text())
    daily_data = daily_raw["data"]
    panel, approximate_events = build_panel(trade_rows, mark_rows, daily_data)
    filters_raw = json.loads(args.filters.read_text())
    filters = {row["symbol"]: row for row in filters_raw["symbols"]}
    base_rule = SwingRule(rank_hours=168, trend_hours=1512, mean_hours=2880,
                          decision_hours=6, delay_bars=1)
    mechanisms = {
        "rotate_either": dict(exit_mode="either", retain_position=False, btc_gate=False),
        "retain_either": dict(exit_mode="either", retain_position=True, btc_gate=False),
        "rotate_dual": dict(exit_mode="dual", retain_position=False, btc_gate=False),
        "retain_dual": dict(exit_mode="dual", retain_position=True, btc_gate=False),
        "retain_dual_btc_gate": dict(exit_mode="dual", retain_position=True, btc_gate=True),
    }
    results, curves = {}, {}
    for mechanism, config in mechanisms.items():
        results[mechanism] = {}
        for gross in (1., 2., 3.):
            rule = replace(base_rule, gross=gross, **config)
            key = f"{mechanism}_{gross:g}x"
            results[mechanism][f"{gross:g}x"] = {}
            f = features(panel, rule)
            for window, (start_day, end_day) in WINDOWS.items():
                start = int(datetime.fromisoformat(start_day).replace(tzinfo=timezone.utc).timestamp())
                end = int(datetime.fromisoformat(end_day).replace(tzinfo=timezone.utc).timestamp())
                for label, cost in (("10bp", 10.), ("30bp", 30.)):
                    run = replay(panel, f, rule, start=start, end=end, capital=21.25,
                                 cost_bp=cost, filters=filters)
                    results[mechanism][f"{gross:g}x"].setdefault(window, {})[label] = run["summary"]
                    if window == "2022_2026" and label == "10bp":
                        curves[key] = run
            s = results[mechanism][f"{gross:g}x"]["2022_2026"]["10bp"]
            print(key, "final/CAGR/MDD/hld/cost/funding/liquidations",
                  round(s["final_usdt"], 4), round(s["cagr_pct"], 2),
                  round(s["mdd_pct"], 2), s["median_holding_days"],
                  round(s["costs"], 4), round(s["funding_pnl"], 4),
                  s["counts"].get("liquidation", 0), flush=True)

    unit_accounts, unit_curves = {}, {}
    start = int(datetime.fromisoformat(WINDOWS["2022_2026"][0]).replace(tzinfo=timezone.utc).timestamp())
    end = int(datetime.fromisoformat(WINDOWS["2022_2026"][1]).replace(tzinfo=timezone.utc).timestamp())
    for mechanism, config in mechanisms.items():
        unit_accounts[mechanism] = {}
        for gross in (1., 2., 3.):
            rule = replace(base_rule, gross=gross, **config)
            f = features(panel, rule)
            run = replay(panel, f, rule, start=start, end=end, capital=1000.,
                         cost_bp=10., filters=None)
            unit_accounts[mechanism][f"{gross:g}x"] = run["summary"]
            if gross == 1.:
                unit_curves[mechanism] = run
    benchmark = buy_and_hold(panel, start=start, end=end, capital=1000., cost_bp=10.)

    # Delayed hourly execution should affect all strategies consistently; test
    # only the primary persistence candidate at 2x rather than tune the clock.
    timing = {}
    for delay in (1, 2):
        rule = replace(base_rule, gross=2., exit_mode="dual", retain_position=True,
                       delay_bars=delay)
        run = replay(panel, features(panel, rule), rule, start=start, end=end,
                     capital=21.25, cost_bp=10., filters=filters)
        timing[f"delay_{delay}_bars"] = run["summary"]

    sources = []
    for symbol, kind in jobs:
        path = args.cache / f"{symbol}-{kind}-{START}-{END}.json"
        sources.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    sources += [dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                for p in (args.daily_input, args.filters)]
    payload = dict(
        research_only=True, orders_authorized=False, independent_oos=False,
        initial_capital_usdt=21.25, universe=SYMBOLS,
        data_window=dict(start="2021-09-01T00:00:00Z", end_exclusive="2026-10-28T00:00:00Z",
                         trade_and_mark_bars=len(panel["times"]), prior_cache_overlap_rows=overlap_checks),
        hourly_closes=panel["times"].tolist(),
        baseline_rule=asdict(base_rule), mechanisms=mechanisms,
        windows=WINDOWS, one_way_cost_bp=[10, 30], gross_levels=[1, 2, 3],
        entry="Every six hours, rank by positive 168-hour return; require positive 1512-hour return and close above trailing 2880-hour SMA. Ranking winner is selected from only the three fixed contracts; if it is untradeable at the current small-account size, remain in cash.",
        retention="With retain_position=true, do not rotate on rank changes. Exit hourly after a causal signal when the selected exit policy fails; enter a new winner at the next scheduled six-hour entry check.",
        execution="Close of signal hour; next-hour open execution (delay_bars=1); delay_bars=2 is the full-extra-hour latency stress. Funding settles into the interval ending at its timestamp.",
        funding_approximate_events=approximate_events,
        filters_observed_at=filters_raw["observed_at"],
        liquidation_assumptions=dict(collateral="whole wallet", maintenance_fraction=.005,
                                     liquidation_fee_fraction=.01, mark_low="hourly mark-price low"),
        unit_1000_accounts=unit_accounts, btc_eth_sol_1x_buy_hold=benchmark,
        execution_timing=timing, results=results,
        source_hashes=sources,
        limitations=[
            "Only BTC, ETH and SOL have comparable hourly histories in this run; this is not a historical G20-wide survivorship-free universe.",
            "All historical periods were previously inspected; reported calendar splits are diagnostics, not independent out-of-sample tests.",
            "Funding marks missing from the retained daily funding archive use that UTC day's trade open; count is reported.",
            "Current contract filters and minimum notionals are applied retrospectively; historical leverage tiers and liquidation brackets are not reconstructed.",
            "Mark-price hourly lows do not reveal within-hour ordering, order-book fills, stop slippage, or true liquidation matching.",
            "Fixed entry quantities mean actual leverage drifts with price and equity; target multiples are initial-notional/equity, not a guaranteed ceiling.",
        ],
    )
    (args.output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (args.output / "curves.json").write_text(json.dumps(curves, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (args.output / "unit_curves.json").write_text(json.dumps(unit_curves, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print("cached source hashes written; prior hourly overlap rows verified:", overlap_checks)


if __name__ == "__main__":
    main()
