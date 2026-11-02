"""Fixed-quantity, multi-position hourly G20-style portfolio replay.

This module is research-only.  A position is opened once at a scheduled
hourly decision and is closed in full on a trend failure.  All positions
share one wallet and therefore one liquidation boundary.  The contract
sizing is fixed quantity between exits; ``position_mode="fraction"`` exists
only as a sizing ablation against gross drift.
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
    # dual: a missing core group with no eligible candidate blocks all entries.
    # dual_relaxed: fill a missing core when possible, otherwise top up freely.
    # position_mode fixed: quantities frozen between full exits (contract).
    # position_mode fraction: quantities resized to equity*position_gross at
    # each scheduled decision, as a sizing ablation against gross drift.
    # position_mode risk_parity: inverse-vol weights over held+entering slots,
    # total book gross == position_gross (NOT per-slot like fixed/fraction),
    # resized at each scheduled decision; needs replay(vol=...).
    # require_rank_positive: entry also needs positive 7-period rank momentum.
    # min_trend_age: require N bars of continuous close>trend_mean before entry.
    # max_crypto: cap on simultaneous crypto slots (0 = unlimited).
    # dd_deleverage_threshold/factor: deliberate drawdown exposure rule — while
    # account equity sits at least this far below its highwater mark, resize and
    # entry gross is multiplied by the factor, restoring automatically when
    # equity recovers.  0.0 threshold disables the rule.
    position_mode: str = "fixed"
    require_rank_positive: bool = True
    min_trend_age: int = 0
    max_crypto: int = 0
    crypto_symbols: tuple = ("ETHUSDT", "SOLUSDT")
    dd_deleverage_threshold: float = 0.0
    dd_deleverage_factor: float = 1.0

    def __post_init__(self):
        if (self.rank_hours < 1 or self.trend_hours < self.rank_hours or
                self.mean_hours < self.trend_hours or self.decision_hours < 1 or
                self.delay_bars < 1 or self.max_positions < 1 or
                self.position_gross <= 0 or self.min_trend_age < 0 or
                self.max_crypto < 0):
            raise ValueError("invalid_portfolio_rule")
        if not 0 <= self.dd_deleverage_threshold < 1 or not 0 < self.dd_deleverage_factor <= 1:
            raise ValueError("invalid_portfolio_dd_deleverage")
        if self.exit_mode not in ("either", "dual"):
            raise ValueError("invalid_portfolio_exit_mode")
        if self.core_mode not in ("pool", "dual", "dual_relaxed"):
            raise ValueError("invalid_portfolio_core_mode")
        if self.position_mode not in ("fixed", "fraction", "risk_parity"):
            raise ValueError("invalid_portfolio_position_mode")
        if not isinstance(self.require_rank_positive, bool):
            raise ValueError("invalid_portfolio_rule")


def _group(symbol, rule):
    return "crypto" if symbol in rule.crypto_symbols else "etf"


def _eligible(panel, f, signal, j, rule):
    return bool(
        np.isfinite(f["rank_return"][signal, j]) and
        panel["close"][signal, j] > f["trend_mean"][signal, j] and
        f["trend_return"][signal, j] > 0 and
        (f["rank_return"][signal, j] > 0 or not rule.require_rank_positive) and
        (rule.min_trend_age <= 0 or
         int(f["trend_age"][signal, j]) >= rule.min_trend_age)
    )


def _failed(panel, f, signal, j, rule):
    price = panel["close"][signal, j] <= f["trend_mean"][signal, j]
    momentum = f["trend_return"][signal, j] <= 0
    return bool(price or momentum if rule.exit_mode == "either" else price and momentum)


def _ranked_candidates(panel, f, signal, rule, held):
    names = panel["symbols"]
    ranked = [j for j in range(len(names)) if j not in held and
              _eligible(panel, f, signal, j, rule)]
    scores = f["rank_score"] if "rank_score" in f else f["rank_return"]
    ranked.sort(key=lambda j: (-float(scores[signal, j]), names[j]))
    slots = max(0, rule.max_positions - len(held))
    if not slots:
        return []
    if rule.core_mode == "pool":
        picked = ranked
    else:
        # Dual-core selection always requires one crypto and one ETF, including
        # after one side exits.  Fill a missing group before considering a third
        # slot; this prevents an ETH+SOL replacement from silently removing the
        # ETF core.  In strict "dual" mode a missing group with no eligible
        # candidate blocks every entry; "dual_relaxed" fills what it can and
        # otherwise tops up from the ranked pool.
        by_group = {"crypto": [], "etf": []}
        for j in ranked:
            by_group[_group(names[j], rule)].append(j)
        held_groups = {_group(names[j], rule) for j in held}
        if rule.core_mode == "dual":
            if "crypto" not in held_groups and not by_group["crypto"]:
                return []
            if "etf" not in held_groups and not by_group["etf"]:
                return []
        picked = []
        if "crypto" not in held_groups and by_group["crypto"]:
            picked.append(by_group["crypto"][0])
        if "etf" not in held_groups and by_group["etf"]:
            picked.append(by_group["etf"][0])
        picked_set = set(picked)
        picked.extend(j for j in ranked if j not in picked_set)
    # max_crypto caps simultaneous crypto slots across held + entering.
    if rule.max_crypto > 0:
        crypto_count = sum(1 for j in held if _group(names[j], rule) == "crypto")
        capped = []
        for j in picked:
            if _group(names[j], rule) == "crypto":
                if crypto_count >= rule.max_crypto:
                    continue
                crypto_count += 1
            capped.append(j)
            if len(capped) >= slots:
                break
        return capped
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
        # funding_debit is per unit; scale by quantity like the accrual path.
        worst += q * (low - open_price - debit)
        mark_notional += q * low
        maintenance_value += q * low * maintenance
    triggered = bool(positions and worst <= maintenance_value)
    if not triggered:
        return False, worst, float(equity)
    remaining = max(0.0, worst - mark_notional * liquidation_fee)
    return True, worst, remaining


def replay(panel, f, rule, *, start, end, capital=21.25, cost_bp=10.0,
           filters=None, maintenance=0.005, liquidation_fee=0.01,
           keep_records=True, variable_clock=False, vol=None,
           crypto_cost_bp=None):
    """Replay a fixed-quantity portfolio on a shared cross-margin wallet.

    ``position_gross`` is the initial notional/equity for each newly opened
    position.  It is deliberately not a target to be maintained: quantities
    remain unchanged until a complete exit.  Thus two 10x positions represent
    roughly 20x initial portfolio gross exposure.  ``position_mode="fraction"``
    overrides this and resizes held lots to ``equity * position_gross`` at
    every scheduled decision.  ``crypto_cost_bp`` optionally overrides the
    one-way cost on crypto legs only (latency/slippage stress on fills that
    assume the signal price).
    """
    if (capital <= 0 or cost_bp < 0 or not 0 <= maintenance < 1
            or liquidation_fee < 0 or (crypto_cost_bp is not None and crypto_cost_bp < 0)):
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
    crypto_fee = fee if crypto_cost_bp is None else crypto_cost_bp / 10000.0

    def fee_of(symbol):
        return crypto_fee if (crypto_cost_bp is not None and
                              _group(symbol, rule) == "crypto") else fee

    equity = float(capital)
    positions = {}  # symbol -> (column, fixed quantity, entry index)
    counts, curve, fills, holdings = Counter(), [], [], []
    attribution = {s: dict(price=0.0, funding=0.0, costs=0.0) for s in names}
    highwater = equity
    adverse_mdd = 0.0
    max_gross = 0.0
    gross_history = []
    holding_days = []
    holding_bars = []
    ruined = False

    def close_symbol(symbol, i, reason, price=None):
        nonlocal equity
        j, q, entry = positions.pop(symbol)
        px = float(panel["open"][i, j] if price is None else price)
        charge = q * px * fee_of(symbol)
        equity -= charge
        attribution[symbol]["costs"] += charge
        elapsed = int(times[i]) - int(times[entry])
        fills.append(dict(time=int(times[i]), symbol=symbol, side="SELL",
                          quantity=float(q), price=px, costs=float(charge),
                          reason=reason, holding_hours=elapsed // 3600,
                          holding_bars=int(i - entry),
                          holding_days=elapsed / 86400.0))
        counts[reason] += 1
        holding_days.append(elapsed / 86400.0)
        holding_bars.append(int(i - entry))

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

        # Deliberate drawdown de-leveraging: while account equity sits below
        # the highwater mark by at least the threshold, resize and entry gross
        # is scaled down and restores automatically on recovery.  Decisions
        # use start-of-bar equity, so the rule reacts at decision points only.
        dd_now = 1.0 - equity / highwater if highwater > 0 else 0.0
        live_gross = rule.position_gross
        if rule.dd_deleverage_threshold > 0 and dd_now >= rule.dd_deleverage_threshold:
            live_gross *= rule.dd_deleverage_factor

        # Fraction sizing ablation: at each scheduled decision resize every
        # held lot to equity*position_gross at the current open, charging the
        # fee on the traded delta.  Fixed mode never touches quantities.
        if scheduled and equity > 0 and rule.position_mode == "fraction" and positions:
            for symbol, (j, q, entry) in list(positions.items()):
                price = float(panel["open"][i, j])
                target = rounded_quantity(equity * live_gross,
                                          price, symbol, filters)
                if target <= 0:
                    # Below-minimum target means the slot is cash (contract).
                    close_symbol(symbol, i, "min_notional_exit")
                    continue
                delta = target - q
                if delta:
                    charge = abs(delta) * price * fee_of(symbol)
                    equity -= charge
                    attribution[symbol]["costs"] += charge
                    positions[symbol] = (j, target, entry)
            counts["resize_intervals"] += 1

        # Risk-parity sizing: entries and resizes are sized together so that
        # every slot (held or entering) carries equal risk.  position_gross is
        # the TOTAL book gross target here.  A slot whose target rounds below
        # the exchange minimum goes to cash: unheld slots are skipped, held
        # slots are closed.  Weights are decided once per bar from the
        # decision-time vol matrix, so a dropped slot's share stays cash
        # exactly like a skipped entry instead of being redistributed.
        if scheduled and equity > 0 and rule.position_mode == "risk_parity":
            entering = []
            if len(positions) < rule.max_positions:
                held_idx = {names.index(s) for s in positions}
                for j in _ranked_candidates(panel, f, signal, rule, held_idx):
                    if len(positions) + len(entering) >= rule.max_positions:
                        break
                    entering.append(j)
            book = [(names.index(s), s, True) for s in positions]
            book += [(j, names[j], False) for j in entering]
            inv = {}
            for j, symbol, _ in book:
                v = float(vol[signal, j]) if vol is not None else 1.0
                inv[symbol] = 1.0 / max(v, 1e-8)
            total_inv = sum(inv.values())
            for j, symbol, already_held in book:
                notional = equity * live_gross * inv[symbol] / total_inv
                price = float(panel["open"][i, j])
                quantity = rounded_quantity(notional, price, symbol, filters)
                if quantity <= 0:
                    if not already_held:
                        counts["minimum_notional_skip"] += 1
                    else:
                        # Contract: a below-minimum slot is cash, not a stale
                        # frozen lot.  Closing keeps realized gross bounded by
                        # the decision-time target at every capital size.
                        close_symbol(symbol, i, "min_notional_exit")
                    continue
                old_q = positions[symbol][1] if already_held else 0.0
                delta = quantity - old_q
                charge = abs(delta) * price * fee_of(symbol)
                equity -= charge
                attribution[symbol]["costs"] += charge
                if already_held:
                    positions[symbol] = (j, quantity, positions[symbol][2])
                else:
                    positions[symbol] = (j, quantity, i)
                    fills.append(dict(time=int(times[i]), symbol=symbol, side="BUY",
                                      quantity=float(quantity), price=price,
                                      costs=float(charge), reason="rank_entry"))
                    counts["entry"] += 1
            if book:
                counts["resize_intervals"] += 1

        if (scheduled and equity > 0 and rule.position_mode != "risk_parity"
                and len(positions) < rule.max_positions):
            candidates = _ranked_candidates(panel, f, signal, rule,
                                            {names.index(s) for s in positions})
            for j in candidates:
                if len(positions) >= rule.max_positions:
                    break
                symbol = names[j]
                price = float(panel["open"][i, j])
                slot_fee = fee_of(symbol)
                notional = equity * live_gross / (1 + live_gross * slot_fee)
                quantity = rounded_quantity(notional, price, symbol, filters)
                if quantity <= 0:
                    counts["minimum_notional_skip"] += 1
                    continue
                charge = quantity * price * slot_fee
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
                funding_loss -= q * debit
                liquidation_fee_value += q * low * liquidation_fee
                attribution[symbol]["price"] += q * (low - open_price)
                attribution[symbol]["funding"] -= q * debit
                elapsed = int(times[i]) - int(times[entry])
                fills.append(dict(time=int(times[i]), symbol=symbol, side="SELL",
                                  quantity=float(q), price=low, costs=0.0,
                                  reason="shared_liquidation",
                                  holding_hours=elapsed // 3600,
                                  holding_bars=int(i - entry),
                                  holding_days=elapsed / 86400.0))
                holding_days.append(elapsed / 86400.0)
                holding_bars.append(int(i - entry))
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
    # Statistical-reality reporting: always expose trade counts and per-symbol
    # concentration so small samples cannot masquerade as robust mechanisms.
    symbol_trades = Counter(fl["symbol"] for fl in fills if fl["side"] == "BUY")
    trades = int(sum(symbol_trades.values()))
    nets = {s: v["price"] + v["funding"] - v["costs"] for s, v in attribution.items()}
    positives = sorted((v for v in nets.values() if v > 0), reverse=True)
    positive_sum = float(sum(positives))
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
        mean_holding_days=float(np.mean(holding_days)) if holding_days else None,
        median_holding_days=float(np.median(holding_days)) if holding_days else None,
        max_holding_days=float(max(holding_days)) if holding_days else None,
        mean_holding_bars=float(np.mean(holding_bars)) if holding_bars else None,
        median_holding_bars=float(np.median(holding_bars)) if holding_bars else None,
        max_holding_bars=float(max(holding_bars)) if holding_bars else None,
        funding_pnl=float(sum(v["funding"] for v in attribution.values())),
        price_pnl=float(sum(v["price"] for v in attribution.values())),
        costs=float(sum(v["costs"] for v in attribution.values())),
        trades=trades, symbols_traded=int(len(symbol_trades)),
        symbol_trades=dict(symbol_trades),
        top1_positive_pnl_share=float(positives[0] / positive_sum) if positive_sum > 0 else None,
        top3_positive_pnl_share=float(sum(positives[:3]) / positive_sum) if positive_sum > 0 else None,
        path_evidence=bool(trades < 30),
        counts=dict(counts), attribution=attribution,
    )
    return dict(summary=summary, curve=curve,
                fills=fills if keep_records else [], holdings=holdings if keep_records else [])
