"""Fixed-quantity, multi-position hourly G20-style portfolio replay.

This module is research-only.  A position is opened once at a scheduled
hourly decision, never resized or rebalanced, and is closed in full on a dual
trend failure.  All positions share one wallet and therefore one liquidation
boundary.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from qount.research.crypto_g20_rotation import rounded_quantity
from qount.research.crypto_g20_hourly_swing import features


YEAR_HOURS = 365.25 * 24


@dataclass(frozen=True)
class PortfolioRule:
    rank_hours: int = 168
    trend_hours: int = 1512
    mean_hours: int = 2880
    decision_hours: int = 6
    delay_bars: int = 1
    max_positions: int = 2
    position_gross: float = 5.0
    exit_mode: str = "dual"
    core_mode: str = "dual"

    def __post_init__(self):
        if (self.rank_hours < 1 or self.trend_hours < self.rank_hours or
                self.mean_hours < self.trend_hours or self.decision_hours < 1 or
                self.delay_bars < 1 or self.max_positions < 1 or
                self.position_gross <= 0):
            raise ValueError("invalid_portfolio_rule")
        if self.exit_mode not in ("either", "dual"):
            raise ValueError("invalid_portfolio_exit_mode")
        if self.core_mode not in ("pool", "dual"):
            raise ValueError("invalid_portfolio_core_mode")


def _group(symbol):
    return "crypto" if symbol in ("ETHUSDT", "SOLUSDT") else "etf"


def _eligible(panel, f, signal, j, rule):
    return bool(
        np.isfinite(f["rank_return"][signal, j]) and
        panel["close"][signal, j] > f["trend_mean"][signal, j] and
        f["trend_return"][signal, j] > 0 and
        f["rank_return"][signal, j] > 0
    )


def _failed(panel, f, signal, j, rule):
    price = panel["close"][signal, j] <= f["trend_mean"][signal, j]
    momentum = f["trend_return"][signal, j] <= 0
    return bool(price or momentum if rule.exit_mode == "either" else price and momentum)


def _ranked_candidates(panel, f, signal, rule, held):
    names = panel["symbols"]
    ranked = [j for j in range(len(names)) if j not in held and
              _eligible(panel, f, signal, j, rule)]
    ranked.sort(key=lambda j: (-float(f["rank_return"][signal, j]), names[j]))
    slots = max(0, rule.max_positions - len(held))
    if not slots:
        return []
    if rule.core_mode == "pool":
        return ranked[:slots]

    # Dual-core selection always requires one crypto and one ETF, including
    # after one side exits.  Fill a missing group before considering a third
    # slot; this prevents an ETH+SOL replacement from silently removing the
    # ETF core.
    by_group = {"crypto": [], "etf": []}
    for j in ranked:
        by_group[_group(names[j])].append(j)
    held_groups = {_group(names[j]) for j in held}
    if "crypto" not in held_groups and not by_group["crypto"]:
        return []
    if "etf" not in held_groups and not by_group["etf"]:
        return []
    picked = []
    if "crypto" not in held_groups:
        picked.append(by_group["crypto"][0])
    if "etf" not in held_groups:
        picked.append(by_group["etf"][0])
    picked_set = set(picked)
    picked.extend(j for j in ranked if j not in picked_set)
    return picked[:slots]


def _liq_state(equity, positions, panel, i, maintenance, liquidation_fee):
    """Return shared-wallet liquidation status and conservative equity bound."""
    worst = float(equity)
    mark_notional = 0.0
    maintenance_value = 0.0
    for j, q, _ in positions.values():
        low = float(panel["mark_low"][i, j])
        open_price = float(panel["open"][i, j])
        debit = float(panel["funding_debit"][i, j])
        worst += q * (low - open_price) - debit
        mark_notional += q * low
        maintenance_value += q * low * maintenance
    triggered = bool(positions and worst <= maintenance_value)
    if not triggered:
        return False, worst, float(equity)
    remaining = max(0.0, worst - mark_notional * liquidation_fee)
    return True, worst, remaining


def replay(panel, f, rule, *, start, end, capital=21.25, cost_bp=10.0,
           filters=None, maintenance=0.005, liquidation_fee=0.01,
           keep_records=True, variable_clock=False):
    """Replay a fixed-quantity portfolio on a shared cross-margin wallet.

    ``position_gross`` is the initial notional/equity for each newly opened
    position.  It is deliberately not a target to be maintained: quantities
    remain unchanged until a complete exit.  Thus two 10x positions represent
    roughly 20x initial portfolio gross exposure.
    """
    if capital <= 0 or cost_bp < 0 or not 0 <= maintenance < 1 or liquidation_fee < 0:
        raise ValueError("invalid_portfolio_account")
    times = np.asarray(panel["times"], dtype=np.int64)
    if len(times) < 2 or np.any(np.diff(times) <= 0) or (
            not variable_clock and np.any(np.diff(times) != 3600)):
        raise ValueError("hourly_clock_gap")
    left = int(np.searchsorted(times, start, side="left"))
    right = int(np.searchsorted(times, end, side="left"))
    if left < rule.mean_hours + rule.delay_bars or right <= left or right >= len(times):
        raise ValueError("invalid_portfolio_window_or_warmup")

    names = tuple(panel["symbols"])
    fee = cost_bp / 10000.0
    equity = float(capital)
    positions = {}  # symbol -> (column, fixed quantity, entry index)
    counts, curve, fills, holdings = Counter(), [], [], []
    attribution = {s: dict(price=0.0, funding=0.0, costs=0.0) for s in names}
    highwater = equity
    adverse_mdd = 0.0
    max_gross = 0.0
    gross_history = []
    holding_hours = []
    ruined = False

    def close_symbol(symbol, i, reason, price=None):
        nonlocal equity
        j, q, entry = positions.pop(symbol)
        px = float(panel["open"][i, j] if price is None else price)
        charge = q * px * fee
        equity -= charge
        attribution[symbol]["costs"] += charge
        fills.append(dict(time=int(times[i]), symbol=symbol, side="SELL",
                          quantity=float(q), price=px, costs=float(charge),
                          reason=reason, holding_hours=int(i - entry)))
        counts[reason] += 1
        holding_hours.append(int(i - entry))

    for i in range(left, right):
        before = equity
        signal = i - rule.delay_bars
        scheduled = int(times[signal] // 3600) % rule.decision_hours == rule.decision_hours - 1
        price_pnl = funding_pnl = 0.0
        interval_costs = 0.0

        # Signal-driven exits are complete exits.  A rank change alone never
        # closes a live position.
        for symbol, (j, _, _) in list(positions.items()):
            if _failed(panel, f, signal, j, rule):
                close_symbol(symbol, i, "trend_exit")

        if scheduled and equity > 0 and len(positions) < rule.max_positions:
            candidates = _ranked_candidates(panel, f, signal, rule,
                                            {names.index(s) for s in positions})
            for j in candidates:
                if len(positions) >= rule.max_positions:
                    break
                symbol = names[j]
                price = float(panel["open"][i, j])
                notional = equity * rule.position_gross / (1 + rule.position_gross * fee)
                quantity = rounded_quantity(notional, price, symbol, filters)
                if quantity <= 0:
                    counts["minimum_notional_skip"] += 1
                    continue
                charge = quantity * price * fee
                equity -= charge
                attribution[symbol]["costs"] += charge
                positions[symbol] = (j, quantity, i)
                fills.append(dict(time=int(times[i]), symbol=symbol, side="BUY",
                                  quantity=float(quantity), price=price,
                                  costs=float(charge), reason="rank_entry"))
                counts["entry"] += 1

        liquidated, worst, liquidation_equity = _liq_state(
            equity, positions, panel, i, maintenance, liquidation_fee)
        if liquidated:
            # Allocate the mark-to-market loss by position for diagnostics;
            # the account itself is closed as one shared-wallet event.
            liquidation_positions = list(positions.items())
            mark_loss = 0.0
            funding_loss = 0.0
            liquidation_fee_value = 0.0
            for symbol, (j, q, entry) in liquidation_positions:
                low = float(panel["mark_low"][i, j])
                open_price = float(panel["open"][i, j])
                debit = float(panel["funding_debit"][i, j])
                mark_loss += q * (low - open_price)
                funding_loss -= debit
                liquidation_fee_value += q * low * liquidation_fee
                attribution[symbol]["price"] += q * (low - open_price)
                attribution[symbol]["funding"] -= debit
                fills.append(dict(time=int(times[i]), symbol=symbol, side="SELL",
                                  quantity=float(q), price=low, costs=0.0,
                                  reason="shared_liquidation",
                                  holding_hours=int(i - entry)))
                holding_hours.append(int(i - entry))
            for symbol, (j, q, _) in liquidation_positions:
                low = float(panel["mark_low"][i, j])
                share = (q * low / max(sum(
                    qq * float(panel["mark_low"][i, jj])
                    for _, (jj, qq, _) in liquidation_positions), 1e-30))
                attribution[symbol]["costs"] += liquidation_fee_value * share
            positions.clear()
            counts["shared_liquidation"] += 1
            price_pnl = mark_loss
            funding_pnl = funding_loss
            equity = liquidation_equity
            counts["ruin"] += int(equity <= 0 and not ruined)
            ruined = ruined or equity <= 0
            adverse_mdd = 1.0
        else:
            # Open-to-open P&L and funding accrue independently per fixed lot.
            for symbol, (j, q, _) in list(positions.items()):
                px = float(panel["open"][i, j])
                pnl = q * (float(panel["open"][i + 1, j]) - px)
                funding = -q * float(panel["funding_value"][i, j])
                equity += pnl + funding
                price_pnl += pnl
                funding_pnl += funding
                attribution[symbol]["price"] += pnl
                attribution[symbol]["funding"] += funding
                if funding < 0:
                    counts["funding_debit_intervals"] += 1
            adverse_mdd = max(adverse_mdd,
                              1 - max(0.0, worst) / max(highwater, 1e-30))

        if i == right - 1 and positions and equity > 0:
            for symbol in list(positions):
                close_symbol(symbol, i + 1, "terminal_exit")
            counts["terminal_exit"] += 0  # close_symbol owns the event count

        if equity <= 0:
            equity = 0.0
            positions.clear()
            if not ruined:
                counts["ruin"] += 1
                ruined = True

        # Costs are tracked in attribution and exposed as the residual needed
        # for exact equity reconciliation.
        interval_costs = before + price_pnl + funding_pnl - equity
        highwater = max(highwater, equity)
        gross = sum(q * float(panel["open"][i, j]) for j, q, _ in positions.values()) / max(equity, 1e-30)
        max_gross = max(max_gross, gross)
        gross_history.append(gross)
        curve.append(dict(time=int(times[i + 1]), equity=float(equity),
                          returns=float(equity / before - 1) if before else 0.0,
                          price_pnl=float(price_pnl), funding_pnl=float(funding_pnl),
                          costs=float(interval_costs), gross=float(gross),
                          positions=tuple(sorted(positions))))
        holdings.append(dict(time=int(times[i]), symbols=tuple(sorted(positions))))

    nav = np.asarray([capital, *[r["equity"] for r in curve]]) / capital
    mdd = float(np.max(1 - nav / np.maximum.accumulate(nav)))
    years = (times[right] - times[left]) / (365.25 * 86400)
    elapsed_seconds = int(times[right] - times[left])
    cagr = float(nav[-1] ** (1 / years) - 1) if nav[-1] > 0 else -1.0
    summary = dict(
        start=datetime.fromtimestamp(int(times[left]), timezone.utc).isoformat(),
        end_open=datetime.fromtimestamp(int(times[right]), timezone.utc).isoformat(),
        bars=right - left, elapsed_seconds=elapsed_seconds,
        hours=elapsed_seconds / 3600.0,
        initial_usdt=float(capital), final_usdt=float(equity),
        return_pct=float((nav[-1] - 1) * 100), cagr_pct=cagr * 100,
        mdd_pct=mdd * 100, calmar=cagr / mdd if mdd else None,
        intraday_drawdown_bound_pct=adverse_mdd * 100,
        max_positions=rule.max_positions, position_gross=rule.position_gross,
        max_actual_gross=float(max_gross),
        mean_actual_gross=float(np.mean(gross_history)) if gross_history else 0.0,
        active_hours=int(sum(x > 0 for x in gross_history)),
        mean_holding_days=float(np.mean(holding_hours) / 24) if holding_hours else None,
        median_holding_days=float(np.median(holding_hours) / 24) if holding_hours else None,
        max_holding_days=float(max(holding_hours) / 24) if holding_hours else None,
        funding_pnl=float(sum(v["funding"] for v in attribution.values())),
        price_pnl=float(sum(v["price"] for v in attribution.values())),
        costs=float(sum(v["costs"] for v in attribution.values())),
        counts=dict(counts), attribution=attribution,
    )
    return dict(summary=summary, curve=curve,
                fills=fills if keep_records else [], holdings=holdings if keep_records else [])
