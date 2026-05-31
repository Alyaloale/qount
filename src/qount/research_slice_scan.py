from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import Any

from .entry_quality import assess_fresh_entry
from .entry_quality import build_research_slice_tags
from .models import utc_now
from .review import _symbol_snapshot_from_snapshot_entry
from .trade_policy import estimated_action_cost_pct


DEFAULT_TARGET_RESEARCH_SLICE_TAGS = (
    "eth_reclaim_long_failed_breakdown_base",
    "eth_reclaim_long_failed_breakdown_sma_slow_gt004",
    "eth_reclaim_long_failed_breakdown_return1bar_0004",
    "eth_reclaim_long_failed_breakdown_sma_slow_gt004_return1bar_0004",
    "eth_reclaim_long_failed_breakdown_trend_sma_slow_gt004",
    "eth_reclaim_long_failed_breakdown_trend_return1bar_0004",
    "multi_range_action_pullback_sma_fast_gt008",
    "multi_range_action_range_return24_gt012",
    "eth_range_action_pullback_sma_fast_gt008",
    "eth_range_action_pullback_sma_slow_002_004",
    "eth_range_action_pullback_sma_slow_gt008",
    "eth_range_action_range_return24_gt012",
    "eth_trend_impulse_short_breakdown_chase_range_gt012",
    "eth_trend_impulse_short_breakdown_chase_terminal_volume_gt3",
    "eth_trend_impulse_range_noise_range_gt012",
    "eth_trend_impulse_range_noise_washout",
)
DEFAULT_FUTURE_EDGE_HORIZON_BARS = (3, 6, 12, 24)
DEFAULT_RESEARCH_SCAN_FEE_PCT = 0.0004
DEFAULT_RESEARCH_SCAN_SLIPPAGE_PCT = 0.0002
DEFAULT_SHADOW_READINESS_MIN_SAMPLES_PER_HORIZON = 8
DEFAULT_SHADOW_READINESS_MIN_POSITIVE_EDGE_RATE = 0.5
DEFAULT_SHADOW_READINESS_MIN_POSITIVE_WINDOWS = 2


def _normalized_symbol_key(symbol: str) -> str:
    return str(symbol).split(":", 1)[0].strip().upper()


def _window_label(raw: str) -> str:
    value = raw.strip() or "backtest"
    return re.sub(r"^\d+-", "", value)


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _discover_backtest_dirs(root: Path) -> list[tuple[str, Path]]:
    root = root.expanduser()
    if (root / "qount.db").exists():
        return [(_window_label(root.name), root)]

    walk_forward = _load_json_file(root / "walk_forward.json")
    rows: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for window in walk_forward.get("windows") or []:
        if not isinstance(window, dict):
            continue
        raw_path = window.get("backtest_artifact_dir")
        if not raw_path:
            continue
        path = Path(str(raw_path))
        if not path.exists():
            path = root / str(raw_path)
        if (path / "qount.db").exists():
            resolved = path.resolve()
            if resolved not in seen:
                rows.append((str(window.get("label") or _window_label(path.parent.name)), path))
                seen.add(resolved)

    if rows:
        return rows

    for db_path in sorted(root.glob("*/backtest/qount.db")):
        backtest_dir = db_path.parent
        resolved = backtest_dir.resolve()
        if resolved in seen:
            continue
        rows.append((_window_label(backtest_dir.parent.name), backtest_dir))
        seen.add(resolved)
    for db_path in sorted(root.glob("*/qount.db")):
        backtest_dir = db_path.parent
        resolved = backtest_dir.resolve()
        if resolved in seen:
            continue
        rows.append((_window_label(backtest_dir.name), backtest_dir))
        seen.add(resolved)
    for db_path in sorted(root.glob("*/*/backtest/qount.db")):
        backtest_dir = db_path.parent
        resolved = backtest_dir.resolve()
        if resolved in seen:
            continue
        try:
            parent_relative = backtest_dir.parent.relative_to(root)
            label = "/".join(_window_label(part) for part in parent_relative.parts)
        except ValueError:
            label = _window_label(backtest_dir.parent.name)
        rows.append((label, backtest_dir))
        seen.add(resolved)
    return rows


def _normalize_horizon_bars(horizon_bars: list[int] | tuple[int, ...] | None) -> tuple[int, ...]:
    values = horizon_bars or DEFAULT_FUTURE_EDGE_HORIZON_BARS
    normalized: list[int] = []
    for raw_value in values:
        value = int(raw_value)
        if value <= 0:
            raise ValueError(f"research_slice_scan_invalid_horizon_bars:{value}")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _close_price(symbol: Any) -> float | None:
    try:
        close = float(symbol.last_price)
    except (TypeError, ValueError):
        return None
    if close <= 0.0:
        return None
    return close


def _aligned_future_return_pct(action: str, current_close: float, future_close: float) -> float | None:
    if current_close <= 0.0 or future_close <= 0.0:
        return None
    if action == "buy":
        return (future_close / current_close) - 1.0
    if action == "sell":
        return (current_close / future_close) - 1.0
    return None


def _new_edge_accumulator() -> dict[str, Any]:
    return {
        "sample_count": 0,
        "positive_edge_count": 0,
        "sum_aligned_return_pct": 0.0,
        "sum_target_edge_pct": 0.0,
        "min_target_edge_pct": None,
        "max_target_edge_pct": None,
    }


def _add_edge_sample(accumulator: dict[str, Any], *, aligned_return_pct: float, target_edge_pct: float) -> None:
    accumulator["sample_count"] += 1
    if target_edge_pct > 0.0:
        accumulator["positive_edge_count"] += 1
    accumulator["sum_aligned_return_pct"] += aligned_return_pct
    accumulator["sum_target_edge_pct"] += target_edge_pct
    min_value = accumulator["min_target_edge_pct"]
    max_value = accumulator["max_target_edge_pct"]
    accumulator["min_target_edge_pct"] = target_edge_pct if min_value is None else min(float(min_value), target_edge_pct)
    accumulator["max_target_edge_pct"] = target_edge_pct if max_value is None else max(float(max_value), target_edge_pct)


def _finalize_edge_accumulator(accumulator: dict[str, Any]) -> dict[str, Any]:
    sample_count = int(accumulator.get("sample_count") or 0)
    positive_count = int(accumulator.get("positive_edge_count") or 0)
    if sample_count <= 0:
        return {
            "sample_count": 0,
            "positive_edge_count": 0,
            "positive_edge_rate": 0.0,
            "avg_aligned_return_pct": 0.0,
            "avg_target_edge_pct": 0.0,
            "sum_target_edge_pct": 0.0,
            "min_target_edge_pct": None,
            "max_target_edge_pct": None,
        }
    return {
        "sample_count": sample_count,
        "positive_edge_count": positive_count,
        "positive_edge_rate": positive_count / sample_count,
        "avg_aligned_return_pct": float(accumulator.get("sum_aligned_return_pct") or 0.0) / sample_count,
        "avg_target_edge_pct": float(accumulator.get("sum_target_edge_pct") or 0.0) / sample_count,
        "sum_target_edge_pct": float(accumulator.get("sum_target_edge_pct") or 0.0),
        "min_target_edge_pct": accumulator.get("min_target_edge_pct"),
        "max_target_edge_pct": accumulator.get("max_target_edge_pct"),
    }


def _merge_edge_summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    accumulator = _new_edge_accumulator()
    for row in rows:
        sample_count = int(row.get("sample_count") or 0)
        if sample_count <= 0:
            continue
        accumulator["sample_count"] += sample_count
        accumulator["positive_edge_count"] += int(row.get("positive_edge_count") or 0)
        accumulator["sum_aligned_return_pct"] += float(row.get("avg_aligned_return_pct") or 0.0) * sample_count
        accumulator["sum_target_edge_pct"] += float(row.get("sum_target_edge_pct") or 0.0)
        min_value = row.get("min_target_edge_pct")
        max_value = row.get("max_target_edge_pct")
        if min_value is not None:
            current_min = accumulator["min_target_edge_pct"]
            accumulator["min_target_edge_pct"] = float(min_value) if current_min is None else min(float(current_min), float(min_value))
        if max_value is not None:
            current_max = accumulator["max_target_edge_pct"]
            accumulator["max_target_edge_pct"] = float(max_value) if current_max is None else max(float(current_max), float(max_value))
    return _finalize_edge_accumulator(accumulator)


def _summarize_snapshot_future_edges(
    observations_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    horizon_bars: tuple[int, ...],
    contract_market: bool,
    fee_pct: float,
    slippage_pct: float,
) -> dict[str, dict[str, dict[str, Any]]]:
    accumulators_by_horizon: dict[int, dict[str, dict[str, Any]]] = {
        horizon: defaultdict(_new_edge_accumulator)
        for horizon in horizon_bars
    }
    for observations in observations_by_symbol.values():
        for index, observation in enumerate(observations):
            tags = observation.get("tags") or ()
            if not tags:
                continue
            action = str(observation.get("action") or "")
            if action not in {"buy", "sell"}:
                continue
            cost_pct = estimated_action_cost_pct(
                action,
                contract_market=contract_market,
                fee_pct=fee_pct,
                slippage_pct=slippage_pct,
            )
            current_close = float(observation.get("close") or 0.0)
            for horizon in horizon_bars:
                future_index = index + horizon
                if future_index >= len(observations):
                    continue
                future_close = float(observations[future_index].get("close") or 0.0)
                aligned_return_pct = _aligned_future_return_pct(action, current_close, future_close)
                if aligned_return_pct is None:
                    continue
                target_edge_pct = aligned_return_pct - cost_pct
                for tag in tags:
                    _add_edge_sample(
                        accumulators_by_horizon[horizon][str(tag)],
                        aligned_return_pct=aligned_return_pct,
                        target_edge_pct=target_edge_pct,
                    )
    return {
        str(horizon): {
            tag: _finalize_edge_accumulator(accumulator)
            for tag, accumulator in sorted(tag_accumulators.items())
        }
        for horizon, tag_accumulators in accumulators_by_horizon.items()
    }


def _merge_window_future_edge_summaries(windows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, list[tuple[str, dict[str, Any]]]]] = defaultdict(lambda: defaultdict(list))
    for window in windows:
        label = str(window.get("label") or "backtest")
        horizon_summaries = window.get("snapshot_research_slice_future_edge_by_horizon")
        if not isinstance(horizon_summaries, dict):
            continue
        for horizon, tag_summaries in horizon_summaries.items():
            if not isinstance(tag_summaries, dict):
                continue
            for tag, summary in tag_summaries.items():
                if isinstance(summary, dict):
                    grouped[str(horizon)][str(tag)].append((label, summary))

    merged: dict[str, dict[str, dict[str, Any]]] = {}
    for horizon, tags in sorted(grouped.items(), key=lambda item: int(item[0])):
        merged[horizon] = {}
        for tag, labelled_summaries in sorted(tags.items()):
            summaries = [summary for _label, summary in labelled_summaries]
            aggregate = _merge_edge_summaries(summaries)
            aggregate["by_window"] = {
                label: summary
                for label, summary in sorted(labelled_summaries)
                if int(summary.get("sample_count") or 0) > 0
            }
            merged[horizon][tag] = aggregate
    return merged


def _target_future_edge_by_horizon(
    future_edge_by_horizon: dict[str, dict[str, dict[str, Any]]],
    target_tags: tuple[str, ...],
    horizon_bars: tuple[int, ...],
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for horizon in (str(value) for value in horizon_bars):
        tag_summaries = future_edge_by_horizon.get(horizon, {})
        result[horizon] = {
            tag: tag_summaries.get(tag, _finalize_edge_accumulator(_new_edge_accumulator()))
            for tag in target_tags
        }
    return result


def _positive_window_count(summary: dict[str, Any]) -> int:
    by_window = summary.get("by_window")
    if not isinstance(by_window, dict):
        return 0
    count = 0
    for window_summary in by_window.values():
        if not isinstance(window_summary, dict):
            continue
        if int(window_summary.get("sample_count") or 0) <= 0:
            continue
        if float(window_summary.get("avg_target_edge_pct") or 0.0) > 0.0:
            count += 1
    return count


def _rank_shadow_blocked_tags(
    tags: dict[str, dict[str, Any]],
    *,
    min_samples_per_horizon: int,
    min_positive_edge_rate: float,
    min_positive_windows: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tag, item in tags.items():
        if item.get("status") == "ready_for_targeted_shadow_proof":
            continue
        sample_counts = item.get("sample_count_by_horizon")
        sample_counts = sample_counts if isinstance(sample_counts, dict) else {}
        avg_edges = item.get("avg_target_edge_pct_by_horizon")
        avg_edges = avg_edges if isinstance(avg_edges, dict) else {}
        positive_rates = item.get("positive_edge_rate_by_horizon")
        positive_rates = positive_rates if isinstance(positive_rates, dict) else {}
        positive_windows = item.get("positive_window_count_by_horizon")
        positive_windows = positive_windows if isinstance(positive_windows, dict) else {}
        blocking_reasons = list(item.get("blocking_reasons") or [])
        rows.append(
            {
                "tag": tag,
                "status": item.get("status"),
                "snapshot_count": int(item.get("snapshot_count") or 0),
                "ai_decision_count": int(item.get("ai_decision_count") or 0),
                "risk_final_count": int(item.get("risk_final_count") or 0),
                "total_sample_count": sum(int(value or 0) for value in sample_counts.values()),
                "positive_avg_horizon_count": sum(1 for value in avg_edges.values() if float(value or 0.0) > 0.0),
                "sample_ready_horizon_count": sum(
                    1 for value in sample_counts.values() if int(value or 0) >= min_samples_per_horizon
                ),
                "positive_rate_ready_horizon_count": sum(
                    1 for value in positive_rates.values() if float(value or 0.0) >= min_positive_edge_rate
                ),
                "positive_window_ready_horizon_count": sum(
                    1 for value in positive_windows.values() if int(value or 0) >= min_positive_windows
                ),
                "blocking_reason_count": len(blocking_reasons),
                "blocking_reasons": blocking_reasons,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            int(row["blocking_reason_count"]),
            -int(row["positive_avg_horizon_count"]),
            -int(row["sample_ready_horizon_count"]),
            -int(row["positive_rate_ready_horizon_count"]),
            -int(row["positive_window_ready_horizon_count"]),
            -int(row["total_sample_count"]),
            str(row["tag"]),
        ),
    )


def _shadow_candidate_readiness(
    *,
    snapshot_counts: Counter[str],
    ai_decision_counts: Counter[str],
    risk_final_counts: Counter[str],
    target_future_edge_by_horizon: dict[str, dict[str, dict[str, Any]]],
    target_tags: tuple[str, ...],
    horizon_bars: tuple[int, ...],
    min_samples_per_horizon: int = DEFAULT_SHADOW_READINESS_MIN_SAMPLES_PER_HORIZON,
    min_positive_edge_rate: float = DEFAULT_SHADOW_READINESS_MIN_POSITIVE_EDGE_RATE,
    min_positive_windows: int = DEFAULT_SHADOW_READINESS_MIN_POSITIVE_WINDOWS,
) -> dict[str, Any]:
    tags: dict[str, dict[str, Any]] = {}
    ready_tags: list[str] = []
    for tag in target_tags:
        blocking_reasons: list[str] = []
        sample_count_by_horizon: dict[str, int] = {}
        avg_target_edge_pct_by_horizon: dict[str, float] = {}
        positive_edge_rate_by_horizon: dict[str, float] = {}
        positive_window_count_by_horizon: dict[str, int] = {}

        if int(snapshot_counts.get(tag, 0)) <= 0:
            blocking_reasons.append("no_snapshot_coverage")

        for horizon in (str(value) for value in horizon_bars):
            summary = target_future_edge_by_horizon.get(horizon, {}).get(tag, {})
            sample_count = int(summary.get("sample_count") or 0)
            avg_target_edge_pct = float(summary.get("avg_target_edge_pct") or 0.0)
            positive_edge_rate = float(summary.get("positive_edge_rate") or 0.0)
            positive_window_count = _positive_window_count(summary)
            sample_count_by_horizon[horizon] = sample_count
            avg_target_edge_pct_by_horizon[horizon] = avg_target_edge_pct
            positive_edge_rate_by_horizon[horizon] = positive_edge_rate
            positive_window_count_by_horizon[horizon] = positive_window_count
            if sample_count < min_samples_per_horizon:
                blocking_reasons.append(f"h{horizon}_insufficient_samples")
            if avg_target_edge_pct <= 0.0:
                blocking_reasons.append(f"h{horizon}_non_positive_avg_edge")
            if positive_edge_rate < min_positive_edge_rate:
                blocking_reasons.append(f"h{horizon}_low_positive_edge_rate")
            if positive_window_count < min_positive_windows:
                blocking_reasons.append(f"h{horizon}_insufficient_positive_windows")

        status = "ready_for_targeted_shadow_proof" if not blocking_reasons else "not_ready"
        if status == "ready_for_targeted_shadow_proof":
            ready_tags.append(tag)
        tags[tag] = {
            "status": status,
            "snapshot_count": int(snapshot_counts.get(tag, 0)),
            "ai_decision_count": int(ai_decision_counts.get(tag, 0)),
            "risk_final_count": int(risk_final_counts.get(tag, 0)),
            "sample_count_by_horizon": sample_count_by_horizon,
            "avg_target_edge_pct_by_horizon": avg_target_edge_pct_by_horizon,
            "positive_edge_rate_by_horizon": positive_edge_rate_by_horizon,
            "positive_window_count_by_horizon": positive_window_count_by_horizon,
            "blocking_reasons": blocking_reasons,
        }
    return {
        "status": "has_ready_tags" if ready_tags else "no_ready_tags",
        "ready_tags": ready_tags,
        "blocked_tags_ranked": _rank_shadow_blocked_tags(
            tags,
            min_samples_per_horizon=min_samples_per_horizon,
            min_positive_edge_rate=min_positive_edge_rate,
            min_positive_windows=min_positive_windows,
        ),
        "required_horizons": list(horizon_bars),
        "min_samples_per_horizon": min_samples_per_horizon,
        "min_positive_edge_rate": min_positive_edge_rate,
        "min_positive_windows": min_positive_windows,
        "tags": tags,
        "note": "readiness_for_offline_shadow_candidate_proof_only_not_candidate_gate",
    }


def _candidate_filter_manage_only(payload_json: dict[str, Any], symbol: str) -> bool:
    raw_payload = payload_json.get("raw_payload")
    raw_payload = raw_payload if isinstance(raw_payload, dict) else {}
    candidate_filter = raw_payload.get("candidate_filter")
    candidate_filter = candidate_filter if isinstance(candidate_filter, dict) else {}
    summaries = candidate_filter.get("symbols")
    if not isinstance(summaries, list):
        return False
    normalized_symbol = _normalized_symbol_key(symbol)
    for item in summaries:
        if not isinstance(item, dict):
            continue
        if _normalized_symbol_key(str(item.get("symbol") or "")) == normalized_symbol:
            return bool(item.get("manage_only"))
    return False


def _scan_backtest_dir(
    label: str,
    backtest_dir: Path,
    *,
    symbols_filter: set[str] | None,
    horizon_bars: tuple[int, ...],
    contract_market: bool,
    fee_pct: float,
    slippage_pct: float,
) -> dict[str, Any]:
    db_path = backtest_dir / "qount.db"
    snapshot_tag_counts: Counter[str] = Counter()
    ai_decision_tag_counts: Counter[str] = Counter()
    risk_final_tag_counts: Counter[str] = Counter()
    observations_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    snapshot_count = 0
    decision_count = 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute("SELECT run_id, snapshot_json FROM snapshots ORDER BY run_id"):
            snapshot = json.loads(row["snapshot_json"])
            for symbol_entry in snapshot.get("symbols") or []:
                symbol = _symbol_snapshot_from_snapshot_entry(symbol_entry)
                if symbol is None:
                    continue
                if symbols_filter is not None and _normalized_symbol_key(symbol.symbol) not in symbols_filter:
                    continue
                snapshot_count += 1
                assessment = assess_fresh_entry(symbol)
                tags = build_research_slice_tags(symbol, assessment)
                snapshot_tag_counts.update(tags)
                close_price = _close_price(symbol)
                if close_price is not None:
                    observations_by_symbol[_normalized_symbol_key(symbol.symbol)].append(
                        {
                            "run_id": int(row["run_id"]),
                            "symbol": symbol.symbol,
                            "close": close_price,
                            "action": assessment.action,
                            "tags": tags,
                        }
                    )

        query = """
            SELECT
                v.payload_json AS payload_json,
                r.verdict_json AS verdict_json,
                s.snapshot_json AS snapshot_json
            FROM ai_decisions_validated v
            JOIN snapshots s ON s.run_id = v.run_id
            LEFT JOIN risk_actions r ON r.run_id = v.run_id
            ORDER BY v.run_id
        """
        for row in conn.execute(query):
            payload = json.loads(row["payload_json"])
            decision = payload.get("decision") if isinstance(payload, dict) else None
            if not isinstance(decision, dict):
                continue
            symbol_name = str(decision.get("symbol") or "")
            if symbols_filter is not None and _normalized_symbol_key(symbol_name) not in symbols_filter:
                continue
            snapshot = json.loads(row["snapshot_json"])
            symbol_entry = next(
                (
                    item
                    for item in snapshot.get("symbols") or []
                    if _normalized_symbol_key(str(item.get("symbol") or "")) == _normalized_symbol_key(symbol_name)
                ),
                None,
            )
            symbol = _symbol_snapshot_from_snapshot_entry(symbol_entry) if isinstance(symbol_entry, dict) else None
            if symbol is None:
                continue
            decision_count += 1
            manage_only = _candidate_filter_manage_only(payload, symbol_name)
            ai_assessment = assess_fresh_entry(symbol, action=str(decision.get("action") or "hold"))
            ai_decision_tag_counts.update(
                build_research_slice_tags(
                    symbol,
                    ai_assessment,
                    manage_only=manage_only,
                )
            )
            verdict = json.loads(row["verdict_json"]) if row["verdict_json"] else {}
            final_assessment = assess_fresh_entry(symbol, action=str(verdict.get("final_action") or "hold"))
            risk_final_tag_counts.update(
                build_research_slice_tags(
                    symbol,
                    final_assessment,
                    manage_only=manage_only,
                )
            )
    finally:
        conn.close()

    return {
        "label": label,
        "backtest_artifact_dir": str(backtest_dir),
        "db_path": str(db_path),
        "snapshot_count": snapshot_count,
        "decision_count": decision_count,
        "snapshot_research_slice_tag_counts": dict(sorted(snapshot_tag_counts.items())),
        "ai_decision_research_slice_tag_counts": dict(sorted(ai_decision_tag_counts.items())),
        "risk_final_research_slice_tag_counts": dict(sorted(risk_final_tag_counts.items())),
        "snapshot_research_slice_future_edge_by_horizon": _summarize_snapshot_future_edges(
            observations_by_symbol,
            horizon_bars=horizon_bars,
            contract_market=contract_market,
            fee_pct=fee_pct,
            slippage_pct=slippage_pct,
        ),
    }


def research_slice_scan(
    artifact_dir: Path,
    *,
    symbols_filter: list[str] | tuple[str, ...] | None = None,
    target_tags: list[str] | tuple[str, ...] | None = None,
    horizon_bars: list[int] | tuple[int, ...] | None = None,
    contract_market: bool = True,
    fee_pct: float = DEFAULT_RESEARCH_SCAN_FEE_PCT,
    slippage_pct: float = DEFAULT_RESEARCH_SCAN_SLIPPAGE_PCT,
) -> dict[str, Any]:
    root = artifact_dir.expanduser()
    backtest_dirs = _discover_backtest_dirs(root)
    if not backtest_dirs:
        raise ValueError(f"research_slice_scan_no_backtest_databases:{root}")

    normalized_symbols = None
    if symbols_filter:
        normalized_symbols = {_normalized_symbol_key(symbol) for symbol in symbols_filter}
    target_tag_values = tuple(target_tags or DEFAULT_TARGET_RESEARCH_SLICE_TAGS)
    horizon_values = _normalize_horizon_bars(horizon_bars)
    windows = [
        _scan_backtest_dir(
            label,
            backtest_dir,
            symbols_filter=normalized_symbols,
            horizon_bars=horizon_values,
            contract_market=contract_market,
            fee_pct=fee_pct,
            slippage_pct=slippage_pct,
        )
        for label, backtest_dir in backtest_dirs
    ]
    snapshot_counts: Counter[str] = Counter()
    ai_decision_counts: Counter[str] = Counter()
    risk_final_counts: Counter[str] = Counter()
    for window in windows:
        snapshot_counts.update(window["snapshot_research_slice_tag_counts"])
        ai_decision_counts.update(window["ai_decision_research_slice_tag_counts"])
        risk_final_counts.update(window["risk_final_research_slice_tag_counts"])
    snapshot_future_edge = _merge_window_future_edge_summaries(windows)
    target_future_edge = _target_future_edge_by_horizon(
        snapshot_future_edge,
        target_tag_values,
        horizon_values,
    )

    walk_forward = _load_json_file(root / "walk_forward.json")
    aggregate = walk_forward.get("aggregate") if isinstance(walk_forward.get("aggregate"), dict) else None
    offline_future_edge_readiness = _shadow_candidate_readiness(
        snapshot_counts=snapshot_counts,
        ai_decision_counts=ai_decision_counts,
        risk_final_counts=risk_final_counts,
        target_future_edge_by_horizon=target_future_edge,
        target_tags=target_tag_values,
        horizon_bars=horizon_values,
    )
    return {
        "version": "research_slice_scan_v2",
        "generated_at": utc_now().isoformat(),
        "artifact_dir": str(root),
        "source_mode": "walk_forward" if walk_forward else "backtest_collection",
        "backtest_count": len(windows),
        "symbols_filter": list(symbols_filter or []),
        "target_tags": list(target_tag_values),
        "future_edge_horizon_bars": list(horizon_values),
        "future_edge_cost_model": {
            "contract_market": contract_market,
            "fee_pct": fee_pct,
            "slippage_pct": slippage_pct,
        },
        "walk_forward_aggregate": aggregate,
        "snapshot_research_slice_tag_counts": dict(sorted(snapshot_counts.items())),
        "ai_decision_research_slice_tag_counts": dict(sorted(ai_decision_counts.items())),
        "risk_final_research_slice_tag_counts": dict(sorted(risk_final_counts.items())),
        "snapshot_research_slice_future_edge_by_horizon": snapshot_future_edge,
        "target_snapshot_research_slice_tag_counts": {
            tag: int(snapshot_counts.get(tag, 0))
            for tag in target_tag_values
        },
        "target_ai_decision_research_slice_tag_counts": {
            tag: int(ai_decision_counts.get(tag, 0))
            for tag in target_tag_values
        },
        "target_risk_final_research_slice_tag_counts": {
            tag: int(risk_final_counts.get(tag, 0))
            for tag in target_tag_values
        },
        "target_snapshot_research_slice_future_edge_by_horizon": target_future_edge,
        "offline_future_edge_readiness": offline_future_edge_readiness,
        "shadow_candidate_readiness": offline_future_edge_readiness,
        "windows": windows,
        "promotion_note": "offline_research_slice_scan_only_not_candidate_gate",
    }
