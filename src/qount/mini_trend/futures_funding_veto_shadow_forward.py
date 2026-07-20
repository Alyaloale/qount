"""Future-only dual-state shadow monitoring for the fixed UM funding veto."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_base_forward import BASE_FORWARD_PREREG_VERSION
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto_report import _data_hash, _run_variants
from qount.mini_trend.futures_funding_veto_state_decay import (
    FUNDING_VETO_STATE_DECAY_REPORT_VERSION,
)
from qount.mini_trend.futures_funding_veto_state_decay import (
    FUNDING_VETO_STATE_DECAY_PROTOCOL,
)
from qount.mini_trend.futures_funding_veto_state_decay import compare_execution_states
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.futures_risk_tier import file_sha256
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.models import utc_now
from qount.rv.stats import sharpe
from qount.settings import Settings


FUNDING_VETO_SHADOW_FORWARD_PREREG_VERSION = (
    "mini_trend_um_funding_veto_shadow_forward_preregistration_v0.2"
)
FUNDING_VETO_SHADOW_FORWARD_REPORT_VERSION = (
    "mini_trend_um_funding_veto_shadow_forward_report_v0.2"
)
_DAY_MS = 86_400_000


@dataclass(frozen=True)
class FundingVetoShadowForwardProtocol:
    strategy: str = "MiniTrend-UM-FundingVeto-Shadow-v0.1"
    reference: str = "MiniTrend-UM-RegimeStopLatch-v0.1"
    candidate: str = "MiniTrend-UM-FundingVeto-v0.1"
    capital_usdt: float = 400.0
    market: str = "um"
    interval: str = "1d"
    forward_start_date: str = "2026-07-19"
    warmup_completed_bars: int = 200
    minimum_forward_bars: int = 60
    minimum_active_bars_per_path: int = 10
    minimum_funding_veto_events: int = 1
    minimum_daily_funding_settlements_per_symbol: int = 3
    maximum_candidate_drawdown_pct: float = 15.0
    daily_chandelier_atr_multiple: float = 3.0
    stop_cooldown_completed_bars: int = 3
    gross_cap_policy: str = "renormalize_active_targets_with_filter_floors"

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "reference": {
                "strategy": self.reference,
                "contract_hash": FUTURES_FUNDING_VETO_PROTOCOL.contract_basis[
                    "inherited_stop_latch_contract_hash"
                ],
            },
            "candidate": {
                "strategy": self.candidate,
                "contract_hash": FUTURES_FUNDING_VETO_PROTOCOL.contract_hash,
                "funding_veto_threshold": FUTURES_FUNDING_VETO_PROTOCOL.annualized_funding_veto,
            },
            "data": {
                "source": "existing Binance public UM daily kline and funding cache",
                "market": self.market,
                "interval": self.interval,
                "forward_start_date": self.forward_start_date,
                "completed_daily_bars_only": True,
                "minimum_daily_funding_settlements_per_symbol": (
                    self.minimum_daily_funding_settlements_per_symbol
                ),
                "evaluate_only_contiguous_price_and_funding_complete_prefix": True,
                "network_download_allowed": False,
                "private_exchange_data": False,
            },
            "initialization": {
                "same_initial_capital_usdt": self.capital_usdt,
                "same_initial_positions": "all cash",
                "same_initial_trail_high": "empty",
                "same_initial_cooldown": "empty",
                "same_initial_stop_latch": False,
                "historical_trading_state_carried_into_forward": False,
                "warmup_completed_bars_for_signals_only": self.warmup_completed_bars,
            },
            "execution": FUTURES_FUNDING_VETO_PROTOCOL.contract_basis["execution"],
            "stops": FUTURES_FUNDING_VETO_PROTOCOL.contract_basis["stops"],
            "journal": {
                "persist_both_equity_paths": True,
                "persist_both_execution_states": True,
                "persist_daily_return_components": True,
                "state_hash_per_path": True,
                "row_hash": True,
                "append_chain_hash": True,
                "stop_after_first_state_resynchronization": False,
                "orders_allowed": False,
            },
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "holdout_role": "future_only_shadow_monitoring",
            "minimum_forward_bars": self.minimum_forward_bars,
            "minimum_active_bars_per_path": self.minimum_active_bars_per_path,
            "minimum_funding_veto_events": self.minimum_funding_veto_events,
            "minimum_daily_funding_settlements_per_symbol": (
                self.minimum_daily_funding_settlements_per_symbol
            ),
            "required_candidate_funding_coverage": 1.0,
            "maximum_candidate_drawdown_pct": self.maximum_candidate_drawdown_pct,
            "required_runtime_filter_coverage": 1.0,
            "required_state_journal_coverage": 1.0,
            "trial_count": 1,
            "parameter_search_allowed": False,
            "universe_search_allowed": False,
            "threshold_search_allowed": False,
            "paper_or_live_allowed": False,
            "review_rule": (
                "Passing gates permits a shadow-evidence review only; it never permits paper or live."
            ),
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


FUNDING_VETO_SHADOW_FORWARD_PROTOCOL = FundingVetoShadowForwardProtocol()


def _load_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _load_base_preregistration(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = _load_object(source)
    if payload.get("schema_version") != BASE_FORWARD_PREREG_VERSION:
        raise ValueError("unexpected UM base forward preregistration schema")
    if payload.get("decision_contract", {}).get("contract_hash") != (
        FUTURES_BASE_FORWARD_PROTOCOL.contract_hash
    ):
        raise ValueError("UM base forward contract hash mismatch")
    if payload.get("protocol", {}).get("protocol_hash") != (
        FUTURES_BASE_FORWARD_PROTOCOL.protocol_hash
    ):
        raise ValueError("UM base forward protocol hash mismatch")
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "selected_rules_hash": payload["exchange_rules"]["selected_rules_hash"],
        "live_lessons": payload["live_lessons"],
    }


def _load_state_decay_historical(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = _load_object(source)
    if payload.get("schema_version") != FUNDING_VETO_STATE_DECAY_REPORT_VERSION:
        raise ValueError("unexpected funding-veto state-decay schema")
    if payload.get("artifact_type") != (
        "mini_trend_um_funding_veto_state_decay_historical_diagnostic"
    ):
        raise ValueError("unexpected funding-veto state-decay artifact")
    if payload.get("contract_hash") != FUNDING_VETO_STATE_DECAY_PROTOCOL.contract_hash:
        raise ValueError("funding-veto state-decay contract hash mismatch")
    if payload.get("protocol_hash") != FUNDING_VETO_STATE_DECAY_PROTOCOL.protocol_hash:
        raise ValueError("funding-veto state-decay protocol hash mismatch")
    if payload.get("diagnostics", {}).get("verdict") != (
        "historical_execution_state_decay_resolved"
    ):
        raise ValueError("shadow forward requires the resolved state-decay audit")
    return {
        "artifact_path": str(source),
        "artifact_sha256": file_sha256(source),
        "verdict": payload["diagnostics"]["verdict"],
        "exchange_rules_hash": payload["exchange_rules_hash"],
        "source_historical_sha256": payload["source_historical_sha256"],
        "historical_state_divergent_bar_count": payload["state_decay"][
            "state_divergent_bar_count"
        ],
        "historical_first_sync_median_bars": payload["state_decay"][
            "first_sync_duration_summary"
        ]["median"],
    }


def build_funding_veto_shadow_forward_preregistration(
    rules_artifact: Mapping[str, Any],
    base_preregistration_path: str | Path,
    state_decay_historical_path: str | Path,
) -> dict[str, Any]:
    _, rules_hash = selected_um_rules(rules_artifact)
    base = _load_base_preregistration(base_preregistration_path)
    state_decay = _load_state_decay_historical(state_decay_historical_path)
    if base["selected_rules_hash"] != rules_hash:
        raise ValueError("base preregistration exchange-rules hash mismatch")
    if state_decay["exchange_rules_hash"] != rules_hash:
        raise ValueError("state-decay exchange-rules hash mismatch")
    protocol = FUNDING_VETO_SHADOW_FORWARD_PROTOCOL
    return {
        "schema_version": FUNDING_VETO_SHADOW_FORWARD_PREREG_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_shadow_forward_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "future_only": True,
            "existing_cache_only_at_registration": True,
            "network_download_allowed": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "decision_contract": protocol.contract_basis | {"contract_hash": protocol.contract_hash},
        "protocol": protocol.protocol_basis | {"protocol_hash": protocol.protocol_hash},
        "exchange_rules": {"selected_rules_hash": rules_hash, "symbols": sorted(TOP3)},
        "base_preregistration": base,
        "source_state_decay": state_decay,
    }


def validate_funding_veto_shadow_forward_registration(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    base_preregistration_path: str | Path,
    state_decay_historical_path: str | Path,
) -> None:
    protocol = FUNDING_VETO_SHADOW_FORWARD_PROTOCOL
    if preregistration.get("schema_version") != FUNDING_VETO_SHADOW_FORWARD_PREREG_VERSION:
        raise ValueError("unexpected funding-veto shadow-forward preregistration schema")
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("funding-veto shadow-forward contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("funding-veto shadow-forward protocol hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("funding-veto shadow-forward exchange-rules hash mismatch")
    base = _load_base_preregistration(base_preregistration_path)
    if preregistration.get("base_preregistration", {}).get("artifact_sha256") != base[
        "artifact_sha256"
    ]:
        raise ValueError("funding-veto shadow-forward base preregistration hash mismatch")
    state_decay = _load_state_decay_historical(state_decay_historical_path)
    if preregistration.get("source_state_decay", {}).get("artifact_sha256") != state_decay[
        "artifact_sha256"
    ]:
        raise ValueError("funding-veto shadow-forward state-decay hash mismatch")


def _gap_count(dates: Sequence[str]) -> int:
    parsed = [dt.date.fromisoformat(value) for value in dates]
    return sum(max((right - left).days - 1, 0) for left, right in zip(parsed, parsed[1:]))


def _daily_funding_settlement_counts(
    funding: Mapping[str, Sequence[Funding]],
) -> dict[str, dict[int, int]]:
    counts: dict[str, dict[int, int]] = {symbol: {} for symbol in TOP3}
    for symbol in TOP3:
        for row in funding.get(symbol, []):
            bar_open = ((row.ts_ms - 1) // _DAY_MS) * _DAY_MS
            counts[symbol][bar_open] = counts[symbol].get(bar_open, 0) + 1
    return counts


def complete_forward_input_prefix(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
    *,
    start_index: int,
    minimum_settlements: int,
) -> dict[str, Any]:
    counts = _daily_funding_settlement_counts(funding)
    total_pair_count = max(len(bars["BTCUSDT"]) - start_index - 1, 0)
    complete_prefix_pair_count = 0
    first_incomplete_pair: dict[str, Any] | None = None
    for index in range(start_index, len(bars["BTCUSDT"]) - 1):
        decision = bars["BTCUSDT"][index]
        outcome = bars["BTCUSDT"][index + 1]
        settlement_counts = {
            symbol: {
                "decision_day": counts[symbol].get(decision.ts_ms, 0),
                "holding_day": counts[symbol].get(outcome.ts_ms, 0),
            }
            for symbol in TOP3
        }
        consecutive_price_pair = outcome.ts_ms - decision.ts_ms == _DAY_MS
        funding_complete = all(
            values[period] >= minimum_settlements
            for values in settlement_counts.values()
            for period in ("decision_day", "holding_day")
        )
        if not consecutive_price_pair or not funding_complete:
            first_incomplete_pair = {
                "decision_date": decision.date,
                "outcome_date": outcome.date,
                "consecutive_price_pair": consecutive_price_pair,
                "settlement_counts": settlement_counts,
            }
            break
        complete_prefix_pair_count += 1
    return {
        "total_price_pair_count": total_pair_count,
        "complete_prefix_pair_count": complete_prefix_pair_count,
        "first_incomplete_pair": first_incomplete_pair,
    }


def _path_summary(result: VariantResult, capital_usdt: float) -> dict[str, Any]:
    curve = [capital_usdt] + [float(row["equity"]) for row in result.equity]
    returns = [float(row["net_return"]) for row in result.equity]
    return {
        "start_equity_usdt": capital_usdt,
        "end_equity_usdt": round(curve[-1], 8),
        "return_pct": round((curve[-1] / capital_usdt - 1.0) * 100.0, 8),
        "max_drawdown_pct": round(max_drawdown_pct(curve), 8),
        "sharpe": round(
            sharpe(returns, periods_per_year=365.0) if len(returns) >= 2 else 0.0,
            8,
        ),
        "rows": len(result.equity),
        "active_bars": sum(float(row["gross"]) > 0.0 for row in result.equity),
        "orders": sum(int(row["orders"]) for row in result.equity),
        "stop_events": sum(bool(row["stopped"]) for row in result.equity),
        "runtime_filter_coverage": result.metrics["runtime_filter_coverage"],
        "duplicate_decision_count": result.metrics["duplicate_decision_count"],
        "same_bar_stop_reentry_count": result.metrics["same_bar_stop_reentry_count"],
    }


def _journal_rows(reference: VariantResult, candidate: VariantResult) -> dict[str, Any]:
    if len(reference.equity) != len(candidate.equity):
        raise ValueError("shadow paths have different lengths")
    initial_state = {
        "capital_usdt": FUNDING_VETO_SHADOW_FORWARD_PROTOCOL.capital_usdt,
        "positions": {symbol: 0.0 for symbol in TOP3},
        "trail_high": {},
        "cooldown": {},
        "stop_latch": False,
    }
    initial_state_hash = canonical_hash(initial_state)
    previous_chain_hash = initial_state_hash
    rows = []
    state_divergent = 0
    for reference_row, candidate_row in zip(reference.equity, candidate.equity):
        dates = (reference_row["decision_date"], reference_row["outcome_date"])
        if dates != (candidate_row["decision_date"], candidate_row["outcome_date"]):
            raise ValueError("shadow paths are not date aligned")
        comparison = compare_execution_states(
            reference_row["execution_state"], candidate_row["execution_state"]
        )
        state_divergent += int(comparison["divergent"])
        core = {
            "decision_date": dates[0],
            "outcome_date": dates[1],
            "reference": {
                "equity_usdt": reference_row["equity"],
                "gross": reference_row["gross"],
                "net_return": reference_row["net_return"],
                "gross_price_return": reference_row["gross_price_return"],
                "funding_return": reference_row["funding_return"],
                "trading_cost_return": reference_row["trading_cost_return"],
                "execution_state": reference_row["execution_state"],
                "state_hash": canonical_hash(reference_row["execution_state"]),
            },
            "candidate": {
                "equity_usdt": candidate_row["equity"],
                "gross": candidate_row["gross"],
                "net_return": candidate_row["net_return"],
                "gross_price_return": candidate_row["gross_price_return"],
                "funding_return": candidate_row["funding_return"],
                "trading_cost_return": candidate_row["trading_cost_return"],
                "execution_state": candidate_row["execution_state"],
                "state_hash": canonical_hash(candidate_row["execution_state"]),
            },
            "state_divergent": comparison["divergent"],
            "return_delta": float(candidate_row["net_return"])
            - float(reference_row["net_return"]),
        }
        row_hash = canonical_hash(core)
        chain_hash = canonical_hash(
            {"previous_chain_hash": previous_chain_hash, "row_hash": row_hash}
        )
        rows.append(core | {"row_hash": row_hash, "chain_hash": chain_hash})
        previous_chain_hash = chain_hash
    return {
        "initial_state": initial_state,
        "initial_state_hash": initial_state_hash,
        "rows": rows,
        "final_chain_hash": previous_chain_hash,
        "state_divergent_bar_count": state_divergent,
    }


def build_funding_veto_shadow_forward_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    base_preregistration_path: str | Path,
    state_decay_historical_path: str | Path,
) -> dict[str, Any]:
    validate_funding_veto_shadow_forward_registration(
        preregistration,
        rules_artifact,
        base_preregistration_path,
        state_decay_historical_path,
    )
    protocol = FUNDING_VETO_SHADOW_FORWARD_PROTOCOL
    rules, rules_hash = selected_um_rules(rules_artifact)
    bars = align_bars(bars_by_symbol, TOP3)
    common_dates = [bar.date for bar in bars["BTCUSDT"]]
    latest_by_symbol = {symbol: rows[-1].date for symbol, rows in bars.items()}
    forward_dates = [date for date in common_dates if date >= protocol.forward_start_date]
    forward_price_pair_count = max(len(forward_dates) - 1, 0)
    start_index = (
        next(
            index
            for index, date in enumerate(common_dates)
            if date >= protocol.forward_start_date
        )
        if forward_dates
        else len(common_dates)
    )
    input_prefix = complete_forward_input_prefix(
        bars,
        funding_by_symbol,
        start_index=start_index,
        minimum_settlements=protocol.minimum_daily_funding_settlements_per_symbol,
    )
    complete_prefix_pair_count = input_prefix["complete_prefix_pair_count"]
    evaluated_dates = common_dates[
        start_index : start_index + complete_prefix_pair_count + 1
    ]
    report: dict[str, Any] = {
        "schema_version": FUNDING_VETO_SHADOW_FORWARD_REPORT_VERSION,
        "artifact_type": "mini_trend_um_funding_veto_shadow_forward_report",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "future_only": True,
            "existing_cache_only": True,
            "network_download_used": False,
            "private_exchange_data": False,
            "strategy_results_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "exchange_rules_hash": rules_hash,
        "base_preregistration_sha256": preregistration["base_preregistration"][
            "artifact_sha256"
        ],
        "state_decay_sha256": preregistration["source_state_decay"]["artifact_sha256"],
        "data": {
            "common_bar_count": len(common_dates),
            "first_common_date": common_dates[0] if common_dates else None,
            "last_common_date": common_dates[-1] if common_dates else None,
            "latest_date_by_symbol": latest_by_symbol,
            "forward_input_bar_count": len(forward_dates),
            "forward_price_pair_count": forward_price_pair_count,
            "forward_input_gap_count": _gap_count(forward_dates),
            "funding_complete_prefix_pair_count": complete_prefix_pair_count,
            "minimum_daily_funding_settlements_per_symbol": (
                protocol.minimum_daily_funding_settlements_per_symbol
            ),
            "first_incomplete_pair": input_prefix["first_incomplete_pair"],
            "evaluation_bar_count": 0,
            "evaluation_gap_count": _gap_count(evaluated_dates),
            "forward_start_date": protocol.forward_start_date,
            "data_hash": _data_hash(bars, funding_by_symbol),
        },
        "initialization": {
            "same_initial_capital_usdt": protocol.capital_usdt,
            "same_initial_cash_state": True,
            "historical_trading_state_carried": False,
            "warmup_completed_bars": protocol.warmup_completed_bars,
        },
        "diagnostics": {
            "gates": {},
            "verdict": "await_shadow_forward_data",
            "shadow_review_allowed": False,
            "paper_or_live_allowed": False,
        },
    }
    if complete_prefix_pair_count == 0:
        blocker = (
            "no_completed_decision_outcome_pair_on_or_after_forward_start"
            if forward_price_pair_count == 0
            else "no_contiguous_price_and_funding_complete_forward_pair"
        )
        report["diagnostics"]["blockers"] = [blocker]
        if forward_price_pair_count > 0:
            report["diagnostics"]["verdict"] = "await_complete_shadow_inputs"
        return report
    if start_index < protocol.warmup_completed_bars:
        report["diagnostics"]["blockers"] = ["insufficient_signal_warmup_before_forward_start"]
        return report
    slice_start = start_index - protocol.warmup_completed_bars
    slice_end = start_index + complete_prefix_pair_count + 1
    sliced_bars = {symbol: rows[slice_start:slice_end] for symbol, rows in bars.items()}
    _, reference, candidate, funding_activity = _run_variants(
        sliced_bars, funding_by_symbol, rules
    )
    if not reference.equity or reference.equity[0]["decision_date"] < protocol.forward_start_date:
        raise ValueError("shadow forward contains pre-registered historical decisions")
    journal = _journal_rows(reference, candidate)
    reference_summary = _path_summary(reference, protocol.capital_usdt)
    candidate_summary = _path_summary(candidate, protocol.capital_usdt)
    journal_coverage = len(journal["rows"]) / len(reference.equity)
    gates = {
        "data_complete": report["data"]["evaluation_gap_count"] == 0
        and len(reference.equity) == complete_prefix_pair_count,
        "minimum_forward_bars": len(reference.equity) >= protocol.minimum_forward_bars,
        "minimum_reference_active_bars": reference_summary["active_bars"]
        >= protocol.minimum_active_bars_per_path,
        "minimum_candidate_active_bars": candidate_summary["active_bars"]
        >= protocol.minimum_active_bars_per_path,
        "funding_veto_exercised": funding_activity["vetoed_bar_count"]
        >= protocol.minimum_funding_veto_events,
        "candidate_funding_coverage": funding_activity["funding_coverage"] == 1.0,
        "maximum_candidate_drawdown": candidate_summary["max_drawdown_pct"]
        <= protocol.maximum_candidate_drawdown_pct,
        "runtime_filter_coverage": reference_summary["runtime_filter_coverage"] == 1.0
        and candidate_summary["runtime_filter_coverage"] == 1.0,
        "state_journal_coverage": journal_coverage == 1.0,
        "no_duplicate_decisions": reference_summary["duplicate_decision_count"] == 0
        and candidate_summary["duplicate_decision_count"] == 0,
        "no_same_bar_stop_reentry": reference_summary["same_bar_stop_reentry_count"] == 0
        and candidate_summary["same_bar_stop_reentry_count"] == 0,
        "same_initial_state": journal["initial_state"]["capital_usdt"]
        == protocol.capital_usdt,
        "future_only_journal": all(
            row["decision_date"] >= protocol.forward_start_date for row in journal["rows"]
        ),
    }
    passed = all(gates.values())
    report["meta"]["strategy_results_evaluated"] = True
    report["data"]["evaluation_bar_count"] = len(reference.equity)
    report["evaluation"] = {
        "reference": reference_summary,
        "candidate": candidate_summary,
        "candidate_minus_reference": {
            "return_percentage_points": round(
                candidate_summary["return_pct"] - reference_summary["return_pct"], 8
            ),
            "max_drawdown_percentage_points": round(
                candidate_summary["max_drawdown_pct"]
                - reference_summary["max_drawdown_pct"],
                8,
            ),
            "sharpe": round(candidate_summary["sharpe"] - reference_summary["sharpe"], 8),
        },
        "funding_veto_activity": funding_activity,
        "state_divergent_bar_count": journal["state_divergent_bar_count"],
        "journal_coverage": journal_coverage,
    }
    report["journal"] = journal
    report["diagnostics"]["gates"] = gates
    report["diagnostics"]["blockers"] = [name for name, passed in gates.items() if not passed]
    report["diagnostics"]["verdict"] = (
        "review_shadow_forward_evidence" if passed else "collect_shadow_forward"
    )
    report["diagnostics"]["shadow_review_allowed"] = passed
    return report


def write_funding_veto_shadow_forward_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-shadow-forward-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_shadow_forward_preregistration.json",
        explicit_path=explicit_path,
    )


def write_funding_veto_shadow_forward_report_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-funding-veto-shadow-forward",
        path_key="artifact_path",
        default_filename="mini_trend_um_funding_veto_shadow_forward.json",
        explicit_path=explicit_path,
    )
