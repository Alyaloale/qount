"""G20 v2 for small accounts with leverage: data-driven redesign experiments.

Market-structure findings this design encodes (see analyze_g20_market_structure):

* Trend continuation is real for ETF proxies (P(up next 5d | 63d up) 0.53-0.63
  vs ~0.54 unconditional) and absent for crypto (0.45-0.51).  The trend engine
  belongs to ETF slots; crypto is a single tail-capture satellite (crypto-corr
  0.69 means six crypto are one bet, capped at one slot).
* Longs pay 11-14%/yr funding on crypto in uptrends (BNB is the exception at
  -3.3%), so ranking subtracts trailing funding cost.
* Crypto vol is 4-7x ETF vol, so slots are sized by inverse vol (equal risk).
* Real min notional: ETH/LTC/LINK 20U vs SOL/BNB/XRP and ETF perps 5U.  At
  21.25U the 20U tier needs >=1x gross per slot; feasibility is measured, not
  assumed.  Leverage here buys slot feasibility and exposure, not return.

v2 candidate: pool + max_crypto=1, risk-parity book (position_gross = total
gross target), either-exit, no rank-momentum filter, min_trend_age=20,
funding-penalized ranking, realistic min-notional filters.

Execution caveats: daily bars; crypto daily open equals the previous close in
a 24/7 market, so crypto fills sit on the signal price (optimistic latency,
partly covered by 10bp costs).  ETF legs trade next session open after a NY
close signal (causal).  Yahoo ETFs remain adjusted proxies with zero funding;
recent real SPY perp funding averages -4.7%/yr to longs and is not backfilled.

research_only=true / orders_authorized=false.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
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


ETF_ROOT = Path("state/research_cache/binance_macro_etf_history_20261015")
PANEL7 = Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json")
ETF_INFO = Path("state/research_cache/binance_etf_leverage_20261015/exchange-info.json")
CRYPTO = ("ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT", "LINKUSDT")
DAY = 86400
CAPITAL = 21.25
COST_BP = 10.0
MM = 0.025
DAILY_RULE = dict(rank_hours=7, trend_hours=63, mean_hours=120, decision_hours=1)


def source(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def load_cli():
    spec = importlib.util.spec_from_file_location(
        "ablation_study", REPO_ROOT / "scripts/research/study_g20_dsf_mechanism_ablations.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_full_panel(etf_root=ETF_ROOT):
    """6 non-BTC crypto (daily klines + funding) + 8 ETF proxies, common days."""
    raw = json.loads(PANEL7.read_text())["data"]
    sources = [source(PANEL7)]
    crypto_ohlc, funding_rate = {}, {}
    for symbol in CRYPTO:
        rows = raw[symbol + "_klines"]
        crypto_ohlc[symbol] = {int(r[0]) // 1000: (float(r[1]), float(r[2]), float(r[3]), float(r[4]))
                               for r in rows}
        daily = {}
        for r in raw[symbol + "_funding"]:
            day = int(r["fundingTime"]) // 1000 // DAY * DAY
            daily[day] = daily.get(day, 0.0) + float(r["fundingRate"])
        funding_rate[symbol] = daily
    etf_ohlc = {}
    for symbol, ticker in SIGNAL_MAPPING.items():
        matches = sorted(etf_root.glob(f"yahoo-{ticker}-*.json"))
        if len(matches) != 1:
            raise ValueError(f"etf_source_ambiguous:{ticker}:{len(matches)}")
        path = matches[0]
        bars = adjusted_bars(json.loads(path.read_text()))
        etf_ohlc[symbol] = {b.t // DAY * DAY: (b.o, b.h, b.l, b.c) for b in bars}
        sources.append(source(path))
    days = sorted(set.intersection(*(set(crypto_ohlc[s]) for s in CRYPTO),
                                   *(set(etf_ohlc[s]) for s in SIGNAL_MAPPING)))
    if len(days) < 800:
        raise ValueError("insufficient_full_panel_history")
    symbols = (*CRYPTO, *SIGNAL_MAPPING)
    n, m = len(days), len(symbols)
    arrays = {k: np.zeros((n, m), dtype=float) for k in ("open", "high", "low", "close", "mark_low")}
    funding_value = np.zeros((n - 1, m), dtype=float)
    funding_debit = np.zeros_like(funding_value)
    funding_annual = np.zeros((n, m), dtype=float)
    for j, symbol in enumerate(symbols):
        mp = crypto_ohlc[symbol] if symbol in crypto_ohlc else etf_ohlc[symbol]
        for i, d in enumerate(days):
            o, h, l, c = mp[d]
            arrays["open"][i, j], arrays["high"][i, j] = o, h
            arrays["low"][i, j], arrays["close"][i, j] = l, c
            arrays["mark_low"][i, j] = l
        arrays["mark_low"][:-1, j] = np.minimum(arrays["low"][:-1, j], arrays["open"][1:, j])
        if symbol in funding_rate:
            fr = funding_rate[symbol]
            for i, d in enumerate(days):
                rate = fr.get(d, 0.0)
                if i < n - 1 and rate:
                    value = rate * arrays["close"][i, j]
                    funding_value[i, j] = value
                    funding_debit[i, j] = max(value, 0.0)
                funding_annual[i, j] = rate * 365.0
    panel = dict(symbols=symbols, times=np.asarray(days, dtype=np.int64),
                 open=arrays["open"], high=arrays["high"], low=arrays["low"],
                 close=arrays["close"], mark_low=arrays["mark_low"],
                 funding_value=funding_value, funding_debit=funding_debit,
                 periods_per_year=365.0)
    return panel, dict(funding_annual=funding_annual), sources


def trend_age_matrix(panel, f):
    close, mean = panel["close"], f["trend_mean"]
    n, m = close.shape
    age = np.zeros((n, m), dtype=float)
    for j in range(m):
        run = 0
        for i in range(n):
            if np.isfinite(mean[i, j]) and close[i, j] > mean[i, j]:
                run += 1
            else:
                run = 0
            age[i, j] = run
    return age


def vol_matrix(panel, window=20):
    closes = panel["close"]
    r = np.zeros_like(closes)
    r[1:] = np.log(closes[1:] / closes[:-1])
    n, _ = closes.shape
    vol = np.ones((n, closes.shape[1]), dtype=float)
    for i in range(window, n):
        vol[i] = np.std(r[i - window + 1:i + 1], axis=0, ddof=1) * np.sqrt(365.0)
    return np.maximum(vol, 0.05)


def build_features(panel, extra, rule, funding_penalty, trend_age):
    f = features(panel, rule)
    if funding_penalty:
        f["rank_score"] = f["rank_return"] - extra["funding_annual"] * rule.rank_hours / 365.0
    if trend_age:
        f["trend_age"] = trend_age_matrix(panel, f)
    return f


def build_filters():
    info = json.loads(ETF_INFO.read_text())
    want = set(CRYPTO) | set(SIGNAL_MAPPING)
    out = {}
    for s in info.get("symbols", []):
        name = s.get("symbol", "")
        if name in want:
            rows = {x["filterType"]: x for x in s.get("filters", [])}
            lot, mn = rows.get("MARKET_LOT_SIZE", {}), rows.get("MIN_NOTIONAL", {})
            out[name] = {"filters": [
                {"filterType": "MARKET_LOT_SIZE", "minQty": float(lot.get("minQty", 0)),
                 "stepSize": float(lot.get("stepSize", 0.001)),
                 "maxQty": float(lot.get("maxQty", 1e9))},
                {"filterType": "MIN_NOTIONAL", "notional": float(mn.get("notional", 5))}]}
    missing = want - set(out)
    if missing:
        raise ValueError(f"missing_exchange_filters:{sorted(missing)}")
    return out


def run_cells(panel, extra, cells, filters, capital=CAPITAL, crypto_cost_bp=None):
    """cells: (key, rule_kwargs, use_filters, funding_penalty, start, end)."""
    results, cache, vol = {}, {}, vol_matrix(panel)
    for key, rule_kwargs, use_filters, funding_penalty, start, end in cells:
        rule = PortfolioRule(**{**DAILY_RULE, **rule_kwargs})
        ck = (rule.rank_hours, rule.trend_hours, rule.mean_hours,
              funding_penalty, rule.min_trend_age > 0)
        if ck not in cache:
            cache[ck] = build_features(panel, extra, rule, funding_penalty,
                                       rule.min_trend_age > 0)
        run = replay(panel, cache[ck], rule, start=start, end=end, capital=capital,
                     cost_bp=COST_BP, filters=filters if use_filters else None,
                     maintenance=MM, variable_clock=True,
                     vol=vol if rule.position_mode == "risk_parity" else None,
                     crypto_cost_bp=crypto_cost_bp)
        summary = dict(run["summary"])
        summary["min_notional_skips"] = summary["counts"].get("minimum_notional_skip", 0)
        results[key] = dict(rule=asdict(rule), maintenance=MM, cost_bp=COST_BP,
                            crypto_cost_bp=crypto_cost_bp,
                            with_filters=use_filters, funding_penalty=funding_penalty,
                            summary=summary)
    return results


def fmt(row):
    s = row["summary"]
    liq = s["counts"].get("shared_liquidation", 0)
    top1 = s["top1_positive_pnl_share"]
    return (f"  final={s['final_usdt']:>8.2f}  cagr={s['cagr_pct']:>8.2f}%  "
            f"mdd={s['mdd_pct']:>6.2f}%  bound={s['intraday_drawdown_bound_pct']:>6.2f}%  "
            f"trades={s['trades']:>3}  syms={s['symbols_traded']:>2}  "
            f"top1={'n/a' if top1 is None else f'{top1:.2f}'}  liq={liq}  "
            f"skips={s['min_notional_skips']}  path_ev={s['path_evidence']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/g20_v2_small_leverage_20261102"))
    parser.add_argument("--capital", type=float, default=CAPITAL,
                        help="research principal in USDT (min-notional feasibility scales)")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    cli = load_cli()
    panel, extra, sources = build_full_panel()
    etf_panel, etf_sources = cli.build_etf_panel()
    filters = build_filters()
    payload = dict(
        research_only=True, orders_authorized=False,
        generated_at=datetime.now(timezone.utc).isoformat(),
        capital_usdt=args.capital,
        sources=dict(full=sources, etf=etf_sources),
        assumptions=[
            "Daily bars: crypto fills sit on the signal price (24/7 open==prior close); "
            "optimistic latency on crypto legs, partly covered by 10bp costs.",
            "Yahoo ETF proxies keep zero funding; real SPY perp funding (2026-04..11) "
            "averages -4.7%/yr to longs and is not backfilled.",
            "Min-notional/lot filters synthesized from Binance exchange-info cache.",
            "MM=2.5% flat shared-wallet tier; liquidation fee 1%.",
            "Sizing: a slot whose resize target rounds below the exchange minimum goes to "
            "cash (min_notional_exit; closed if held). Runs archived before 2026-11-02 froze "
            "stale lots instead — see g20_v2_small_leverage/g20_v2_capital4387 for the "
            "pre-fix artifacts.",
        ],
        experiments={})

    days = panel["times"]
    era_start = int(np.searchsorted(days, int(datetime(2022, 6, 28, tzinfo=timezone.utc).timestamp())))
    era = (int(days[era_start]), int(days[-1]))
    pre = (int(days[121]), era[0])
    era_etf_ts = int(datetime(2022, 6, 28, 20, 0, tzinfo=timezone.utc).timestamp())
    era_etf = (era_etf_ts, int(etf_panel["times"][-1]))
    pre_etf = (int(etf_panel["times"][121]), era_etf_ts)

    v2 = dict(max_positions=3, position_gross=3.0, core_mode="pool",
              exit_mode="either", position_mode="risk_parity",
              require_rank_positive=False, min_trend_age=20, max_crypto=1,
              crypto_symbols=CRYPTO)
    v1 = dict(max_positions=2, position_gross=1.0, core_mode="dual", exit_mode="dual",
              position_mode="fixed", require_rank_positive=True,
              crypto_symbols=("ETHUSDT", "SOLUSDT"))

    # ---- full panel, era window: candidate + ablations + ladder + v1 ----
    cells = [("v2_core_3x3", dict(v2), True, True, *era),
             ("v2_no_funding_penalty", dict(v2), True, False, *era),
             ("v2_no_trend_age", dict(v2, min_trend_age=0), True, True, *era),
             ("v2_dual_exit", dict(v2, exit_mode="dual"), True, True, *era),
             ("v2_no_crypto_cap", dict(v2, max_crypto=0), True, True, *era),
             ("v2_equal_notional", dict(v2, position_mode="fraction", position_gross=1.0),
              True, True, *era),
             ("v2_fixed_qty", dict(v2, position_mode="fixed", position_gross=1.0),
              True, True, *era),
             ("v2_no_filters", dict(v2), False, True, *era)]
    for total in (2.0, 4.0):
        cells.append((f"v2_core_{total:g}x3", dict(v2, position_gross=total), True, True, *era))
    for slots, total in ((4, 3.0), (4, 4.0)):
        cells.append((f"v2_core_{total:g}x{slots}",
                      dict(v2, max_positions=slots, position_gross=total), True, True, *era))
    # Sensitivity around the trend-age hypothesis (pre-registered from fill
    # anatomy: winners entered at age 24/34/257, losers 0-2) and the exit mode
    # at the risk-efficient corner.
    for age in (10, 40):
        cells.append((f"v2_age{age}_3x3", dict(v2, min_trend_age=age), True, True, *era))
    cells.append(("v2_dual_exit_2x3", dict(v2, exit_mode="dual", position_gross=2.0),
                  True, True, *era))
    cells.append(("v1_baseline_dual2x", dict(v1), False, True, *era))
    grid = run_cells(panel, extra, cells, filters, capital=args.capital)
    payload["experiments"]["full_panel_era"] = grid

    # ---- short pre-window (2021-07..2022-06): candidate + v1 ----
    grid_pre = run_cells(panel, extra, [
        ("v2_core_3x3_pre", dict(v2), True, True, *pre),
        ("v1_baseline_dual2x_pre", dict(v1), False, True, *pre),
    ], filters, capital=args.capital)
    payload["experiments"]["full_panel_pre"] = grid_pre

    # ---- ETF-only mechanism retest with v2 rules, both long windows ----
    grid_etf = run_cells(etf_panel, dict(funding_annual=np.zeros(
        (len(etf_panel["times"]), len(etf_panel["symbols"])))), [
        (f"v2_etf_only_3x3_{tag}",
         dict(max_positions=3, position_gross=3.0, core_mode="pool", exit_mode="either",
              position_mode="risk_parity", require_rank_positive=False,
              min_trend_age=20, max_crypto=0, crypto_symbols=()),
         True, True, *win)
        for tag, win in (("pre", pre_etf), ("era", era_etf))], filters, capital=args.capital)
    payload["experiments"]["etf_only"] = grid_etf

    # ---- buy-and-hold baselines (index-based windows) ----
    payload["experiments"]["baselines"] = {
        "ew_14_full_pre": cli.equal_weight_baseline(panel, 121, era_start - 1, capital=args.capital),
        "ew_14_full_era": cli.equal_weight_baseline(panel, era_start, len(days) - 1, capital=args.capital),
        "ew_8_etf_pre": cli.equal_weight_baseline(
            etf_panel, 121,
            int(np.searchsorted(etf_panel["times"], era_etf_ts, "right")) - 1, capital=args.capital),
        "ew_8_etf_era": cli.equal_weight_baseline(
            etf_panel, int(np.searchsorted(etf_panel["times"], era_etf_ts)),
            len(etf_panel["times"]) - 1, capital=args.capital),
    }

    (args.output / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n")

    print("== full panel era (2022-06-28..2025-12-31)")
    for key, row in grid.items():
        print(key, fmt(row))
    print("== full panel pre (short, 2021-07..2022-06)")
    for key, row in grid_pre.items():
        print(key, fmt(row))
    print("== etf only")
    for key, row in grid_etf.items():
        print(key, fmt(row))
    print("== baselines:", json.dumps(payload["experiments"]["baselines"], indent=1))


if __name__ == "__main__":
    main()
