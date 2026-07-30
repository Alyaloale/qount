"""Consumed-history target sensitivity matrix for the causal regime HMM."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.regime_hmm_audit import HMMAuditConfig
from qount.mini_trend.regime_hmm_audit import build_hmm_economic_audit
from qount.mini_trend.regime_ml import RegimeMLConfig
from qount.mini_trend.regime_ml import build_regime_ml_dataset
from qount.models import utc_now
from qount.settings import Settings


HMM_TARGET_MATRIX_VERSION = "mini_trend_regime_hmm_target_matrix_v0.1"


@dataclass(frozen=True)
class HMMTargetMatrixConfig:
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    horizons: tuple[int, ...] = (10, 20, 30, 60)
    barrier_sigmas: tuple[float, ...] = (0.75, 1.0, 1.25)
    probability_bins: int = 5
    bootstrap_samples: int = 1_000
    seed: int = 20260718

    @property
    def trial_count(self) -> int:
        return len(self.horizons) * len(self.barrier_sigmas)

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "trial_count": self.trial_count,
                "selection": (
                    "rank all consumed-history trials by passed economic gates, fold stability, "
                    "block-bootstrap probability, then mean Brier uplift"
                ),
                "promotion_allowed": False,
            }
        )


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _compact_trial(
    audit: Mapping[str, Any], *, horizon_days: int, barrier_sigma: float
) -> dict[str, Any]:
    economics = audit["economic_conditioning"]
    fold_quality = audit["fold_probability_quality"]
    bootstrap = economics["block_bootstrap"]["forward_return_horizon"]
    return {
        "trial_id": f"h{horizon_days}_sigma{barrier_sigma:g}",
        "horizon_days": horizon_days,
        "barrier_sigma": barrier_sigma,
        "sample": dict(audit["sample"]),
        "dataset_contract_hash": audit["lineage"]["dataset_contract_hash"],
        "dataset_data_hash": audit["lineage"]["dataset_data_hash"],
        "fold_probability_quality": list(fold_quality),
        "mean_brier_improvement_vs_constant": _mean(
            [float(row["brier_improvement_vs_constant"]) for row in fold_quality]
        ),
        "positive_brier_fold_count": sum(
            float(row["brier_improvement_vs_constant"]) > 0 for row in fold_quality
        ),
        "probability_reliability": dict(audit["probability_reliability"]),
        "risk_score_top3_return_spearman": economics[
            "risk_score_top3_return_spearman"
        ],
        "risk_score_base_return_spearman": economics[
            "risk_score_base_return_spearman"
        ],
        "bear_probability_base_drawdown_spearman": economics[
            "bear_probability_base_drawdown_spearman"
        ],
        "high_minus_low_top3_return": economics["high_minus_low_top3_return"],
        "high_minus_low_base_return": economics["high_minus_low_base_return"],
        "high_minus_low_base_drawdown": economics["high_minus_low_base_drawdown"],
        "positive_top3_return_spread_fold_count": economics[
            "positive_top3_return_spread_fold_count"
        ],
        "fold_economics": list(economics["folds"]),
        "bootstrap_return_spread": dict(bootstrap),
        "gates": dict(audit["diagnostics"]["gates"]),
        "passed_gate_count": audit["diagnostics"]["passed_gate_count"],
        "gate_count": audit["diagnostics"]["gate_count"],
        "verdict": audit["diagnostics"]["verdict"],
    }


def _ranking_key(trial: Mapping[str, Any]) -> tuple[float, ...]:
    return (
        float(trial["passed_gate_count"]),
        float(trial["positive_top3_return_spread_fold_count"]),
        float(trial["bootstrap_return_spread"]["probability_spread_positive"]),
        float(trial["mean_brier_improvement_vs_constant"]),
    )


def build_hmm_target_matrix(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    base_result: VariantResult,
    config: HMMTargetMatrixConfig | None = None,
) -> dict[str, Any]:
    config = config or HMMTargetMatrixConfig()
    trials = []
    for horizon_days in config.horizons:
        for barrier_sigma in config.barrier_sigmas:
            dataset = build_regime_ml_dataset(
                bars_by_symbol,
                funding_by_symbol,
                RegimeMLConfig(
                    start_date=config.start_date,
                    end_date=config.end_date,
                    horizon_days=horizon_days,
                    barrier_sigma=barrier_sigma,
                    trial_count=config.trial_count,
                    seed=config.seed,
                ),
            )
            audit = build_hmm_economic_audit(
                dataset,
                base_result,
                HMMAuditConfig(
                    probability_bins=config.probability_bins,
                    economic_horizon_days=horizon_days,
                    bootstrap_block_days=horizon_days,
                    bootstrap_samples=config.bootstrap_samples,
                    seed=config.seed + horizon_days * 100 + round(barrier_sigma * 10),
                    trial_count=config.trial_count,
                ),
            )
            trials.append(
                _compact_trial(
                    audit,
                    horizon_days=horizon_days,
                    barrier_sigma=barrier_sigma,
                )
            )
    ranked = sorted(trials, key=_ranking_key, reverse=True)
    retained = [
        row for row in ranked if row["verdict"] == "retain_hmm_for_dynamic_risk_ablation"
    ]
    return {
        "schema_version": HMM_TARGET_MATRIX_VERSION,
        "artifact_type": "mini_trend_regime_hmm_target_matrix",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "network_download_used": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "trial_count": config.trial_count,
            "contract_hash": config.contract_hash,
        },
        "base_result_hash": canonical_hash(base_result.equity),
        "trials": trials,
        "ranking": [row["trial_id"] for row in ranked],
        "best_trial": dict(ranked[0]) if ranked else None,
        "retained_trial_ids": [row["trial_id"] for row in retained],
        "diagnostics": {
            "trial_count": len(trials),
            "retained_trial_count": len(retained),
            "verdict": (
                "retain_hmm_target_candidates_for_risk_ablation"
                if retained
                else "reject_hmm_target_family_after_sensitivity_matrix"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_hmm_target_matrix_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-regime-hmm-target-matrix",
        path_key="artifact_path",
        default_filename="mini_trend_regime_hmm_target_matrix.json",
        explicit_path=explicit_path,
    )
