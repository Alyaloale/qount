"""Forward freshness report for the preregistered UM base trend control."""

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_base_forward import BASE_FORWARD_PREREG_VERSION
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_recovery import canonical_hash, load_live_lessons_evidence
from qount.mini_trend.futures_recovery import selected_um_rules
from qount.mini_trend.futures_recovery_backtest import run_variant
from qount.models import utc_now
from qount.settings import Settings


BASE_FORWARD_REPORT_VERSION = "mini_trend_um_base_forward_report_v0.1"


def _data_hash(bars: Mapping[str, Sequence[Bar]], funding: Mapping[str, Sequence[Funding]]) -> str:
    return canonical_hash(
        {
            "bars": {s: [[b.ts_ms, b.open, b.high, b.low, b.close, b.volume] for b in bars[s]] for s in TOP3},
            "funding": {s: [[f.ts_ms, f.rate] for f in funding[s]] for s in TOP3},
        }
    )


def _validate(
    preregistration: Mapping[str, Any],
    rules_artifact: Mapping[str, Any],
    lessons_path: str,
) -> dict[str, Any]:
    if preregistration.get("schema_version") != BASE_FORWARD_PREREG_VERSION:
        raise ValueError("unexpected UM base forward preregistration schema")
    protocol = FUTURES_BASE_FORWARD_PROTOCOL
    if preregistration.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("UM base forward contract hash mismatch")
    if preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("UM base forward protocol hash mismatch")
    _, rules_hash = selected_um_rules(rules_artifact)
    if preregistration.get("exchange_rules", {}).get("selected_rules_hash") != rules_hash:
        raise ValueError("UM base forward exchange-rules hash mismatch")
    lessons = load_live_lessons_evidence(lessons_path)
    if preregistration.get("live_lessons", {}).get("artifact_sha256") != lessons["artifact_sha256"]:
        raise ValueError("UM base forward live-lessons hash mismatch")
    return lessons


def _gap_count(dates: Sequence[str]) -> int:
    parsed = [dt.date.fromisoformat(value) for value in dates]
    return sum(max((right - left).days - 1, 0) for left, right in zip(parsed, parsed[1:]))


def build_base_forward_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    lessons_path: str,
) -> dict[str, Any]:
    lessons = _validate(preregistration, rules_artifact, lessons_path)
    rules, rules_hash = selected_um_rules(rules_artifact)
    bars = align_bars(bars_by_symbol, TOP3)
    common_dates = [bar.date for bar in bars["BTCUSDT"]]
    protocol = FUTURES_BASE_FORWARD_PROTOCOL
    eval_dates = [date for date in common_dates if date >= protocol.forward_start_date]
    latest_by_symbol = {symbol: rows[-1].date for symbol, rows in bars.items()}
    base = {
        "schema_version": BASE_FORWARD_REPORT_VERSION,
        "artifact_type": "mini_trend_um_base_forward_report",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
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
        "live_lessons_sha256": lessons["artifact_sha256"],
        "data": {
            "common_bar_count": len(common_dates),
            "evaluation_bar_count": len(eval_dates),
            "first_common_date": common_dates[0] if common_dates else None,
            "last_common_date": common_dates[-1] if common_dates else None,
            "latest_date_by_symbol": latest_by_symbol,
            "evaluation_gap_count": _gap_count(eval_dates),
            "data_hash": _data_hash(bars, funding_by_symbol),
            "forward_start_date": protocol.forward_start_date,
        },
        "diagnostics": {
            "gates": {},
            "verdict": "await_forward_data",
            "paper_review_allowed": False,
            "paper_or_live_allowed": False,
        },
    }
    if not eval_dates:
        base["diagnostics"]["blockers"] = ["no_completed_bars_on_or_after_forward_start"]
        return base

    result = run_variant(
        bars,
        funding_by_symbol,
        rules,
        recovery_enabled=False,
        daily_chandelier_atr_multiple=protocol.daily_chandelier_atr_multiple,
        stop_cooldown_completed_bars=protocol.stop_cooldown_completed_bars,
    )
    forward_rows = [row for row in result.equity if row["outcome_date"] >= protocol.forward_start_date]
    prior_rows = [row for row in result.equity if row["outcome_date"] < protocol.forward_start_date]
    start_equity = float(prior_rows[-1]["equity"]) if prior_rows else protocol.capital_usdt
    curve = [start_equity] + [float(row["equity"]) for row in forward_rows]
    active = sum(1 for row in forward_rows if float(row["gross"]) > 0)
    forward_return = (curve[-1] / curve[0] - 1.0) * 100.0 if curve[0] else 0.0
    max_drawdown = 0.0
    peak = curve[0] if curve else 0.0
    for value in curve:
        peak = max(peak, value)
        if peak:
            max_drawdown = max(max_drawdown, (peak - value) / peak * 100.0)
    gates = {
        "data_complete": base["data"]["evaluation_gap_count"] == 0,
        "minimum_forward_bars": len(forward_rows) >= protocol.minimum_forward_bars,
        "minimum_active_bars": active >= protocol.minimum_active_bars,
        "maximum_forward_drawdown": max_drawdown <= protocol.maximum_forward_drawdown_pct,
        "runtime_filter_coverage": result.metrics["runtime_filter_coverage"] == 1.0,
        "no_duplicate_decisions": result.metrics["duplicate_decision_count"] == 0,
        "no_same_bar_stop_reentry": result.metrics["same_bar_stop_reentry_count"] == 0,
    }
    base["meta"]["strategy_results_evaluated"] = bool(forward_rows)
    base["evaluation"] = {
        "start_equity_usdt": round(curve[0], 8),
        "end_equity_usdt": round(curve[-1], 8),
        "forward_return_pct": round(forward_return, 8),
        "forward_max_drawdown_pct": round(max_drawdown, 8),
        "forward_rows": len(forward_rows),
        "active_bars": active,
        "orders": sum(int(row["orders"]) for row in forward_rows),
        "stop_events": sum(1 for row in forward_rows if row["stopped"]),
        "runtime_filter_coverage": result.metrics["runtime_filter_coverage"],
    }
    base["diagnostics"]["gates"] = gates
    base["diagnostics"]["blockers"] = [name for name, passed in gates.items() if not passed]
    base["diagnostics"]["verdict"] = (
        "review_paper_readiness" if all(gates.values()) else "collect_forward"
    )
    base["diagnostics"]["paper_review_allowed"] = all(gates.values())
    return base


def write_base_forward_report_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-base-forward",
        path_key="artifact_path",
        default_filename="mini_trend_um_base_forward.json",
        explicit_path=explicit_path,
    )
