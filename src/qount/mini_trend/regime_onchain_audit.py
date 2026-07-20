"""Fixed-polarity economic audit of latest-vintage BTC on-chain features."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_economic_ml import _bootstrap_spread
from qount.mini_trend.regime_economic_ml import _quintile_spread, _spearman
from qount.mini_trend.regime_ml import RegimeMLConfig, build_regime_ml_dataset
from qount.models import utc_now
from qount.settings import Settings


ONCHAIN_AUDIT_VERSION = "mini_trend_onchain_feature_audit_v0.2"
FEATURE_POLARITIES = {
    "mvrv_level": -1,
    "mvrv_z365": -1,
    "exchange_net_flow_z90": -1,
    "exchange_gross_flow_z90": -1,
    "active_addresses_z90": 1,
    "tx_count_z90": 1,
    "hashrate_z90": 1,
}


@dataclass(frozen=True)
class OnchainAuditConfig:
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    horizon_days: int = 60
    bootstrap_samples: int = 2_000
    seed: int = 20260718
    prior_research_trial_count: int = 120
    minimum_feature_coverage: float = 0.99

    @property
    def trial_count(self) -> int:
        return len(FEATURE_POLARITIES)

    @property
    def cumulative_trial_count(self) -> int:
        return self.prior_research_trial_count + self.trial_count

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "feature_polarities": FEATURE_POLARITIES,
                "selection": "fixed economic polarity before outcome audit",
                "source_vintage": "latest_available_response_not_historical_vintage",
                "paper_or_live_allowed": False,
            }
        )


def _folds(
    rows: Sequence[Mapping[str, Any]], test_years: Sequence[int]
) -> list[dict[str, Any]]:
    result = []
    for year in test_years:
        selected = [row for row in rows if str(row["decision_date"]).startswith(str(year))]
        if not selected:
            continue
        predicted = [float(row["predicted"]) for row in selected]
        actual = [float(row["actual"]) for row in selected]
        result.append(
            {
                "test_year": year,
                "rows": len(selected),
                "rank_ic": _spearman(predicted, actual),
                "high_minus_low_actual": _quintile_spread(actual, predicted),
            }
        )
    return result


def build_onchain_feature_audit(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    onchain_dataset: Mapping[str, Any],
    config: OnchainAuditConfig | None = None,
) -> dict[str, Any]:
    config = config or OnchainAuditConfig()
    if onchain_dataset.get("diagnostics", {}).get("verdict") != "pass_latest_vintage_dataset":
        raise ValueError("on-chain dataset did not pass the latest-vintage data gate")
    dataset = build_regime_ml_dataset(
        bars_by_symbol,
        funding_by_symbol,
        RegimeMLConfig(
            start_date=config.start_date,
            end_date=config.end_date,
            horizon_days=config.horizon_days,
            barrier_sigma=1.0,
            trial_count=config.trial_count,
            seed=config.seed,
        ),
    )
    by_date = {
        str(row["decision_date"]): row for row in onchain_dataset["daily_features"]
    }
    test_years = tuple(int(year) for year in dataset["contract"]["test_years"])
    eligible = [
        row
        for row in dataset["rows"]
        if int(str(row["decision_date"])[:4]) in test_years
    ]
    joined = [row for row in eligible if row["decision_date"] in by_date]
    coverage = len(joined) / len(eligible) if eligible else 0.0
    trials = []
    for index, (feature, polarity) in enumerate(FEATURE_POLARITIES.items()):
        rows = [
            {
                "decision_date": row["decision_date"],
                "predicted": polarity * float(by_date[row["decision_date"]][feature]),
                "actual": float(row["forward_return_horizon"]),
            }
            for row in joined
        ]
        predicted = [float(row["predicted"]) for row in rows]
        actual = [float(row["actual"]) for row in rows]
        folds = _folds(rows, test_years)
        bootstrap = _bootstrap_spread(
            rows,
            block_days=config.horizon_days,
            samples=config.bootstrap_samples,
            seed=config.seed + index,
        )
        rank_ic = _spearman(predicted, actual)
        spread = _quintile_spread(actual, predicted)
        gates = {
            "minimum_feature_coverage": coverage >= config.minimum_feature_coverage,
            "pooled_rank_ic_above_005": rank_ic > 0.05,
            "positive_rank_ic_in_three_folds": sum(row["rank_ic"] > 0 for row in folds) >= 3,
            "positive_spread_in_three_folds": sum(
                row["high_minus_low_actual"] > 0 for row in folds
            )
            >= 3,
            "bootstrap_positive_probability_at_least_80pct": (
                bootstrap["probability_spread_positive"] >= 0.8
            ),
        }
        trials.append(
            {
                "trial_id": f"{feature}_polarity_{polarity:+d}",
                "feature": feature,
                "polarity": polarity,
                "rows": len(rows),
                "conservative_effective_rows": math.ceil(len(rows) / config.horizon_days),
                "pooled_rank_ic": rank_ic,
                "pooled_high_minus_low_actual": spread,
                "positive_rank_ic_fold_count": sum(row["rank_ic"] > 0 for row in folds),
                "positive_spread_fold_count": sum(
                    row["high_minus_low_actual"] > 0 for row in folds
                ),
                "folds": folds,
                "bootstrap": bootstrap,
                "gates": gates,
                "passed_gate_count": sum(gates.values()),
                "gate_count": len(gates),
                "verdict": (
                    "retain_onchain_feature"
                    if all(gates.values())
                    else "reject_onchain_feature"
                ),
            }
        )
    ranked = sorted(
        trials,
        key=lambda row: (
            row["passed_gate_count"],
            row["positive_rank_ic_fold_count"],
            row["bootstrap"]["probability_spread_positive"],
            row["pooled_rank_ic"],
        ),
        reverse=True,
    )
    retained = [row for row in ranked if row["verdict"].startswith("retain_")]
    return {
        "schema_version": ONCHAIN_AUDIT_VERSION,
        "artifact_type": "mini_trend_onchain_feature_economic_audit",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "source_vintage": "latest_available_response_not_historical_vintage",
            "point_in_time_promotion_ready": False,
            "network_download_used_by_source_dataset": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "feature_polarities": FEATURE_POLARITIES,
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "contract_hash": config.contract_hash,
        },
        "lineage": {
            "regime_dataset_contract_hash": dataset["contract"]["contract_hash"],
            "regime_dataset_data_hash": dataset["data_hash"],
            "onchain_contract_hash": onchain_dataset["contract"]["contract_hash"],
            "onchain_data_hash": onchain_dataset["data_hash"],
        },
        "coverage": {
            "regime_rows": len(eligible),
            "joined_rows": len(joined),
            "ratio": coverage,
            "test_years": list(test_years),
        },
        "trials": trials,
        "ranking": [row["trial_id"] for row in ranked],
        "retained_trial_ids": [row["trial_id"] for row in retained],
        "diagnostics": {
            "trial_count": len(trials),
            "cumulative_trial_count": config.cumulative_trial_count,
            "retained_trial_count": len(retained),
            "verdict": (
                "retain_onchain_features_for_model_ablation"
                if retained
                else "reject_onchain_feature_matrix"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_onchain_feature_audit_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-onchain-feature-audit",
        path_key="artifact_path",
        default_filename="mini_trend_onchain_feature_audit.json",
        explicit_path=explicit_path,
    )
