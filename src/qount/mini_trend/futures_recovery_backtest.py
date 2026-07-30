"""Offline historical diagnostic for the preregistered USD-M recovery candidate."""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.mini_trend.signals import sma, target_weights
from qount.research_data.indicators import ATR


_DAY_MS = 86_400_000


@dataclass(frozen=True)
class VariantResult:
    metrics: dict[str, Any]
    equity: list[dict[str, Any]]


BaseConfigSelector = Callable[
    [Mapping[str, Sequence[Bar]]],
    tuple[MiniTrendConfig, str],
]
BaseConfigFeedback = Callable[[str, set[str]], None]
DesiredWeightsTransform = Callable[
    [
        Mapping[str, Sequence[Bar]],
        MiniTrendConfig,
        Mapping[str, float],
        Mapping[str, float],
    ],
    Mapping[str, float],
]
DesiredWeightsSelector = Callable[
    [
        Mapping[str, Sequence[Bar]],
        Mapping[str, Mapping[str, Any]],
        float,
        MiniTrendConfig,
    ],
    tuple[Mapping[str, float], str, bool],
]


def _std_returns(bars: Sequence[Bar], lookback: int = 20) -> float:
    closes = [bar.close for bar in bars]
    values = [closes[i] / closes[i - 1] - 1.0 for i in range(len(closes) - lookback, len(closes))]
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _atr_last(bars: Sequence[Bar], lookback: int = 14) -> float | None:
    atr = ATR(lookback)
    value = None
    for bar in bars:
        value = atr.update(bar)
    return value


def recovery_confirmed(bars: Mapping[str, Sequence[Bar]]) -> bool:
    protocol = FUTURES_RECOVERY_PROTOCOL
    required = math.ceil(protocol.recovery_breadth * len(TOP3) - 1e-12)
    for offset in range(protocol.recovery_confirmation_bars):
        btc = list(bars["BTCUSDT"][: len(bars["BTCUSDT"]) - offset])
        btc_sma = sma([bar.close for bar in btc], protocol.recovery_sma)
        if btc_sma is None or btc[-1].close <= btc_sma:
            return False
        above = 0
        for symbol in TOP3:
            rows = list(bars[symbol][: len(bars[symbol]) - offset])
            average = sma([bar.close for bar in rows], protocol.recovery_sma)
            above += int(average is not None and rows[-1].close > average)
        if above < required:
            return False
    return True


def _floor_usdt(rule: Mapping[str, Any], price: float) -> float:
    return max(float(rule.get("min_notional") or 0.0), float(rule.get("min_qty") or 0.0) * price)


def allocate_with_filters(
    raw_weights: Mapping[str, float],
    gross: float,
    equity: float,
    prices: Mapping[str, float],
    rules: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, float], bool]:
    protocol = FUTURES_RECOVERY_PROTOCOL
    active = {symbol: max(float(weight), 0.0) for symbol, weight in raw_weights.items() if weight > 0}
    if not active or gross <= 0 or equity <= 0:
        return {symbol: 0.0 for symbol in TOP3}, True
    floors = {
        symbol: _floor_usdt(rules[symbol], prices[symbol]) * protocol.filter_buffer / equity
        for symbol in active
    }
    required = sum(floors.values())
    if required > gross + 1e-12:
        return {symbol: 0.0 for symbol in TOP3}, False
    raw_total = sum(active.values())
    remainder = gross - required
    weights = {symbol: 0.0 for symbol in TOP3}
    for symbol, raw in active.items():
        weights[symbol] = floors[symbol] + remainder * raw / raw_total
    return weights, True


def enforce_gross_cap(
    target: Mapping[str, float],
    maximum_gross: float,
    equity: float,
    prices: Mapping[str, float],
    rules: Mapping[str, Mapping[str, Any]],
    *,
    policy: str,
) -> tuple[dict[str, float], bool]:
    gross = sum(max(float(weight), 0.0) for weight in target.values())
    normalized = {symbol: max(float(target.get(symbol, 0.0)), 0.0) for symbol in TOP3}
    if gross <= maximum_gross + 1e-12:
        return normalized, False
    if policy == "fail_closed":
        raise ValueError("effective gross exceeded preregistered cap")
    if policy != "renormalize_active_targets_with_filter_floors":
        raise ValueError(f"unknown gross cap policy: {policy}")
    allocated, feasible = allocate_with_filters(
        normalized,
        maximum_gross,
        equity,
        prices,
        rules,
    )
    if not feasible:
        raise ValueError("gross cap normalization cannot satisfy runtime filters")
    return allocated, True


def desired_weights(
    bars: Mapping[str, Sequence[Bar]],
    rules: Mapping[str, Mapping[str, Any]],
    equity: float,
    *,
    recovery_enabled: bool,
    base_config: MiniTrendConfig | None = None,
) -> tuple[dict[str, float], str, bool]:
    cfg = base_config or frozen_top3_config()
    base = target_weights(bars, cfg)
    prices = {symbol: bars[symbol][-1].close for symbol in TOP3}
    if base.gate.risk_on:
        raw = {symbol: weight for symbol, weight in base.targets.items() if weight > 0}
        gross = min(sum(raw.values()), FUTURES_RECOVERY_PROTOCOL.maximum_effective_gross)
        allocated, feasible = allocate_with_filters(raw, gross, equity, prices, rules)
        return allocated, "base_trend", feasible
    if not recovery_enabled or not recovery_confirmed(bars):
        return {symbol: 0.0 for symbol in TOP3}, "cash", True
    eligible = {}
    for symbol in TOP3:
        rows = bars[symbol]
        average = sma([bar.close for bar in rows], FUTURES_RECOVERY_PROTOCOL.recovery_sma)
        volatility = _std_returns(rows)
        if average is not None and rows[-1].close > average and volatility > 0:
            eligible[symbol] = 1.0 / volatility
    allocated, feasible = allocate_with_filters(
        eligible,
        FUTURES_RECOVERY_PROTOCOL.recovery_maximum_gross,
        equity,
        prices,
        rules,
    )
    return allocated, "recovery" if feasible else "cash_filter_blocked", feasible


def _funding_sums(
    funding: Mapping[str, Sequence[Funding]], start_ms: int, end_ms: int
) -> dict[str, float]:
    return {
        symbol: sum(row.rate for row in funding.get(symbol, []) if start_ms < row.ts_ms <= end_ms)
        for symbol in TOP3
    }


def run_variant(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    rules: Mapping[str, Mapping[str, Any]],
    *,
    recovery_enabled: bool,
    base_config: MiniTrendConfig | None = None,
    base_config_selector: BaseConfigSelector | None = None,
    base_config_feedback: BaseConfigFeedback | None = None,
    desired_weights_selector: DesiredWeightsSelector | None = None,
    desired_weights_transform: DesiredWeightsTransform | None = None,
    daily_chandelier_atr_multiple: float | None = None,
    stop_cooldown_completed_bars: int | None = None,
    gross_cap_policy: str = "fail_closed",
    capital_usdt: float | None = None,
    transaction_cost_multiplier: float = 1.0,
    funding_multiplier: float = 1.0,
) -> VariantResult:
    protocol = FUTURES_RECOVERY_PROTOCOL
    initial_capital = protocol.capital_usdt if capital_usdt is None else float(capital_usdt)
    if not math.isfinite(initial_capital) or initial_capital <= 0.0:
        raise ValueError("initial capital must be positive and finite")
    if not math.isfinite(transaction_cost_multiplier) or transaction_cost_multiplier < 0.0:
        raise ValueError("transaction cost multiplier must be finite and non-negative")
    if not math.isfinite(funding_multiplier) or funding_multiplier < 0.0:
        raise ValueError("funding multiplier must be finite and non-negative")
    cfg = base_config or frozen_top3_config()
    chandelier_multiple = (
        protocol.daily_chandelier_atr_multiple
        if daily_chandelier_atr_multiple is None
        else daily_chandelier_atr_multiple
    )
    cooldown_bars = (
        protocol.stop_cooldown_completed_bars
        if stop_cooldown_completed_bars is None
        else stop_cooldown_completed_bars
    )
    bars = align_bars(bars_by_symbol, TOP3)
    n = len(bars["BTCUSDT"])
    warmup = max(cfg.gate_sma, cfg.trend_sma, cfg.slow_sma, protocol.recovery_sma)
    if n <= warmup + 1:
        raise ValueError(f"insufficient UM daily bars: {n}")
    equity = initial_capital
    previous = {symbol: 0.0 for symbol in TOP3}
    trail_high: dict[str, float] = {}
    cooldown_until: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    order_count = decision_batches = stop_count = stop_reentry = 0
    floor_failures = blocked_rebalances = recovery_bars = gross_cap_normalizations = 0
    cost_usdt = funding_usdt = 0.0

    for index in range(warmup, n - 1):
        window = {symbol: bars[symbol][: index + 1] for symbol in TOP3}
        prices = {symbol: window[symbol][-1].close for symbol in TOP3}
        active_cfg, risk_stage = (
            base_config_selector(window) if base_config_selector is not None else (cfg, "fixed")
        )
        if not risk_stage:
            raise ValueError("base config selector returned an empty risk stage")
        if desired_weights_selector is None:
            desired, mode, feasible = desired_weights(
                window,
                rules,
                equity,
                recovery_enabled=recovery_enabled,
                base_config=active_cfg,
            )
        else:
            selected, mode, feasible = desired_weights_selector(
                window,
                rules,
                equity,
                active_cfg,
            )
            desired = {symbol: float(selected.get(symbol, 0.0)) for symbol in TOP3}
            if set(selected) != set(TOP3):
                raise ValueError("desired weights selector must return exactly TOP3")
            if any(not math.isfinite(value) or value < 0.0 for value in desired.values()):
                raise ValueError("desired weights selector returned an invalid target")
        if desired_weights_transform is not None:
            desired = dict(
                desired_weights_transform(window, active_cfg, desired, previous)
            )
            if set(desired) != set(TOP3):
                raise ValueError("desired weights transform must return exactly TOP3")
            if any(not math.isfinite(float(value)) or float(value) < 0 for value in desired.values()):
                raise ValueError("desired weights transform returned an invalid target")
        floor_failures += int(not feasible)
        stopped: set[str] = set()
        for symbol in TOP3:
            if previous[symbol] <= 0:
                continue
            trail_high[symbol] = max(trail_high.get(symbol, prices[symbol]), prices[symbol])
            atr = _atr_last(window[symbol], active_cfg.atr_lookback)
            if atr is not None and prices[symbol] <= trail_high[symbol] - chandelier_multiple * atr:
                desired[symbol] = 0.0
                cooldown_until[symbol] = index + cooldown_bars
                stopped.add(symbol)
                stop_count += 1
        for symbol, release_index in cooldown_until.items():
            if index <= release_index:
                desired[symbol] = 0.0
        if base_config_feedback is not None:
            base_config_feedback(risk_stage, stopped)

        target = dict(desired)
        for symbol in TOP3:
            current, wanted = previous[symbol], target[symbol]
            if wanted > 0 and current > 0:
                denominator = max(wanted, current)
                if abs(wanted - current) < active_cfg.rebalance_band * denominator:
                    target[symbol] = current
                    continue
            if wanted > 0 and abs(wanted - current) * equity < _floor_usdt(rules[symbol], prices[symbol]):
                target[symbol] = current
                blocked_rebalances += 1
        target, normalized = enforce_gross_cap(
            target,
            protocol.maximum_effective_gross,
            equity,
            prices,
            rules,
            policy=gross_cap_policy,
        )
        gross_cap_normalizations += int(normalized)
        gross = sum(target.values())
        stop_reentry += sum(1 for symbol in stopped if target[symbol] > 0)
        changes = [symbol for symbol in TOP3 if abs(target[symbol] - previous[symbol]) > 1e-12]
        turnover = sum(abs(target[symbol] - previous[symbol]) for symbol in TOP3)
        order_count += len(changes)
        decision_batches += int(bool(changes))
        recovery_bars += int(mode == "recovery" and gross > 0)

        next_prices = {symbol: bars[symbol][index + 1].close for symbol in TOP3}
        gross_return = sum(
            target[symbol] * (next_prices[symbol] / prices[symbol] - 1.0) for symbol in TOP3
        )
        funding_rates = _funding_sums(
            funding,
            bars["BTCUSDT"][index].ts_ms + _DAY_MS,
            bars["BTCUSDT"][index + 1].ts_ms + _DAY_MS,
        )
        funding_return = (
            -sum(target[symbol] * funding_rates[symbol] for symbol in TOP3)
            * funding_multiplier
        )
        trading_cost = (
            turnover
            * (protocol.taker_fee_bps + protocol.slippage_bps)
            / 10_000.0
            * transaction_cost_multiplier
        )
        before = equity
        net_return = gross_return + funding_return - trading_cost
        equity *= 1.0 + net_return
        if equity <= 0:
            raise ValueError("candidate equity became non-positive")
        cost_usdt += before * trading_cost
        funding_usdt += before * funding_return
        row = {
                "decision_date": bars["BTCUSDT"][index].date,
                "outcome_date": bars["BTCUSDT"][index + 1].date,
                "equity": round(equity, 8),
                "mode": mode,
                "risk_stage": risk_stage,
                "gross": round(gross, 8),
                "turnover": round(turnover, 8),
                "orders": len(changes),
                "stopped": sorted(stopped),
                "gross_price_return": gross_return,
                "funding_return": funding_return,
                "trading_cost_return": -trading_cost,
                "net_return": net_return,
            }
        rows.append(row)
        for symbol in TOP3:
            if target[symbol] > 0:
                if previous[symbol] <= 0:
                    trail_high[symbol] = prices[symbol]
            elif index > cooldown_until.get(symbol, -1):
                trail_high.pop(symbol, None)
        previous = target
        selector_snapshot = getattr(base_config_selector, "state_snapshot", None)
        transform_snapshot = getattr(desired_weights_transform, "state_snapshot", None)
        row["execution_state"] = {
            "decision_risk_stage": risk_stage,
            "active_vol_target": active_cfg.vol_target,
            "target_weights": {symbol: target[symbol] for symbol in TOP3},
            "trail_high": {
                symbol: trail_high[symbol] for symbol in TOP3 if symbol in trail_high
            },
            "cooldown_remaining": {
                symbol: max(cooldown_until.get(symbol, index) - index, 0)
                for symbol in TOP3
            },
            "selector_state": (
                dict(selector_snapshot()) if callable(selector_snapshot) else {}
            ),
            "desired_transform_state": (
                dict(transform_snapshot()) if callable(transform_snapshot) else {}
            ),
        }

    values = [initial_capital] + [float(row["equity"]) for row in rows]
    metrics = {
        "start": rows[0]["decision_date"],
        "end": rows[-1]["outcome_date"],
        "return_pct": round((equity / initial_capital - 1.0) * 100.0, 8),
        "max_drawdown_pct": round(max_drawdown_pct(values), 8),
        "order_count": order_count,
        "decision_batch_count": decision_batches,
        "duplicate_decision_count": 0,
        "active_bar_count": sum(1 for row in rows if row["gross"] > 0),
        "recovery_bar_count": recovery_bars,
        "stop_count": stop_count,
        "same_bar_stop_reentry_count": stop_reentry,
        "floor_allocation_failure_count": floor_failures,
        "blocked_small_rebalance_count": blocked_rebalances,
        "gross_cap_normalization_count": gross_cap_normalizations,
        "runtime_filter_coverage": 1.0,
        "trading_cost_usdt": round(cost_usdt, 8),
        "funding_pnl_usdt": round(funding_usdt, 8),
        "transaction_cost_multiplier": transaction_cost_multiplier,
        "funding_multiplier": funding_multiplier,
    }
    return VariantResult(metrics=metrics, equity=rows)
