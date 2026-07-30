"""Fixed macro-feature audit for the retained MiniTrend rolling ranker."""

from __future__ import annotations

import datetime as dt
from bisect import bisect_right
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_economic_ml import run_economic_ml_walk_forward
from qount.mini_trend.regime_ml import FEATURE_NAMES
from qount.mini_trend.regime_ml import RegimeMLConfig
from qount.mini_trend.regime_ml import build_regime_ml_dataset
from qount.models import utc_now
from qount.settings import Settings


MACRO_H41_MODEL_VERSION = "mini_trend_fed_h41_feature_audit_v0.1"
MACRO_FEATURE_NAMES = (
    "fed_assets_4w_change_pct",
    "fed_assets_13w_change_pct",
    "fed_assets_4w_acceleration",
)


@dataclass(frozen=True)
class H41FeatureAuditConfig:
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    horizon_days: int = 60
    training_window_days: int = 365
    model: str = "random_forest"
    target: str = "return"
    bootstrap_samples: int = 10_000
    seed: int = 20260718
    prior_family_trial_count: int = 131

    @property
    def trial_count(self) -> int:
        return len(MACRO_FEATURE_NAMES)

    @property
    def cumulative_trial_count(self) -> int:
        return self.prior_family_trial_count + self.trial_count

    @property
    def model_seed(self) -> int:
        return self.seed + self.horizon_days * 100 + self.training_window_days

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "model_seed": self.model_seed,
                "macro_features": list(MACRO_FEATURE_NAMES),
                "feature_sets": "base plus exactly one macro feature per trial",
                "join": "latest H.4.1 feature with decision_date <= market decision_date",
                "selection": "no window, polarity, model, or feature-combination search",
                "split": "2023-2026 annual folds purged on 60-day horizon end",
                "promotion_allowed": False,
            }
        )


def augment_dataset_with_h41_feature(
    base_dataset: Mapping[str, Any],
    h41_dataset: Mapping[str, Any],
    feature_name: str,
) -> dict[str, Any]:
    if feature_name not in MACRO_FEATURE_NAMES:
        raise ValueError(f"unknown H.4.1 feature: {feature_name}")
    diagnostics = h41_dataset.get("diagnostics", {})
    if diagnostics.get("verdict") != "pass_point_in_time_macro_dataset":
        raise ValueError("H.4.1 dataset did not pass its point-in-time data gate")
    source = sorted(
        h41_dataset.get("weekly_features", []), key=lambda row: row["decision_date"]
    )
    if not source:
        raise ValueError("H.4.1 dataset has no weekly features")
    dates = [dt.date.fromisoformat(row["decision_date"]) for row in source]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise ValueError("H.4.1 feature decision dates must be unique and increasing")

    rows = []
    unmatched = 0
    for original in base_dataset["rows"]:
        decision = dt.date.fromisoformat(original["decision_date"])
        index = bisect_right(dates, decision) - 1
        if index < 0:
            unmatched += 1
            continue
        macro = source[index]
        if dt.date.fromisoformat(macro["decision_date"]) > decision:
            raise AssertionError("H.4.1 as-of join used a future release")
        row = dict(original)
        row["features"] = {
            **original["features"],
            feature_name: float(macro[feature_name]),
        }
        row["h41_lineage"] = {
            "macro_decision_date": macro["decision_date"],
            "release_date": macro["release_date"],
            "observation_date": macro["observation_date"],
        }
        rows.append(row)

    result = dict(base_dataset)
    result["schema_version"] = MACRO_H41_MODEL_VERSION
    result["artifact_type"] = "mini_trend_regime_ml_dataset_with_fed_h41"
    result["created_at"] = utc_now().isoformat()
    base_features = list(
        base_dataset["contract"].get(
            "feature_names", base_dataset.get("features", FEATURE_NAMES)
        )
    )
    result["features"] = [*base_features, feature_name]
    result["rows"] = rows
    result["summary"] = {
        **base_dataset["summary"],
        "row_count": len(rows),
        "unmatched_before_first_macro_decision": unmatched,
        "macro_feature": feature_name,
        "macro_feature_first_decision_date": source[0]["decision_date"],
        "macro_feature_last_decision_date": source[-1]["decision_date"],
    }
    result["contract"] = {
        **base_dataset["contract"],
        "macro_feature": feature_name,
        "macro_join": "as-of latest macro decision_date <= market decision_date",
        "base_dataset_contract_hash": base_dataset["contract"]["contract_hash"],
        "h41_dataset_contract_hash": h41_dataset["contract"]["contract_hash"],
        "contract_hash": canonical_hash(
            {
                "base_dataset_contract_hash": base_dataset["contract"]["contract_hash"],
                "h41_dataset_contract_hash": h41_dataset["contract"]["contract_hash"],
                "h41_data_hash": h41_dataset["data_hash"],
                "macro_feature": feature_name,
                "join": "as-of latest macro decision_date <= market decision_date",
            }
        ),
    }
    result["data_hash"] = canonical_hash(
        {
            "base_data_hash": base_dataset["data_hash"],
            "h41_data_hash": h41_dataset["data_hash"],
            "macro_feature": feature_name,
            "joined": [
                [
                    row["decision_date"],
                    row["h41_lineage"]["macro_decision_date"],
                    row["features"][feature_name],
                ]
                for row in rows
            ],
        }
    )
    return result


def _ranking_key(row: Mapping[str, Any]) -> tuple[float, ...]:
    return (
        float(row["passed_gate_count"]),
        float(row["positive_rank_ic_fold_count"]),
        float(row["positive_spread_fold_count"]),
        float(row["bootstrap"]["probability_spread_positive"]),
        float(row["pooled_rank_ic"]),
        float(row["pooled_high_minus_low_actual"]),
    )


def build_h41_feature_audit(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    h41_dataset: Mapping[str, Any],
    config: H41FeatureAuditConfig | None = None,
) -> dict[str, Any]:
    config = config or H41FeatureAuditConfig()
    if config.model != "random_forest" or config.target != "return":
        raise ValueError("H.4.1 audit v0.1 freezes random_forest/return")
    if config.horizon_days != 60 or config.training_window_days != 365:
        raise ValueError("H.4.1 audit v0.1 freezes 60-day target and 365-day training")
    base = build_regime_ml_dataset(
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
    control = run_economic_ml_walk_forward(
        base,
        target=config.target,
        model_name=config.model,
        use_gpu=False,
        seed=config.model_seed,
        bootstrap_samples=config.bootstrap_samples,
        feature_names=FEATURE_NAMES,
        training_window_days=config.training_window_days,
    )
    trials = []
    lineage = {}
    for feature_name in MACRO_FEATURE_NAMES:
        dataset = augment_dataset_with_h41_feature(base, h41_dataset, feature_name)
        result = run_economic_ml_walk_forward(
            dataset,
            target=config.target,
            model_name=config.model,
            use_gpu=False,
            seed=config.model_seed,
            bootstrap_samples=config.bootstrap_samples,
            feature_names=(*FEATURE_NAMES, feature_name),
            training_window_days=config.training_window_days,
            include_predictions=True,
        )
        result["trial_id"] = f"h41_{feature_name}"
        result["macro_feature"] = feature_name
        result["model_verdict"] = result["verdict"]
        fold_2026 = next(row for row in result["folds"] if row["test_year"] == 2026)
        gates = {
            "all_horizon_purge_checks_passed": all(
                row["purge_check_passed"] for row in result["folds"]
            ),
            "positive_rank_ic_in_three_folds": result["positive_rank_ic_fold_count"] >= 3,
            "positive_spread_in_three_folds": result["positive_spread_fold_count"] >= 3,
            "bootstrap_probability_at_least_80pct": (
                result["bootstrap"]["probability_spread_positive"] >= 0.8
            ),
            "positive_2026_rank_ic_and_spread": (
                fold_2026["rank_ic"] > 0 and fold_2026["high_minus_low_actual"] > 0
            ),
            "pooled_rank_ic_not_lower_than_control": (
                result["pooled_rank_ic"] >= control["pooled_rank_ic"]
            ),
            "pooled_spread_not_lower_than_control": (
                result["pooled_high_minus_low_actual"]
                >= control["pooled_high_minus_low_actual"]
            ),
            "bootstrap_probability_not_lower_than_control": (
                result["bootstrap"]["probability_spread_positive"]
                >= control["bootstrap"]["probability_spread_positive"]
            ),
        }
        retained = all(gates.values())
        result["comparison"] = {
            "pooled_rank_ic_delta": result["pooled_rank_ic"] - control["pooled_rank_ic"],
            "pooled_spread_delta": (
                result["pooled_high_minus_low_actual"]
                - control["pooled_high_minus_low_actual"]
            ),
            "bootstrap_probability_delta": (
                result["bootstrap"]["probability_spread_positive"]
                - control["bootstrap"]["probability_spread_positive"]
            ),
        }
        result["gates"] = gates
        result["passed_gate_count"] = sum(gates.values())
        result["gate_count"] = len(gates)
        result["verdict"] = (
            "retain_h41_feature_against_rolling_control"
            if retained
            else "reject_h41_feature_against_rolling_control"
        )
        trials.append(result)
        lineage[feature_name] = {
            "dataset_contract_hash": dataset["contract"]["contract_hash"],
            "dataset_data_hash": dataset["data_hash"],
            "rows": len(dataset["rows"]),
            "unmatched_before_first_macro_decision": dataset["summary"][
                "unmatched_before_first_macro_decision"
            ],
        }
    ranked = sorted(trials, key=_ranking_key, reverse=True)
    retained = [row for row in ranked if row["verdict"].startswith("retain_")]
    return {
        "schema_version": MACRO_H41_MODEL_VERSION,
        "artifact_type": "mini_trend_fed_h41_feature_audit",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "network_download_used": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "macro_features": list(MACRO_FEATURE_NAMES),
            "model_seed": config.model_seed,
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "contract_hash": config.contract_hash,
        },
        "data_lineage": {
            "base_dataset_contract_hash": base["contract"]["contract_hash"],
            "base_dataset_data_hash": base["data_hash"],
            "h41_dataset_contract_hash": h41_dataset["contract"]["contract_hash"],
            "h41_data_hash": h41_dataset["data_hash"],
            "trials": lineage,
        },
        "control": control,
        "trials": trials,
        "ranking": [row["trial_id"] for row in ranked],
        "best_trial": dict(ranked[0]) if ranked else None,
        "retained_trial_ids": [row["trial_id"] for row in retained],
        "diagnostics": {
            "trial_count": len(trials),
            "cumulative_trial_count": config.cumulative_trial_count,
            "retained_trial_count": len(retained),
            "verdict": (
                "retain_h41_macro_features_for_strategy_ablation"
                if retained
                else "reject_h41_macro_feature_audit"
            ),
            "promotion_evidence": False,
            "paper_or_live_allowed": False,
        },
    }


def write_h41_feature_audit_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-fed-h41-feature-audit",
        path_key="artifact_path",
        default_filename="mini_trend_fed_h41_feature_audit.json",
        explicit_path=explicit_path,
    )
