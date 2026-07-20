from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings

from .tradeflow_experiment import TRADEFLOW_EXPERIMENT_VERSION
from .tradeflow_experiment import FrozenTradeFlowContract
from .tradeflow_experiment import TradeFlowExperimentConfig
from .tradeflow_experiment import _rolling_beta_before_decision
from .tradeflow_experiment import build_tradeflow_experiment


FLOW_ABSORPTION_VERSION = "alpha_agent_flow_absorption_v0.1"


@dataclass(frozen=True)
class FrozenFlowAbsorptionContract(FrozenTradeFlowContract):
    contract_id: str = "agg_flow_price_absorption_z168_entry2_hold6_cooldown18_reversal_v1"
    source_feature: str = "completed_hour_flow_price_absorption"
    hypothesis: str = (
        "extreme aggressive flow that fails to move beta-residual price in the same direction "
        "reveals passive absorption and predicts a six-hour reversal"
    )
    absorption_rule: str = "flow_zscore * completed_hour_beta_residual_return_pct <= 0"
    execution_rule: str = "signal=-flow_zscore on absorption, otherwise zero"


FROZEN_FLOW_ABSORPTION_CONTRACT = FrozenFlowAbsorptionContract()


@dataclass(frozen=True)
class FlowAbsorptionProtocol:
    protocol_id: str = "flow_price_absorption_cross_symbol_discovery_v1"
    discovery_symbols: tuple[str, ...] = ("ETHUSDT", "BNBUSDT", "SOLUSDT")
    benchmark_symbol: str = "BTCUSDT"
    discovery_window: str = "2024-01..2024-03"
    reserved_oos_window: str = "2024-04"
    contract_hash: str = FROZEN_FLOW_ABSORPTION_CONTRACT.contract_hash
    minimum_passing_symbol_count: int = 2
    minimum_positive_rank_ic_count: int = 2
    minimum_positive_residual_count: int = 2
    minimum_median_rank_ic: float = 0.02
    minimum_mean_net_residual_pct: float = 0.0
    minimum_filter_coverage: float = 1.0
    maximum_rolling_24h_turnover: float = 2.0
    selection_trials: int = 1
    oos_consumption_rule: str = (
        "do not download or evaluate April aggTrades unless the frozen three-symbol Q1 report passes"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def protocol_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()


FROZEN_FLOW_ABSORPTION_PROTOCOL = FlowAbsorptionProtocol()


def build_flow_absorption_preregistration(
    protocol: FlowAbsorptionProtocol = FROZEN_FLOW_ABSORPTION_PROTOCOL,
) -> dict[str, Any]:
    return {
        "schema_version": FLOW_ABSORPTION_VERSION,
        "artifact_type": "preregistration",
        "created_at": utc_now().isoformat(),
        "contract": {
            **FROZEN_FLOW_ABSORPTION_CONTRACT.to_dict(),
            "contract_hash": FROZEN_FLOW_ABSORPTION_CONTRACT.contract_hash,
        },
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "diagnostics": {
            "verdict": "preregistered",
            "discovery_data_evaluated": False,
            "reserved_oos_consumed": False,
            "parameter_tuning_allowed": False,
            "next_action": "run the exact frozen Q1 contract for ETHUSDT, BNBUSDT, and SOLUSDT",
        },
        "hard_boundaries": [
            "Q1 is discovery because prior trade-flow work has already exposed that window.",
            "The absorption direction, lookback, entry, holding, cooldown, costs, and gates are frozen before evaluation.",
            "All three registered symbols remain in the denominator; failed symbols cannot be dropped.",
            "April aggTrades remain unconsumed unless this discovery protocol passes.",
            "This research artifact cannot authorize A10, paper, live, VPS changes, or order placement.",
        ],
    }


def _apply_flow_absorption_signal(
    hourly: list[dict[str, Any]],
    aligned: list[tuple[int, dict[str, Any]]],
    config: TradeFlowExperimentConfig,
    contract: FrozenTradeFlowContract,
) -> list[dict[str, Any]]:
    index_by_ts = {ts_ms: index for index, (ts_ms, _bars) in enumerate(aligned)}
    bars_by_ts = {ts_ms: bars for ts_ms, bars in aligned}
    transformed: list[dict[str, Any]] = []
    for raw in hourly:
        row = dict(raw)
        flow_zscore = row.get("signal_zscore")
        decision_ts = int(row["decision_ts_ms"])
        completed_hour_ts = int(row["hour_ts_ms"])
        decision_index = index_by_ts.get(decision_ts)
        completed_bars = bars_by_ts.get(completed_hour_ts)
        beta = (
            _rolling_beta_before_decision(
                aligned,
                index=decision_index,
                strategy_symbol=config.strategy_symbol,
                lookback=contract.beta_lookback_hours,
            )
            if decision_index is not None
            else None
        )
        residual_impact: float | None = None
        absorbed: bool | None = None
        if flow_zscore is not None and completed_bars is not None and beta is not None:
            strategy_bar = completed_bars[config.strategy_symbol]
            btc_bar = completed_bars["BTCUSDT"]
            strategy_return = (strategy_bar.close / strategy_bar.open - 1.0) * 100.0
            btc_return = (btc_bar.close / btc_bar.open - 1.0) * 100.0
            residual_impact = strategy_return - beta * btc_return
            absorbed = float(flow_zscore) * residual_impact <= 0.0
        row["raw_flow_zscore"] = flow_zscore
        row["completed_hour_beta"] = beta
        row["completed_hour_beta_residual_return_pct"] = residual_impact
        row["flow_absorbed"] = absorbed
        row["signal_zscore"] = (
            -float(flow_zscore)
            if flow_zscore is not None and absorbed is True
            else (0.0 if flow_zscore is not None and absorbed is False else None)
        )
        transformed.append(row)
    return transformed


def build_flow_absorption_experiment(
    config: TradeFlowExperimentConfig,
    *,
    contract: FrozenFlowAbsorptionContract = FROZEN_FLOW_ABSORPTION_CONTRACT,
    **kwargs: Any,
) -> dict[str, Any]:
    artifact = build_tradeflow_experiment(
        config,
        contract=contract,
        hourly_signal_transform=_apply_flow_absorption_signal,
        strategy_metadata={
            "data_spec": (
                "checksum-verified Binance USD-M aggTrades plus as-of 1h klines; completed-hour "
                "aggressive-flow z-score crossed with same-hour BTC beta-residual price impact"
            ),
            "kill_line": (
                "do not consume reserved April aggTrades unless at least two of three registered "
                "Q1 symbols pass IC, net residual, cost, filter, entry-count, and turnover gates"
            ),
            "position_rule": (
                "when extreme completed-hour flow is absorbed, trade the opposite direction for six hours, "
                "then remain cash for eighteen hours; no direct flips"
            ),
            "claims_cross_sectional_edge": True,
        },
        **kwargs,
    )
    artifact["meta"]["experiment_family"] = "flow_price_absorption"
    artifact["decision_contract"]["frozen_before_independent_oos"] = True
    artifact["diagnostics"]["promotion_note"] = (
        "This is a pre-registered discovery kill-test. It cannot authorize OOS consumption, paper, or live."
    )
    return artifact


def _load_json(path: str | Path) -> tuple[dict[str, Any], Path, str]:
    source = Path(path).expanduser().resolve()
    blob = source.read_bytes()
    return json.loads(blob), source, hashlib.sha256(blob).hexdigest()


def _experiment_summary(payload: dict[str, Any], path: Path, digest: str) -> dict[str, Any]:
    diagnostics = payload.get("diagnostics", {})
    return {
        "symbol": str(payload.get("config", {}).get("strategy_symbol", "")).upper(),
        "path": str(path),
        "sha256": digest,
        "contract_hash": payload.get("decision_contract", {}).get("contract_hash"),
        "holdout_role": diagnostics.get("holdout_role"),
        "verdict": diagnostics.get("verdict"),
        "rank_ic": float(diagnostics.get("ic", {}).get("rank_ic", 0.0)),
        "net_residual_return_pct": float(
            diagnostics.get("score", {}).get("net_residual_return_pct", 0.0)
        ),
        "entry_count": int(diagnostics.get("execution", {}).get("entry_count", 0)),
        "max_rolling_24h_turnover": float(
            diagnostics.get("execution", {}).get("max_rolling_24h_turnover", 0.0)
        ),
        "filter_coverage": float(
            diagnostics.get("filter_diagnostics", {}).get("filter_coverage", 0.0)
        ),
        "blockers": list(diagnostics.get("blockers", [])),
    }


def build_flow_absorption_discovery_report(
    *,
    preregistration_path: str | Path,
    experiment_paths: list[str | Path],
    protocol: FlowAbsorptionProtocol = FROZEN_FLOW_ABSORPTION_PROTOCOL,
) -> dict[str, Any]:
    preregistration, prereg_path, prereg_hash = _load_json(preregistration_path)
    if (
        preregistration.get("schema_version") != FLOW_ABSORPTION_VERSION
        or preregistration.get("artifact_type") != "preregistration"
        or preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash
    ):
        raise ValueError("preregistration does not match the frozen flow-absorption protocol")
    summaries: dict[str, dict[str, Any]] = {}
    for experiment_path in experiment_paths:
        payload, source, digest = _load_json(experiment_path)
        if payload.get("schema_version") != TRADEFLOW_EXPERIMENT_VERSION:
            raise ValueError("experiment path is not a trade-flow experiment artifact")
        summary = _experiment_summary(payload, source, digest)
        symbol = summary["symbol"]
        if symbol in summaries:
            raise ValueError(f"duplicate experiment for {symbol}")
        summaries[symbol] = summary
    expected = set(protocol.discovery_symbols)
    unexpected = sorted(set(summaries) - expected)
    missing = sorted(expected - set(summaries))
    contract_mismatches = sorted(
        symbol
        for symbol, summary in summaries.items()
        if summary["contract_hash"] != protocol.contract_hash
    )
    role_mismatches = sorted(
        symbol for symbol, summary in summaries.items() if summary["holdout_role"] != "discovery"
    )
    ordered = [summaries[symbol] for symbol in protocol.discovery_symbols if symbol in summaries]
    passing_count = sum(summary["verdict"] == "advance_to_independent_oos" for summary in ordered)
    positive_ic_count = sum(summary["rank_ic"] > 0 for summary in ordered)
    positive_residual_count = sum(summary["net_residual_return_pct"] > 0 for summary in ordered)
    median_ic = statistics.median([summary["rank_ic"] for summary in ordered]) if ordered else 0.0
    mean_residual = (
        statistics.fmean([summary["net_residual_return_pct"] for summary in ordered])
        if ordered
        else 0.0
    )
    filter_complete = bool(ordered) and all(
        summary["filter_coverage"] >= protocol.minimum_filter_coverage for summary in ordered
    )
    turnover_within_budget = bool(ordered) and all(
        summary["max_rolling_24h_turnover"] <= protocol.maximum_rolling_24h_turnover + 1e-12
        for summary in ordered
    )
    blockers: list[str] = []
    if missing:
        blockers.append("registered_symbol_missing")
    if unexpected:
        blockers.append("unexpected_symbol_present")
    if contract_mismatches:
        blockers.append("frozen_contract_mismatch")
    if role_mismatches:
        blockers.append("holdout_role_mismatch")
    if passing_count < protocol.minimum_passing_symbol_count:
        blockers.append("passing_symbol_count_below_protocol")
    if positive_ic_count < protocol.minimum_positive_rank_ic_count:
        blockers.append("positive_rank_ic_count_below_protocol")
    if positive_residual_count < protocol.minimum_positive_residual_count:
        blockers.append("positive_residual_count_below_protocol")
    if median_ic < protocol.minimum_median_rank_ic:
        blockers.append("median_rank_ic_below_protocol")
    if mean_residual <= protocol.minimum_mean_net_residual_pct:
        blockers.append("mean_net_residual_non_positive")
    if not filter_complete:
        blockers.append("filter_coverage_incomplete")
    if not turnover_within_budget:
        blockers.append("turnover_budget_exceeded")
    passed = not blockers
    return {
        "schema_version": FLOW_ABSORPTION_VERSION,
        "artifact_type": "discovery_report",
        "created_at": utc_now().isoformat(),
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "preregistration": {
            "path": str(prereg_path),
            "sha256": prereg_hash,
        },
        "experiments": {summary["symbol"]: summary for summary in ordered},
        "diagnostics": {
            "verdict": "advance_to_reserved_oos_preregistration" if passed else "block_discovery",
            "blockers": blockers,
            "missing_symbols": missing,
            "unexpected_symbols": unexpected,
            "contract_mismatches": contract_mismatches,
            "holdout_role_mismatches": role_mismatches,
            "passing_symbol_count": passing_count,
            "positive_rank_ic_count": positive_ic_count,
            "positive_residual_count": positive_residual_count,
            "median_rank_ic": median_ic,
            "mean_net_residual_return_pct": mean_residual,
            "filter_coverage_complete": filter_complete,
            "turnover_within_budget": turnover_within_budget,
            "reserved_oos_consumed": False,
            "next_action": (
                "write a separate April OOS preregistration before downloading new aggTrades"
                if passed
                else "stop this hypothesis without parameter rescue or April consumption"
            ),
        },
        "hard_boundary": "This report cannot authorize A10, paper, live, VPS changes, or order placement.",
    }


def write_flow_absorption_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-flow-absorption",
        path_key="artifact_path",
        default_filename="alpha_agent_flow_absorption.json",
        explicit_path=explicit_path,
    )
