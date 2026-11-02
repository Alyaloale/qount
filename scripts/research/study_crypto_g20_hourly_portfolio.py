"""Research fixed-quantity, multi-position hourly G20 portfolios.

The run uses ETH/SOL plus Binance TradFi perpetuals and deliberately excludes
BTC.  It is an offline study only; it never queries an account or submits an
order.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from qount.research.crypto_g20_hourly_portfolio import PortfolioRule, replay
from qount.research.crypto_g20_hourly_swing import features
from qount.research.crypto_g20_rotation import rounded_quantity

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CRYPTO = ("ETHUSDT", "SOLUSDT")
ETFS = ("SPYUSDT", "QQQUSDT", "SMHUSDT", "IWMUSDT", "XLEUSDT",
        "XAUUSDT", "COPPERUSDT", "CLUSDT")
SYMBOLS = (*CRYPTO, *ETFS)
START = int(datetime(2026, 4, 7, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 10, 25, 23, tzinfo=timezone.utc).timestamp())
DEFAULT_CACHE = Path("state/research_cache/crypto_g20_hourly_swing_20261102")
NATIVE_ROOT = Path("state/research_cache/macro_native_tail_20261026")
FILTERS = Path("state/research_cache/crypto_g20_rotation_20261102/exchange_filters.json")


def _source(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def _rows(path):
    return json.loads(path.read_text())


def _bar_time(row):
    return int(row[0]) // 1000 if isinstance(row, (list, tuple)) else int(row.t)


def _bar_ohlc(row):
    return (float(row[1]), float(row[2]), float(row[3]), float(row[4])) if isinstance(row, (list, tuple)) else (float(row.o), float(row.h), float(row.l), float(row.c))


def build_panel(cache=DEFAULT_CACHE):
    """Load a common hourly grid without forward-filling missing bars."""
    from scripts.research.study_g20_cross_asset_mechanisms import native_inputs

    native_book, _, native_sources = native_inputs()
    sources = list(native_sources)
    books = {}
    for symbol in CRYPTO:
        trade_path = cache / f"{symbol}-trade-1630454400-1793145600.json"
        mark_path = cache / f"{symbol}-mark-1630454400-1793145600.json"
        books[symbol] = dict(
            trade=_rows(trade_path), mark=_rows(mark_path),
            funding=native_book[symbol]["funding"],
        )
        sources.extend((_source(trade_path), _source(mark_path)))
    for symbol in ETFS:
        books[symbol] = native_book[symbol]

    first = max(min(_bar_time(r) for r in b["trade"]) for b in books.values())
    last = min(max(_bar_time(r) for r in b["trade"]) for b in books.values())
    first = max(first, START)
    last = min(last, END)
    times = np.arange(first, last + 3600, 3600, dtype=np.int64)
    n, m = len(times), len(SYMBOLS)
    arrays = {key: np.empty((n, m), dtype=float)
              for key in ("open", "high", "low", "close", "mark_low")}
    funding_value = np.zeros((n - 1, m), dtype=float)
    funding_debit = np.zeros_like(funding_value)
    approximate_funding = 0
    for j, symbol in enumerate(SYMBOLS):
        trade = {_bar_time(r): r for r in books[symbol]["trade"]}
        mark = {_bar_time(r): r for r in books[symbol]["mark"]}
        if set(times) - set(trade) or set(times) - set(mark):
            raise ValueError(f"hourly_common_calendar_gap:{symbol}")
        for i, t in enumerate(times):
            row = trade[int(t)]
            arrays["open"][i, j], arrays["high"][i, j], arrays["low"][i, j], arrays["close"][i, j] = _bar_ohlc(row)
            arrays["mark_low"][i, j] = _bar_ohlc(mark[int(t)])[2]
        for row in books[symbol]["funding"]:
            stamp = int(row["fundingTime"]) // 1000
            k = int(np.searchsorted(times, stamp, side="left") - 1)
            if k < 0 or k >= n - 1 or not times[k] < stamp <= times[k + 1]:
                continue
            mark_price = row.get("markPrice")
            if mark_price:
                mark_price = float(mark_price)
            else:
                # Only a small number of old rows omit markPrice.  The
                # fallback is observable and counted; it is not a future value.
                mark_price = _bar_ohlc(trade[int(times[k])])[0]
                approximate_funding += 1
            value = float(row["fundingRate"]) * mark_price
            funding_value[k, j] += value
            funding_debit[k, j] += max(value, 0.0)
    panel = dict(symbols=SYMBOLS, times=times, open=arrays["open"],
                 high=arrays["high"], low=arrays["low"], close=arrays["close"],
                 mark_low=arrays["mark_low"], funding_value=funding_value,
                 funding_debit=funding_debit, periods_per_year=8766.0)
    return panel, sources, approximate_funding


def load_filters():
    raw = json.loads(FILTERS.read_text())
    filters = {row["symbol"]: row for row in raw["symbols"]}
    exchange = json.loads((NATIVE_ROOT / "exchange-info.json").read_text())
    for row in exchange["symbols"]:
        if row["symbol"] in ETFS:
            filters[row["symbol"]] = row
    missing = [s for s in SYMBOLS if s not in filters]
    if missing:
        raise ValueError(f"missing_exchange_filters:{missing}")
    return filters, [_source(FILTERS), _source(NATIVE_ROOT / "exchange-info.json")]


def run_studies(panel, filters):
    # The listed ETF contracts have only a few months of hourly history.
    # Use a 30d/60d warm-up proxy to test portfolio mechanics; this is not the
    # production 63d/120d signal and is labelled as such in the report.
    start = int(datetime(2026, 9, 29, tzinfo=timezone.utc).timestamp())
    end = int(datetime(2026, 10, 25, 23, tzinfo=timezone.utc).timestamp())
    result = {}
    curves = {}
    for core in ("dual", "pool"):
        for slots in (2, 3):
            for gross in (2.0, 4.0, 6.0, 10.0):
                position_gross = gross / slots
                rule = PortfolioRule(rank_hours=168, trend_hours=720,
                                     mean_hours=1440, max_positions=slots,
                                     position_gross=position_gross,
                                     core_mode=core, exit_mode="dual")
                f = features(panel, rule)
                for cost_bp in (10.0, 30.0):
                    key = f"{core}_{slots}slots_{gross:g}x_{cost_bp:g}bp"
                    run = replay(panel, f, rule, start=start, end=end,
                                 capital=21.25, cost_bp=cost_bp, filters=filters)
                    result[key] = dict(rule=asdict(rule), cost_bp=cost_bp,
                                       summary=run["summary"])
                    curves[key] = dict(curve=run["curve"], fills=run["fills"],
                                       holdings=run["holdings"])
    for slots in (2, 3):
        rule = PortfolioRule(rank_hours=168, trend_hours=720,
                             mean_hours=1440, max_positions=slots,
                             position_gross=10.0, core_mode="dual", exit_mode="dual")
        f = features(panel, rule)
        key = f"dual_{slots}slots_each10x_" + "10bp"
        run = replay(panel, f, rule, start=start, end=end, capital=21.25,
                     cost_bp=10.0, filters=filters)
        result[key] = dict(rule=asdict(rule), cost_bp=10.0,
                           summary=run["summary"])
        curves[key] = dict(curve=run["curve"], fills=run["fills"],
                           holdings=run["holdings"])
    return result, curves, dict(start=start, end=end)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/crypto_g20_hourly_portfolio_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    panel, sources, approximate = build_panel(args.cache)
    filters, filter_sources = load_filters()
    sources.extend(filter_sources)
    results, curves, window = run_studies(panel, filters)
    payload = dict(
        research_only=True, orders_authorized=False,
        symbols=list(SYMBOLS), excluded_symbols=["BTCUSDT"],
        source_window=dict(start=datetime.fromtimestamp(int(panel["times"][0]), timezone.utc).isoformat(),
                           end=datetime.fromtimestamp(int(panel["times"][-1]), timezone.utc).isoformat(),
                           bars=len(panel["times"])),
        tested_window=dict(start=datetime.fromtimestamp(window["start"], timezone.utc).isoformat(),
                           end=datetime.fromtimestamp(window["end"], timezone.utc).isoformat()),
        mechanism=("Six-hour decisions use prior seven-day momentum, positive "
                    "30-day momentum, and price above a 60-day SMA as a short "
                    "window feasibility proxy; the intended production "
                    "parameters remain 63-day momentum and 120-day SMA. Positions "
                    "are fixed quantity; rank changes do not rotate them. A "
                    "dual-core entry requires one ETH/SOL crypto and one non-BTC "
                    "ETF. Exits are complete and occur only after both momentum "
                    "and price trend legs fail. Liquidation uses the shared "
                    "wallet and hourly mark lows."),
        cost_assumptions="One-way 10bp and 30bp; funding rows with markPrice, current filters, 0.5% maintenance and 1% liquidation fee proxy.",
        leverage_definition="gross is initial notional/equity per portfolio; each10x means approximately 20x or 30x total initial notional for two or three positions.",
        approximate_funding_events=approximate, results=results, sources=sources,
        limitations=[
            "ETF perpetuals only have a short 2026 listing history; this is a feasibility window, not long-term evidence.",
            "Historical leverage tiers, mark-price liquidation matching, spread, impact and execution queue are not reconstructed.",
            "A shared-wallet liquidation trigger uses hourly mark lows and closes all positions at a conservative wallet-level bound.",
            "The strategy opens fixed quantities and never adds, trims, rebalances or rotates a held symbol.",
        ],
    )
    (args.output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (args.output / "curves.json").write_text(json.dumps(curves, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print("panel bars", len(panel["times"]), "from", panel["times"][0], "to", panel["times"][-1])
    print("approximate funding events", approximate)
    for key, row in results.items():
        s = row["summary"]
        print(key, "final", round(s["final_usdt"], 4), "return", round(s["return_pct"], 2),
              "mdd", round(s["mdd_pct"], 2), "liq", s["counts"].get("shared_liquidation", 0),
              "entries", s["counts"].get("entry", 0))


if __name__ == "__main__":
    main()
