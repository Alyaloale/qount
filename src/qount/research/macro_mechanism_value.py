"""Daily ETF mechanism experiments; never an execution model for live perps."""
from __future__ import annotations

import datetime as dt
import math
import statistics

from qount.research.engine.evaluation import nav_metrics
from qount.research.engine.linear_account import LinearAccount
from qount.research_data.bars import NY
from qount.research_data.regime import compute_atr, compute_ema


PROFILES = ("structural21", "structural7", "original_all", "original_mr", "original_trend",
            "mr_no_state", "mr_own_regime", "simple_dip21", "trend_no_state", "original_momentum_rank")


def mechanism_rows(bars, features):
    closes = [b.c for b in bars]
    ema20, ema50 = compute_ema(closes, 20), compute_ema(closes, 50)
    volatility = compute_atr(bars)
    fs = {f["available"]: f for f in features}
    result = {}
    for i in range(200, len(bars)):
        b, f = bars[i], fs[bars[i].t]
        lower = statistics.mean(closes[i-19:i+1])-2*statistics.pstdev(closes[i-19:i+1])
        bounce = b.l < lower < b.c and b.c > b.o
        trend = b.c > ema20[i] > ema50[i] and f["er20"] >= .28 and (
            b.c > max(x.h for x in bars[i-20:i]) or b.l <= 1.02*ema20[i] and b.c > b.o)
        result[b.t] = dict(f, atr=volatility[i], simple_bounce=bounce,
            simple_dip=closes[i]/closes[i-5]-1 < 0 and b.c > b.o,
            trend_no_state=trend)
    return result


def eligibility(f, profile):
    structural = f["hold_structural"]
    if profile.startswith("structural"):
        return structural, 21 if profile == "structural21" else 7, "structural"
    if profile in ("original_all", "original_momentum_rank"):
        setup = f["tactical_setup"]
        return f["entry_tactical"], 21 if setup == "mean_reversion" else 7, setup
    if profile == "original_mr":
        return f["entry_tactical"] and f["tactical_setup"] == "mean_reversion", 21, "mean_reversion"
    if profile == "original_trend":
        return f["entry_tactical"] and f["tactical_setup"] in ("breakout", "pullback"), 7, f["tactical_setup"]
    if profile == "mr_no_state":
        return structural and f["simple_bounce"], 21, "mean_reversion"
    if profile == "mr_own_regime":
        return f["structural"] and f["simple_bounce"] and f["state"] == "CHOP", 21, "mean_reversion"
    if profile == "simple_dip21":
        return structural and f["simple_dip"], 21, "mean_reversion"
    if profile == "trend_no_state":
        return structural and f["trend_no_state"], 7, "trend"
    raise ValueError("unknown_mechanism_profile")


def daily_replay(book, rows, profile, *, start="2017-01-01", end="2026-01-01",
                 capital=10000., vol_target=None, fee=.0005, slip=.0025,
                 stops=True, holding="original", execution_symbol=None, entry_times=None,
                 mr_holding_rule=None):
    """One unlevered position, next-open orders, calendar-day horizon, causal stops.

    Current-day lows can trigger an existing stop; current close/ATR can only
    change the next session's stop. No same-session reentry after an exit.
    """
    if profile not in PROFILES:
        raise ValueError("unknown_mechanism_profile")
    if holding not in ("original", "fixed15") or execution_symbol is not None and execution_symbol not in book:
        raise ValueError("unknown_mechanism_execution")
    if mr_holding_rule is not None and (not callable(mr_holding_rule) or holding != "original"):
        raise ValueError("invalid_mr_holding_rule")
    symbols = sorted(book)
    times = [b.t for b in book[symbols[0]]]
    if any([b.t for b in book[s]] != times for s in symbols):
        raise ValueError("shared_ETF_calendar_required")
    indices = [i for i in range(1, len(times)) if start <=
               dt.datetime.fromtimestamp(times[i], NY).date().isoformat() < end]
    if not indices:
        raise ValueError("empty_evaluation_window")
    account, pos = LinearAccount(capital, fee, slip), None
    curve, exposures, holdings = [], [], []
    for i in indices:
        date = dt.datetime.fromtimestamp(times[i], NY).date()
        opening = int(dt.datetime.combine(date, dt.time(9, 30), NY).timestamp())
        previous = times[i-1]
        known = {s: rows[s].get(previous) for s in symbols}
        if any(f is None for f in known.values()):
            raise ValueError("warmup_features_missing")
        if not curve:
            curve.append(dict(t=opening, nav=1.0, equity=capital))
        just_closed = False
        if pos:
            s, f, bar = pos["symbol"], known[pos["source_symbol"]], book[pos["symbol"]][i]
            holding_allowed = (f["structural"] if profile == "mr_own_regime" else f["hold_structural"]
                if pos["setup"] in ("mean_reversion", "structural") else f["hold_tactical"])
            if mr_holding_rule is not None and pos["setup"] == "mean_reversion":
                holding_allowed = mr_holding_rule(account.position, f, opening, holding_allowed)
                if not isinstance(holding_allowed, bool):
                    raise ValueError("invalid_mr_holding_result")
            reason = ("stop_gap" if stops and bar.o <= account.position["stop"] else
                      "regime_exit" if holding == "original" and not holding_allowed else
                      "time_exit" if holding == "original" and opening >= pos["deadline"] else None)
            if reason:
                account.close(bar.o, opening, reason)
                pos, just_closed = None, True
        if pos is None and not just_closed:
            candidates = []
            for s, f in known.items():
                allowed, days, setup = eligibility(f, profile)
                if allowed:
                    rank = f["rank_tactical"] if profile == "original_all" else f["rank_core"]
                    candidates.append((-rank, s, days, setup))
            if candidates and (entry_times is None or opening in entry_times):
                _, source_symbol, days, setup = min(candidates)
                s = execution_symbol or source_symbol
                bar, f = book[s][i], known[s]
                weight = 1. if vol_target is None else min(1., vol_target/max(f["realized_vol20"], 1e-8))
                fill = bar.o*(1+slip)
                quantity = account.cash*weight/(fill*(1+fee))
                stop = fill-2*f["atr"]
                if stop > 0:
                    account.open(s, quantity, bar.o, stop, opening, previous)
                    account.position.update(setup=setup, weight=weight, equity_at_entry=account.cash+quantity*fill*fee)
                    account.position["source_symbol"] = source_symbol
                    pos = dict(symbol=s, source_symbol=source_symbol, setup=setup,
                               entry_index=i, deadline=opening+days*86400,
                               structural_r=2*f["atr"], highest_close=fill)
        exposure, holding_symbol = 0., None
        if pos:
            s, bar = pos["symbol"], book[pos["symbol"]][i]
            exposure = account.position["quantity"]*bar.o/account.equity(bar.o)
            holding_symbol = s
            if stops and bar.l <= account.position["stop"]:
                account.close(min(bar.o, account.position["stop"]), times[i], "stop_intraday")
                pos = None
            else:
                pos["highest_close"] = max(pos["highest_close"], bar.c)
                if stops and bar.c-account.position["entry_price"] >= 2*pos["structural_r"]:
                    account.position["stop"] = max(account.position["stop"],
                        pos["highest_close"]-2*rows[s][times[i]]["atr"])
            if pos and holding == "fixed15" and i >= pos["entry_index"]+14:
                account.close(bar.c, times[i], "fixed15_close")
                pos = None
        value = account.equity(book[pos["symbol"]][i].c) if pos else account.cash
        if i == indices[-1] and pos:
            account.close(book[pos["symbol"]][i].c, times[i], "end_of_sample")
            pos, value = None, account.cash
        curve.append(dict(t=times[i], nav=value/capital, equity=value))
        exposures.append(exposure)
        holdings.append(holding_symbol)
    assert math.isclose(account.cash, capital+sum(t["net_pnl"] for t in account.trades), abs_tol=1e-7)
    for t in account.trades:
        assert t["signal_time"] < t["entry_time"] <= t["exit_time"]
        net = t["quantity"]*(t["exit_price"]-t["entry_price"])-t["entry_fee"]-t["exit_fee"]
        assert math.isclose(net, t["net_pnl"], abs_tol=1e-8)
        assert t["quantity"]*t["entry_price"]+t["entry_fee"] <= t["equity_at_entry"]+1e-7
    summary = nav_metrics(curve, sampling="daily_close")
    years = {}
    for a, b in zip(curve, curve[1:]):
        year = dt.datetime.fromtimestamp(b["t"], NY).strftime("%Y")
        years[year] = years.get(year, 1.)*b["nav"]/a["nav"]
    summary.update(trades=len(account.trades), average_open_exposure=statistics.mean(exposures),
        years={y: v-1 for y, v in years.items()},
        pnl_by_asset={s: sum(t["net_pnl"] for t in account.trades if t["symbol"] == s) for s in symbols})
    return dict(profile=profile, vol_target=vol_target, stops=stops, holding=holding,
                execution_symbol=execution_symbol, summary=summary, curve=curve,
                trades=account.trades, daily_exposures=exposures, daily_holdings=holdings)
