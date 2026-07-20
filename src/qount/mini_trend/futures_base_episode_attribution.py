"""Episode-level attribution for the frozen MiniTrend UM Base v0.2."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult, run_variant
from qount.mini_trend.regime_adaptation_ablation import _benchmark_returns
from qount.mini_trend.regime_adaptation_ablation import _beta_residual
from qount.mini_trend.regime_adaptation_ablation import _data_hash
from qount.mini_trend.regime_adaptation_ablation import _summarize
from qount.models import utc_now
from qount.settings import Settings


BASE_EPISODE_PREREG_VERSION = "mini_trend_um_base_episode_preregistration_v0.1"
BASE_EPISODE_REPORT_VERSION = "mini_trend_um_base_episode_attribution_v0.1"
_DAY_MS = 86_400_000
_EPSILON = 1e-12


@dataclass(frozen=True)
class BaseEpisodeAttributionConfig:
    prior_family_trial_count: int = 142
    holding_buckets: tuple[tuple[str, int | None], ...] = (
        ("01_1_to_7", 7),
        ("02_8_to_30", 30),
        ("03_31_to_90", 90),
        ("04_over_90", None),
    )
    minimum_exit_family_episode_count: int = 10
    minimum_negative_exit_year_count: int = 3

    @property
    def trial_count(self) -> int:
        return 0

    @property
    def cumulative_trial_count(self) -> int:
        return self.prior_family_trial_count

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "strategy": FUTURES_BASE_FORWARD_PROTOCOL.strategy,
                "base_config": asdict(frozen_top3_config()),
                "episode": "per-symbol continuous positive target weight",
                "components": (
                    "daily equity-weighted price PnL, holding-day funding PnL, "
                    "and entry/rebalance/exit trading cost"
                ),
                "excursions": "outcome-bar high/low relative to decision-close entry price",
                "exit_reasons": (
                    "chandelier_stop",
                    "master_gate_cash",
                    "signal_or_allocation_exit",
                    "open_censored",
                ),
                "mechanism_screen": (
                    "at least 10 closed episodes, negative total net PnL, negative in at "
                    "least 3 exit years, and positive median MFE"
                ),
                "strategy_trial": False,
                "parameter_search_allowed": False,
                "paper_or_live_allowed": False,
            }
        )


def build_base_episode_preregistration(
    rules_artifact: Mapping[str, Any],
    config: BaseEpisodeAttributionConfig | None = None,
) -> dict[str, Any]:
    config = config or BaseEpisodeAttributionConfig()
    _, rules_hash = selected_um_rules(rules_artifact)
    return {
        "schema_version": BASE_EPISODE_PREREG_VERSION,
        "artifact_type": "mini_trend_um_base_episode_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "strategy_results_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "contract_hash": config.contract_hash,
        },
        "source": {
            "base_forward_contract_hash": FUTURES_BASE_FORWARD_PROTOCOL.contract_hash,
            "exchange_rules_hash": rules_hash,
        },
    }


def validate_base_episode_preregistration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    config: BaseEpisodeAttributionConfig,
) -> None:
    if preregistration.get("schema_version") != BASE_EPISODE_PREREG_VERSION:
        raise ValueError("unexpected Base episode preregistration schema")
    if preregistration.get("contract", {}).get("contract_hash") != config.contract_hash:
        raise ValueError("Base episode attribution contract hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("source", {}).get("exchange_rules_hash") != rules_hash:
        raise ValueError("Base episode attribution exchange-rules hash mismatch")


def _funding_sum(rows: Sequence[Funding], start_ms: int, end_ms: int) -> float:
    return sum(float(row.rate) for row in rows if start_ms < row.ts_ms <= end_ms)


def _exit_reason(row: Mapping[str, Any], symbol: str) -> str:
    if symbol in row.get("stopped", []):
        return "chandelier_stop"
    if row.get("mode") == "cash":
        return "master_gate_cash"
    return "signal_or_allocation_exit"


def _finalize_episode(episode: dict[str, Any]) -> dict[str, Any]:
    entry_price = float(episode.pop("_entry_price"))
    exit_price = float(episode.pop("_last_price"))
    entry_equity = float(episode.pop("_entry_equity"))
    weight_sum = float(episode.pop("_weight_sum"))
    price_pnl = float(episode["price_pnl_usdt"])
    funding_pnl = float(episode["funding_pnl_usdt"])
    trading_cost = float(episode["trading_cost_usdt"])
    net_pnl = price_pnl + funding_pnl - trading_cost
    underlying_return = (exit_price / entry_price - 1.0) * 100.0
    mfe = float(episode["mfe_pct"])
    episode.update(
        {
            "entry_price": round(entry_price, 8),
            "exit_price": round(exit_price, 8),
            "underlying_return_pct": round(underlying_return, 8),
            "giveback_from_mfe_percentage_points": round(mfe - underlying_return, 8),
            "mfe_capture_ratio": round(underlying_return / mfe, 8) if mfe > 0 else None,
            "average_target_weight": round(
                weight_sum / int(episode["holding_bars"]), 8
            )
            if episode["holding_bars"]
            else 0.0,
            "price_pnl_usdt": round(price_pnl, 8),
            "funding_pnl_usdt": round(funding_pnl, 8),
            "trading_cost_usdt": round(trading_cost, 8),
            "net_pnl_usdt": round(net_pnl, 8),
            "net_contribution_pct_of_entry_equity": round(
                net_pnl / entry_equity * 100.0, 8
            ),
        }
    )
    return episode


def extract_base_episodes(
    result: VariantResult,
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    *,
    capital_usdt: float = 400.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bars = align_bars(bars_by_symbol, TOP3)
    by_date = {symbol: {bar.date: bar for bar in bars[symbol]} for symbol in TOP3}
    cost_rate = (
        FUTURES_RECOVERY_PROTOCOL.taker_fee_bps
        + FUTURES_RECOVERY_PROTOCOL.slippage_bps
    ) / 10_000.0
    prior = {symbol: 0.0 for symbol in TOP3}
    active: dict[str, dict[str, Any]] = {}
    counters = {symbol: 0 for symbol in TOP3}
    episodes: list[dict[str, Any]] = []
    equity = float(capital_usdt)
    total_price_pnl = total_funding_pnl = total_cost = 0.0

    for row in result.equity:
        decision_date = str(row["decision_date"])
        outcome_date = str(row["outcome_date"])
        targets = {
            symbol: float(row["execution_state"]["target_weights"][symbol])
            for symbol in TOP3
        }
        before = equity
        row_price_return = row_funding_return = row_cost_return = 0.0
        for symbol in TOP3:
            decision = by_date[symbol][decision_date]
            outcome = by_date[symbol][outcome_date]
            previous_weight = prior[symbol]
            current_weight = targets[symbol]
            price_return = current_weight * (outcome.close / decision.close - 1.0)
            funding_rate = _funding_sum(
                funding_by_symbol.get(symbol, []),
                decision.ts_ms + _DAY_MS,
                outcome.ts_ms + _DAY_MS,
            )
            funding_return = -current_weight * funding_rate
            cost_return = abs(current_weight - previous_weight) * cost_rate
            row_price_return += price_return
            row_funding_return += funding_return
            row_cost_return += cost_return

            if previous_weight <= _EPSILON and current_weight > _EPSILON:
                counters[symbol] += 1
                active[symbol] = {
                    "episode_id": f"{symbol}-{counters[symbol]:03d}",
                    "symbol": symbol,
                    "status": "open",
                    "entry_date": decision_date,
                    "entry_year": decision_date[:4],
                    "exit_date": None,
                    "exit_year": None,
                    "exit_reason": None,
                    "holding_bars": 0,
                    "mfe_pct": 0.0,
                    "mae_pct": 0.0,
                    "maximum_target_weight": 0.0,
                    "price_pnl_usdt": 0.0,
                    "funding_pnl_usdt": 0.0,
                    "trading_cost_usdt": 0.0,
                    "_entry_price": float(decision.close),
                    "_last_price": float(decision.close),
                    "_entry_equity": before,
                    "_weight_sum": 0.0,
                }
            episode = active.get(symbol)
            if episode is not None:
                episode["price_pnl_usdt"] += before * price_return
                episode["funding_pnl_usdt"] += before * funding_return
                episode["trading_cost_usdt"] += before * cost_return
                if current_weight > _EPSILON:
                    episode["holding_bars"] += 1
                    episode["_weight_sum"] += current_weight
                    episode["maximum_target_weight"] = max(
                        float(episode["maximum_target_weight"]), current_weight
                    )
                    entry_price = float(episode["_entry_price"])
                    episode["mfe_pct"] = max(
                        float(episode["mfe_pct"]),
                        (float(outcome.high) / entry_price - 1.0) * 100.0,
                    )
                    episode["mae_pct"] = min(
                        float(episode["mae_pct"]),
                        (float(outcome.low) / entry_price - 1.0) * 100.0,
                    )
                    episode["_last_price"] = float(outcome.close)
                elif previous_weight > _EPSILON:
                    episode["status"] = "closed"
                    episode["exit_date"] = decision_date
                    episode["exit_year"] = decision_date[:4]
                    episode["exit_reason"] = _exit_reason(row, symbol)
                    episode["_last_price"] = float(decision.close)
                    episodes.append(_finalize_episode(active.pop(symbol)))

        if not math.isclose(
            row_price_return, float(row["gross_price_return"]), abs_tol=1e-12
        ):
            raise AssertionError(f"price attribution mismatch on {decision_date}")
        if not math.isclose(
            row_funding_return, float(row["funding_return"]), abs_tol=1e-12
        ):
            raise AssertionError(f"funding attribution mismatch on {decision_date}")
        if not math.isclose(
            -row_cost_return, float(row["trading_cost_return"]), abs_tol=1e-12
        ):
            raise AssertionError(f"cost attribution mismatch on {decision_date}")
        net_return = row_price_return + row_funding_return - row_cost_return
        if not math.isclose(net_return, float(row["net_return"]), abs_tol=1e-12):
            raise AssertionError(f"net attribution mismatch on {decision_date}")
        total_price_pnl += before * row_price_return
        total_funding_pnl += before * row_funding_return
        total_cost += before * row_cost_return
        equity *= 1.0 + net_return
        if not math.isclose(equity, float(row["equity"]), abs_tol=1e-6):
            raise AssertionError(f"equity attribution mismatch on {decision_date}")
        prior = targets

    for symbol in sorted(active):
        episode = active[symbol]
        episode["status"] = "open_censored"
        episode["exit_date"] = result.equity[-1]["outcome_date"]
        episode["exit_year"] = str(episode["exit_date"])[:4]
        episode["exit_reason"] = "open_censored"
        episodes.append(_finalize_episode(episode))

    episodes.sort(key=lambda row: (row["entry_date"], row["symbol"], row["episode_id"]))
    attributed_net = sum(float(row["net_pnl_usdt"]) for row in episodes)
    strategy_net = equity - capital_usdt
    reconciliation = {
        "start_equity_usdt": round(capital_usdt, 8),
        "final_equity_usdt": round(equity, 8),
        "strategy_net_pnl_usdt": round(strategy_net, 8),
        "attributed_net_pnl_usdt": round(attributed_net, 8),
        "net_pnl_difference_usdt": round(attributed_net - strategy_net, 8),
        "price_pnl_usdt": round(total_price_pnl, 8),
        "funding_pnl_usdt": round(total_funding_pnl, 8),
        "trading_cost_usdt": round(total_cost, 8),
        "component_identity_difference_usdt": round(
            total_price_pnl + total_funding_pnl - total_cost - strategy_net, 8
        ),
        "episode_count": len(episodes),
        "closed_episode_count": sum(row["status"] == "closed" for row in episodes),
        "open_censored_episode_count": sum(
            row["status"] == "open_censored" for row in episodes
        ),
    }
    if abs(float(reconciliation["net_pnl_difference_usdt"])) > 1e-5:
        raise AssertionError("episode net PnL did not reconcile to strategy equity")
    return episodes, reconciliation


def _holding_bucket(holding_bars: int, config: BaseEpisodeAttributionConfig) -> str:
    for label, upper in config.holding_buckets:
        if upper is None or holding_bars <= upper:
            return label
    raise AssertionError("holding bucket contract is incomplete")


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "episode_count": 0,
            "closed_episode_count": 0,
            "net_pnl_usdt": 0.0,
        }
    closed = [row for row in rows if row["status"] == "closed"]
    net = [float(row["net_pnl_usdt"]) for row in rows]
    holdings = [int(row["holding_bars"]) for row in rows]
    mfe = [float(row["mfe_pct"]) for row in rows]
    mae = [float(row["mae_pct"]) for row in rows]
    giveback = [float(row["giveback_from_mfe_percentage_points"]) for row in rows]
    return {
        "episode_count": len(rows),
        "closed_episode_count": len(closed),
        "open_censored_episode_count": len(rows) - len(closed),
        "positive_net_pnl_count": sum(value > 0 for value in net),
        "positive_net_pnl_rate": round(sum(value > 0 for value in net) / len(net), 8),
        "net_pnl_usdt": round(sum(net), 8),
        "price_pnl_usdt": round(sum(float(row["price_pnl_usdt"]) for row in rows), 8),
        "funding_pnl_usdt": round(sum(float(row["funding_pnl_usdt"]) for row in rows), 8),
        "trading_cost_usdt": round(sum(float(row["trading_cost_usdt"]) for row in rows), 8),
        "median_net_pnl_usdt": round(statistics.median(net), 8),
        "median_holding_bars": round(statistics.median(holdings), 8),
        "maximum_holding_bars": max(holdings),
        "median_mfe_pct": round(statistics.median(mfe), 8),
        "median_mae_pct": round(statistics.median(mae), 8),
        "median_giveback_percentage_points": round(statistics.median(giveback), 8),
        "positive_mfe_to_negative_underlying_count": sum(
            float(row["mfe_pct"]) > 0 and float(row["underlying_return_pct"]) < 0
            for row in rows
        ),
    }


def _group_summary(
    episodes: Sequence[Mapping[str, Any]], key
) -> dict[str, Any]:
    values = sorted({str(key(row)) for row in episodes})
    return {
        value: _summary([row for row in episodes if str(key(row)) == value])
        for value in values
    }


def _mechanism_screen(
    episodes: Sequence[Mapping[str, Any]], config: BaseEpisodeAttributionConfig
) -> list[dict[str, Any]]:
    closed = [row for row in episodes if row["status"] == "closed"]
    results = []
    for reason in sorted({str(row["exit_reason"]) for row in closed}):
        rows = [row for row in closed if row["exit_reason"] == reason]
        years = _group_summary(rows, lambda row: row["exit_year"])
        summary = _summary(rows)
        negative_years = sum(float(value["net_pnl_usdt"]) < 0 for value in years.values())
        gates = {
            "minimum_episode_count": len(rows)
            >= config.minimum_exit_family_episode_count,
            "negative_total_net_pnl": float(summary["net_pnl_usdt"]) < 0,
            "negative_in_minimum_exit_years": negative_years
            >= config.minimum_negative_exit_year_count,
            "positive_median_mfe": float(summary["median_mfe_pct"]) > 0,
        }
        results.append(
            {
                "exit_reason": reason,
                "summary": summary,
                "exit_years": years,
                "negative_exit_year_count": negative_years,
                "gates": gates,
                "eligible_for_one_future_ablation": all(gates.values()),
            }
        )
    return sorted(
        results,
        key=lambda row: (
            row["eligible_for_one_future_ablation"],
            -float(row["summary"]["net_pnl_usdt"]),
        ),
        reverse=True,
    )


def build_base_episode_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    config: BaseEpisodeAttributionConfig | None = None,
) -> dict[str, Any]:
    config = config or BaseEpisodeAttributionConfig()
    validate_base_episode_preregistration(preregistration, rules_artifact, config)
    bars = align_bars(bars_by_symbol, TOP3)
    rules, rules_hash = selected_um_rules(rules_artifact)
    result = run_variant(
        bars,
        funding_by_symbol,
        rules,
        recovery_enabled=False,
        base_config=frozen_top3_config(),
        daily_chandelier_atr_multiple=(
            FUTURES_BASE_FORWARD_PROTOCOL.daily_chandelier_atr_multiple
        ),
        stop_cooldown_completed_bars=(
            FUTURES_BASE_FORWARD_PROTOCOL.stop_cooldown_completed_bars
        ),
        gross_cap_policy="renormalize_active_targets_with_filter_floors",
    )
    episodes, reconciliation = extract_base_episodes(
        result, bars, funding_by_symbol, capital_usdt=FUTURES_RECOVERY_PROTOCOL.capital_usdt
    )
    metrics = _summarize(result)
    strategy_returns = [float(row["net_return"]) for row in result.equity]
    benchmark = _benchmark_returns(result.equity, bars, funding_by_symbol)
    metrics["beta_residual"] = {
        name: _beta_residual(strategy_returns, values) for name, values in benchmark.items()
    }
    for episode in episodes:
        episode["holding_bucket"] = _holding_bucket(int(episode["holding_bars"]), config)
    screen = _mechanism_screen(episodes, config)
    qualified = [
        row["exit_reason"]
        for row in screen
        if row["eligible_for_one_future_ablation"]
    ]
    return {
        "schema_version": BASE_EPISODE_REPORT_VERSION,
        "artifact_type": "mini_trend_um_base_episode_attribution",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "strategy_trial": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": preregistration["contract"],
        "lineage": {
            "preregistration_hash": canonical_hash(preregistration),
            "data_hash": _data_hash(bars, funding_by_symbol),
            "exchange_rules_hash": rules_hash,
            "base_forward_contract_hash": FUTURES_BASE_FORWARD_PROTOCOL.contract_hash,
        },
        "strategy": metrics,
        "reconciliation": reconciliation,
        "summary": _summary(episodes),
        "by_symbol": _group_summary(episodes, lambda row: row["symbol"]),
        "by_exit_reason": _group_summary(episodes, lambda row: row["exit_reason"]),
        "by_entry_year": _group_summary(episodes, lambda row: row["entry_year"]),
        "by_holding_bucket": _group_summary(episodes, lambda row: row["holding_bucket"]),
        "mechanism_screen": screen,
        "episodes": episodes,
        "diagnostics": {
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "qualified_exit_reasons": qualified,
            "verdict": "base_episode_attribution_complete",
            "paper_or_live_allowed": False,
        },
    }


def write_base_episode_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-base-episode-attribution",
        path_key="artifact_path",
        default_filename="mini_trend_um_base_episode_attribution.json",
        explicit_path=explicit_path,
    )
