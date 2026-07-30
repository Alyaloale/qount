"""Report and gates for the preregistered USD-M recovery diagnostic."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery import validate_futures_recovery_registration
from qount.mini_trend.futures_recovery_backtest import run_variant
from qount.models import utc_now
from qount.settings import Settings


FUTURES_RECOVERY_REPORT_VERSION = "mini_trend_um_recovery_historical_v0.1"


def _data_hash(bars: Mapping[str, Sequence[Bar]], funding: Mapping[str, Sequence[Funding]]) -> str:
    basis = {
        "bars": {s: [[b.ts_ms, b.open, b.high, b.low, b.close, b.volume] for b in bars[s]] for s in TOP3},
        "funding": {s: [[row.ts_ms, row.rate] for row in funding[s]] for s in TOP3},
    }
    return canonical_hash(basis)


def build_historical_diagnostic_report(
    inputs: Mapping[str, Mapping[str, Any]],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    live_lessons_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    protocol = FUTURES_RECOVERY_PROTOCOL
    validate_futures_recovery_registration(
        preregistration, rules_artifact, live_lessons_evidence
    )
    rules, rules_hash = selected_um_rules(rules_artifact)
    segments = []
    for spec in protocol.historical_diagnostic_windows:
        source = inputs[spec["label"]]
        bars = align_bars(source["bars"], TOP3)
        funding = source["funding"]
        control = run_variant(bars, funding, rules, recovery_enabled=False)
        candidate = run_variant(bars, funding, rules, recovery_enabled=True)
        segments.append(
            {
                "label": spec["label"],
                "expected_window": {"start": spec["start"], "end": spec["end"]},
                "data_hash": _data_hash(bars, funding),
                "control": control.metrics,
                "candidate": candidate.metrics,
                "incremental_return_pct": round(
                    candidate.metrics["return_pct"] - control.metrics["return_pct"], 8
                ),
                "drawdown_worsening_percentage_points": round(
                    candidate.metrics["max_drawdown_pct"] - control.metrics["max_drawdown_pct"], 8
                ),
            }
        )
    positive = sum(row["incremental_return_pct"] > 0 for row in segments)
    thresholds = protocol.protocol_basis["historical_pass_gates"]
    gates = {
        "data_complete": all(
            row["control"]["start"] == row["expected_window"]["start"]
            and row["control"]["end"] == row["expected_window"]["end"]
            for row in segments
        ),
        "positive_incremental_net_return_segments": positive
        >= thresholds["positive_incremental_net_return_segments"],
        "maximum_drawdown_worsening": all(
            row["drawdown_worsening_percentage_points"]
            <= thresholds["maximum_drawdown_worsening_percentage_points"]
            for row in segments
        ),
        "runtime_filter_coverage": all(
            row["candidate"]["runtime_filter_coverage"] == 1.0 for row in segments
        ),
        "no_duplicate_decisions": all(
            row["candidate"]["duplicate_decision_count"] == 0 for row in segments
        ),
        "no_same_bar_stop_reentry": all(
            row["candidate"]["same_bar_stop_reentry_count"] == 0 for row in segments
        ),
    }
    passed = all(gates.values())
    return {
        "schema_version": FUTURES_RECOVERY_REPORT_VERSION,
        "artifact_type": "mini_trend_um_recovery_historical_diagnostic",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "existing_cache_only": True,
            "network_download_used": False,
            "private_exchange_data": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "exchange_rules_hash": rules_hash,
        "live_lessons_sha256": live_lessons_evidence["artifact_sha256"],
        "segments": segments,
        "diagnostics": {
            "positive_incremental_segment_count": positive,
            "gates": gates,
            "historical_gate_passed": passed,
            "verdict": "collect_new_forward" if passed else "reject_historical_candidate",
            "forward_start_date": protocol.forward_start_date,
            "paper_or_live_allowed": False,
        },
    }


def write_historical_diagnostic_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-recovery-historical",
        path_key="artifact_path",
        default_filename="mini_trend_um_recovery_historical.json",
        explicit_path=explicit_path,
    )
