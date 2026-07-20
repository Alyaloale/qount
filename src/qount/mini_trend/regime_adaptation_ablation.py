"""OOS-score, downside-only risk ablation for the retained rolling ranker."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult, run_variant
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.models import utc_now
from qount.rv.stats import sharpe
from qount.settings import Settings


ADAPTATION_ABLATION_VERSION = "mini_trend_regime_adaptation_ablation_v0.1"
_DAY_MS = 86_400_000
_BASE_VOL_TARGET = frozen_top3_config().vol_target


@dataclass(frozen=True)
class RiskReductionSpec:
    trial_id: str
    score_bands: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        thresholds = [threshold for threshold, _ in self.score_bands]
        if thresholds != sorted(thresholds):
            raise ValueError("score bands must be sorted by ascending threshold")
        if any(target <= 0 or target > _BASE_VOL_TARGET for _, target in self.score_bands):
            raise ValueError("risk ablation may only reduce the positive base vol target")

    def vol_target(self, score: float) -> float:
        for threshold, target in self.score_bands:
            if score <= threshold:
                return target
        return _BASE_VOL_TARGET


RISK_REDUCTION_SPECS = (
    RiskReductionSpec("z_le_minus_0_5_to_1pct", ((-0.5, 0.010),)),
    RiskReductionSpec("z_le_0_to_1pct", ((0.0, 0.010),)),
    RiskReductionSpec("tiered_z_le_0_minus_1", ((-1.0, 0.005), (0.0, 0.010))),
)


@dataclass(frozen=True)
class AdaptationAblationConfig:
    candidate_id: str = "h60_train365_base_random_forest"
    confirmation_verdict: str = "retain_rolling_return_ranker_for_strategy_ablation"
    prior_family_trial_count: int = 117
    maximum_return_degradation_percentage_points: float = 3.0
    minimum_drawdown_improvement_percentage_points: float = 0.5
    minimum_nonnegative_annual_delta_count: int = 2

    @property
    def trial_count(self) -> int:
        return len(RISK_REDUCTION_SPECS)

    @property
    def cumulative_trial_count(self) -> int:
        return self.prior_family_trial_count + self.trial_count

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "risk_reduction_specs": [asdict(spec) for spec in RISK_REDUCTION_SPECS],
                "base_vol_target": _BASE_VOL_TARGET,
                "direction": "downside_only_risk_reduction",
                "selection": "three fixed score-threshold ablations; no result-driven rescue",
                "holdout_role": "consumed_historical_discovery_pool",
                "paper_or_live_allowed": False,
            }
        )


class RiskScoreSelector:
    def __init__(self, scores: Mapping[str, float], spec: RiskReductionSpec):
        self._scores = dict(scores)
        self._spec = spec
        self._last: dict[str, Any] = {}

    def __call__(self, bars: Mapping[str, Sequence[Bar]]):
        date = bars["BTCUSDT"][-1].date
        if date not in self._scores:
            raise ValueError(f"missing OOS risk score for decision date {date}")
        score = float(self._scores[date])
        target = self._spec.vol_target(score)
        reduced = target < _BASE_VOL_TARGET
        self._last = {
            "decision_date": date,
            "oos_score": score,
            "active_vol_target": target,
            "risk_reduced": reduced,
        }
        config = replace(
            frozen_top3_config(),
            strategy=f"MiniTrend-UM-ML-Risk-{self._spec.trial_id}",
            vol_target=target,
        )
        stage = f"ml_reduced_{target:.3f}" if reduced else "ml_base"
        return config, stage

    def state_snapshot(self) -> dict[str, Any]:
        return dict(self._last)


def _compound(returns: Sequence[float]) -> float:
    total = 1.0
    for value in returns:
        total *= 1.0 + float(value)
    return total - 1.0


def _curve(returns: Sequence[float]) -> list[float]:
    values = [1.0]
    for value in returns:
        values.append(values[-1] * (1.0 + float(value)))
    return values


def _period_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(row["net_return"]) for row in rows]
    gross = [float(row["gross"]) for row in rows]
    return {
        "bar_count": len(rows),
        "return_pct": round(_compound(returns) * 100.0, 8),
        "sharpe": round(sharpe(returns, periods_per_year=365.0), 8),
        "max_drawdown_pct": round(max_drawdown_pct(_curve(returns)), 8),
        "average_effective_gross": round(statistics.fmean(gross), 8) if gross else 0.0,
        "maximum_effective_gross": round(max(gross), 8) if gross else 0.0,
    }


def _summarize(result: VariantResult) -> dict[str, Any]:
    rows = result.equity
    years = sorted({row["decision_date"][:4] for row in rows})
    gross = [float(row["gross"]) for row in rows]
    returns = [float(row["net_return"]) for row in rows]
    return dict(result.metrics) | {
        "sharpe": round(sharpe(returns, periods_per_year=365.0), 8),
        "average_effective_gross": round(statistics.fmean(gross), 8),
        "maximum_effective_gross": round(max(gross), 8),
        "annual": {
            year: _period_metrics([row for row in rows if row["decision_date"].startswith(year)])
            for year in years
        },
    }


def _covariance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / (
        len(left) - 1
    )


def _beta_residual(
    strategy_returns: Sequence[float], benchmark_returns: Sequence[float]
) -> dict[str, float]:
    variance = _covariance(benchmark_returns, benchmark_returns)
    beta = _covariance(strategy_returns, benchmark_returns) / variance if variance > 0 else 0.0
    residual = [
        strategy - beta * benchmark
        for strategy, benchmark in zip(strategy_returns, benchmark_returns)
    ]
    return {
        "beta": round(beta, 8),
        "residual_sum_pct": round(sum(residual) * 100.0, 8),
        "residual_compound_pct": round(_compound(residual) * 100.0, 8),
    }


def _funding_sum(rows: Sequence[Funding], start_ms: int, end_ms: int) -> float:
    return sum(row.rate for row in rows if start_ms < row.ts_ms <= end_ms)


def _benchmark_returns(
    rows: Sequence[Mapping[str, Any]],
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
) -> dict[str, list[float]]:
    by_date = {
        symbol: {bar.date: bar for bar in bars[symbol]}
        for symbol in TOP3
    }
    cost_rate = (
        FUTURES_BASE_FORWARD_PROTOCOL.taker_fee_bps
        + FUTURES_BASE_FORWARD_PROTOCOL.slippage_bps
    ) / 10_000.0
    btc: list[float] = []
    top3: list[float] = []
    for index, row in enumerate(rows):
        decision_date = str(row["decision_date"])
        outcome_date = str(row["outcome_date"])
        values = {}
        for symbol in TOP3:
            decision = by_date[symbol][decision_date]
            outcome = by_date[symbol][outcome_date]
            price_return = outcome.close / decision.close - 1.0
            funding_return = -_funding_sum(
                funding.get(symbol, []),
                decision.ts_ms + _DAY_MS,
                outcome.ts_ms + _DAY_MS,
            )
            values[symbol] = price_return + funding_return
        entry_cost = cost_rate if index == 0 else 0.0
        btc.append(values["BTCUSDT"] - entry_cost)
        top3.append(statistics.fmean(values.values()) - entry_cost)
    return {"btc_1x": btc, "top3_equal_weight_1x": top3}


def _slice_for_scores(
    bars_by_symbol: Mapping[str, Sequence[Bar]], scores: Mapping[str, float]
) -> dict[str, list[Bar]]:
    aligned = align_bars(bars_by_symbol, TOP3)
    dates = [bar.date for bar in aligned["BTCUSDT"]]
    first, last = min(scores), max(scores)
    if first not in dates or last not in dates:
        raise ValueError("OOS score boundary is missing from the aligned price panel")
    warmup = max(
        frozen_top3_config().gate_sma,
        frozen_top3_config().trend_sma,
        frozen_top3_config().slow_sma,
    )
    first_index, last_index = dates.index(first), dates.index(last)
    if first_index < warmup or last_index + 1 >= len(dates):
        raise ValueError("insufficient warmup or outcome bar for the OOS score window")
    start = first_index - warmup
    end = last_index + 2
    return {symbol: list(aligned[symbol][start:end]) for symbol in TOP3}


def _data_hash(
    bars: Mapping[str, Sequence[Bar]], funding: Mapping[str, Sequence[Funding]]
) -> str:
    return canonical_hash(
        {
            "bars": {
                symbol: [
                    [bar.ts_ms, bar.open, bar.high, bar.low, bar.close, bar.volume]
                    for bar in bars[symbol]
                ]
                for symbol in TOP3
            },
            "funding": {
                symbol: [[row.ts_ms, row.rate] for row in funding.get(symbol, [])]
                for symbol in TOP3
            },
        }
    )


def _comparison(
    candidate: Mapping[str, Any], control: Mapping[str, Any]
) -> dict[str, Any]:
    annual_delta = {
        year: round(
            float(candidate["annual"][year]["return_pct"])
            - float(control["annual"][year]["return_pct"]),
            8,
        )
        for year in control["annual"]
    }
    return {
        "return_delta_percentage_points": round(
            float(candidate["return_pct"]) - float(control["return_pct"]), 8
        ),
        "sharpe_delta": round(float(candidate["sharpe"]) - float(control["sharpe"]), 8),
        "drawdown_improvement_percentage_points": round(
            float(control["max_drawdown_pct"])
            - float(candidate["max_drawdown_pct"]),
            8,
        ),
        "average_gross_delta": round(
            float(candidate["average_effective_gross"])
            - float(control["average_effective_gross"]),
            8,
        ),
        "annual_return_delta_percentage_points": annual_delta,
        "nonnegative_annual_delta_count": sum(value >= 0 for value in annual_delta.values()),
    }


def build_adaptation_risk_ablation(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    confirmation: Mapping[str, Any],
    config: AdaptationAblationConfig | None = None,
) -> dict[str, Any]:
    config = config or AdaptationAblationConfig()
    if confirmation.get("diagnostics", {}).get("verdict") != config.confirmation_verdict:
        raise ValueError("rolling ranker confirmation did not authorize strategy ablation")
    if confirmation.get("contract", {}).get("candidate_id") != config.candidate_id:
        raise ValueError("unexpected confirmed rolling candidate")
    prediction_rows = confirmation["confirmation_result"].get("prediction_rows", [])
    scores = {str(row["decision_date"]): float(row["predicted"]) for row in prediction_rows}
    if len(scores) != len(prediction_rows) or not scores:
        raise ValueError("OOS prediction dates must be present and unique")

    bars = _slice_for_scores(bars_by_symbol, scores)
    rules, rules_hash = selected_um_rules(rules_artifact)
    common = {
        "recovery_enabled": False,
        "base_config": frozen_top3_config(),
        "daily_chandelier_atr_multiple": (
            FUTURES_BASE_FORWARD_PROTOCOL.daily_chandelier_atr_multiple
        ),
        "stop_cooldown_completed_bars": (
            FUTURES_BASE_FORWARD_PROTOCOL.stop_cooldown_completed_bars
        ),
        "gross_cap_policy": "renormalize_active_targets_with_filter_floors",
    }
    control_result = run_variant(bars, funding_by_symbol, rules, **common)
    decision_dates = [row["decision_date"] for row in control_result.equity]
    score_coverage_complete = set(decision_dates) == set(scores)
    if not score_coverage_complete:
        raise ValueError("OOS score coverage does not exactly match strategy decision dates")
    control = _summarize(control_result)
    benchmark = _benchmark_returns(control_result.equity, bars, funding_by_symbol)
    control_returns = [float(row["net_return"]) for row in control_result.equity]
    control["beta_residual"] = {
        name: _beta_residual(control_returns, values) for name, values in benchmark.items()
    }

    trials = []
    for spec in RISK_REDUCTION_SPECS:
        selector = RiskScoreSelector(scores, spec)
        candidate_result = run_variant(
            bars,
            funding_by_symbol,
            rules,
            base_config_selector=selector,
            **common,
        )
        candidate = _summarize(candidate_result)
        candidate_returns = [float(row["net_return"]) for row in candidate_result.equity]
        candidate["beta_residual"] = {
            name: _beta_residual(candidate_returns, values)
            for name, values in benchmark.items()
        }
        comparison = _comparison(candidate, control)
        reduced_rows = [
            row
            for row in candidate_result.equity
            if row["execution_state"]["selector_state"].get("risk_reduced")
        ]
        gates = {
            "score_coverage_complete": score_coverage_complete,
            "risk_target_never_above_base": all(
                float(row["execution_state"]["active_vol_target"]) <= _BASE_VOL_TARGET
                for row in candidate_result.equity
            ),
            "maximum_effective_gross_at_most_one": (
                candidate["maximum_effective_gross"] <= 1.0
            ),
            "average_effective_gross_not_higher": (
                candidate["average_effective_gross"]
                <= control["average_effective_gross"] + 1e-12
            ),
            "minimum_drawdown_improvement": (
                comparison["drawdown_improvement_percentage_points"]
                >= config.minimum_drawdown_improvement_percentage_points
            ),
            "sharpe_not_lower": candidate["sharpe"] >= control["sharpe"],
            "maximum_return_degradation": (
                comparison["return_delta_percentage_points"]
                >= -config.maximum_return_degradation_percentage_points
            ),
            "minimum_nonnegative_annual_delta_count": (
                comparison["nonnegative_annual_delta_count"]
                >= config.minimum_nonnegative_annual_delta_count
            ),
            "execution_contract_clean": (
                candidate["runtime_filter_coverage"] == 1.0
                and candidate["duplicate_decision_count"] == 0
                and candidate["same_bar_stop_reentry_count"] == 0
            ),
        }
        trials.append(
            {
                "trial_id": spec.trial_id,
                "score_bands": [list(band) for band in spec.score_bands],
                "risk_reduced_bar_count": len(reduced_rows),
                "risk_reduced_active_bar_count": sum(
                    float(row["gross"]) > 0 for row in reduced_rows
                ),
                "candidate": candidate,
                "comparison": comparison,
                "gates": gates,
                "passed_gate_count": sum(gates.values()),
                "gate_count": len(gates),
                "verdict": (
                    "retain_risk_reduction_ablation"
                    if all(gates.values())
                    else "reject_risk_reduction_ablation"
                ),
            }
        )

    ranked = sorted(
        trials,
        key=lambda row: (
            row["passed_gate_count"],
            row["comparison"]["sharpe_delta"],
            row["comparison"]["drawdown_improvement_percentage_points"],
            row["comparison"]["return_delta_percentage_points"],
        ),
        reverse=True,
    )
    retained = [row for row in ranked if row["verdict"].startswith("retain_")]
    score_rows = [[date, scores[date]] for date in sorted(scores)]
    return {
        "schema_version": ADAPTATION_ABLATION_VERSION,
        "artifact_type": "mini_trend_regime_adaptation_risk_ablation",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "private_exchange_data": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "risk_reduction_specs": [asdict(spec) for spec in RISK_REDUCTION_SPECS],
            "contract_hash": config.contract_hash,
        },
        "lineage": {
            "confirmation_hash": canonical_hash(confirmation),
            "confirmation_contract_hash": confirmation["contract"]["contract_hash"],
            "score_hash": canonical_hash(score_rows),
            "data_hash": _data_hash(bars, funding_by_symbol),
            "exchange_rules_hash": rules_hash,
        },
        "score_coverage": {
            "rows": len(scores),
            "start": min(scores),
            "end": max(scores),
            "exact_strategy_date_match": score_coverage_complete,
            "actual_outcome_fields_used_by_selector": False,
        },
        "control": control,
        "trials": trials,
        "ranking": [row["trial_id"] for row in ranked],
        "retained_trial_ids": [row["trial_id"] for row in retained],
        "diagnostics": {
            "trial_count": len(trials),
            "cumulative_trial_count": config.cumulative_trial_count,
            "retained_trial_count": len(retained),
            "verdict": (
                "retain_ml_risk_overlay_for_future_only_preregistration"
                if retained
                else "reject_ml_risk_overlay_after_strategy_ablation"
            ),
            "interpretation": (
                "OOS model scores, but strategy thresholds and selection reuse consumed history; "
                "discovery evidence only."
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_adaptation_risk_ablation_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-regime-adaptation-risk-ablation",
        path_key="artifact_path",
        default_filename="mini_trend_regime_adaptation_risk_ablation.json",
        explicit_path=explicit_path,
    )
