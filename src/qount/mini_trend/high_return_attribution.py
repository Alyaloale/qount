"""Offline attribution of the retired X4 headline returns.

The report deliberately preserves the legacy X4 readout and then recomputes the same final
strategies with all three daily USD-M funding settlements.  It is discovery evidence only: the
historical window has already been consumed and cannot promote a strategy.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict
from typing import Any, Callable, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import run_variant
from qount.models import utc_now
from qount.research_data.metrics import returns_from_curve, sharpe
from qount.settings import Settings
from qount.legacy.x4.backtest import X4Result, run_directional
from qount.legacy.x4.funding import holding_period_funding
from qount.legacy.x4.strategies import MomentumBreakout, TrendFollow


ATTRIBUTION_VERSION = "mini_trend_high_return_attribution_v0.1"
_DAY_MS = 86_400_000
_CAPITAL = 100_000.0
_TAKER_FEE = 0.0005
_SLIPPAGE = 0.0002


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _daily_funding(rows: Sequence[Funding]) -> dict[int, float]:
    out: dict[int, float] = {}
    for row in rows:
        day = row.ts_ms // _DAY_MS
        out[day] = out.get(day, 0.0) + row.rate
    return out


def _legacy_exact_funding(rows: Sequence[Funding]) -> Callable[[Bar], float]:
    by_ts = {row.ts_ms: row.rate for row in rows}
    return lambda bar: by_ts.get(bar.ts_ms, 0.0)


def _all_next_holding_day_funding(
    rows: Sequence[Funding], bars: Sequence[Bar]
) -> Callable[[Bar], float]:
    """Return all settlements during the next close-to-close holding day.

    ``run_directional`` asks for funding after trading each bar.  A signal traded at the completed
    daily close should therefore pay the next UTC day's 00:00/08:00/16:00 settlements.  The final
    bar has no subsequent holding period and is assigned zero.
    """

    by_bar = holding_period_funding(rows, bars, "1d")
    return lambda bar: by_bar.get(bar.ts_ms, 0.0)


def _summary(result: X4Result) -> dict[str, Any]:
    return {
        "total_return_pct": round(result.total_return * 100.0, 8),
        "sharpe": round(result.sharpe, 8),
        "max_drawdown_pct": round(abs(result.max_drawdown) * 100.0, 8),
        "trade_count": result.trade_count,
        "fees_paid_usdt": round(result.fees_paid, 8),
        "funding_pnl_usdt": round(result.funding_pnl, 8),
    }


def _delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, float]:
    return {
        "return_delta_pp": round(
            float(after["total_return_pct"]) - float(before["total_return_pct"]), 8
        ),
        "sharpe_delta": round(float(after["sharpe"]) - float(before["sharpe"]), 8),
        "max_drawdown_change_pp": round(
            float(after["max_drawdown_pct"]) - float(before["max_drawdown_pct"]), 8
        ),
    }


def _stage(
    btc_bars: Sequence[Bar],
    funding: Callable[[Bar], float] | None,
    *,
    interval: str,
    allow_short: bool,
    regime_sma: int = 0,
    s4_volume_multiple: float = 1.5,
    s4_exit_lookback: int = 20,
    rebalance_band: float = 0.25,
    vol_target: float = 0.0,
    max_leverage: float = 1.0,
    s4_chandelier: float = 0.0,
    taker_fee: float = _TAKER_FEE,
    slippage: float = _SLIPPAGE,
) -> tuple[X4Result, X4Result]:
    periods = 365.0 if interval == "1d" else 365.0 * 24.0
    common = {
        "initial_capital": _CAPITAL,
        "taker_fee": taker_fee,
        "slippage": slippage,
        "funding": funding,
        "rebalance_band": rebalance_band,
        "vol_target": vol_target,
        "max_leverage": max_leverage,
        "periods_per_year": periods,
    }
    s3 = run_directional(
        btc_bars,
        TrendFollow(fast=20, slow=100, allow_short=allow_short, regime_sma=regime_sma),
        **common,
    )
    s4 = run_directional(
        btc_bars,
        MomentumBreakout(
            lookback=20,
            exit_lookback=s4_exit_lookback,
            vol_mult=s4_volume_multiple,
            allow_short=allow_short,
            regime_sma=regime_sma,
        ),
        chandelier_mult=s4_chandelier,
        chandelier_lookback=22,
        **common,
    )
    return s3, s4


def _stage_payload(
    stage_id: str,
    change: str,
    results: tuple[X4Result, X4Result],
) -> dict[str, Any]:
    return {
        "stage": stage_id,
        "change": change,
        "s3_cta": _summary(results[0]),
        "s4_mom": _summary(results[1]),
    }


def _max_drawdown(values: Sequence[float]) -> float:
    peak = values[0] if values else 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def _buy_hold(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    weights: Mapping[str, float],
) -> dict[str, Any]:
    bars = align_bars(bars_by_symbol, TOP3)
    funding = {symbol: _daily_funding(funding_by_symbol.get(symbol, [])) for symbol in TOP3}
    equity = _CAPITAL * (1.0 - sum(abs(weight) for weight in weights.values()) * (_TAKER_FEE + _SLIPPAGE))
    funding_pnl = 0.0
    curve = [_CAPITAL, equity]
    for index in range(len(bars["BTCUSDT"]) - 1):
        gross_return = sum(
            float(weights.get(symbol, 0.0))
            * (bars[symbol][index + 1].close / bars[symbol][index].close - 1.0)
            for symbol in TOP3
        )
        holding_day = bars["BTCUSDT"][index + 1].ts_ms // _DAY_MS
        funding_return = -sum(
            float(weights.get(symbol, 0.0)) * funding[symbol].get(holding_day, 0.0)
            for symbol in TOP3
        )
        before = equity
        equity *= 1.0 + gross_return + funding_return
        funding_pnl += before * funding_return
        curve.append(equity)
    return {
        "start": bars["BTCUSDT"][0].date,
        "end": bars["BTCUSDT"][-1].date,
        "total_return_pct": round((equity / _CAPITAL - 1.0) * 100.0, 8),
        "max_drawdown_pct": round(_max_drawdown(curve), 8),
        "funding_pnl_usdt": round(funding_pnl, 8),
        "entry_cost_usdt": round(_CAPITAL * (_TAKER_FEE + _SLIPPAGE), 8),
        "gross": round(sum(abs(weight) for weight in weights.values()), 8),
    }


def _beta_attribution(bars: Sequence[Bar], curve: Sequence[float]) -> dict[str, float]:
    btc = [bars[i].close / bars[i - 1].close - 1.0 for i in range(1, len(bars))]
    strategy = returns_from_curve(curve)
    n = min(len(btc), len(strategy))
    btc, strategy = btc[:n], strategy[:n]
    mean_btc = statistics.mean(btc)
    mean_strategy = statistics.mean(strategy)
    var_btc = statistics.variance(btc)
    var_strategy = statistics.variance(strategy)
    covariance = sum(
        (x - mean_btc) * (y - mean_strategy) for x, y in zip(btc, strategy)
    ) / (n - 1)
    beta = covariance / var_btc if var_btc > 0 else 0.0
    correlation = covariance / math.sqrt(var_btc * var_strategy) if var_btc > 0 and var_strategy > 0 else 0.0
    return {
        "btc_price_beta": round(beta, 8),
        "r_squared": round(correlation * correlation, 8),
        "in_sample_arithmetic_alpha_pct_per_year": round(
            (mean_strategy - beta * mean_btc) * 365.0 * 100.0, 8
        ),
    }


def _current_base_summary(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    rules, rules_hash = selected_um_rules(rules_artifact)
    result = run_variant(
        bars,
        funding,
        rules,
        recovery_enabled=False,
        daily_chandelier_atr_multiple=FUTURES_BASE_FORWARD_PROTOCOL.daily_chandelier_atr_multiple,
        stop_cooldown_completed_bars=FUTURES_BASE_FORWARD_PROTOCOL.stop_cooldown_completed_bars,
    )
    curve = [FUTURES_RECOVERY_PROTOCOL.capital_usdt] + [
        float(row["equity"]) for row in result.equity
    ]
    metrics = dict(result.metrics)
    metrics["sharpe"] = round(sharpe(returns_from_curve(curve), periods_per_year=365.0), 8)
    metrics["average_effective_gross"] = round(
        statistics.mean(float(row["gross"]) for row in result.equity), 8
    )
    return {
        "strategy": FUTURES_BASE_FORWARD_PROTOCOL.strategy,
        "config": asdict(frozen_top3_config()),
        "daily_chandelier_atr_multiple": FUTURES_BASE_FORWARD_PROTOCOL.daily_chandelier_atr_multiple,
        "exchange_rules_hash": rules_hash,
        "metrics": metrics,
    }


def build_high_return_attribution(
    bars_1d_by_symbol: Mapping[str, Sequence[Bar]],
    btc_bars_1h: Sequence[Bar],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    live_lessons: Mapping[str, Any],
) -> dict[str, Any]:
    aligned = align_bars(bars_1d_by_symbol, TOP3)
    btc_1d = aligned["BTCUSDT"]
    btc_funding = funding_by_symbol["BTCUSDT"]
    legacy_1h_funding = _legacy_exact_funding(btc_funding)
    legacy_1d_funding = _legacy_exact_funding(btc_funding)
    corrected_funding = _all_next_holding_day_funding(btc_funding, btc_1d)

    hourly_raw = _stage(
        btc_bars_1h, legacy_1h_funding, interval="1h", allow_short=True, rebalance_band=0.0
    )
    hourly_deadband = _stage(
        btc_bars_1h, legacy_1h_funding, interval="1h", allow_short=True
    )
    daily_dual = _stage(btc_1d, legacy_1d_funding, interval="1d", allow_short=True)
    daily_long = _stage(btc_1d, legacy_1d_funding, interval="1d", allow_short=False)
    daily_fast_exit = _stage(
        btc_1d,
        legacy_1d_funding,
        interval="1d",
        allow_short=False,
        s4_exit_lookback=10,
    )
    daily_b3 = _stage(
        btc_1d,
        legacy_1d_funding,
        interval="1d",
        allow_short=False,
        s4_exit_lookback=10,
        s4_volume_multiple=1.0,
    )
    daily_regime = _stage(
        btc_1d,
        legacy_1d_funding,
        interval="1d",
        allow_short=False,
        regime_sma=200,
        s4_exit_lookback=10,
        s4_volume_multiple=1.0,
    )
    daily_vol = _stage(
        btc_1d,
        legacy_1d_funding,
        interval="1d",
        allow_short=False,
        regime_sma=200,
        s4_exit_lookback=10,
        s4_volume_multiple=1.0,
        vol_target=0.03,
        max_leverage=2.0,
    )
    legacy_headline = _stage(
        btc_1d,
        legacy_1d_funding,
        interval="1d",
        allow_short=False,
        regime_sma=200,
        s4_exit_lookback=10,
        s4_volume_multiple=1.0,
        vol_target=0.03,
        max_leverage=2.0,
        s4_chandelier=4.0,
    )

    stages = [
        _stage_payload("hourly_dual_raw", "original 1h long/short book", hourly_raw),
        _stage_payload("hourly_dual_deadband", "add 25% rebalance deadband", hourly_deadband),
        _stage_payload("daily_dual", "change only 1h to 1d", daily_dual),
        _stage_payload("daily_long_only", "remove short side with the same signals", daily_long),
        _stage_payload("daily_s4_fast_exit", "S4 exit channel 20 to 10", daily_fast_exit),
        _stage_payload("daily_b3", "S4 volume multiple 1.5 to 1.0", daily_b3),
        _stage_payload("daily_regime", "require price above SMA200", daily_regime),
        _stage_payload("daily_vol_target", "3% ATR target with 2x ceiling", daily_vol),
        _stage_payload("legacy_headline", "add S4 4xATR chandelier", legacy_headline),
    ]

    stage_by_id = {row["stage"]: row for row in stages}
    bridge = {
        "deadband": {
            strategy: _delta(stage_by_id["hourly_dual_raw"][strategy], stage_by_id["hourly_dual_deadband"][strategy])
            for strategy in ("s3_cta", "s4_mom")
        },
        "timeframe_1h_to_1d": {
            strategy: _delta(stage_by_id["hourly_dual_deadband"][strategy], stage_by_id["daily_dual"][strategy])
            for strategy in ("s3_cta", "s4_mom")
        },
        "remove_short_side": {
            strategy: _delta(stage_by_id["daily_dual"][strategy], stage_by_id["daily_long_only"][strategy])
            for strategy in ("s3_cta", "s4_mom")
        },
        "s4_fast_exit": _delta(
            stage_by_id["daily_long_only"]["s4_mom"], stage_by_id["daily_s4_fast_exit"]["s4_mom"]
        ),
        "s4_volume_relaxation": _delta(
            stage_by_id["daily_s4_fast_exit"]["s4_mom"], stage_by_id["daily_b3"]["s4_mom"]
        ),
        "sma200_regime_gate": {
            strategy: _delta(stage_by_id["daily_b3"][strategy], stage_by_id["daily_regime"][strategy])
            for strategy in ("s3_cta", "s4_mom")
        },
        "volatility_target": {
            strategy: _delta(stage_by_id["daily_regime"][strategy], stage_by_id["daily_vol_target"][strategy])
            for strategy in ("s3_cta", "s4_mom")
        },
        "s4_chandelier": _delta(
            stage_by_id["daily_vol_target"]["s4_mom"], stage_by_id["legacy_headline"]["s4_mom"]
        ),
    }

    corrected = _stage(
        btc_1d,
        corrected_funding,
        interval="1d",
        allow_short=False,
        regime_sma=200,
        s4_exit_lookback=10,
        s4_volume_multiple=1.0,
        vol_target=0.03,
        max_leverage=2.0,
        s4_chandelier=4.0,
    )
    corrected_one_x = _stage(
        btc_1d,
        corrected_funding,
        interval="1d",
        allow_short=False,
        regime_sma=200,
        s4_exit_lookback=10,
        s4_volume_multiple=1.0,
        vol_target=0.03,
        max_leverage=1.0,
        s4_chandelier=4.0,
    )
    no_funding = _stage(
        btc_1d,
        None,
        interval="1d",
        allow_short=False,
        regime_sma=200,
        s4_exit_lookback=10,
        s4_volume_multiple=1.0,
        vol_target=0.03,
        max_leverage=2.0,
        s4_chandelier=4.0,
    )
    frictionless = _stage(
        btc_1d,
        corrected_funding,
        interval="1d",
        allow_short=False,
        regime_sma=200,
        s4_exit_lookback=10,
        s4_volume_multiple=1.0,
        vol_target=0.03,
        max_leverage=2.0,
        s4_chandelier=4.0,
        taker_fee=0.0,
        slippage=0.0,
    )
    corrected_payload = {}
    for index, strategy in enumerate(("s3_cta", "s4_mom")):
        legacy = _summary(legacy_headline[index])
        honest = _summary(corrected[index])
        corrected_payload[strategy] = {
            "legacy_headline": legacy,
            "all_daily_settlements": honest,
            "headline_inflation_from_funding_undercount_pp": round(
                legacy["total_return_pct"] - honest["total_return_pct"], 8
            ),
            "funding_drag_vs_no_funding_pp": round(
                honest["total_return_pct"] - _summary(no_funding[index])["total_return_pct"], 8
            ),
            "trading_friction_drag_pp": round(
                honest["total_return_pct"] - _summary(frictionless[index])["total_return_pct"], 8
            ),
            "two_x_ceiling_vs_one_x_return_delta_pp": round(
                honest["total_return_pct"] - _summary(corrected_one_x[index])["total_return_pct"], 8
            ),
            "beta_attribution": _beta_attribution(btc_1d, corrected[index].equity_curve),
        }

    current_base = _current_base_summary(aligned, funding_by_symbol, rules_artifact)
    benchmarks = {
        "btc_um_buy_hold_1x": _buy_hold(aligned, funding_by_symbol, {"BTCUSDT": 1.0}),
        "top3_equal_weight_um_1x": _buy_hold(
            aligned, funding_by_symbol, {symbol: 1.0 / len(TOP3) for symbol in TOP3}
        ),
    }
    lessons_equity = live_lessons["equity"]
    lessons_orders = live_lessons["orders"]
    lessons_ops = live_lessons["operations"]
    live_reality = {
        "strategy_return_before_withdrawal_pct": lessons_equity[
            "inception_to_pre_withdrawal_return_pct"
        ],
        "july_rebound_giveback_usdt": lessons_equity["july_rebound_giveback_usdt"],
        "june_gain_erased_pct": lessons_equity["june_gain_erased_pct"],
        "post_inception_placed_order_count": lessons_orders["post_inception_placed_order_count"],
        "exact_duplicate_order_count": lessons_orders["exact_duplicate_order_count"],
        "same_bar_direction_flip_group_count": lessons_orders[
            "same_bar_direction_flip_group_count"
        ],
        "fail_closed_unknown_capital_count": lessons_ops["fail_closed_unknown_capital_count"],
    }

    return {
        "schema_version": ATTRIBUTION_VERSION,
        "artifact_type": "mini_trend_high_return_attribution",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "historical_window_consumed": True,
            "promotion_allowed": False,
            "paper_or_live_allowed": False,
        },
        "window": {
            "start": btc_1d[0].date,
            "end": btc_1d[-1].date,
            "daily_bars": len(btc_1d),
            "hourly_bars": len(btc_bars_1h),
        },
        "data_hash": _canonical_hash(
            {
                "daily": {symbol: [[bar.ts_ms, bar.close] for bar in aligned[symbol]] for symbol in TOP3},
                "hourly_btc": [[bar.ts_ms, bar.close] for bar in btc_bars_1h],
                "funding": {
                    symbol: [[row.ts_ms, row.rate] for row in funding_by_symbol[symbol]]
                    for symbol in TOP3
                },
            }
        ),
        "legacy_stage_bridge": stages,
        "mechanism_deltas": bridge,
        "funding_and_friction_correction": corrected_payload,
        "benchmarks": benchmarks,
        "current_um_base": current_base,
        "live_reality": live_reality,
        "diagnostics": {
            "legacy_daily_funding_bug": (
                "x4_compare matched funding timestamp exactly to the daily bar open and therefore "
                "captured only the 00:00 settlement, omitting 08:00 and 16:00 settlements"
            ),
            "high_return_explanation": [
                "Moving from noisy hourly trading to daily bars removed most whipsaw losses.",
                "Removing the short side avoided repeated squeezes in a positive-drift asset class.",
                "The SMA200 gate converted bear regimes to cash and concentrated exposure in bull regimes.",
                "Volatility targeting and the S4 chandelier improved risk shape; the 2x ceiling was not a robust return source.",
                "The legacy headline was materially inflated by incomplete daily funding accrual.",
                "The remaining return is still bull-regime beta timing, not demonstrated stable alpha.",
            ],
            "verdict": "legacy_high_return_explained_not_promotable",
        },
        "recommended_strategy": {
            "strategy": FUTURES_BASE_FORWARD_PROTOCOL.strategy,
            "status": "retain_frozen_future_control_after_v0_2_preregistration",
            "capital_location": "Binance USD-M futures wallet",
            "market": "um",
            "interval": "1d",
            "direction": "long_cash",
            "universe": list(TOP3),
            "carry_allowed": False,
            "shorting_allowed": False,
            "leverage_boost_allowed": False,
            "maximum_effective_gross": 1.0,
            "daily_chandelier_atr_multiple": FUTURES_BASE_FORWARD_PROTOCOL.daily_chandelier_atr_multiple,
            "stop_cooldown_completed_bars": FUTURES_BASE_FORWARD_PROTOCOL.stop_cooldown_completed_bars,
            "one_decision_per_completed_bar": True,
            "unknown_capital_action": "fail_closed",
            "runtime_filter_coverage_required": 1.0,
            "historical_readout_is_discovery_only": True,
            "minimum_future_bars_before_readout": FUTURES_BASE_FORWARD_PROTOCOL.minimum_forward_bars,
            "minimum_active_future_bars": FUTURES_BASE_FORWARD_PROTOCOL.minimum_active_bars,
            "paper_or_live_allowed": False,
        },
    }


def write_high_return_attribution_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-high-return-attribution",
        path_key="artifact_path",
        default_filename="mini_trend_high_return_attribution.json",
        explicit_path=explicit_path,
    )
