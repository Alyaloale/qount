"""Point-in-time DVOL feature augmentation for direct economic ML research."""

from __future__ import annotations

import bisect
import datetime as dt
import statistics
from dataclasses import asdict
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_economic_ml import EconomicMLConfig
from qount.mini_trend.regime_economic_ml import _ranking_key
from qount.mini_trend.regime_economic_ml import run_economic_ml_walk_forward
from qount.mini_trend.regime_ml import FEATURE_NAMES
from qount.mini_trend.regime_ml import RegimeMLConfig
from qount.mini_trend.regime_ml import build_regime_ml_dataset
from qount.models import utc_now
from qount.settings import Settings


DVOL_ML_VERSION = "mini_trend_regime_dvol_economic_ml_v0.1"
DAY_MS = 86_400_000
DVOL_FEATURE_NAMES = (
    "btc_dvol_level",
    "eth_dvol_level",
    "eth_minus_btc_dvol_level",
    "btc_dvol_return_1d",
    "eth_dvol_return_1d",
    "dvol_spread_change_1d",
    "btc_dvol_return_7d",
    "eth_dvol_return_7d",
    "btc_dvol_z_30d",
    "eth_dvol_z_30d",
    "dvol_spread_z_30d",
    "btc_dvol_range_mean_1d",
    "eth_dvol_range_mean_1d",
)
ALL_DVOL_FEATURE_NAMES = FEATURE_NAMES + DVOL_FEATURE_NAMES


def _zscore(value: float, history: Sequence[float]) -> float:
    mean = statistics.fmean(history)
    std = statistics.stdev(history) if len(history) > 1 else 0.0
    return (value - mean) / std if std > 0 else 0.0


def _decision_cutoff_ms(decision_date: str) -> int:
    value = dt.datetime.combine(
        dt.date.fromisoformat(decision_date), dt.time(), tzinfo=dt.UTC
    )
    return int(value.timestamp() * 1000) + DAY_MS


def augment_dataset_with_dvol(
    dataset: Mapping[str, Any], dvol_payload: Mapping[str, Any]
) -> dict[str, Any]:
    hourly = [row for row in dvol_payload["hourly_features"] if row.get("complete")]
    hourly.sort(key=lambda row: int(row["decision_ts_ms"]))
    decision_times = [int(row["decision_ts_ms"]) for row in hourly]
    btc_close = [float(row["btc_dvol_close"]) for row in hourly]
    eth_close = [float(row["eth_dvol_close"]) for row in hourly]
    spread = [float(row["eth_minus_btc_dvol_close"]) for row in hourly]
    rows = []
    skipped_warmup = skipped_coverage = 0
    for source in dataset["rows"]:
        cutoff = _decision_cutoff_ms(str(source["decision_date"]))
        index = bisect.bisect_right(decision_times, cutoff) - 1
        if index < 0 or decision_times[index] > cutoff:
            skipped_coverage += 1
            continue
        if index < 720:
            skipped_warmup += 1
            continue
        if cutoff - decision_times[index] > 3_600_000:
            skipped_coverage += 1
            continue
        btc_history = btc_close[index - 719 : index + 1]
        eth_history = eth_close[index - 719 : index + 1]
        spread_history = spread[index - 719 : index + 1]
        recent = hourly[index - 23 : index + 1]
        extra = {
            "btc_dvol_level": btc_close[index],
            "eth_dvol_level": eth_close[index],
            "eth_minus_btc_dvol_level": spread[index],
            "btc_dvol_return_1d": btc_close[index] / btc_close[index - 24] - 1.0,
            "eth_dvol_return_1d": eth_close[index] / eth_close[index - 24] - 1.0,
            "dvol_spread_change_1d": spread[index] - spread[index - 24],
            "btc_dvol_return_7d": btc_close[index] / btc_close[index - 168] - 1.0,
            "eth_dvol_return_7d": eth_close[index] / eth_close[index - 168] - 1.0,
            "btc_dvol_z_30d": _zscore(btc_close[index], btc_history),
            "eth_dvol_z_30d": _zscore(eth_close[index], eth_history),
            "dvol_spread_z_30d": _zscore(spread[index], spread_history),
            "btc_dvol_range_mean_1d": statistics.fmean(
                (float(row["btc_dvol_high"]) - float(row["btc_dvol_low"]))
                / max(float(row["btc_dvol_close"]), 1e-12)
                for row in recent
            ),
            "eth_dvol_range_mean_1d": statistics.fmean(
                (float(row["eth_dvol_high"]) - float(row["eth_dvol_low"]))
                / max(float(row["eth_dvol_close"]), 1e-12)
                for row in recent
            ),
        }
        if tuple(extra) != DVOL_FEATURE_NAMES:
            raise AssertionError("DVOL feature order changed")
        rows.append(
            dict(source)
            | {
                "features": dict(source["features"]) | extra,
                "dvol_decision_ts_ms": decision_times[index],
            }
        )
    result = dict(dataset)
    result["schema_version"] = DVOL_ML_VERSION
    result["features"] = list(ALL_DVOL_FEATURE_NAMES)
    result["rows"] = rows
    result["summary"] = dict(dataset["summary"]) | {
        "row_count": len(rows),
        "first_decision_date": rows[0]["decision_date"] if rows else None,
        "last_decision_date": rows[-1]["decision_date"] if rows else None,
        "dvol_skipped_warmup": skipped_warmup,
        "dvol_skipped_coverage": skipped_coverage,
    }
    dvol_hash = str(dvol_payload["meta"]["data_hash"])
    result["contract"] = dict(dataset["contract"]) | {
        "base_contract_hash": dataset["contract"]["contract_hash"],
        "dvol_data_hash": dvol_hash,
        "dvol_point_in_time_rule": "last hourly candle with decision_ts_ms <= daily close",
        "contract_hash": canonical_hash(
            {
                "base_contract_hash": dataset["contract"]["contract_hash"],
                "dvol_data_hash": dvol_hash,
                "features": list(ALL_DVOL_FEATURE_NAMES),
            }
        ),
    }
    result["data_hash"] = canonical_hash(
        {
            "base_data_hash": dataset["data_hash"],
            "dvol_data_hash": dvol_hash,
            "dvol_features": [
                [row["decision_date"], *[row["features"][name] for name in DVOL_FEATURE_NAMES]]
                for row in rows
            ],
        }
    )
    return result


def build_dvol_economic_ml_matrix(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    dvol_payload: Mapping[str, Any],
    config: EconomicMLConfig,
    *,
    use_gpu: bool,
) -> dict[str, Any]:
    trials = []
    lineage = {}
    for horizon in config.horizons:
        base_dataset = build_regime_ml_dataset(
            bars_by_symbol,
            funding_by_symbol,
            RegimeMLConfig(
                start_date=config.start_date,
                end_date=config.end_date,
                horizon_days=horizon,
                barrier_sigma=1.0,
                trial_count=config.trial_count,
                seed=config.seed,
            ),
        )
        dataset = augment_dataset_with_dvol(base_dataset, dvol_payload)
        lineage[str(horizon)] = {
            "contract_hash": dataset["contract"]["contract_hash"],
            "data_hash": dataset["data_hash"],
            "rows": len(dataset["rows"]),
        }
        for target in config.targets:
            for model_name in config.models:
                trial = run_economic_ml_walk_forward(
                    dataset,
                    target=target,
                    model_name=model_name,
                    use_gpu=use_gpu,
                    seed=config.seed + horizon * 100 + config.models.index(model_name),
                    bootstrap_samples=config.bootstrap_samples,
                    feature_names=ALL_DVOL_FEATURE_NAMES,
                )
                trial["trial_id"] = f"h{horizon}_{target}_{model_name}_dvol"
                trial["horizon_days"] = horizon
                trials.append(trial)
    ranked = sorted(trials, key=_ranking_key, reverse=True)
    retained = [row for row in ranked if row["verdict"].startswith("retain_")]
    return {
        "schema_version": DVOL_ML_VERSION,
        "artifact_type": "mini_trend_regime_dvol_economic_ml_matrix",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "network_download_used": True,
            "download_node": "wsl",
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "features": list(ALL_DVOL_FEATURE_NAMES),
            "new_family_trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "contract_hash": canonical_hash(
                {
                    "config": asdict(config),
                    "features": list(ALL_DVOL_FEATURE_NAMES),
                    "dvol_data_hash": dvol_payload["meta"]["data_hash"],
                }
            ),
        },
        "dvol_lineage": {
            "schema_version": dvol_payload["schema_version"],
            "data_hash": dvol_payload["meta"]["data_hash"],
            "coverage": dvol_payload["diagnostics"]["aligned_coverage_ratio"],
            "first_ts_ms": dvol_payload["hourly_features"][0]["ts_ms"],
            "last_ts_ms": dvol_payload["hourly_features"][-1]["ts_ms"],
        },
        "data_lineage": lineage,
        "trials": trials,
        "ranking": [row["trial_id"] for row in ranked],
        "best_by_target": {
            target: next((row for row in ranked if row["target"] == target), None)
            for target in config.targets
        },
        "retained_trial_ids": [row["trial_id"] for row in retained],
        "diagnostics": {
            "trial_count": len(trials),
            "cumulative_trial_count": config.cumulative_trial_count,
            "retained_trial_count": len(retained),
            "verdict": (
                "retain_dvol_economic_models_for_ablation"
                if retained
                else "reject_dvol_economic_model_matrix"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_dvol_economic_ml_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-regime-dvol-economic-ml",
        path_key="artifact_path",
        default_filename="mini_trend_regime_dvol_economic_ml.json",
        explicit_path=explicit_path,
    )
