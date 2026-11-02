"""Daily G20 portfolio replay using the long original ETF history.

ETF prices are the project's adjusted Yahoo daily bars. ETH/SOL are sampled
from the native hourly futures at each ETF session close. This is a causal
daily proxy for a dual-core strategy, not an executable Binance ETF-contract
backtest: ETF quantities are fractional and ETF funding is zero.
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

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qount.research.binance_macro_history import adjusted_bars
from qount.research.crypto_g20_hourly_portfolio import PortfolioRule, replay
from qount.research.crypto_g20_hourly_swing import features
from qount.strategies.macro_1atr import SIGNAL_MAPPING


ROOT = Path("state/research_cache")
ETF_ROOT = ROOT / "binance_macro_etf_history_20261015"
CRYPTO_CACHE = ROOT / "crypto_g20_hourly_swing_20261102"
CRYPTO_PANEL = ROOT / "independent_crypto_factors_20261027/panel_seven.json"
CRYPTO = ("ETHUSDT", "SOLUSDT")
ETFS = tuple(SIGNAL_MAPPING)
SYMBOLS = (*CRYPTO, *ETFS)


def source(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def ohlc(row):
    return (float(row[1]), float(row[2]), float(row[3]), float(row[4]))


def load_crypto_hourly(symbol):
    trade_path = CRYPTO_CACHE / f"{symbol}-trade-1630454400-1793145600.json"
    mark_path = CRYPTO_CACHE / f"{symbol}-mark-1630454400-1793145600.json"
    trade = {int(r[0]) // 1000: ohlc(r) for r in json.loads(trade_path.read_text())}
    mark = {int(r[0]) // 1000: ohlc(r) for r in json.loads(mark_path.read_text())}
    return trade, mark, [source(trade_path), source(mark_path)]


def build_panel():
    etf_bars, sources = {}, []
    for symbol, ticker in SIGNAL_MAPPING.items():
        path = ETF_ROOT / f"yahoo-{ticker}-20160101-2026-01-01.json"
        etf_bars[symbol] = adjusted_bars(json.loads(path.read_text()))
        sources.append(source(path))
    common = sorted(set.intersection(*(set(b.t for b in bars) for bars in etf_bars.values())))
    # Original files are synchronous NYSE sessions. Keep the full crypto era
    # after warm-up, while retaining only ETF dates shared by all components.
    common = [t for t in common if t >= int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp())]
    if len(common) < 800:
        raise ValueError("insufficient_original_etf_history")
    times = np.asarray(common, dtype=np.int64)
    n, m = len(times), len(SYMBOLS)
    arrays = {k: np.zeros((n, m), dtype=float) for k in ("open", "close", "high", "low", "mark_low")}
    funding_value = np.zeros((n - 1, m), dtype=float)
    funding_debit = np.zeros_like(funding_value)

    by_etf = {s: {b.t: b for b in etf_bars[s]} for s in ETFS}
    for j, symbol in enumerate(ETFS, start=len(CRYPTO)):
        for i, t in enumerate(times):
            b = by_etf[symbol][int(t)]
            arrays["open"][i, j], arrays["high"][i, j] = b.o, b.h
            arrays["low"][i, j], arrays["close"][i, j] = b.l, b.c
            arrays["mark_low"][i, j] = b.l
        # The next-session open is part of an open-to-open interval and is
        # therefore included in the conservative mark-low bound.
        arrays["mark_low"][:-1, j] = np.minimum(arrays["low"][:-1, j], arrays["open"][1:, j])

    raw = json.loads(CRYPTO_PANEL.read_text())["data"]
    crypto_data = {}
    for j, symbol in enumerate(CRYPTO):
        trade, mark, src = load_crypto_hourly(symbol)
        sources.extend(src)
        for i, t in enumerate(times):
            if int(t) not in trade:
                raise ValueError(f"crypto_sample_missing:{symbol}:{t}")
            arrays["open"][i, j], _, _, arrays["close"][i, j] = trade[int(t)]
            arrays["high"][i, j] = trade[int(t)][1]
            arrays["low"][i, j] = trade[int(t)][2]
            arrays["mark_low"][i, j] = mark[int(t)][2]
        settlements = raw[symbol + "_funding"]
        for i in range(n - 1):
            for row in settlements:
                stamp = int(row["fundingTime"]) // 1000
                if int(times[i]) < stamp <= int(times[i + 1]):
                    mark_price = float(row.get("markPrice") or trade[int(times[i])][0])
                    value = float(row["fundingRate"]) * mark_price
                    funding_value[i, j] += value
                    funding_debit[i, j] += max(value, 0.0)

    # Mark lows for crypto include every hourly mark low between the two ETF
    # close timestamps, including the starting sampled hour.
    for j, symbol in enumerate(CRYPTO):
        _, mark, _ = load_crypto_hourly(symbol)
        for i in range(n - 1):
            keys = range(int(times[i]), int(times[i + 1]), 3600)
            lows = [mark[k][2] for k in keys if k in mark]
            if not lows:
                raise ValueError(f"crypto_interval_mark_missing:{symbol}:{times[i]}")
            arrays["mark_low"][i, j] = min(lows)

    panel = dict(symbols=SYMBOLS, times=times, open=arrays["open"],
                 high=arrays["high"], low=arrays["low"], close=arrays["close"],
                 mark_low=arrays["mark_low"], funding_value=funding_value,
                 funding_debit=funding_debit, periods_per_year=365.25)
    return panel, sources


def run(panel):
    # 120-session mean warm-up plus one execution delay.
    start = int(panel["times"][121])
    end = int(panel["times"][-1])
    results, curves = {}, {}
    for core in ("dual", "pool"):
        for slots in (2, 3):
            for total_gross in (2.0, 4.0, 6.0, 10.0):
                rule = PortfolioRule(rank_hours=7, trend_hours=63,
                    mean_hours=120, decision_hours=1, max_positions=slots,
                    position_gross=total_gross / slots, core_mode=core,
                    exit_mode="dual")
                f = features(panel, rule)
                for cost in (10.0, 30.0):
                    key = f"{core}_{slots}slots_{total_gross:g}x_{cost:g}bp"
                    run = replay(panel, f, rule, start=start, end=end,
                                 capital=21.25, cost_bp=cost, filters=None,
                                 variable_clock=True)
                    results[key] = dict(rule=asdict(rule), cost_bp=cost,
                                        summary=run["summary"])
                    curves[key] = dict(curve=run["curve"], fills=run["fills"],
                                       holdings=run["holdings"])
    # Explicitly show the user's proposed "10x on every position" case.  It
    # is 20x aggregate initial notional for two slots and 30x for three.
    for slots in (2, 3):
        rule = PortfolioRule(rank_hours=7, trend_hours=63, mean_hours=120,
            decision_hours=1, max_positions=slots, position_gross=10.0,
            core_mode="dual", exit_mode="dual")
        f = features(panel, rule)
        key = f"dual_{slots}slots_each10x_10bp"
        run = replay(panel, f, rule, start=start, end=end, capital=21.25,
                     cost_bp=10.0, filters=None, variable_clock=True)
        results[key] = dict(rule=asdict(rule), cost_bp=10.0,
                            summary=run["summary"])
        curves[key] = dict(curve=run["curve"], fills=run["fills"],
                           holdings=run["holdings"])
    return results, curves, start, end


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/crypto_g20_daily_original_etf_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    panel, sources = build_panel()
    results, curves, start, end = run(panel)
    payload = dict(
        research_only=True, orders_authorized=False,
        symbols=list(SYMBOLS), excluded_symbols=["BTCUSDT"],
        source_window=dict(start=datetime.fromtimestamp(int(panel["times"][0]), timezone.utc).isoformat(),
                           end=datetime.fromtimestamp(int(panel["times"][-1]), timezone.utc).isoformat(),
                           bars=len(panel["times"])),
        tested_window=dict(start=datetime.fromtimestamp(start, timezone.utc).isoformat(),
                           end=datetime.fromtimestamp(end, timezone.utc).isoformat()),
        mechanism=("Daily close signals use 7-day ranking momentum, positive "
                   "63-day momentum and 120-day mean. Entry is the next ETF "
                   "session open or next synchronized crypto sample. Positions "
                   "are fixed quantity, never resized or rebalanced, and rank "
                   "changes never rotate a held symbol. Dual mode requires one "
                   "ETH/SOL position and one original ETF. A shared wallet "
                   "liquidates all positions on the hourly mark-low bound."),
        proxy_warning=("Original Yahoo ETFs are adjusted daily proxies with "
                       "fractional quantities and zero ETF funding; they are "
                       "not Binance ETF perpetual execution prices."),
        cost_assumptions="One-way 10bp and 30bp; crypto funding from observed settlements; 0.5% maintenance and 1% liquidation fee proxy.",
        leverage_definition="total gross is initial aggregate notional/equity; 10x total is split equally across slots, while each10x would imply 20x/30x aggregate and is not a sensible default.",
        results=results, sources=sources,
        limitations=[
            "ETF history is long, but the synchronized crypto sample begins in 2022 and uses ETF session closes.",
            "Adjusted ETF OHLC includes distributions in the price series; it is a research proxy, not a perpetual contract ledger.",
            "Fractional ETF quantities ignore exchange min-notional and broker lot restrictions; real 21.25U execution can differ materially.",
            "Hourly mark lows and historical leverage tiers are not reconstructed exactly; liquidation is a conservative shared-wallet proxy.",
        ],
    )
    (args.output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (args.output / "curves.json").write_text(json.dumps(curves, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print("panel sessions", len(panel["times"]), "start", payload["source_window"]["start"], "end", payload["source_window"]["end"])
    for key, row in results.items():
        s = row["summary"]
        print(key, "final", round(s["final_usdt"], 4), "return", round(s["return_pct"], 2),
              "mdd", round(s["mdd_pct"], 2), "liq", s["counts"].get("shared_liquidation", 0),
              "entries", s["counts"].get("entry", 0))


if __name__ == "__main__":
    main()
