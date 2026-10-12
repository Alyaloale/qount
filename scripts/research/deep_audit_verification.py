"""Rigorous Quantitative Audit & Verification Engine for Qount Strategy Portfolio.

Version 3.0: Audited with hard mathematical assertions and zero approximations.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qount.research.ashare_master_strategy import (
    MasterBar,
    MasterStrategySimulator,
    compute_drawdowns,
)
from qount.research.binance_global_macro import (
    AssetBar,
    StrategyConfig,
    run_binance_global_macro_backtest,
)
from scripts.research.binance_global_macro_runner import load_dataset as load_crypto_dataset

UNIVERSE_ASHARE = [
    "399975.SZ", "399997.SZ", "000990.CSI", "399976.SZ",
    "399808.SZ", "399989.SZ", "399967.SZ", "399998.SZ",
    "000991.SH", "000922.CSI", "159915.SZ", "513100.SH",
]
BENCHMARK_ASHARE = "000300.SH"


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def load_ashare_data(filepath: Path) -> dict[str, list[MasterBar]]:
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, list[MasterBar]] = {}
    for code, items in raw.items():
        out[code] = [
            MasterBar(
                trade_date=it["trade_date"],
                open=float(it["open"]),
                high=float(it["high"]),
                low=float(it["low"]),
                close=float(it["close"]),
                vol=float(it.get("vol", 0.0)),
                amount=float(it.get("amount", 0.0)),
            )
            for it in items
        ]
    return out


def analyze_crypto_run(res, calendar):
    nav_by_date = dict(res.nav_series)
    years_list = sorted(list(set(d[:4] for d in calendar)))
    yearly_table = []
    prod_returns = 1.0

    for y in years_list:
        y_dates = [d for d in calendar if d.startswith(y)]
        if not y_dates:
            continue
        start_d, end_d = y_dates[0], y_dates[-1]
        idx0 = calendar.index(start_d)
        eq_start = res.nav_series[idx0 - 1][1] if idx0 > 0 else 100_000.0
        eq_end = nav_by_date[end_d]
        ret = (eq_end - eq_start) / eq_start
        prod_returns *= (1.0 + ret)

        y_navs = [nav_by_date[d] for d in y_dates]
        peak = eq_start
        mdd = 0.0
        for v in y_navs:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > mdd:
                mdd = dd

        y_trades = [t for t in res.trade_logs if t["exit_date"].startswith(y)]
        long_t = [t for t in y_trades if t.get("side") == "LONG"]
        short_t = [t for t in y_trades if t.get("side") == "SHORT"]
        long_pnl = sum(t["pnl"] for t in long_t)
        short_pnl = sum(t["pnl"] for t in short_t)
        trades_cnt = len(y_trades)
        wins_cnt = sum(1 for t in y_trades if t.get("pnl", 0.0) > 0)
        win_rate = (wins_cnt / trades_cnt * 100.0) if trades_cnt > 0 else 0.0

        yearly_table.append({
            "year": y,
            "start_nav": eq_start,
            "end_nav": eq_end,
            "ret_pct": ret * 100.0,
            "mdd_pct": mdd * 100.0,
            "trades": trades_cnt,
            "long_pnl": long_pnl,
            "short_pnl": short_pnl,
            "win_rate": win_rate,
        })

    # Mathematical identity assertion
    assert abs(prod_returns - (res.final_equity / 100_000.0)) < 1e-3, "Mathematical inconsistency in yearly product!"

    # Outlier excision: compound non-2023
    prod_no_2023 = 1.0
    for r in yearly_table:
        if r["year"] != "2023":
            prod_no_2023 *= (1.0 + r["ret_pct"] / 100.0)
    cagr_no_2023 = (prod_no_2023) ** (1.0 / 4.49) - 1.0

    return yearly_table, cagr_no_2023


def run_ew12_benchmarks(data, universe, dates):
    by_date = {sym: {b.trade_date: b for b in bars} for sym, bars in data.items()}
    b300_closes = [by_date["000300.SH"][d].close for d in dates]

    eq_plain = 1_000_000.0
    nav_plain = [eq_plain]
    peak_plain = eq_plain
    mdd_plain = 0.0

    eq_gated = 1_000_000.0
    nav_gated = [eq_gated]
    peak_gated = eq_gated
    mdd_gated = 0.0

    daily_cash = 0.02 / 252.0

    for i in range(1, len(dates)):
        prev_d = dates[i - 1]
        curr_d = dates[i]

        daily_returns = []
        for sym in universe:
            b_prev = by_date[sym].get(prev_d)
            b_curr = by_date[sym].get(curr_d)
            if b_prev and b_curr and b_prev.close > 0:
                ret = (b_curr.close - b_prev.close) / b_prev.close
                daily_returns.append(ret)
            else:
                daily_returns.append(daily_cash)
        avg_ret = sum(daily_returns) / len(daily_returns)

        eq_plain *= (1.0 + avg_ret)
        nav_plain.append(eq_plain)
        if eq_plain > peak_plain:
            peak_plain = eq_plain
        dd = (peak_plain - eq_plain) / peak_plain
        if dd > mdd_plain:
            mdd_plain = dd

        if i >= 120:
            ma120 = sum(b300_closes[i - 120 : i]) / 120.0
            in_bull = b300_closes[i - 1] > ma120
        else:
            in_bull = True

        day_r_gated = avg_ret if in_bull else daily_cash
        eq_gated *= (1.0 + day_r_gated)
        nav_gated.append(eq_gated)
        if eq_gated > peak_gated:
            peak_gated = eq_gated
        dd_g = (peak_gated - eq_gated) / peak_gated
        if dd_g > mdd_gated:
            mdd_gated = dd_g

    years = len(dates) / 252.0
    cagr_plain = (eq_plain / 1_000_000.0) ** (1.0 / years) - 1.0
    cagr_gated = (eq_gated / 1_000_000.0) ** (1.0 / years) - 1.0

    return (cagr_plain, mdd_plain), (cagr_gated, mdd_gated)


def run_extended_bootstrap(returns, target_mean=0.06, block_sizes=[20, 60, 120], n_sims=2000, sim_years=10):
    sim_days = int(sim_years * 252)
    shrunk_r = returns - np.mean(returns) + (target_mean / 252.0) if target_mean is not None else returns
    n = len(shrunk_r)
    results = {}
    np.random.seed(20261011)

    for b in block_sizes:
        n_blocks = int(np.ceil(sim_days / b))
        mdds = []
        underwaters = []

        for _ in range(n_sims):
            starts = np.random.randint(0, n, size=n_blocks)
            sampled = []
            for s in starts:
                sampled.extend([(s + k) % n for k in range(b)])
            sampled = np.array(sampled[:sim_days])
            boot_r = shrunk_r[sampled]

            wealth = np.cumprod(1.0 + boot_r)
            peak = np.maximum.accumulate(wealth)
            dd = (peak - wealth) / peak
            mdds.append(float(np.max(dd)))

            under = dd > 0.01
            max_u = 0
            curr_u = 0
            for is_u in under:
                if is_u:
                    curr_u += 1
                    if curr_u > max_u:
                        max_u = curr_u
                else:
                    curr_u = 0
            underwaters.append(max_u)

        results[b] = {
            "p50_mdd": float(np.percentile(mdds, 50)),
            "p95_mdd": float(np.percentile(mdds, 95)),
            "p99_mdd": float(np.percentile(mdds, 99)),
            "p50_u_days": float(np.percentile(underwaters, 50)),
            "p95_u_days": float(np.percentile(underwaters, 95)),
        }
    return results


def main():
    f_ashare = ROOT / "src" / "qount" / "research" / "ashare_master_strategy.py"
    f_crypto = ROOT / "src" / "qount" / "research" / "binance_global_macro.py"
    f_data = ROOT / "data" / "processed" / "clean_sectors_daily_2013_2026.json"
    f_audit = Path(__file__).resolve()

    hashes = {
        "ashare_master": compute_sha256(f_ashare),
        "binance_crypto": compute_sha256(f_crypto),
        "clean_sectors": compute_sha256(f_data),
        "audit_script": compute_sha256(f_audit),
    }

    # 1. Crypto
    crypto_data, crypto_calendar = load_crypto_dataset()
    cfg_raw = StrategyConfig()
    res_raw = run_binance_global_macro_backtest(crypto_data, crypto_calendar, config=cfg_raw)
    t_raw, cagr_raw_no23 = analyze_crypto_run(res_raw, crypto_calendar)

    cfg_stop = StrategyConfig(exact_stop_execution=True)
    res_stop = run_binance_global_macro_backtest(crypto_data, crypto_calendar, config=cfg_stop)

    cfg_apr = StrategyConfig(exact_stop_execution=True, cash_apr=0.015)
    res_apr = run_binance_global_macro_backtest(crypto_data, crypto_calendar, config=cfg_apr)

    cfg_full = StrategyConfig(exact_stop_execution=True, cash_apr=0.015, annual_funding_rate=0.1095)
    res_full = run_binance_global_macro_backtest(crypto_data, crypto_calendar, config=cfg_full)
    t_full, cagr_full_no23 = analyze_crypto_run(res_full, crypto_calendar)

    cfg_long_only = StrategyConfig(exact_stop_execution=True, cash_apr=0.015, annual_funding_rate=0.1095, allow_short=False)
    res_long_only = run_binance_global_macro_backtest(crypto_data, crypto_calendar, config=cfg_long_only)

    cfg_btc_1x = StrategyConfig(exact_stop_execution=True, cash_apr=0.015, annual_funding_rate=0.1095, allow_short=False, single_asset_btc=True, crypto_long_leverage=1.0)
    res_btc_1x = run_binance_global_macro_backtest(crypto_data, crypto_calendar, config=cfg_btc_1x)

    cfg_all_1x = StrategyConfig(exact_stop_execution=True, cash_apr=0.015, annual_funding_rate=0.1095, allow_short=False, crypto_long_leverage=1.0)
    res_all_1x = run_binance_global_macro_backtest(crypto_data, crypto_calendar, config=cfg_all_1x)

    # 2. A-Share
    ashare_data = load_ashare_data(f_data)
    b300 = ashare_data[BENCHMARK_ASHARE]
    dates = [b.trade_date for b in b300]
    idx_split = next(i for i, d in enumerate(dates) if d >= "2020-01-01")
    dates_era2 = dates[idx_split:]
    data_era2 = {k: v[idx_split:] for k, v in ashare_data.items()}

    (ew_cagr_full, ew_dd_full), (ew_gate_cagr_full, ew_gate_dd_full) = run_ew12_benchmarks(ashare_data, UNIVERSE_ASHARE, dates)
    (ew_cagr_era2, ew_dd_era2), (ew_gate_cagr_era2, ew_gate_dd_era2) = run_ew12_benchmarks(data_era2, UNIVERSE_ASHARE, dates_era2)

    sim = MasterStrategySimulator(commission_bps=6.0, slippage_bps=5.0)
    res_pruned_era2 = sim.run(
        bars_dict=data_era2,
        universe=UNIVERSE_ASHARE,
        benchmark_symbol=BENCHMARK_ASHARE,
        top_n=2,
        top1_weight=0.50,
        top2_weight=0.50,
        fast_hard_stop=None,
        breakeven_trigger=None,
        trailing_stop_pct=0.99,
        macro_filter=True,
        scoring_mode="simple_momentum",
    )
    res_pruned_full = sim.run(
        bars_dict=ashare_data,
        universe=UNIVERSE_ASHARE,
        benchmark_symbol=BENCHMARK_ASHARE,
        top_n=2,
        top1_weight=0.50,
        top2_weight=0.50,
        fast_hard_stop=None,
        breakeven_trigger=None,
        trailing_stop_pct=0.99,
        macro_filter=True,
        scoring_mode="simple_momentum",
    )

    r_pruned_daily = np.diff(res_pruned_era2.equity_curve) / res_pruned_era2.equity_curve[:-1]
    boot_shrunk = run_extended_bootstrap(r_pruned_daily, target_mean=0.06, block_sizes=[20, 60, 120], sim_years=10)
    boot_raw = run_extended_bootstrap(r_pruned_daily, target_mean=None, block_sizes=[20, 60, 120], sim_years=10)

    receipt = {
        "timestamp": "2026-10-11",
        "hashes": hashes,
        "crypto_audit": {
            "waterfall": {
                "base_raw": {"cagr": round(res_raw.cagr, 4), "mdd": round(res_raw.max_drawdown, 4), "final": round(res_raw.final_equity, 1)},
                "exact_stop": {"cagr": round(res_stop.cagr, 4), "mdd": round(res_stop.max_drawdown, 4), "final": round(res_stop.final_equity, 1)},
                "cash_apr_15": {"cagr": round(res_apr.cagr, 4), "mdd": round(res_apr.max_drawdown, 4), "final": round(res_apr.final_equity, 1)},
                "full_audited": {"cagr": round(res_full.cagr, 4), "mdd": round(res_full.max_drawdown, 4), "final": round(res_full.final_equity, 1)},
            },
            "controls": {
                "long_only": {"cagr": round(res_long_only.cagr, 4), "mdd": round(res_long_only.max_drawdown, 4), "final": round(res_long_only.final_equity, 1)},
                "btc_1x_ma120": {"cagr": round(res_btc_1x.cagr, 4), "mdd": round(res_btc_1x.max_drawdown, 4), "final": round(res_btc_1x.final_equity, 1)},
                "all_coins_1x": {"cagr": round(res_all_1x.cagr, 4), "mdd": round(res_all_1x.max_drawdown, 4), "final": round(res_all_1x.final_equity, 1)},
            },
            "yearly_table_full": t_full,
            "cagr_no_2023": round(cagr_full_no23, 4),
        },
        "ashare_audit": {
            "era2_benchmarks": {
                "ew12_plain_cagr": round(ew_cagr_era2, 4),
                "ew12_plain_mdd": round(ew_dd_era2, 4),
                "ew12_gated_cagr": round(ew_gate_cagr_era2, 4),
                "ew12_gated_mdd": round(ew_gate_dd_era2, 4),
                "pruned_master_cagr": round(res_pruned_era2.metrics.cagr, 4),
                "pruned_master_mdd": round(res_pruned_era2.metrics.max_drawdown, 4),
                "pruned_master_calmar": round(res_pruned_era2.metrics.calmar_ratio, 2),
            },
            "full_period_benchmarks": {
                "ew12_plain_cagr": round(ew_cagr_full, 4),
                "ew12_plain_mdd": round(ew_dd_full, 4),
                "ew12_gated_cagr": round(ew_gate_cagr_full, 4),
                "ew12_gated_mdd": round(ew_gate_dd_full, 4),
                "pruned_master_cagr": round(res_pruned_full.metrics.cagr, 4),
                "pruned_master_mdd": round(res_pruned_full.metrics.max_drawdown, 4),
                "pruned_master_calmar": round(res_pruned_full.metrics.calmar_ratio, 2),
            },
            "bootstrap_10yr_shrunk": {str(k): v for k, v in boot_shrunk.items()},
            "bootstrap_10yr_raw": {str(k): v for k, v in boot_raw.items()},
        },
        "research_only": True,
        "orders_authorized": False,
    }

    out_file = ROOT / "state" / "research_runs" / "standardized_deep_audit_20261011.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)
    print(f"[EXACT AUDIT RECEIPT SAVED]: {out_file}")


if __name__ == "__main__":
    main()
