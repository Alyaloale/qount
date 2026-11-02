"""Hourly signals with persistent multi-day crypto trend positions."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone

import numpy as np

from qount.research.crypto_g20_rotation import rounded_quantity


@dataclass(frozen=True)
class SwingRule:
    rank_hours: int = 168
    trend_hours: int = 1512
    mean_hours: int = 2880
    decision_hours: int = 1
    delay_bars: int = 1
    gross: float = 1.0
    exit_mode: str = "either"
    retain_position: bool = True
    btc_gate: bool = False

    def __post_init__(self):
        if (self.rank_hours < 1 or self.trend_hours < self.rank_hours or
                self.mean_hours < self.trend_hours or
                self.decision_hours < 1 or self.delay_bars < 1 or self.gross <= 0):
            raise ValueError("invalid_swing_rule")
        if self.exit_mode not in ("either", "dual"):
            raise ValueError("invalid_swing_exit_mode")


def _trailing_mean(values, width):
    out = np.full_like(values, np.nan, dtype=float)
    if len(values) < width:
        return out
    cumulative = np.vstack([np.zeros((1, values.shape[1])), np.cumsum(values, axis=0)])
    out[width - 1:] = (cumulative[width:] - cumulative[:-width]) / width
    return out


def features(panel, rule):
    close = np.asarray(panel["close"], dtype=float)
    if close.ndim != 2 or not np.all(np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("invalid_hourly_closes")
    rank = np.full_like(close, np.nan)
    trend = np.full_like(close, np.nan)
    rank[rule.rank_hours:] = close[rule.rank_hours:] / close[:-rule.rank_hours] - 1
    trend[rule.trend_hours:] = close[rule.trend_hours:] / close[:-rule.trend_hours] - 1
    return dict(rank_return=rank, trend_return=trend,
                trend_mean=_trailing_mean(close, rule.mean_hours))


def trend_failure(panel, f, signal, symbol_index, rule):
    price_fails = panel["close"][signal, symbol_index] <= f["trend_mean"][signal, symbol_index]
    momentum_fails = f["trend_return"][signal, symbol_index] <= 0
    return bool(price_fails or momentum_fails if rule.exit_mode == "either"
                else price_fails and momentum_fails)


def _winner(panel, f, signal, execution_index, equity, rule, cost_bp, filters):
    if rule.btc_gate:
        btc = panel["symbols"].index("BTCUSDT")
        if not (panel["close"][signal, btc] > f["trend_mean"][signal, btc] and
                f["trend_return"][signal, btc] > 0):
            return None, 0.0
    momentum = f["rank_return"][signal]
    qualified = ((panel["close"][signal] > f["trend_mean"][signal]) &
                 (f["trend_return"][signal] > 0) & (momentum > 0))
    candidates = np.flatnonzero(qualified)
    candidates = sorted(candidates, key=lambda j: (-momentum[j], panel["symbols"][j]))
    fee = cost_bp / 10000
    if not candidates:
        return None, 0.0
    j = candidates[0]
    price = panel["open"][execution_index, j]
    notional = equity * rule.gross / (1 + rule.gross * fee)
    quantity = rounded_quantity(notional, price, panel["symbols"][j], filters)
    return (int(j), quantity) if quantity > 0 else (None, 0.0)


def replay(panel, f, rule, *, start, end, capital=21.25, cost_bp=10.0,
           filters=None, maintenance=0.005, liquidation_fee=0.01):
    """One long-only, single-position, open-to-open self-financing account.

    A completed hourly close informs a decision; delay_bars=1 executes at the
    next hour open. Entries are considered every decision_hours. Positions
    are fixed-quantity and retained until their trend exit unless rank rotation
    is explicitly enabled. Funding is charged over each open-to-open interval.
    """
    if capital <= 0 or cost_bp < 0 or not 0 <= maintenance < 1 or liquidation_fee < 0:
        raise ValueError("invalid_swing_account")
    times = np.asarray(panel["times"], dtype=np.int64)
    if np.any(np.diff(times) != 3600):
        raise ValueError("hourly_clock_gap")
    left = int(np.searchsorted(times, start, side="left"))
    right = int(np.searchsorted(times, end, side="left"))
    if left < rule.trend_hours + rule.delay_bars or right <= left or right >= len(times):
        raise ValueError("invalid_swing_window_or_warmup")

    equity = float(capital)
    held, quantity, entry_index = None, 0.0, None
    fee = cost_bp / 10000
    counts, curve, trades = Counter(), [], []
    attribution = {s: dict(price=0.0, funding=0.0, costs=0.0)
                   for s in panel["symbols"]}
    highwater = float(capital)
    adverse_mdd = 0.0
    ruined = False
    holding_hours = []
    prior_gross, max_gross, turnover = [], 0.0, 0.0

    def close_position(index, reason):
        nonlocal equity, held, quantity, entry_index, turnover
        j = held
        price = panel["open"][index, j]
        charge = quantity * price * fee
        equity -= charge
        attribution[panel["symbols"][j]]["costs"] += charge
        turnover += quantity * price
        trades.append(dict(time=int(times[index]), symbol=panel["symbols"][j],
                           side="SELL", quantity=float(quantity), price=float(price),
                           costs=float(charge), reason=reason,
                           holding_hours=int(index - entry_index)))
        counts[reason] += 1
        holding_hours.append(int(index - entry_index))
        held, quantity, entry_index = None, 0.0, None

    for t in range(left, right):
        before = equity
        signal = t - rule.delay_bars
        scheduled = (int(times[signal] // 3600) % rule.decision_hours == rule.decision_hours - 1)

        market_failed = False
        if held is not None and rule.btc_gate:
            btc = panel["symbols"].index("BTCUSDT")
            market_failed = trend_failure(panel, f, signal, btc, rule)
        if held is not None and market_failed:
            close_position(t, "market_exit")
        elif held is not None and trend_failure(panel, f, signal, held, rule):
            close_position(t, "trend_exit")

        if scheduled and equity > 0:
            target, wanted = _winner(panel, f, signal, t, equity, rule, cost_bp, filters)
            if held is not None and not rule.retain_position and target != held:
                close_position(t, "rank_rotation_exit")
            if held is None and target is not None and wanted > 0:
                price = panel["open"][t, target]
                charge = wanted * price * fee
                equity -= charge
                attribution[panel["symbols"][target]]["costs"] += charge
                turnover += wanted * price
                held, quantity, entry_index = target, wanted, t
                trades.append(dict(time=int(times[t]), symbol=panel["symbols"][target],
                    side="BUY", quantity=float(wanted), price=float(price),
                    costs=float(charge), reason="rank_entry"))
                counts["entry"] += 1
            elif held is None:
                counts["no_tradeable_qualified_coin"] += int(bool(
                    np.any((panel["close"][signal] > f["trend_mean"][signal]) &
                           (f["trend_return"][signal] > 0) & (f["rank_return"][signal] > 0))))

        interval_funding = 0.0
        interval_debit = 0.0
        pnl = 0.0
        gross = 0.0
        if held is not None and equity > 0:
            price = panel["open"][t, held]
            gross = quantity * price / equity
            mark_low = panel["mark_low"][t, held]
            interval_funding = -quantity * panel["funding_value"][t, held]
            interval_debit = quantity * panel["funding_debit"][t, held]
            worst_equity = equity + quantity * (mark_low - price) - interval_debit
            if worst_equity <= quantity * mark_low * maintenance:
                liq_price = max(0.0, (quantity * price - equity + interval_debit) /
                                (quantity * (1 - maintenance)))
                remaining = max(0.0, quantity * liq_price * (maintenance - liquidation_fee))
                attribution[panel["symbols"][held]]["price"] += remaining - equity + interval_debit
                attribution[panel["symbols"][held]]["funding"] -= interval_debit
                pnl = remaining - equity + interval_debit
                equity = remaining
                interval_funding = -interval_debit
                counts["liquidation"] += 1
                trades.append(dict(time=int(times[t]), symbol=panel["symbols"][held],
                    side="SELL", quantity=float(quantity), price=float(liq_price), costs=0.0,
                    reason="liquidation", holding_hours=int(t - entry_index)))
                holding_hours.append(int(t - entry_index))
                held, quantity, entry_index = None, 0.0, None
                adverse_mdd = 1.0
            else:
                pnl = quantity * (panel["open"][t + 1, held] - price)
                equity += pnl + interval_funding
                name = panel["symbols"][held]
                attribution[name]["price"] += pnl
                attribution[name]["funding"] += interval_funding
                adverse_mdd = max(adverse_mdd,
                    1 - max(0.0, worst_equity) / max(highwater, 1e-30))
                if interval_funding < 0:
                    counts["funding_debit_intervals"] += 1
        else:
            equity = max(equity, 0.0)

        if t == right - 1 and held is not None and equity > 0:
            close_position(t + 1, "terminal_exit")
        if equity <= 0:
            if not ruined:
                counts["ruin"] += 1
                ruined = True
            equity = 0.0
            held, quantity, entry_index = None, 0.0, None

        highwater = max(highwater, equity)
        max_gross = max(max_gross, gross)
        prior_gross.append(gross)
        turnover += 0.0
        curve.append(dict(time=int(times[t + 1]), equity=float(equity),
                          returns=float(equity / before - 1) if before else 0.0,
                          price_pnl=float(pnl), funding_pnl=float(interval_funding),
                          costs=float(pnl + interval_funding - (equity - before)),
                          gross=float(gross)))

    nav = np.asarray([capital, *[row["equity"] for row in curve]]) / capital
    mdd = float(np.max(1 - nav / np.maximum.accumulate(nav)))
    hours = right - left
    years = hours / 8766
    cagr = float(nav[-1] ** (1 / years) - 1) if nav[-1] > 0 else -1.0
    summary = dict(start=datetime.fromtimestamp(int(times[left]), timezone.utc).isoformat(),
        end_open=datetime.fromtimestamp(int(times[right]), timezone.utc).isoformat(), hours=hours,
        initial_usdt=float(capital), final_usdt=float(equity),
        return_pct=float((nav[-1] - 1) * 100), cagr_pct=cagr * 100,
        mdd_pct=mdd * 100, calmar=cagr / mdd if mdd else None,
        intraday_drawdown_bound_pct=adverse_mdd * 100,
        gross_target=rule.gross, max_actual_gross=float(max_gross),
        mean_actual_gross=float(np.mean(prior_gross)),
        active_hours=int(sum(x > 0 for x in prior_gross)),
        mean_holding_days=float(np.mean(holding_hours) / 24) if holding_hours else None,
        median_holding_days=float(np.median(holding_hours) / 24) if holding_hours else None,
        max_holding_days=float(max(holding_hours) / 24) if holding_hours else None,
        turnover_usdt=float(turnover),
        funding_pnl=float(sum(v["funding"] for v in attribution.values())),
        price_pnl=float(sum(v["price"] for v in attribution.values())),
        costs=float(sum(v["costs"] for v in attribution.values())),
        counts=dict(counts), attribution=attribution)
    return dict(summary=summary, curve=curve, trades=trades)
