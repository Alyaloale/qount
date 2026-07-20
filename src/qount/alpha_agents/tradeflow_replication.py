from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings

from .tradeflow_experiment import FROZEN_LOW_TURNOVER_CONTRACT
from .tradeflow_experiment import TRADEFLOW_EXPERIMENT_VERSION


TRADEFLOW_REPLICATION_VERSION = "alpha_agent_tradeflow_replication_v0.1"


@dataclass(frozen=True)
class TradeFlowReplicationProtocol:
    protocol_id: str = "frozen_tradeflow_v1_cross_symbol_replication_v1"
    anchor_symbol: str = "ETHUSDT"
    replication_symbols: tuple[str, ...] = ("BTCUSDT", "BNBUSDT", "SOLUSDT")
    discovery_window: str = "2024-01..2024-03"
    historical_oos_window: str = "2024-04"
    frozen_contract_hash: str = FROZEN_LOW_TURNOVER_CONTRACT.contract_hash
    minimum_replica_oos_count: int = 2
    minimum_positive_replica_rank_ic_count: int = 2
    minimum_positive_replica_residual_count: int = 2
    minimum_effective_breadth: float = 2.0
    maximum_abs_pairwise_correlation: float = 0.80
    minimum_filter_coverage: float = 1.0
    require_positive_equal_weight_residual: bool = True
    require_positive_leave_one_out_residual: bool = True
    oos_consumption_rule: str = "consume a symbol's April archive only after its frozen Q1 discovery passes"
    pbo_policy: str = "single pre-registered candidate remains non-identifiable and blocking at pbo=1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def protocol_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()


FROZEN_REPLICATION_PROTOCOL = TradeFlowReplicationProtocol()


def build_tradeflow_replication_preregistration(
    protocol: TradeFlowReplicationProtocol = FROZEN_REPLICATION_PROTOCOL,
) -> dict[str, Any]:
    return {
        "schema_version": TRADEFLOW_REPLICATION_VERSION,
        "created_at": utc_now().isoformat(),
        "artifact_type": "preregistration",
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "diagnostics": {
            "verdict": "preregistered",
            "replication_data_consumed": False,
            "parameter_tuning_allowed": False,
            "symbol_selection_allowed": False,
            "promotion_gate_changes_allowed": False,
            "next_action": "run frozen Q1 discovery for every replication symbol",
        },
        "hard_boundaries": [
            "The ETH contract and Q1/April results are already observed and cannot be retuned.",
            "Every replica uses the exact same feature, z-score, polarity, holding, cooldown, costs, and filters.",
            "A failed replica is reported; it cannot be silently removed from the denominator.",
            "G4 PBO remains blocking and is not waived by a successful correlation stress.",
            "This artifact cannot authorize A10, paper, live, VPS changes, or order placement.",
        ],
    }


def _load_experiment(path: str | Path) -> tuple[dict[str, Any], Path, str]:
    source = Path(path).expanduser().resolve()
    blob = source.read_bytes()
    payload = json.loads(blob)
    if payload.get("schema_version") != TRADEFLOW_EXPERIMENT_VERSION:
        raise ValueError("replication inputs must be trade-flow experiment artifacts")
    return payload, source, hashlib.sha256(blob).hexdigest()


def _compound_pct(values: list[float]) -> float:
    total = 1.0
    for value in values:
        total *= 1.0 + value / 100.0
    return (total - 1.0) * 100.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _covariance(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = _mean(left)
    right_mean = _mean(right)
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / (len(left) - 1)


def _correlation(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(_variance(left) * _variance(right))
    return _covariance(left, right) / denominator if denominator > 0 else 0.0


def _daily_returns(periods: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for period in periods:
        stamp = int(period["ts"])
        day = dt.datetime.fromtimestamp(stamp / 1000, dt.UTC).strftime("%Y-%m-%d")
        buckets.setdefault(day, []).append(period)
    return {
        day: {
            "strategy_return_pct": _compound_pct(
                [float(period["strategy_return_pct"]) for period in rows]
            ),
            "btc_return_pct": _compound_pct([float(period["btc_return_pct"]) for period in rows]),
        }
        for day, rows in sorted(buckets.items())
    }


def _beta_residual(strategy: list[float], btc: list[float]) -> dict[str, float]:
    btc_variance = _variance(btc)
    beta = _covariance(strategy, btc) / btc_variance if btc_variance > 0 else 0.0
    residuals = [value - beta * benchmark for value, benchmark in zip(strategy, btc)]
    return {
        "beta_to_btc": beta,
        "net_residual_return_pct": sum(residuals),
        "compounded_residual_return_pct": _compound_pct(residuals),
    }


def _experiment_summary(payload: dict[str, Any], path: Path, digest: str) -> dict[str, Any]:
    diagnostics = payload.get("diagnostics", {})
    config = payload.get("config", {})
    return {
        "symbol": str(config.get("strategy_symbol", "")).upper(),
        "path": str(path),
        "sha256": digest,
        "holdout_role": diagnostics.get("holdout_role"),
        "verdict": diagnostics.get("verdict"),
        "contract_hash": payload.get("decision_contract", {}).get("contract_hash"),
        "rank_ic": float(diagnostics.get("ic", {}).get("rank_ic", 0.0)),
        "net_residual_return_pct": float(diagnostics.get("score", {}).get("net_residual_return_pct", 0.0)),
        "entry_count": int(diagnostics.get("execution", {}).get("entry_count", 0)),
        "max_rolling_24h_turnover": float(
            diagnostics.get("execution", {}).get("max_rolling_24h_turnover", 0.0)
        ),
        "filter_coverage": float(
            diagnostics.get("filter_diagnostics", {}).get("filter_coverage", 0.0)
        ),
        "blockers": list(diagnostics.get("blockers", [])),
    }


def _aligned_oos_panel(
    experiments: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, list[float]], list[float]]:
    daily = {symbol: _daily_returns(payload.get("periods", [])) for symbol, payload in experiments.items()}
    symbols = sorted(daily)
    common = set(daily[symbols[0]])
    for symbol in symbols[1:]:
        common &= set(daily[symbol])
    dates = sorted(common)
    strategy_panel = {
        symbol: [float(daily[symbol][date]["strategy_return_pct"]) for date in dates]
        for symbol in symbols
    }
    btc = [float(daily[symbols[0]][date]["btc_return_pct"]) for date in dates]
    for symbol in symbols[1:]:
        other = [float(daily[symbol][date]["btc_return_pct"]) for date in dates]
        if any(abs(left - right) > 1e-10 for left, right in zip(btc, other)):
            raise ValueError("replication artifacts contain mismatched BTC benchmark returns")
    return dates, strategy_panel, btc


def _correlation_stress(
    experiments: dict[str, dict[str, Any]],
    *,
    protocol: TradeFlowReplicationProtocol,
) -> dict[str, Any]:
    dates, panel, btc = _aligned_oos_panel(experiments)
    symbols = sorted(panel)
    pairwise: list[dict[str, Any]] = []
    for left_index, left in enumerate(symbols):
        for right in symbols[left_index + 1 :]:
            correlation = _correlation(panel[left], panel[right])
            pairwise.append({"left": left, "right": right, "correlation": correlation})
    absolute = [abs(float(item["correlation"])) for item in pairwise]
    mean_abs = _mean(absolute)
    effective_breadth = len(symbols) / (1.0 + (len(symbols) - 1) * mean_abs) if symbols else 0.0
    portfolio = [_mean([panel[symbol][index] for symbol in symbols]) for index in range(len(dates))]
    portfolio_score = _beta_residual(portfolio, btc)
    leave_one_out: dict[str, dict[str, float]] = {}
    for excluded in symbols:
        included = [symbol for symbol in symbols if symbol != excluded]
        returns = [_mean([panel[symbol][index] for symbol in included]) for index in range(len(dates))]
        leave_one_out[excluded] = _beta_residual(returns, btc)
    minimum_leave_one_out = min(
        (score["net_residual_return_pct"] for score in leave_one_out.values()),
        default=0.0,
    )
    max_abs = max(absolute, default=0.0)
    blockers: list[str] = []
    if effective_breadth < protocol.minimum_effective_breadth:
        blockers.append("effective_breadth_below_protocol")
    if max_abs > protocol.maximum_abs_pairwise_correlation:
        blockers.append("pairwise_correlation_above_protocol")
    if protocol.require_positive_equal_weight_residual and portfolio_score["net_residual_return_pct"] <= 0:
        blockers.append("equal_weight_residual_non_positive")
    if protocol.require_positive_leave_one_out_residual and minimum_leave_one_out <= 0:
        blockers.append("leave_one_out_residual_non_positive")
    return {
        "date_count": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "symbols": symbols,
        "pairwise_correlations": pairwise,
        "mean_abs_pairwise_correlation": mean_abs,
        "max_abs_pairwise_correlation": max_abs,
        "effective_breadth": effective_breadth,
        "equal_weight_portfolio": portfolio_score,
        "leave_one_out": leave_one_out,
        "minimum_leave_one_out_residual_pct": minimum_leave_one_out,
        "blockers": blockers,
        "pass": not blockers,
    }


def build_tradeflow_replication_report(
    *,
    anchor_discovery_path: str | Path,
    anchor_oos_path: str | Path,
    replica_discovery_paths: dict[str, str | Path],
    replica_oos_paths: dict[str, str | Path],
    preregistration_path: str | Path,
    protocol: TradeFlowReplicationProtocol = FROZEN_REPLICATION_PROTOCOL,
) -> dict[str, Any]:
    preregistration_source = Path(preregistration_path).expanduser().resolve()
    preregistration_blob = preregistration_source.read_bytes()
    preregistration = json.loads(preregistration_blob)
    registered_hash = preregistration.get("protocol", {}).get("protocol_hash")
    if (
        preregistration.get("schema_version") != TRADEFLOW_REPLICATION_VERSION
        or preregistration.get("artifact_type") != "preregistration"
        or registered_hash != protocol.protocol_hash
    ):
        raise ValueError("replication preregistration does not match the frozen protocol")

    anchor_discovery, anchor_discovery_source, anchor_discovery_hash = _load_experiment(anchor_discovery_path)
    anchor_oos, anchor_oos_source, anchor_oos_hash = _load_experiment(anchor_oos_path)
    anchor_discovery_summary = _experiment_summary(
        anchor_discovery, anchor_discovery_source, anchor_discovery_hash
    )
    anchor_oos_summary = _experiment_summary(anchor_oos, anchor_oos_source, anchor_oos_hash)
    if anchor_discovery_summary["symbol"] != protocol.anchor_symbol or anchor_oos_summary["symbol"] != protocol.anchor_symbol:
        raise ValueError("anchor artifacts do not match the protocol anchor symbol")

    discoveries: dict[str, dict[str, Any]] = {}
    discovery_summaries: dict[str, dict[str, Any]] = {}
    for raw_symbol in protocol.replication_symbols:
        symbol = raw_symbol.upper()
        path = replica_discovery_paths.get(symbol)
        if path is None:
            continue
        payload, source, digest = _load_experiment(path)
        summary = _experiment_summary(payload, source, digest)
        if summary["symbol"] != symbol:
            raise ValueError(f"discovery path does not match {symbol}")
        discoveries[symbol] = payload
        discovery_summaries[symbol] = summary

    oos_experiments: dict[str, dict[str, Any]] = {protocol.anchor_symbol: anchor_oos}
    oos_summaries: dict[str, dict[str, Any]] = {}
    for raw_symbol in protocol.replication_symbols:
        symbol = raw_symbol.upper()
        path = replica_oos_paths.get(symbol)
        if path is None:
            continue
        payload, source, digest = _load_experiment(path)
        summary = _experiment_summary(payload, source, digest)
        if summary["symbol"] != symbol:
            raise ValueError(f"OOS path does not match {symbol}")
        oos_experiments[symbol] = payload
        oos_summaries[symbol] = summary

    all_summaries = [anchor_discovery_summary, anchor_oos_summary, *discovery_summaries.values(), *oos_summaries.values()]
    contract_mismatches = [
        summary["symbol"]
        for summary in all_summaries
        if summary["contract_hash"] != protocol.frozen_contract_hash
    ]
    role_mismatches = [
        summary["symbol"]
        for summary in [anchor_discovery_summary, *discovery_summaries.values()]
        if summary["holdout_role"] != "discovery"
    ] + [
        summary["symbol"]
        for summary in [anchor_oos_summary, *oos_summaries.values()]
        if summary["holdout_role"] != "historical_oos"
    ]
    oos_without_discovery_pass = [
        symbol
        for symbol in oos_summaries
        if discovery_summaries.get(symbol, {}).get("verdict") != "advance_to_independent_oos"
    ]
    discovery_missing = sorted(set(protocol.replication_symbols) - set(discovery_summaries))
    oos_count = len(oos_summaries)
    positive_ic_count = sum(summary["rank_ic"] > 0 for summary in oos_summaries.values())
    positive_residual_count = sum(
        summary["net_residual_return_pct"] > 0 for summary in oos_summaries.values()
    )
    capacity_checked = bool(oos_summaries) and all(
        summary["filter_coverage"] >= protocol.minimum_filter_coverage
        for summary in [anchor_oos_summary, *oos_summaries.values()]
    )
    stress = _correlation_stress(oos_experiments, protocol=protocol) if oos_count >= protocol.minimum_replica_oos_count else None
    blockers: list[str] = []
    if anchor_discovery_summary["verdict"] != "advance_to_independent_oos":
        blockers.append("anchor_discovery_not_passed")
    if anchor_oos_summary["verdict"] != "pass_independent_oos":
        blockers.append("anchor_oos_not_passed")
    if discovery_missing:
        blockers.append("replica_discovery_missing")
    if contract_mismatches:
        blockers.append("frozen_contract_mismatch")
    if role_mismatches:
        blockers.append("holdout_role_mismatch")
    if oos_without_discovery_pass:
        blockers.append("oos_consumed_without_discovery_pass")
    if oos_count < protocol.minimum_replica_oos_count:
        blockers.append("replica_oos_count_below_protocol")
    if positive_ic_count < protocol.minimum_positive_replica_rank_ic_count:
        blockers.append("positive_replica_rank_ic_count_below_protocol")
    if positive_residual_count < protocol.minimum_positive_replica_residual_count:
        blockers.append("positive_replica_residual_count_below_protocol")
    if not capacity_checked:
        blockers.append("replica_capacity_incomplete")
    if stress is None or not stress["pass"]:
        blockers.append("correlation_stress_failed")
    report_basis = {
        "protocol_hash": protocol.protocol_hash,
        "preregistration_sha256": hashlib.sha256(preregistration_blob).hexdigest(),
        "anchor_discovery": anchor_discovery_summary,
        "anchor_oos": anchor_oos_summary,
        "replica_discovery": discovery_summaries,
        "replica_oos": oos_summaries,
        "stress": stress,
    }
    report_hash = hashlib.sha256(json.dumps(report_basis, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema_version": TRADEFLOW_REPLICATION_VERSION,
        "created_at": utc_now().isoformat(),
        "artifact_type": "replication_report",
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "preregistration": {
            "path": str(preregistration_source),
            "sha256": hashlib.sha256(preregistration_blob).hexdigest(),
            "matched_before_report": True,
        },
        "anchor": {"discovery": anchor_discovery_summary, "historical_oos": anchor_oos_summary},
        "replicas": {
            symbol: {
                "discovery": discovery_summaries.get(symbol),
                "historical_oos": oos_summaries.get(symbol),
                "oos_consumed": symbol in oos_summaries,
            }
            for symbol in protocol.replication_symbols
        },
        "diagnostics": {
            "verdict": "pass_correlation_stress" if not blockers else "block_correlation_stress",
            "blockers": blockers,
            "contract_mismatches": contract_mismatches,
            "holdout_role_mismatches": role_mismatches,
            "oos_without_discovery_pass": oos_without_discovery_pass,
            "discovery_missing_symbols": discovery_missing,
            "replica_oos_count": oos_count,
            "positive_replica_rank_ic_count": positive_ic_count,
            "positive_replica_residual_count": positive_residual_count,
            "capacity_checked": capacity_checked,
            "correlation_stress": stress,
            "report_hash": report_hash,
            "g4_pbo_unchanged": 1.0,
            "promotion_note": "G5 evidence cannot waive the still-blocking G4 PBO or G6 forward-paper gate.",
        },
    }


def load_tradeflow_replication_artifact(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != TRADEFLOW_REPLICATION_VERSION
        or payload.get("artifact_type") != "replication_report"
    ):
        raise ValueError("invalid trade-flow replication report")
    return payload


def assert_replication_matches_anchor(payload: dict[str, Any], anchor_oos_path: str | Path) -> None:
    expected = Path(anchor_oos_path).expanduser().resolve()
    actual = payload.get("anchor", {}).get("historical_oos", {}).get("path")
    if not actual or Path(actual).expanduser().resolve() != expected:
        raise ValueError("replication report does not match the supplied anchor OOS artifact")


def replication_meta(payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = payload.get("diagnostics", {})
    stress = diagnostics.get("correlation_stress") or {}
    return {
        "effective_breadth": float(stress.get("effective_breadth", 0.0)),
        "claims_cross_sectional_edge": False,
        "correlation_stress_pass": diagnostics.get("verdict") == "pass_correlation_stress",
        "capacity_checked": bool(diagnostics.get("capacity_checked", False)),
        "replication_artifact_path": payload.get("artifact_path") or payload.get("persistent_artifact_path"),
        "replication_protocol_hash": payload.get("protocol", {}).get("protocol_hash"),
    }


def write_tradeflow_replication_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-tradeflow-replication",
        path_key="artifact_path",
        default_filename="alpha_agent_tradeflow_replication.json",
        explicit_path=explicit_path,
    )
