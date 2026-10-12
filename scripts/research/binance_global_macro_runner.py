"""Run specialized dual-engine backtest across Binance Crypto, US ETFs, and Gold (2021-2026).

Synthesizing local Crypto & US ETF research findings:
- Assets:
  - Crypto: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
  - US ETFs: XLK, XLE, XLF, XLI, XLV
  - Gold: PAXGUSDT
  - Cash: USDT (5.0% APR)
- Dual Specialization:
  - Crypto: Kaufman Efficiency Ratio (KER), 2.2x 14d ATR trailing, BTC Master Gate shutoff.
  - US ETFs: Macro sector rotation, tight 5.5% stop, capital refuge absorption during crypto bear.
- Evaluation: Base, Double Cost, Extra Day Delay, Double Cost + Delay.
- research_only=true, orders_authorized=false.
"""

from __future__ import annotations

import json
import os
from typing import Any

from qount.research_data.market_data import load_klines
from qount.research.binance_global_macro import (
    AssetBar,
    StrategyConfig,
    run_binance_global_macro_backtest,
)


def load_dataset() -> tuple[dict[str, list[AssetBar]], list[str]]:
    raw_data: dict[str, list[AssetBar]] = {}

    # 1. Load Crypto from state/grid_b/klines
    crypto_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    for sym in crypto_symbols:
        raw_bars = load_klines(
            sym, "1d",
            start=(2021, 1), end=(2026, 6),
            market="um",
            cache_dir="state/grid_b/klines",
        )
        raw_data[sym] = [
            AssetBar(
                date=b.date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
            )
            for b in raw_bars
            if "2021-01-01" <= b.date <= "2026-06-30"
        ]

    # 2. Load Gold PAXGUSDT
    paxg_path = "state/research_runs/c60_pit_universe_v1/cache/PAXGUSDT.json"
    if os.path.exists(paxg_path):
        with open(paxg_path) as f:
            paxg_dict = json.load(f)
        paxg_rows = paxg_dict.get("rows", {})
        paxg_bars = []
        for d in sorted(paxg_rows.keys()):
            if "2021-01-01" <= d <= "2026-06-30":
                p = paxg_rows[d][0]
                vol = paxg_rows[d][1] if len(paxg_rows[d]) > 1 else 0.0
                paxg_bars.append(AssetBar(date=d, open=p, high=p, low=p, close=p, volume=vol))
        raw_data["PAXGUSDT"] = paxg_bars

    # 3. Load US Sector ETFs from state/research_cache/tiingo_spdr_sector_etf
    us_symbols = ["XLK", "XLE", "XLF", "XLI", "XLV"]
    for us_sym in us_symbols:
        path = f"state/research_cache/tiingo_spdr_sector_etf/tiingo_{us_sym}.json"
        if os.path.exists(path):
            with open(path) as f:
                raw_us = json.load(f)
            bars = []
            for row in raw_us:
                d = row["date"][:10]
                if "2021-01-01" <= d <= "2026-06-30":
                    bars.append(AssetBar(
                        date=d,
                        open=row.get("adjOpen", row["open"]),
                        high=row.get("adjHigh", row["high"]),
                        low=row.get("adjLow", row["low"]),
                        close=row.get("adjClose", row["close"]),
                        volume=row.get("adjVolume", row.get("volume", 0.0)),
                    ))
            raw_data[f"{us_sym}BUSDT"] = bars

    calendar = [b.date for b in raw_data["BTCUSDT"]]

    # Forward fill ALL symbols on non-trading days/missing bars
    aligned_data: dict[str, list[AssetBar]] = {}
    for sym, bars in raw_data.items():
        existing_map = {b.date: b for b in bars}
        filled: list[AssetBar] = []
        last_known = bars[0]
        for d in calendar:
            if d in existing_map:
                last_known = existing_map[d]
                filled.append(last_known)
            else:
                filled.append(AssetBar(
                    date=d,
                    open=last_known.close,
                    high=last_known.close,
                    low=last_known.close,
                    close=last_known.close,
                    volume=0.0,
                ))
        aligned_data[sym] = filled

    return aligned_data, calendar


def run_full_suite() -> dict[str, Any]:
    market_data, calendar = load_dataset()
    print(f"Loaded {len(market_data)} symbols across {len(calendar)} days ({calendar[0]} -> {calendar[-1]})")

    config = StrategyConfig(
        crypto_long_leverage=1.35,
        crypto_short_leverage=1.10,
        crypto_long_margin_pct=0.35,
        crypto_short_margin_pct=0.25,
        us_slot_margin_pct=0.20,
        crypto_long_hard_stop=0.075,
        crypto_long_profit_lock=0.15,
        crypto_long_lock_buffer=0.02,
        crypto_long_atr_mult=2.2,
        crypto_short_hard_stop=0.050,
        crypto_short_profit_lock=0.12,
        crypto_short_lock_buffer=0.015,
        crypto_short_trailing_pct=0.090,
        us_hard_stop=0.055,
        us_profit_lock=0.10,
        us_lock_buffer=0.015,
        us_trailing_pct=0.10,
        cooldown_bars=7,
        cash_apr=0.05,
    )

    # 1. Base run
    res_base = run_binance_global_macro_backtest(
        market_data=market_data,
        calendar=calendar,
        config=config,
        initial_capital=100_000.0,
        cost_multiplier=1.0,
        execution_delay=1,
    )

    # 2. Double cost run (14 bps / 30 bps)
    res_double = run_binance_global_macro_backtest(
        market_data=market_data,
        calendar=calendar,
        config=config,
        initial_capital=100_000.0,
        cost_multiplier=2.0,
        execution_delay=1,
    )

    # 3. Extra day delay (T+2)
    res_delay = run_binance_global_macro_backtest(
        market_data=market_data,
        calendar=calendar,
        config=config,
        initial_capital=100_000.0,
        cost_multiplier=1.0,
        execution_delay=2,
    )

    # 4. Double cost + Extra day delay
    res_stress = run_binance_global_macro_backtest(
        market_data=market_data,
        calendar=calendar,
        config=config,
        initial_capital=100_000.0,
        cost_multiplier=2.0,
        execution_delay=2,
    )

    # Benchmarks
    btc_bars = market_data["BTCUSDT"]
    btc_p0, btc_p1 = btc_bars[0].close, btc_bars[-1].close
    years = len(calendar) / 365.25
    btc_cagr = (btc_p1 / btc_p0) ** (1.0 / years) - 1.0
    btc_peak = btc_p0
    btc_mdd = 0.0
    for b in btc_bars:
        if b.close > btc_peak:
            btc_peak = b.close
        dd = (btc_peak - b.close) / btc_peak
        if dd > btc_mdd:
            btc_mdd = dd

    xlk_bars = market_data["XLKBUSDT"]
    xlk_p0, xlk_p1 = xlk_bars[0].close, xlk_bars[-1].close
    xlk_cagr = (xlk_p1 / xlk_p0) ** (1.0 / years) - 1.0
    xlk_peak = xlk_p0
    xlk_mdd = 0.0
    for b in xlk_bars:
        if b.close > xlk_peak:
            xlk_peak = b.close
        dd = (xlk_peak - b.close) / xlk_peak
        if dd > xlk_mdd:
            xlk_mdd = dd

    yearly_returns = {}
    for i in range(1, len(res_base.nav_series)):
        dt0, eq0 = res_base.nav_series[i - 1]
        dt1, eq1 = res_base.nav_series[i]
        y = dt1[:4]
        if y not in yearly_returns:
            yearly_returns[y] = {"start": eq0, "end": eq1}
        else:
            yearly_returns[y]["end"] = eq1

    yearly_pct = {
        y: round((d["end"] - d["start"]) / d["start"] * 100, 2)
        for y, d in sorted(yearly_returns.items())
    }

    nav_by_date = dict(res_base.nav_series)
    years_list = sorted(list(set(d[:4] for d in calendar)))
    yearly_details = {}
    for y in years_list:
        y_dates = [d for d in calendar if d.startswith(y)]
        if not y_dates:
            continue
        start_d, end_d = y_dates[0], y_dates[-1]
        idx0 = calendar.index(start_d)
        eq_start = res_base.nav_series[idx0 - 1][1] if idx0 > 0 else 100_000.0
        eq_end = nav_by_date[end_d]
        ret = (eq_end - eq_start) / eq_start

        y_navs = [nav_by_date[d] for d in y_dates]
        peak = eq_start
        mdd = 0.0
        for v in y_navs:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > mdd:
                mdd = dd

        y_trades = [t for t in res_base.trade_logs if t["exit_date"].startswith(y)]
        long_t = [t for t in y_trades if t.get("side") == "LONG"]
        short_t = [t for t in y_trades if t.get("side") == "SHORT"]
        long_pnl = sum(t["pnl"] for t in long_t)
        short_pnl = sum(t["pnl"] for t in short_t)
        wins = [t for t in y_trades if t["pnl"] > 0]
        wr = len(wins) / len(y_trades) if y_trades else 0.0
        tot_win = sum(t["pnl"] for t in wins)
        tot_loss = abs(sum(t["pnl"] for t in y_trades if t["pnl"] <= 0))
        pf = (tot_win / tot_loss) if tot_loss > 0 else 99.0

        yearly_details[y] = {
            "start_equity": round(eq_start, 2),
            "end_equity": round(eq_end, 2),
            "return_pct": round(ret * 100, 2),
            "max_drawdown_pct": round(mdd * 100, 2),
            "trades_count": len(y_trades),
            "long_trades": len(long_t),
            "short_trades": len(short_t),
            "long_pnl": round(long_pnl, 2),
            "short_pnl": round(short_pnl, 2),
            "win_rate_pct": round(wr * 100, 2),
            "profit_factor": round(pf, 2),
        }

    # Trade analytics
    long_trades = [t for t in res_base.trade_logs if t.get("side") == "LONG"]
    short_trades = [t for t in res_base.trade_logs if t.get("side") == "SHORT"]
    long_wins = [t for t in long_trades if t["pnl"] > 0]
    short_wins = [t for t in short_trades if t["pnl"] > 0]

    crypto_trades = [t for t in res_base.trade_logs if "BUSDT" not in t["symbol"] and "XL" not in t["symbol"] and "PAXG" not in t["symbol"]]
    us_trades = [t for t in res_base.trade_logs if ("BUSDT" in t["symbol"] or "XL" in t["symbol"] or "PAXG" in t["symbol"])]

    summary = {
        "dataset": {
            "period": f"{calendar[0]} to {calendar[-1]}",
            "days": len(calendar),
            "years": round(years, 2),
            "symbols": list(market_data.keys()),
        },
        "benchmarks": {
            "BTC_buy_hold": {
                "cagr": round(btc_cagr * 100, 2),
                "max_drawdown": round(btc_mdd * 100, 2),
                "final_equity": round(100_000.0 * (btc_p1 / btc_p0), 2),
            },
            "XLK_buy_hold": {
                "cagr": round(xlk_cagr * 100, 2),
                "max_drawdown": round(xlk_mdd * 100, 2),
                "final_equity": round(100_000.0 * (xlk_p1 / xlk_p0), 2),
            },
        },
        "yearly_breakdown": yearly_details,
        "strategy_curves": {
            "base": {
                "cagr": round(res_base.cagr * 100, 2),
                "max_drawdown": round(res_base.max_drawdown * 100, 2),
                "sharpe": round(res_base.sharpe, 2),
                "calmar": round(res_base.calmar, 2),
                "final_equity": round(res_base.final_equity, 2),
                "trades_count": res_base.trades_count,
                "win_rate": round(res_base.win_rate * 100, 2),
                "profit_factor": round(res_base.profit_factor, 2),
                "yearly_returns_pct": yearly_pct,
                "trade_breakdown": {
                    "long_trades": len(long_trades),
                    "long_pnl": round(sum(t["pnl"] for t in long_trades), 2),
                    "long_win_rate": round(len(long_wins) / len(long_trades) * 100, 2) if long_trades else 0.0,
                    "short_trades": len(short_trades),
                    "short_pnl": round(sum(t["pnl"] for t in short_trades), 2),
                    "short_win_rate": round(len(short_wins) / len(short_trades) * 100, 2) if short_trades else 0.0,
                    "crypto_pnl": round(sum(t["pnl"] for t in crypto_trades), 2),
                    "us_macro_pnl": round(sum(t["pnl"] for t in us_trades), 2),
                },
            },
            "double_cost": {
                "cagr": round(res_double.cagr * 100, 2),
                "max_drawdown": round(res_double.max_drawdown * 100, 2),
                "sharpe": round(res_double.sharpe, 2),
                "calmar": round(res_double.calmar, 2),
                "final_equity": round(res_double.final_equity, 2),
                "trades_count": res_double.trades_count,
            },
            "extra_day_delay": {
                "cagr": round(res_delay.cagr * 100, 2),
                "max_drawdown": round(res_delay.max_drawdown * 100, 2),
                "sharpe": round(res_delay.sharpe, 2),
                "calmar": round(res_delay.calmar, 2),
                "final_equity": round(res_delay.final_equity, 2),
                "trades_count": res_delay.trades_count,
            },
            "double_cost_extra_day": {
                "cagr": round(res_stress.cagr * 100, 2),
                "max_drawdown": round(res_stress.max_drawdown * 100, 2),
                "sharpe": round(res_stress.sharpe, 2),
                "calmar": round(res_stress.calmar, 2),
                "final_equity": round(res_stress.final_equity, 2),
                "trades_count": res_stress.trades_count,
            },
        },
    }

    out_dir = "state/research_runs/binance_global_macro_20261011"
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("--- DUAL SPECIALIZED ENGINE COMPLETE ---")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    run_full_suite()
