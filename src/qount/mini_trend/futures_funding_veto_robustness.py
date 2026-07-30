"""Conditional path-robustness audit for the fixed UM funding-veto candidate."""

from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.futures_funding_veto import FUNDING_VETO_PREREG_VERSION
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto_report import FUNDING_VETO_REPORT_VERSION
from qount.mini_trend.futures_funding_veto_report import _data_hash, _metrics, _run_variants
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.futures_risk_tier import file_sha256
from qount.mini_trend.forward import TOP3
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.models import utc_now
from qount.research_data.metrics import sharpe
from qount.settings import Settings


FUNDING_VETO_ROBUSTNESS_PREREG_VERSION = (
    "mini_trend_um_funding_veto_robustness_preregistration_v0.1"
)
FUNDING_VETO_ROBUSTNESS_REPORT_VERSION = (
    "mini_trend_um_funding_veto_robustness_historical_v0.1"
)


@dataclass(frozen=True)
class FundingVetoRobustnessProtocol:
    strategy: str = "MiniTrend-UM-FundingVeto-v0.1"
    reference: str = "MiniTrend-UM-RegimeStopLatch-v0.1"
    block_length_completed_days: int = 20
    bootstrap_samples: int = 5_000
    deterministic_seed: int = 20_260_717
    periods_per_year: float = 365.0
    lower_quantile: float = 0.05
    upper_quantile: float = 0.95
    minimum_win_probability: float = 0.55

    @property
    def full_window(self) -> dict[str, str]:
        return FUTURES_FUNDING_VETO_PROTOCOL.full_window

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "candidate_contract_hash": FUTURES_FUNDING_VETO_PROTOCOL.contract_hash,
            "reference": self.reference,
            "reference_contract_hash": (
                FUTURES_FUNDING_VETO_PROTOCOL.contract_basis[
                    "inherited_stop_latch_contract_hash"
                ]
            ),
            "comparison": {
                "source": "paired realized net daily simple returns from an exact historical replay",
                "same_day_pairing_required": True,
                "costs_and_funding_inherited": True,
                "signal_state_reestimated_inside_bootstrap": False,
                "parameters_reestimated_inside_bootstrap": False,
            },
            "bootstrap": {
                "method": "paired_circular_moving_block_bootstrap",
                "block_length_completed_days": self.block_length_completed_days,
                "bootstrap_samples": self.bootstrap_samples,
                "deterministic_seed": self.deterministic_seed,
                "sample_path_length": "same as realized full-window daily return sequence",
                "block_start_sampling": "uniform with replacement over every observed day",
                "block_boundary": "wrap around the end of the realized sequence",
                "annualized_sharpe_periods": self.periods_per_year,
                "reported_quantiles": [self.lower_quantile, 0.5, self.upper_quantile],
            },
            "limitations": {
                "holdout_role": "consumed_historical_discovery_only",
                "conditional_on_realized_return_sequences": True,
                "not_signal_path_resimulation": True,
                "not_oos": True,
                "not_paper_or_live_evidence": True,
            },
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "full_window": self.full_window,
            "robustness_gates": {
                "minimum_candidate_terminal_return_win_probability": self.minimum_win_probability,
                "minimum_candidate_sharpe_win_probability": self.minimum_win_probability,
                "minimum_candidate_lower_max_drawdown_probability": self.minimum_win_probability,
                "minimum_median_terminal_return_delta_percentage_points": 0.0,
                "minimum_median_sharpe_delta": 0.0,
                "maximum_median_max_drawdown_delta_percentage_points": 0.0,
                "strict_delta_signs_required": True,
                "exact_historical_replay_required": True,
            },
            "trial_count": 1,
            "parameter_search_allowed": False,
            "block_length_search_allowed": False,
            "seed_search_allowed": False,
            "metric_selection_after_result_allowed": False,
            "paper_or_live_allowed": False,
            "promotion_rule": (
                "This conditional bootstrap may retain or downgrade the consumed-history candidate; "
                "it can never promote it to OOS, paper, or live."
            ),
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


FUNDING_VETO_ROBUSTNESS_PROTOCOL = FundingVetoRobustnessProtocol()


def _load_json_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _load_funding_veto_preregistration(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = _load_json_object(source)
    if payload.get("schema_version") != FUNDING_VETO_PREREG_VERSION:
        raise ValueError("unexpected funding-veto preregistration schema")
    if payload.get("decision_contract", {}).get("contract_hash") != (
        FUTURES_FUNDING_VETO_PROTOCOL.contract_hash
    ):
        raise ValueError("funding-veto preregistration contract hash mismatch")
    if payload.get("protocol", {}).get("protocol_hash") != (
        FUTURES_FUNDING_VETO_PROTOCOL.protocol_hash
    ):
        raise ValueError("funding-veto preregistration protocol hash mismatch")
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
    }


def _load_source_historical(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = _load_json_object(source)
    if payload.get("schema_version") != FUNDING_VETO_REPORT_VERSION:
        raise ValueError("unexpected funding-veto historical schema")
    if payload.get("artifact_type") != "mini_trend_um_funding_veto_historical_diagnostic":
        raise ValueError("unexpected funding-veto historical artifact")
    if payload.get("contract_hash") != FUTURES_FUNDING_VETO_PROTOCOL.contract_hash:
        raise ValueError("funding-veto historical contract hash mismatch")
    if payload.get("protocol_hash") != FUTURES_FUNDING_VETO_PROTOCOL.protocol_hash:
        raise ValueError("funding-veto historical protocol hash mismatch")
    if payload.get("diagnostics", {}).get("verdict") != (
        "retain_historical_funding_veto_candidate"
    ):
        raise ValueError("robustness audit requires the retained historical candidate")
    meta = payload.get("meta", {})
    if meta.get("holdout_role") != "discovery_pool" or meta.get("network_download_used") is not False:
        raise ValueError("source historical artifact has an invalid data boundary")
    full = payload.get("full_window", {})
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "verdict": payload["diagnostics"]["verdict"],
        "contract_hash": payload["contract_hash"],
        "protocol_hash": payload["protocol_hash"],
        "exchange_rules_hash": payload["exchange_rules_hash"],
        "full_window_data_hash": full["data_hash"],
        "reference_metrics": {
            key: full["reference_stop_latch"][key]
            for key in ("return_pct", "sharpe", "max_drawdown_pct")
        },
        "candidate_metrics": {
            key: full["candidate"][key]
            for key in ("return_pct", "sharpe", "max_drawdown_pct")
        },
        "funding_veto_event_count": full["funding_veto_event_audit"]["event_count"],
    }


def build_funding_veto_robustness_preregistration(
    rules_artifact: Mapping[str, Any],
    funding_veto_preregistration_path: str | Path,
    funding_veto_historical_path: str | Path,
) -> dict[str, Any]:
    _, rules_hash = selected_um_rules(rules_artifact)
    parent = _load_funding_veto_preregistration(funding_veto_preregistration_path)
    source = _load_source_historical(funding_veto_historical_path)
    if source["exchange_rules_hash"] != rules_hash:
        raise ValueError("source historical exchange-rules hash mismatch")
    protocol = FUNDING_VETO_ROBUSTNESS_PROTOCOL
    return {
        "schema_version": FUNDING_VETO_ROBUSTNESS_PREREG_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_robustness_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "bootstrap_results_evaluated": False,
            "source_historical_results_consumed": True,
            "existing_cache_only": True,
            "network_download_allowed": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "decision_contract": protocol.contract_basis | {"contract_hash": protocol.contract_hash},
        "protocol": protocol.protocol_basis | {"protocol_hash": protocol.protocol_hash},
        "exchange_rules": {"selected_rules_hash": rules_hash, "symbols": sorted(TOP3)},
        "funding_veto_preregistration": parent,
        "source_historical": source,
    }


def validate_funding_veto_robustness_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    funding_veto_preregistration_path: str | Path,
    funding_veto_historical_path: str | Path,
) -> None:
    protocol = FUNDING_VETO_ROBUSTNESS_PROTOCOL
    if preregistration.get("schema_version") != FUNDING_VETO_ROBUSTNESS_PREREG_VERSION:
        raise ValueError("unexpected funding-veto robustness preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("funding-veto robustness contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("funding-veto robustness protocol hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("funding-veto robustness exchange-rules hash mismatch")
    parent = _load_funding_veto_preregistration(funding_veto_preregistration_path)
    if preregistration.get("funding_veto_preregistration", {}).get(
        "artifact_sha256"
    ) != parent["artifact_sha256"]:
        raise ValueError("funding-veto parent preregistration hash mismatch")
    source = _load_source_historical(funding_veto_historical_path)
    if preregistration.get("source_historical", {}).get("artifact_sha256") != source[
        "artifact_sha256"
    ]:
        raise ValueError("funding-veto source historical hash mismatch")


def _daily_simple_returns(result: VariantResult) -> tuple[list[str], list[float]]:
    previous = FUTURES_FUNDING_VETO_PROTOCOL.capital_usdt
    dates: list[str] = []
    returns: list[float] = []
    for row in result.equity:
        equity = float(row["equity"])
        dates.append(str(row["outcome_date"]))
        returns.append(equity / previous - 1.0)
        previous = equity
    return dates, returns


def paired_daily_returns(
    reference: VariantResult, candidate: VariantResult
) -> tuple[list[str], list[float], list[float]]:
    reference_dates, reference_returns = _daily_simple_returns(reference)
    candidate_dates, candidate_returns = _daily_simple_returns(candidate)
    if reference_dates != candidate_dates:
        raise ValueError("reference and candidate daily returns are not aligned")
    if len(reference_returns) < FUNDING_VETO_ROBUSTNESS_PROTOCOL.block_length_completed_days:
        raise ValueError("daily return sequence is shorter than the bootstrap block")
    return reference_dates, reference_returns, candidate_returns


def circular_moving_block_indices(
    rng: random.Random, observations: int, block_length: int
) -> list[int]:
    if observations <= 0:
        raise ValueError("observations must be positive")
    if block_length <= 0 or block_length > observations:
        raise ValueError("block_length must be in [1, observations]")
    indices: list[int] = []
    while len(indices) < observations:
        start = rng.randrange(observations)
        indices.extend((start + offset) % observations for offset in range(block_length))
    return indices[:observations]


def _path_metrics(returns: Sequence[float], periods_per_year: float) -> dict[str, float]:
    curve = [1.0]
    for value in returns:
        next_equity = curve[-1] * (1.0 + float(value))
        if next_equity <= 0.0:
            raise ValueError("bootstrap path equity became non-positive")
        curve.append(next_equity)
    return {
        "terminal_return_pct": (curve[-1] - 1.0) * 100.0,
        "sharpe": sharpe(returns, periods_per_year=periods_per_year),
        "max_drawdown_pct": max_drawdown_pct(curve),
    }


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot compute a quantile of an empty sequence")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("quantile probability must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution_summary(values: Sequence[float]) -> dict[str, float]:
    protocol = FUNDING_VETO_ROBUSTNESS_PROTOCOL
    return {
        "median": round(statistics.median(values), 8),
        "p05": round(_quantile(values, protocol.lower_quantile), 8),
        "p95": round(_quantile(values, protocol.upper_quantile), 8),
    }


def paired_moving_block_bootstrap(
    reference_returns: Sequence[float],
    candidate_returns: Sequence[float],
    *,
    block_length: int,
    samples: int,
    seed: int,
    periods_per_year: float,
) -> dict[str, Any]:
    if len(reference_returns) != len(candidate_returns):
        raise ValueError("paired bootstrap requires equal-length return sequences")
    if samples <= 0:
        raise ValueError("samples must be positive")
    observations = len(reference_returns)
    rng = random.Random(seed)
    return_deltas: list[float] = []
    sharpe_deltas: list[float] = []
    drawdown_deltas: list[float] = []
    for _ in range(samples):
        indices = circular_moving_block_indices(rng, observations, block_length)
        reference = _path_metrics(
            [reference_returns[index] for index in indices], periods_per_year
        )
        candidate = _path_metrics(
            [candidate_returns[index] for index in indices], periods_per_year
        )
        return_deltas.append(candidate["terminal_return_pct"] - reference["terminal_return_pct"])
        sharpe_deltas.append(candidate["sharpe"] - reference["sharpe"])
        drawdown_deltas.append(
            candidate["max_drawdown_pct"] - reference["max_drawdown_pct"]
        )
    return {
        "sample_count": samples,
        "observation_count": observations,
        "block_length_completed_days": block_length,
        "deterministic_seed": seed,
        "win_probabilities": {
            "candidate_terminal_return_above_reference": round(
                sum(value > 0.0 for value in return_deltas) / samples, 8
            ),
            "candidate_sharpe_above_reference": round(
                sum(value > 0.0 for value in sharpe_deltas) / samples, 8
            ),
            "candidate_max_drawdown_below_reference": round(
                sum(value < 0.0 for value in drawdown_deltas) / samples, 8
            ),
        },
        "delta_distributions": {
            "terminal_return_percentage_points": _distribution_summary(return_deltas),
            "sharpe": _distribution_summary(sharpe_deltas),
            "max_drawdown_percentage_points": _distribution_summary(drawdown_deltas),
        },
    }


def _metric_deltas(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, float]:
    return {
        key: round(float(actual[key]) - float(expected[key]), 10)
        for key in ("return_pct", "sharpe", "max_drawdown_pct")
    }


def build_funding_veto_robustness_report(
    source: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    funding_veto_preregistration_path: str | Path,
    funding_veto_historical_path: str | Path,
) -> dict[str, Any]:
    validate_funding_veto_robustness_registration(
        preregistration,
        rules_artifact,
        funding_veto_preregistration_path,
        funding_veto_historical_path,
    )
    rules, rules_hash = selected_um_rules(rules_artifact)
    bars = align_bars(source["bars"], TOP3)
    data_hash = _data_hash(bars, source["funding"])
    registered_source = preregistration["source_historical"]
    if data_hash != registered_source["full_window_data_hash"]:
        raise ValueError("funding-veto robustness data hash mismatch")
    _, reference, candidate, funding_activity = _run_variants(
        bars, source["funding"], rules
    )
    reference_metrics = _metrics(reference)
    candidate_metrics = _metrics(candidate, funding_activity)
    reference_replay_delta = _metric_deltas(
        reference_metrics, registered_source["reference_metrics"]
    )
    candidate_replay_delta = _metric_deltas(
        candidate_metrics, registered_source["candidate_metrics"]
    )
    replay_tolerance = 1e-8
    replay_exact = all(
        abs(value) <= replay_tolerance
        for value in list(reference_replay_delta.values()) + list(candidate_replay_delta.values())
    )
    dates, reference_returns, candidate_returns = paired_daily_returns(reference, candidate)
    protocol = FUNDING_VETO_ROBUSTNESS_PROTOCOL
    bootstrap = paired_moving_block_bootstrap(
        reference_returns,
        candidate_returns,
        block_length=protocol.block_length_completed_days,
        samples=protocol.bootstrap_samples,
        seed=protocol.deterministic_seed,
        periods_per_year=protocol.periods_per_year,
    )
    observed_reference = _path_metrics(reference_returns, protocol.periods_per_year)
    observed_candidate = _path_metrics(candidate_returns, protocol.periods_per_year)
    observed_delta = {
        key: round(observed_candidate[key] - observed_reference[key], 8)
        for key in observed_reference
    }
    probabilities = bootstrap["win_probabilities"]
    distributions = bootstrap["delta_distributions"]
    thresholds = protocol.protocol_basis["robustness_gates"]
    gates = {
        "exact_historical_replay": replay_exact,
        "minimum_candidate_terminal_return_win_probability": probabilities[
            "candidate_terminal_return_above_reference"
        ]
        >= thresholds["minimum_candidate_terminal_return_win_probability"],
        "minimum_candidate_sharpe_win_probability": probabilities[
            "candidate_sharpe_above_reference"
        ]
        >= thresholds["minimum_candidate_sharpe_win_probability"],
        "minimum_candidate_lower_max_drawdown_probability": probabilities[
            "candidate_max_drawdown_below_reference"
        ]
        >= thresholds["minimum_candidate_lower_max_drawdown_probability"],
        "positive_median_terminal_return_delta": distributions[
            "terminal_return_percentage_points"
        ]["median"]
        > thresholds["minimum_median_terminal_return_delta_percentage_points"],
        "positive_median_sharpe_delta": distributions["sharpe"]["median"]
        > thresholds["minimum_median_sharpe_delta"],
        "negative_median_max_drawdown_delta": distributions[
            "max_drawdown_percentage_points"
        ]["median"]
        < thresholds["maximum_median_max_drawdown_delta_percentage_points"],
    }
    passed = all(gates.values())
    return {
        "schema_version": FUNDING_VETO_ROBUSTNESS_REPORT_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_robustness_historical_diagnostic",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "discovery_pool",
            "existing_cache_only": True,
            "network_download_used": False,
            "conditional_bootstrap": True,
            "signal_path_resimulation": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "exchange_rules_hash": rules_hash,
        "source_historical_sha256": registered_source["artifact_sha256"],
        "data_hash": data_hash,
        "date_range": {"start": dates[0], "end": dates[-1]},
        "historical_replay": {
            "tolerance": replay_tolerance,
            "exact": replay_exact,
            "reference_metric_deltas": reference_replay_delta,
            "candidate_metric_deltas": candidate_replay_delta,
            "funding_veto_event_count": funding_activity["vetoed_bar_count"],
        },
        "observed_realized_path": {
            "reference": {key: round(value, 8) for key, value in observed_reference.items()},
            "candidate": {key: round(value, 8) for key, value in observed_candidate.items()},
            "candidate_minus_reference": observed_delta,
        },
        "bootstrap": bootstrap,
        "diagnostics": {
            "gates": gates,
            "robustness_gate_passed": passed,
            "verdict": (
                "retain_historical_candidate_after_conditional_bootstrap"
                if passed
                else "downgrade_historical_candidate_after_conditional_bootstrap"
            ),
            "interpretation": (
                "Paired block resampling tests realized-path sensitivity only; it is not OOS "
                "and does not rerun signal state on synthetic market paths."
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_funding_veto_robustness_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-robustness-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_robustness_preregistration.json",
        explicit_path=explicit_path,
    )


def write_funding_veto_robustness_report_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-robustness-historical",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_robustness_historical.json",
        explicit_path=explicit_path,
    )
