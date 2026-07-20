"""OOS H.4.1 veto of only the marginal strong-bull risk boost."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto import FundingVetoRegimeSelector
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import run_variant
from qount.mini_trend.futures_funding_veto_robustness import paired_moving_block_bootstrap
from qount.mini_trend.futures_regime_overlay import regime_overlay_config
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_BOOSTED
from qount.mini_trend.macro_h41_model import MACRO_H41_MODEL_VERSION
from qount.mini_trend.regime_adaptation_ablation import _benchmark_returns
from qount.mini_trend.regime_adaptation_ablation import _beta_residual
from qount.mini_trend.regime_adaptation_ablation import _comparison
from qount.mini_trend.regime_adaptation_ablation import _data_hash
from qount.mini_trend.regime_adaptation_ablation import _slice_for_scores
from qount.mini_trend.regime_adaptation_ablation import _summarize
from qount.mini_trend.regime_macro_strategy import MACRO_AUDIT_VERDICT
from qount.mini_trend.regime_macro_strategy import MACRO_CANDIDATE_ID
from qount.models import utc_now
from qount.settings import Settings


MACRO_BOOST_VETO_PREREG_VERSION = "mini_trend_h41_boost_veto_preregistration_v0.1"
MACRO_BOOST_VETO_REPORT_VERSION = "mini_trend_h41_boost_veto_ablation_v0.1"
STRONG_BULL_MACRO_VETO = "strong_bull_macro_veto_base"


@dataclass(frozen=True)
class MacroBoostVetoConfig:
    prior_family_trial_count: int = 141
    score_threshold: float = 0.0
    maximum_return_degradation_percentage_points: float = 3.0
    minimum_drawdown_improvement_percentage_points: float = 0.5
    bootstrap_block_days: int = 20
    bootstrap_samples: int = 5_000
    bootstrap_seed: int = 20260718
    minimum_bootstrap_sharpe_win_probability: float = 0.90
    minimum_bootstrap_drawdown_win_probability: float = 0.75

    @property
    def trial_count(self) -> int:
        return 1

    @property
    def cumulative_trial_count(self) -> int:
        return self.prior_family_trial_count + self.trial_count

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "candidate": MACRO_CANDIDATE_ID,
                "score": "annual-fold OOS standardized 60-day TOP3 return prediction",
                "threshold_basis": "zero of the existing fold-standardized score; not searched",
                "reference": "FundingVetoRegimeSelector",
                "mechanism": (
                    "after funding and stop-latch checks, veto only the 0.020 strong-bull "
                    "boost to the 0.015 Base target when the OOS score is nonpositive"
                ),
                "base_risk_reduction_allowed": False,
                "maximum_effective_gross": 1.0,
                "carry_allowed": False,
                "shorting_allowed": False,
                "parameter_search_allowed": False,
                "paper_or_live_allowed": False,
            }
        )


class MacroBoostVetoSelector:
    """Keep Funding Veto and use macro only on an otherwise eligible boost."""

    def __init__(
        self,
        funding: Mapping[str, Sequence[Funding]],
        scores: Mapping[str, float],
        *,
        score_threshold: float = 0.0,
    ) -> None:
        if not scores or any(not math.isfinite(float(value)) for value in scores.values()):
            raise ValueError("macro boost veto requires finite OOS scores")
        self._base = FundingVetoRegimeSelector(funding)
        self._scores = {str(date): float(value) for date, value in scores.items()}
        self._threshold = float(score_threshold)
        self._eligible = 0
        self._vetoed = 0
        self._events: list[dict[str, Any]] = []
        self._last: dict[str, Any] = {}

    def __call__(self, bars: Mapping[str, Sequence[Bar]]):
        date = bars["BTCUSDT"][-1].date
        if date not in self._scores:
            raise ValueError(f"missing OOS macro score for decision date {date}")
        config, stage = self._base(bars)
        score = self._scores[date]
        macro_vetoed = False
        if stage == STRONG_BULL_BOOSTED:
            self._eligible += 1
            if score <= self._threshold:
                self._vetoed += 1
                macro_vetoed = True
                stage = STRONG_BULL_MACRO_VETO
                config = regime_overlay_config(FUTURES_FUNDING_VETO_PROTOCOL.base_vol_target)
                self._events.append({"decision_date": date, "oos_score": score})
        self._last = {
            "decision_date": date,
            "oos_score": score,
            "score_threshold": self._threshold,
            "macro_boost_eligible": stage in {STRONG_BULL_BOOSTED, STRONG_BULL_MACRO_VETO},
            "macro_vetoed": macro_vetoed,
            "risk_stage": stage,
        }
        return config, stage

    def observe_stops(self, risk_stage: str, stopped: set[str]) -> None:
        inherited_stage = (
            STRONG_BULL_BOOSTED if risk_stage == STRONG_BULL_MACRO_VETO else risk_stage
        )
        self._base.observe_stops(inherited_stage, stopped)

    def state_snapshot(self) -> dict[str, Any]:
        return dict(self._base.state_snapshot()) | dict(self._last)

    def summary(self) -> dict[str, Any]:
        return {
            "score_threshold": self._threshold,
            "macro_boost_eligible_bar_count": self._eligible,
            "macro_vetoed_bar_count": self._vetoed,
            "macro_veto_rate": self._vetoed / self._eligible if self._eligible else 0.0,
            "events": list(self._events),
            "funding_veto": self._base.summary(),
        }


def _macro_trial(macro_audit: Mapping[str, Any]) -> Mapping[str, Any]:
    if macro_audit.get("schema_version") != MACRO_H41_MODEL_VERSION:
        raise ValueError("unexpected H.4.1 feature-audit schema")
    if macro_audit.get("diagnostics", {}).get("verdict") != MACRO_AUDIT_VERDICT:
        raise ValueError("H.4.1 feature audit did not retain strategy research features")
    if MACRO_CANDIDATE_ID not in macro_audit.get("retained_trial_ids", []):
        raise ValueError("fixed H.4.1 macro candidate was not retained")
    trial = next(
        row for row in macro_audit.get("trials", []) if row.get("trial_id") == MACRO_CANDIDATE_ID
    )
    rows = trial.get("prediction_rows", [])
    if not rows:
        raise ValueError("H.4.1 candidate has no OOS prediction rows")
    dates = [str(row["decision_date"]) for row in rows]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise ValueError("H.4.1 OOS prediction dates must be unique and increasing")
    if not all(fold.get("purge_check_passed") is True for fold in trial.get("folds", [])):
        raise ValueError("H.4.1 OOS folds did not pass the purge check")
    return trial


def _scores(macro_audit: Mapping[str, Any]) -> dict[str, float]:
    trial = _macro_trial(macro_audit)
    scores = {
        str(row["decision_date"]): float(row["predicted"])
        for row in trial["prediction_rows"]
    }
    if any(not math.isfinite(value) for value in scores.values()):
        raise ValueError("H.4.1 OOS predictions contain a non-finite score")
    return scores


def build_macro_boost_veto_preregistration(
    macro_audit: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    config: MacroBoostVetoConfig | None = None,
) -> dict[str, Any]:
    config = config or MacroBoostVetoConfig()
    scores = _scores(macro_audit)
    _, rules_hash = selected_um_rules(rules_artifact)
    return {
        "schema_version": MACRO_BOOST_VETO_PREREG_VERSION,
        "artifact_type": "mini_trend_h41_boost_veto_preregistration",
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
            "macro_audit_hash": canonical_hash(macro_audit),
            "macro_audit_contract_hash": macro_audit["contract"]["contract_hash"],
            "h41_data_hash": macro_audit["data_lineage"]["h41_data_hash"],
            "score_hash": canonical_hash([[date, scores[date]] for date in sorted(scores)]),
            "score_rows": len(scores),
            "score_start": min(scores),
            "score_end": max(scores),
            "funding_veto_contract_hash": FUTURES_FUNDING_VETO_PROTOCOL.contract_hash,
            "exchange_rules_hash": rules_hash,
        },
    }


def validate_macro_boost_veto_preregistration(
    preregistration: Mapping[str, Any],
    macro_audit: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    config: MacroBoostVetoConfig,
) -> None:
    if preregistration.get("schema_version") != MACRO_BOOST_VETO_PREREG_VERSION:
        raise ValueError("unexpected macro boost-veto preregistration schema")
    if preregistration.get("contract", {}).get("contract_hash") != config.contract_hash:
        raise ValueError("macro boost-veto contract hash mismatch")
    scores = _scores(macro_audit)
    _, rules_hash = selected_um_rules(rules_artifact)
    source = preregistration.get("source", {})
    if source.get("macro_audit_hash") != canonical_hash(macro_audit):
        raise ValueError("macro boost-veto audit hash mismatch")
    if source.get("score_hash") != canonical_hash(
        [[date, scores[date]] for date in sorted(scores)]
    ):
        raise ValueError("macro boost-veto score hash mismatch")
    if source.get("exchange_rules_hash") != rules_hash:
        raise ValueError("macro boost-veto exchange-rules hash mismatch")


def _run(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    rules: Mapping[str, Mapping[str, Any]],
    scores: Mapping[str, float],
    config: MacroBoostVetoConfig,
):
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
    base = run_variant(bars, funding, rules, **common)
    reference_selector = FundingVetoRegimeSelector(funding)
    reference = run_variant(
        bars,
        funding,
        rules,
        base_config_selector=reference_selector,
        base_config_feedback=reference_selector.observe_stops,
        **common,
    )
    candidate_selector = MacroBoostVetoSelector(
        funding, scores, score_threshold=config.score_threshold
    )
    candidate = run_variant(
        bars,
        funding,
        rules,
        base_config_selector=candidate_selector,
        base_config_feedback=candidate_selector.observe_stops,
        **common,
    )
    return base, reference, candidate, reference_selector.summary(), candidate_selector.summary()


def build_macro_boost_veto_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    macro_audit: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    config: MacroBoostVetoConfig | None = None,
) -> dict[str, Any]:
    config = config or MacroBoostVetoConfig()
    validate_macro_boost_veto_preregistration(
        preregistration, macro_audit, rules_artifact, config
    )
    scores = _scores(macro_audit)
    bars = _slice_for_scores(bars_by_symbol, scores)
    rules, rules_hash = selected_um_rules(rules_artifact)
    base_result, reference_result, candidate_result, reference_activity, activity = _run(
        bars, funding_by_symbol, rules, scores, config
    )
    decision_dates = [row["decision_date"] for row in candidate_result.equity]
    score_coverage_complete = decision_dates == sorted(scores)
    if not score_coverage_complete:
        raise ValueError("OOS macro score coverage does not match strategy decision dates")

    base = _summarize(base_result)
    reference = _summarize(reference_result)
    candidate = _summarize(candidate_result)
    benchmark = _benchmark_returns(base_result.equity, bars, funding_by_symbol)
    for summary, result in (
        (base, base_result),
        (reference, reference_result),
        (candidate, candidate_result),
    ):
        returns = [float(row["net_return"]) for row in result.equity]
        summary["beta_residual"] = {
            name: _beta_residual(returns, values) for name, values in benchmark.items()
        }
    reference_returns = [float(row["net_return"]) for row in reference_result.equity]
    candidate_returns = [float(row["net_return"]) for row in candidate_result.equity]
    comparison = _comparison(candidate, reference)
    versus_base = _comparison(candidate, base)
    bootstrap = paired_moving_block_bootstrap(
        reference_returns,
        candidate_returns,
        block_length=config.bootstrap_block_days,
        samples=config.bootstrap_samples,
        seed=config.bootstrap_seed,
        periods_per_year=365.0,
    )
    probabilities = bootstrap["win_probabilities"]
    candidate_targets = [
        float(row["execution_state"]["active_vol_target"])
        for row in candidate_result.equity
    ]
    funding_activity = activity["funding_veto"]
    gates = {
        "score_coverage_complete": score_coverage_complete,
        "purged_oos_predictions_only": all(
            fold.get("purge_check_passed") is True for fold in _macro_trial(macro_audit)["folds"]
        ),
        "base_risk_floor_preserved": min(candidate_targets)
        >= FUTURES_FUNDING_VETO_PROTOCOL.base_vol_target,
        "risk_target_never_above_frozen_boost": max(candidate_targets)
        <= FUTURES_FUNDING_VETO_PROTOCOL.strong_bull_vol_target,
        "maximum_effective_gross_at_most_one": candidate["maximum_effective_gross"] <= 1.0,
        "macro_veto_exercised": activity["macro_vetoed_bar_count"] > 0,
        "funding_coverage_complete": funding_activity["funding_coverage"] == 1.0,
        "candidate_return_not_lower_than_base": candidate["return_pct"] >= base["return_pct"],
        "maximum_return_degradation_vs_funding_veto": (
            comparison["return_delta_percentage_points"]
            >= -config.maximum_return_degradation_percentage_points
        ),
        "sharpe_not_lower_than_funding_veto": candidate["sharpe"] >= reference["sharpe"],
        "minimum_drawdown_improvement_vs_funding_veto": (
            comparison["drawdown_improvement_percentage_points"]
            >= config.minimum_drawdown_improvement_percentage_points
        ),
        "bootstrap_sharpe_win_probability": (
            probabilities["candidate_sharpe_above_reference"]
            >= config.minimum_bootstrap_sharpe_win_probability
        ),
        "bootstrap_drawdown_win_probability": (
            probabilities["candidate_max_drawdown_below_reference"]
            >= config.minimum_bootstrap_drawdown_win_probability
        ),
        "execution_contract_clean": (
            candidate["runtime_filter_coverage"] == 1.0
            and candidate["duplicate_decision_count"] == 0
            and candidate["same_bar_stop_reentry_count"] == 0
        ),
    }
    retained = all(gates.values())
    score_rows = [[date, scores[date]] for date in sorted(scores)]
    return {
        "schema_version": MACRO_BOOST_VETO_REPORT_VERSION,
        "artifact_type": "mini_trend_h41_boost_veto_ablation",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "private_exchange_data": False,
            "actual_outcome_fields_used_by_selector": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": preregistration["contract"],
        "lineage": {
            "preregistration_hash": canonical_hash(preregistration),
            "macro_audit_hash": canonical_hash(macro_audit),
            "score_hash": canonical_hash(score_rows),
            "market_data_hash": _data_hash(bars, funding_by_symbol),
            "exchange_rules_hash": rules_hash,
            "funding_veto_contract_hash": FUTURES_FUNDING_VETO_PROTOCOL.contract_hash,
        },
        "score_coverage": {
            "rows": len(scores),
            "start": min(scores),
            "end": max(scores),
            "exact_strategy_date_match": score_coverage_complete,
        },
        "base": base,
        "reference_funding_veto": reference,
        "reference_funding_activity": reference_activity,
        "candidate": candidate,
        "candidate_activity": activity,
        "comparison_vs_funding_veto": comparison,
        "comparison_vs_base": versus_base,
        "paired_block_bootstrap": bootstrap,
        "gates": gates,
        "passed_gate_count": sum(gates.values()),
        "gate_count": len(gates),
        "diagnostics": {
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "verdict": (
                "retain_h41_boost_veto_for_future_only_research"
                if retained
                else "reject_h41_boost_veto_ablation"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_macro_boost_veto_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-h41-boost-veto",
        path_key="artifact_path",
        default_filename="mini_trend_h41_boost_veto.json",
        explicit_path=explicit_path,
    )
