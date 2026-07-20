from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.settings import Settings


BETA_METRICS_VERSION = "alpha_agent_beta_metrics_v0.1"


@dataclass(frozen=True)
class ReturnRow:
    ts: str
    strategy_return_pct: float
    btc_return_pct: float = 0.0
    top3_equal_weight_return_pct: float = 0.0
    current_live_baseline_return_pct: float = 0.0
    cash_return_pct: float = 0.0


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _row_from_mapping(row: dict[str, Any], index: int) -> ReturnRow:
    return ReturnRow(
        ts=str(row.get("ts") or row.get("timestamp") or row.get("date") or index),
        strategy_return_pct=_as_float(row.get("strategy_return_pct", row.get("strategy_pct"))),
        btc_return_pct=_as_float(row.get("btc_return_pct", row.get("btc_pct"))),
        top3_equal_weight_return_pct=_as_float(
            row.get("top3_equal_weight_return_pct", row.get("top3_ew_return_pct", row.get("top3_pct")))
        ),
        current_live_baseline_return_pct=_as_float(
            row.get("current_live_baseline_return_pct", row.get("live_return_pct", row.get("live_pct")))
        ),
        cash_return_pct=_as_float(row.get("cash_return_pct", row.get("cash_pct"))),
    )


def load_return_rows(path: str | Path) -> tuple[list[ReturnRow], dict[str, Any], str]:
    source = Path(path).expanduser()
    raw = source.read_bytes()
    data_hash = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    meta: dict[str, Any] = {}
    rows: list[ReturnRow] = []
    if source.suffix.lower() == ".csv":
        reader = csv.DictReader(text.splitlines())
        for index, row in enumerate(reader):
            rows.append(_row_from_mapping(dict(row), index))
        return rows, meta, data_hash

    if source.suffix.lower() == ".jsonl":
        for index, line in enumerate(text.splitlines()):
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("JSONL return rows must be objects")
                rows.append(_row_from_mapping(payload, index))
        return rows, meta, data_hash

    payload = json.loads(text)
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        meta = dict(payload.get("meta", {})) if isinstance(payload.get("meta"), dict) else {}
        records = payload.get("periods", payload.get("rows"))
    else:
        raise ValueError("returns JSON must be a list or object with periods/rows")
    if not isinstance(records, list):
        raise ValueError("returns JSON must contain periods or rows list")
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError("return rows must be objects")
        rows.append(_row_from_mapping(row, index))
    return rows, meta, data_hash


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


def _meta_bool(meta: dict[str, Any], key: str, default: bool = False) -> bool:
    value = meta.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "pass"}
    return bool(value)


def build_beta_residual_metrics(
    rows: list[ReturnRow],
    *,
    source_label: str,
    data_hash: str,
    holdout_role: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("at least one return row is required")
    meta = dict(meta or {})
    strategy = [row.strategy_return_pct for row in rows]
    btc = [row.btc_return_pct for row in rows]
    top3 = [row.top3_equal_weight_return_pct for row in rows]
    live = [row.current_live_baseline_return_pct for row in rows]
    cash = [row.cash_return_pct for row in rows]

    btc_var = _variance(btc)
    beta_to_btc = _covariance(strategy, btc) / btc_var if btc_var > 0.0 else 0.0
    residual = [s - beta_to_btc * b for s, b in zip(strategy, btc)]
    residual_sum = sum(residual)
    strategy_total = _compound_pct(strategy)
    btc_total = _compound_pct(btc)
    top3_total = _compound_pct(top3)
    live_total = _compound_pct(live)
    cash_total = _compound_pct(cash)

    costs_included = _meta_bool(meta, "costs_included", False)
    funding_included = _meta_bool(meta, "funding_included", costs_included)
    worst_case_buffer = _as_float(meta.get("worst_case_cost_buffer_pct"), 0.0)
    net_after_cost = residual_sum if costs_included else 0.0
    worst_case_net = net_after_cost - worst_case_buffer if costs_included else 0.0

    config_basis = {
        "source_label": source_label,
        "holdout_role": holdout_role,
        "period_count": len(rows),
        "meta": meta,
    }
    config_hash = hashlib.sha256(json.dumps(config_basis, sort_keys=True).encode("utf-8")).hexdigest()

    return {
        "schema_version": BETA_METRICS_VERSION,
        "source_label": source_label,
        "proposal": {
            "label_spec": meta.get("label_spec", "BTC beta-residual period return"),
            "benchmark_spec": meta.get("benchmark_spec", "cash/BTC/TOP3/current live"),
            "data_spec": meta.get("data_spec", "aligned period return panel"),
            "cost_spec": meta.get("cost_spec", "requires costs_included=true for promotion"),
            "kill_line": meta.get("kill_line", "block if beta residual or cost-adjusted residual is non-positive"),
            "beta_residual_target": True,
        },
        "data": {
            "point_in_time": _meta_bool(meta, "point_in_time", False),
            "as_of_join": _meta_bool(meta, "as_of_join", False),
            "replayable": _meta_bool(meta, "replayable", True),
            "data_hash": data_hash,
            "code_version": BETA_METRICS_VERSION,
            "config_hash": config_hash,
            "holdout_role": holdout_role,
            "trial_count": int(_as_float(meta.get("trial_count"), 1.0)),
            "exchange_rules_source": meta.get("exchange_rules_source", "unknown"),
            "filter_validator_reused": _meta_bool(meta, "filter_validator_reused", False),
        },
        "performance": {
            "period_count": len(rows),
            "strategy_total_return_pct": strategy_total,
            "btc_total_return_pct": btc_total,
            "top3_equal_weight_total_return_pct": top3_total,
            "current_live_baseline_total_return_pct": live_total,
            "cash_total_return_pct": cash_total,
            "excess_vs_btc_pct": strategy_total - btc_total,
            "excess_vs_top3_equal_weight_pct": strategy_total - top3_total,
            "excess_vs_current_live_baseline_pct": strategy_total - live_total,
            "net_residual_return_pct": residual_sum,
            "beta_to_btc": beta_to_btc,
        },
        "benchmarks": {
            "beats_cash": strategy_total > cash_total,
            "beats_btc_buy_hold": strategy_total > btc_total,
            "beats_top3_equal_weight": strategy_total > top3_total,
            "beats_current_live_baseline": strategy_total > live_total,
        },
        "cost": {
            "costs_included": costs_included,
            "net_after_cost_pct": net_after_cost,
            "worst_case_cost_net_pct": worst_case_net,
            "min_notional_coverage": _as_float(meta.get("min_notional_coverage"), 0.0),
            "required_maker_fill_ratio": _as_float(meta.get("required_maker_fill_ratio"), 0.0),
            "actual_maker_fill_ratio": _as_float(meta.get("actual_maker_fill_ratio"), 0.0),
            "funding_included": funding_included,
        },
        "validation": {
            "deflated_sharpe_ratio": _as_float(meta.get("deflated_sharpe_ratio"), 0.0),
            "pbo": _as_float(meta.get("pbo"), 1.0),
            "purged_cv_pass": _meta_bool(meta, "purged_cv_pass", False),
            "largest_contributor_removed_return_pct": _as_float(
                meta.get("largest_contributor_removed_return_pct"), min(residual_sum, 0.0)
            ),
            "embargo_applied": _meta_bool(meta, "embargo_applied", False),
            "artifact_path": meta.get("validation_artifact_path"),
            "source_feature_path": meta.get("validation_source_feature_path"),
        },
        "breadth": {
            "effective_breadth": _as_float(meta.get("effective_breadth"), 1.0),
            "claims_cross_sectional_edge": _meta_bool(meta, "claims_cross_sectional_edge", False),
            "correlation_stress_pass": _meta_bool(meta, "correlation_stress_pass", False),
            "capacity_checked": _meta_bool(meta, "capacity_checked", False),
        },
        "paper": {
            "holdout_role": meta.get("paper_holdout_role", holdout_role),
            "forward_days": int(_as_float(meta.get("paper_forward_days"), 0.0)),
            "schema_errors": int(_as_float(meta.get("paper_schema_errors"), 0.0)),
            "unmanaged_positions": int(_as_float(meta.get("paper_unmanaged_positions"), 0.0)),
            "unknown_price_filter_events": int(_as_float(meta.get("paper_unknown_price_filter_events"), 1.0)),
            "orders_replayable": _meta_bool(meta, "paper_orders_replayable", False),
        },
        "live": {
            "dry_run_days": int(_as_float(meta.get("live_dry_run_days"), 0.0)),
            "pilot_cap_usdt": _as_float(meta.get("live_pilot_cap_usdt"), 999999.0),
            "withdrawal_disabled": _meta_bool(meta, "live_withdrawal_disabled", False),
            "one_way_position_mode": _meta_bool(meta, "live_one_way_position_mode", False),
            "isolated_margin": _meta_bool(meta, "live_isolated_margin", False),
            "rollback_written": _meta_bool(meta, "live_rollback_written", False),
        },
        "llm": {
            "used_for_orders": False,
            "used_for_target_weights": False,
            "used_for_risk_override": False,
        },
        "diagnostics": {
            "first_ts": rows[0].ts,
            "last_ts": rows[-1].ts,
            "returns_are_percent_points": True,
            "residual_formula": "strategy_return_pct - beta_to_btc * btc_return_pct",
            "promotion_note": "Higher-order validation fields default to blocking values unless supplied by quant artifacts.",
        },
    }


def write_beta_metrics_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-beta-metrics",
        path_key="artifact_path",
        default_filename="alpha_agent_beta_metrics.json",
        explicit_path=explicit_path,
    )
