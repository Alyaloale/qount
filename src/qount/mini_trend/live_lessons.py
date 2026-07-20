"""Deterministic, read-only audit of the retired X4 live record set."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings


LIVE_LESSONS_VERSION = "mini_trend_live_lessons_v0.1"
REQUIRED_FILES = (
    "orders.jsonl",
    "snapshots.jsonl",
    "equity_daily.json",
    "inception.json",
    "stops.json",
    "latest.json",
    "cxd_live.log",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"expected object at {path.name}:{line_number}")
            rows.append(row)
    return rows


def _file_evidence(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    line_count = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
            line_count += chunk.count(b"\n")
    return {
        "filename": path.name,
        "sha256": digest.hexdigest(),
        "bytes": path.stat().st_size,
        "line_count": line_count,
    }


def _pct(end: float, start: float) -> float:
    return (end / start - 1.0) * 100.0 if start else 0.0


def _max_drawdown_pct(values: Sequence[float]) -> float:
    peak = 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def _daily_equity_metrics(
    daily: Sequence[Mapping[str, Any]],
    latest: Mapping[str, Any],
    inception: Mapping[str, Any],
) -> dict[str, Any]:
    if not daily:
        raise ValueError("equity_daily.json must contain at least one point")
    rows = sorted(daily, key=lambda row: str(row["day"]))
    start = rows[0]
    end = rows[-1]
    cutoff_rows = [row for row in rows if str(row["day"]) <= "2026-06-30"]
    june_end = cutoff_rows[-1] if cutoff_rows else start
    values = [float(row["equity"]) for row in rows]
    clean_end = float(end["equity"])
    latest_equity = float(latest.get("equity") or 0.0)
    baseline = float(latest.get("inception_equity") or inception.get("equity") or 0.0)
    standalone_baseline = float(inception.get("equity") or 0.0)
    external_flow_gap = clean_end - latest_equity
    contamination_threshold = max(abs(clean_end) * 0.10, 25.0)
    contaminated = abs(external_flow_gap) > contamination_threshold
    june_gain = float(june_end["equity"]) - baseline
    july_giveback = clean_end - float(june_end["equity"])
    return {
        "source_priority": "guarded daily equity; post-withdrawal latest equity excluded from strategy PnL",
        "point_count": len(rows),
        "window": {"start": str(start["day"]), "end": str(end["day"])},
        "strategy_inception_equity_usdt": round(baseline, 8),
        "standalone_inception_file_usdt": round(standalone_baseline, 8),
        "inception_baseline_difference_usdt": round(baseline - standalone_baseline, 8),
        "first_daily_equity_usdt": round(float(start["equity"]), 8),
        "june_end_equity_usdt": round(float(june_end["equity"]), 8),
        "pre_withdrawal_end_equity_usdt": round(clean_end, 8),
        "inception_to_june_end_return_pct": round(_pct(float(june_end["equity"]), baseline), 8),
        "inception_to_pre_withdrawal_return_pct": round(_pct(clean_end, baseline), 8),
        "july_rebound_giveback_usdt": round(july_giveback, 8),
        "july_rebound_giveback_pct": round(_pct(clean_end, float(june_end["equity"])), 8),
        "june_gain_erased_pct": round(abs(july_giveback) / june_gain * 100.0, 8) if june_gain > 0 else None,
        "daily_max_drawdown_pct": round(_max_drawdown_pct(values), 8),
        "latest_account_equity_usdt": round(latest_equity, 8),
        "external_flow_gap_usdt": round(external_flow_gap, 8),
        "latest_total_pnl_contaminated_by_external_flow": contaminated,
        "reported_latest_total_pnl_pct": float(latest.get("total_pnl_pct") or 0.0) * 100.0,
    }


def _order_signature(batch: Mapping[str, Any]) -> tuple[Any, ...]:
    orders = tuple(
        (
            row.get("symbol"),
            row.get("side"),
            float(row.get("base") or 0.0),
            float(row.get("est_usdt") or 0.0),
        )
        for row in batch.get("orders", [])
    )
    return batch.get("bar"), orders


def _order_metrics(
    batches: Sequence[Mapping[str, Any]],
    inception_ts: str,
) -> dict[str, Any]:
    live = [row for row in batches if row.get("mode") == "live" and row.get("armed") is True]
    strategy = [row for row in live if str(row.get("ts", "")) >= inception_ts]
    events: list[dict[str, Any]] = []
    for batch in strategy:
        for order in batch.get("orders", []):
            events.append({**order, "bar": batch.get("bar"), "ts": batch.get("ts")})

    grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"count": 0, "notional": 0.0})
    for row in events:
        key = (str(row.get("symbol")), str(row.get("side")))
        grouped[key]["count"] += 1
        grouped[key]["notional"] += float(row.get("est_usdt") or 0.0)
    by_symbol_side = [
        {
            "symbol": symbol,
            "side": side,
            "count": int(values["count"]),
            "notional_usdt": round(values["notional"], 8),
        }
        for (symbol, side), values in sorted(grouped.items())
    ]

    signatures: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for batch in strategy:
        if batch.get("orders"):
            signatures[_order_signature(batch)].append(batch)
    duplicate_groups = []
    duplicate_order_count = 0
    for rows in signatures.values():
        if len(rows) < 2:
            continue
        order_count = len(rows[0].get("orders", []))
        duplicate_order_count += (len(rows) - 1) * order_count
        duplicate_groups.append(
            {
                "bar": rows[0].get("bar"),
                "batch_count": len(rows),
                "order_count_per_batch": order_count,
                "timestamps": [row.get("ts") for row in rows],
            }
        )

    same_side: Counter[tuple[str, str, str]] = Counter()
    symbol_bar_sides: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in events:
        key = (str(row.get("bar")), str(row.get("symbol")), str(row.get("side")))
        same_side[key] += 1
        symbol_bar_sides[key[:2]].add(key[2])
    repeated_same_side = sum(count - 1 for count in same_side.values() if count > 1)
    flips = sum(1 for sides in symbol_bar_sides.values() if len(sides) > 1)

    stopped_events = [
        {"ts": row.get("ts"), "bar": row.get("bar"), "symbols": list(row.get("stopped") or [])}
        for row in strategy
        if row.get("stopped")
    ]
    blocked = [item for row in batches for item in (row.get("capital_blocked") or [])]
    return {
        "audit_batch_count": len(batches),
        "live_armed_batch_count": len(live),
        "all_logged_placed_order_count": sum(int(row.get("n_placed") or 0) for row in batches),
        "post_inception_placed_order_count": sum(int(row.get("n_placed") or 0) for row in strategy),
        "post_inception_orders_by_symbol_side": by_symbol_side,
        "exact_duplicate_batch_count": sum(len(rows) - 1 for rows in signatures.values() if len(rows) > 1),
        "exact_duplicate_order_count": duplicate_order_count,
        "exact_duplicate_batches": duplicate_groups,
        "same_bar_repeated_same_side_order_count": repeated_same_side,
        "same_bar_direction_flip_group_count": flips,
        "stop_event_count": len(stopped_events),
        "stopped_events": stopped_events,
        "capital_blocked_observation_count": len(blocked),
        "capital_blocked_symbols": sorted({str(row.get("symbol")) for row in blocked}),
    }


def _snapshot_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    exposure = Counter()
    counts = Counter()
    states = Counter()
    for row in rows:
        states[str(row.get("state"))] += 1
        counts[int(row.get("n_holdings") or 0)] += 1
        for holding in row.get("holdings", []):
            symbol = str(holding.get("s") or holding.get("symbol") or "")
            exposure[symbol] += abs(float(holding.get("value") or 0.0))
    total = sum(exposure.values())
    shares = [
        {"symbol": symbol, "notional_time_share": round(value / total, 8) if total else 0.0}
        for symbol, value in sorted(exposure.items())
        if symbol
    ]
    ranked = sorted(shares, key=lambda row: row["notional_time_share"], reverse=True)
    return {
        "record_count": len(rows),
        "window": [rows[0].get("ts"), rows[-1].get("ts")] if rows else [],
        "state_counts": dict(sorted(states.items())),
        "holding_count_records": {str(key): counts[key] for key in sorted(counts)},
        "notional_time_share_by_symbol": shares,
        "top_two_notional_time_share": round(sum(row["notional_time_share"] for row in ranked[:2]), 8),
        "pnl_use_allowed": False,
        "pnl_exclusion_reason": "snapshot equity contains documented cross-cron transfer glitches",
    }


def _log_metrics(path: Path) -> dict[str, int]:
    patterns = {
        "runner_count": re.compile(r"\[X4-LIVE"),
        "fail_closed_unknown_capital_count": re.compile(r"auto-capital .*SKIP trading this run"),
        "legacy_fallback_capital_count": re.compile(r"wallet read failed, using fallback"),
        "zero_diff_below_min_order_count": re.compile(r"below min_order \([+-]0\.00 USDT\)"),
        "stop_sync_count": re.compile(r"\[STOP-SYNC\]"),
    }
    counts = Counter()
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            for name, pattern in patterns.items():
                if pattern.search(line):
                    counts[name] += 1
    return {name: counts[name] for name in patterns}


def build_live_lessons_report(input_dir: str | Path) -> dict[str, Any]:
    root = Path(input_dir).expanduser()
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError(f"live audit input missing files: {','.join(missing)}")
    orders = _load_jsonl(root / "orders.jsonl")
    snapshots = _load_jsonl(root / "snapshots.jsonl")
    daily = _load_json(root / "equity_daily.json")
    inception = _load_json(root / "inception.json")
    stops = _load_json(root / "stops.json")
    latest = _load_json(root / "latest.json")
    if not isinstance(daily, list) or not isinstance(inception, dict) or not isinstance(latest, dict):
        raise ValueError("unexpected live audit JSON shape")
    evidence = [_file_evidence(root / name) for name in REQUIRED_FILES]
    return {
        "schema_version": LIVE_LESSONS_VERSION,
        "artifact_type": "mini_trend_live_lessons",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "vps_read_only_source": True,
            "private_api_called": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
            "raw_log_content_embedded": False,
        },
        "source_evidence": evidence,
        "equity": _daily_equity_metrics(daily, latest, inception),
        "orders": _order_metrics(orders, str(inception.get("ts") or "")),
        "snapshots": _snapshot_metrics(snapshots),
        "stops": {
            "final_latched_symbols": sorted(
                symbol for symbol, state in stops.items() if isinstance(state, Mapping) and state.get("latched")
            )
        },
        "operations": _log_metrics(root / "cxd_live.log"),
        "lessons": {
            "strategy": [
                "The June short-book gain was more than erased during the July rebound.",
                "Do not inherit the old always-on short gate into the next low-frequency candidate.",
                "Carry is removed from the next-capital architecture by owner direction.",
            ],
            "execution": [
                "Allow at most one directional decision per completed daily bar.",
                "Preserve stop latch and require a completed-bar cooldown before re-entry.",
                "Require every target leg to clear runtime quantity and notional filters before activation.",
            ],
            "operations": [
                "Unknown capital must fail closed; never size from a fallback balance.",
                "Do not use leverage to compensate for a small account.",
                "Separate external cash flows from strategy PnL before judging returns.",
            ],
        },
        "candidate_constraints": {
            "capital_location": "Binance USD-M futures wallet",
            "carry_allowed": False,
            "market": "um_futures",
            "interval": "1d",
            "direction": "long_cash",
            "maximum_effective_gross": 1.0,
            "leverage_boost_allowed": False,
            "shorting_allowed": False,
            "one_decision_per_completed_bar": True,
            "unknown_capital_action": "fail_closed",
            "stop_latch_required": True,
            "runtime_filter_coverage_required": 1.0,
            "paper_or_live_allowed": False,
        },
        "verdict": "audit_complete_research_only",
    }


def write_live_lessons_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-live-lessons",
        path_key="artifact_path",
        default_filename="mini_trend_live_lessons.json",
        explicit_path=explicit_path,
    )
