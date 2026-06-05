from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .research_slice_scan import _discover_backtest_dirs
from .research_slice_scan import _normalized_symbol_key
from .review import _symbol_snapshot_from_snapshot_entry
from .models import utc_now
from .settings import Settings
from .trade_policy import estimated_action_cost_pct


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _counter_payload(counter: Counter[str], *, limit: int | None = None) -> dict[str, Any]:
    items = counter.most_common(limit)
    total = sum(counter.values())
    return {
        "total": total,
        "counts": {key: int(value) for key, value in items},
    }


def _action_from_candidate(item: dict[str, Any]) -> str | None:
    thesis = item.get("entry_thesis_candidate")
    if isinstance(thesis, dict):
        direction = str(thesis.get("direction") or "")
        if direction == "long":
            return "buy"
        if direction == "short":
            return "sell"
    bias = str(item.get("higher_timeframe_bias") or "")
    if bias == "long":
        return "buy"
    if bias == "short":
        return "sell"
    return None


def _close_from_snapshot_entry(entry: dict[str, Any]) -> float | None:
    symbol = _symbol_snapshot_from_snapshot_entry(entry)
    if symbol is None:
        return None
    try:
        close = float(symbol.last_price)
    except (TypeError, ValueError):
        return None
    if close <= 0.0:
        return None
    return close


def _aligned_return_pct(action: str, current_close: float, future_close: float) -> float | None:
    if current_close <= 0.0 or future_close <= 0.0:
        return None
    if action == "buy":
        return (future_close / current_close) - 1.0
    if action == "sell":
        return (current_close / future_close) - 1.0
    return None


def _selected_symbols(candidate_filter: dict[str, Any]) -> set[str]:
    return {
        str(symbol)
        for symbol in candidate_filter.get("selected_symbols") or []
        if str(symbol).strip()
    }


def _selected_or_candidate_like(item: dict[str, Any], selected_symbols: set[str]) -> bool:
    symbol = str(item.get("symbol") or "")
    if selected_symbols and symbol in selected_symbols:
        return True
    if bool(item.get("manage_only")):
        return False
    reasons = [str(reason) for reason in item.get("reasons") or []]
    if bool(item.get("eligible")):
        return True
    return any(
        reason == "candidate_ok"
        or reason.endswith("_soft_penalty")
        or reason.startswith("research_shadow_candidate_tag_match")
        for reason in reasons
    )


class IdleWindowDiagnosticService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _order_stats(self, backtest_dir: Path) -> dict[str, int]:
        summary = _load_json(backtest_dir / "summary.json")
        order_stats = summary.get("order_stats")
        if isinstance(order_stats, dict):
            return {
                "paper_filled": int(order_stats.get("paper_filled") or 0),
                "paper_closed": int(order_stats.get("paper_closed") or 0),
                "paper_rejected": int(order_stats.get("paper_rejected") or 0),
                "noop": int(order_stats.get("noop") or 0),
            }
        db_path = backtest_dir / "qount.db"
        if not db_path.exists():
            return {"paper_filled": 0, "paper_closed": 0, "paper_rejected": 0, "noop": 0}
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM orders GROUP BY status").fetchall()
        finally:
            conn.close()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return {
            "paper_filled": counts.get("paper_filled", 0),
            "paper_closed": counts.get("paper_closed", 0),
            "paper_rejected": counts.get("paper_rejected", 0),
            "noop": counts.get("noop", 0),
        }

    def _rows(self, backtest_dir: Path) -> list[dict[str, Any]]:
        conn = sqlite3.connect(backtest_dir / "qount.db")
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT
                    runs.id AS run_id,
                    snapshots.snapshot_json AS snapshot_json,
                    validated.payload_json AS payload_json,
                    risk.verdict_json AS verdict_json
                FROM runs
                JOIN snapshots ON snapshots.run_id = runs.id
                LEFT JOIN ai_decisions_validated AS validated ON validated.run_id = runs.id
                LEFT JOIN risk_actions AS risk ON risk.run_id = runs.id
                ORDER BY runs.id
                """
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def _diagnose_backtest(
        self,
        label: str,
        backtest_dir: Path,
        *,
        symbols_filter: set[str] | None,
        horizon_bars: int,
        top_candidates: int,
        reason_limit: int,
    ) -> dict[str, Any]:
        rows = self._rows(backtest_dir)
        snapshots: list[dict[str, Any]] = [json.loads(row["snapshot_json"]) for row in rows]
        closes_by_run_symbol: dict[tuple[int, str], float] = {}
        for index, snapshot in enumerate(snapshots):
            for entry in snapshot.get("symbols") or []:
                if not isinstance(entry, dict):
                    continue
                symbol = str(entry.get("symbol") or "")
                if symbols_filter is not None and _normalized_symbol_key(symbol) not in symbols_filter:
                    continue
                close = _close_from_snapshot_entry(entry)
                if close is not None:
                    closes_by_run_symbol[(index, _normalized_symbol_key(symbol))] = close

        setup_label_counts: Counter[str] = Counter()
        setup_quality_counts: Counter[str] = Counter()
        setup_phase_counts: Counter[str] = Counter()
        candidate_reason_counts: Counter[str] = Counter()
        traditional_pattern_counts: Counter[str] = Counter()
        ai_hold_reason_counts: Counter[str] = Counter()
        selected_candidate_count = 0
        ai_hold_count = 0
        candidate_filter_hold_count = 0
        scored_candidates: list[dict[str, Any]] = []

        for row_index, row in enumerate(rows):
            payload = json.loads(row["payload_json"]) if row.get("payload_json") else {}
            decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
            raw_payload = payload.get("raw_payload") if isinstance(payload.get("raw_payload"), dict) else {}
            candidate_filter = raw_payload.get("candidate_filter")
            if not isinstance(candidate_filter, dict):
                continue
            selected_symbols = _selected_symbols(candidate_filter)
            if bool(raw_payload.get("candidate_filter_generated")):
                candidate_filter_hold_count += 1
            if str(decision.get("action") or "") == "hold" and not bool(raw_payload.get("candidate_filter_generated")):
                ai_hold_count += 1
                reason = str(decision.get("reason") or "unknown")
                ai_hold_reason_counts.update([reason])

            for item in candidate_filter.get("symbols") or []:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "")
                if symbols_filter is not None and _normalized_symbol_key(symbol) not in symbols_filter:
                    continue
                if bool(item.get("manage_only")):
                    continue
                setup_phase = str(item.get("setup_phase") or "unknown")
                setup_phase_counts.update([setup_phase])
                setup_signal = item.get("setup_model_signal")
                if isinstance(setup_signal, dict):
                    setup_label_counts.update([str(setup_signal.get("label") or "unknown")])
                    setup_quality_counts.update([str(setup_signal.get("quality") or "unknown")])
                else:
                    setup_label_counts.update(["missing"])
                    setup_quality_counts.update(["missing"])
                traditional = item.get("traditional_signal_context")
                if isinstance(traditional, dict):
                    traditional_pattern_counts.update([str(traditional.get("pattern_label") or "unknown")])
                else:
                    traditional_pattern_counts.update(["missing"])
                reasons = [str(reason) for reason in item.get("reasons") or []]
                candidate_reason_counts.update(reasons or ["candidate_ok"])

                if not _selected_or_candidate_like(item, selected_symbols):
                    continue
                action = _action_from_candidate(item)
                if action not in {"buy", "sell"}:
                    continue
                current_close = closes_by_run_symbol.get((row_index, _normalized_symbol_key(symbol)))
                future_close = closes_by_run_symbol.get((row_index + horizon_bars, _normalized_symbol_key(symbol)))
                if current_close is None or future_close is None:
                    continue
                aligned_return_pct = _aligned_return_pct(action, current_close, future_close)
                if aligned_return_pct is None:
                    continue
                selected_candidate_count += 1
                cost_pct = estimated_action_cost_pct(
                    action,
                    contract_market=self.settings.contract_market,
                    fee_pct=self.settings.estimated_fee_pct,
                    slippage_pct=self.settings.estimated_slippage_pct,
                )
                scored_candidates.append(
                    {
                        "run_id": int(row["run_id"]),
                        "symbol": symbol,
                        "action": action,
                        "score": float(item.get("score") or 0.0),
                        "setup_phase": setup_phase,
                        "higher_timeframe_phase": item.get("higher_timeframe_phase"),
                        "setup_model_label": (
                            setup_signal.get("label") if isinstance(setup_signal, dict) else None
                        ),
                        "setup_model_quality": (
                            setup_signal.get("quality") if isinstance(setup_signal, dict) else None
                        ),
                        "candidate_aligned_future_return_pct": aligned_return_pct,
                        "candidate_aligned_future_edge_pct": aligned_return_pct - cost_pct,
                        "reasons": reasons,
                    }
                )

        scored_candidates.sort(key=lambda item: float(item["score"]), reverse=True)
        top_rows = scored_candidates[:top_candidates]
        avg_edge = (
            sum(float(item["candidate_aligned_future_edge_pct"]) for item in top_rows) / len(top_rows)
            if top_rows
            else None
        )
        return {
            "label": label,
            "backtest_artifact_dir": str(backtest_dir),
            "db_path": str(backtest_dir / "qount.db"),
            "run_count": len(rows),
            "order_stats": self._order_stats(backtest_dir),
            "candidate_filter_hold_count": candidate_filter_hold_count,
            "ai_hold_count": ai_hold_count,
            "selected_or_candidate_like_scored_count": selected_candidate_count,
            "top_candidate_count": len(top_rows),
            "top_candidate_avg_future_edge_pct": avg_edge,
            "setup_model_label_counts": _counter_payload(setup_label_counts),
            "setup_model_quality_counts": _counter_payload(setup_quality_counts),
            "setup_phase_counts": _counter_payload(setup_phase_counts),
            "candidate_reason_counts": _counter_payload(candidate_reason_counts, limit=reason_limit),
            "traditional_pattern_label_counts": _counter_payload(traditional_pattern_counts, limit=reason_limit),
            "ai_hold_reason_counts": _counter_payload(ai_hold_reason_counts, limit=reason_limit),
            "top_candidates_by_score": top_rows,
            "_raw_counts": {
                "candidate_reasons": dict(candidate_reason_counts),
                "traditional_patterns": dict(traditional_pattern_counts),
                "ai_hold_reasons": dict(ai_hold_reason_counts),
            },
        }

    def run(
        self,
        *,
        artifact_dir: Path,
        symbols_filter: list[str] | tuple[str, ...] | None = None,
        horizon_bars: int = 6,
        top_candidates: int = 5,
        reason_limit: int = 10,
        include_traded_windows: bool = False,
    ) -> dict[str, Any]:
        if horizon_bars <= 0:
            raise ValueError(f"idle_window_diagnostic_invalid_horizon_bars:{horizon_bars}")
        normalized_symbols = (
            None if symbols_filter is None else {_normalized_symbol_key(symbol) for symbol in symbols_filter}
        )
        backtests = _discover_backtest_dirs(artifact_dir)
        windows: list[dict[str, Any]] = []
        skipped_traded = 0
        for label, backtest_dir in backtests:
            order_stats = self._order_stats(backtest_dir)
            traded = int(order_stats.get("paper_filled") or 0) > 0 or int(order_stats.get("paper_closed") or 0) > 0
            if traded and not include_traded_windows:
                skipped_traded += 1
                continue
            window = self._diagnose_backtest(
                label,
                backtest_dir,
                symbols_filter=normalized_symbols,
                horizon_bars=horizon_bars,
                top_candidates=top_candidates,
                reason_limit=reason_limit,
            )
            window["idle_window"] = not traded
            windows.append(window)

        aggregate_setup_label: Counter[str] = Counter()
        aggregate_setup_quality: Counter[str] = Counter()
        aggregate_setup_phase: Counter[str] = Counter()
        aggregate_reasons: Counter[str] = Counter()
        aggregate_patterns: Counter[str] = Counter()
        aggregate_ai_hold_reasons: Counter[str] = Counter()
        for window in windows:
            aggregate_setup_label.update(window["setup_model_label_counts"]["counts"])
            aggregate_setup_quality.update(window["setup_model_quality_counts"]["counts"])
            aggregate_setup_phase.update(window["setup_phase_counts"]["counts"])
            raw_counts = window.pop("_raw_counts", {})
            aggregate_reasons.update(raw_counts.get("candidate_reasons") or {})
            aggregate_patterns.update(raw_counts.get("traditional_patterns") or {})
            aggregate_ai_hold_reasons.update(raw_counts.get("ai_hold_reasons") or {})

        idle_windows = [window for window in windows if bool(window.get("idle_window"))]
        windows_with_positive_top_edge = sum(
            1
            for window in idle_windows
            if (window.get("top_candidate_avg_future_edge_pct") is not None and float(window["top_candidate_avg_future_edge_pct"]) > 0.0)
        )
        return {
            "version": "idle_window_diagnostic_v1",
            "generated_at": utc_now().isoformat(),
            "artifact_dir": str(artifact_dir.expanduser()),
            "symbols_filter": list(symbols_filter or []),
            "horizon_bars": horizon_bars,
            "top_candidates_per_window": top_candidates,
            "reason_limit": reason_limit,
            "include_traded_windows": include_traded_windows,
            "backtest_count": len(backtests),
            "window_count": len(windows),
            "idle_window_count": len(idle_windows),
            "skipped_traded_window_count": skipped_traded,
            "aggregate": {
                "candidate_filter_hold_count": sum(int(window["candidate_filter_hold_count"]) for window in windows),
                "ai_hold_count": sum(int(window["ai_hold_count"]) for window in windows),
                "selected_or_candidate_like_scored_count": sum(
                    int(window["selected_or_candidate_like_scored_count"])
                    for window in windows
                ),
                "windows_with_positive_top_candidate_avg_future_edge": windows_with_positive_top_edge,
                "positive_top_candidate_avg_future_edge_rate": _rate(windows_with_positive_top_edge, len(idle_windows)),
                "setup_model_label_counts": _counter_payload(aggregate_setup_label),
                "setup_model_quality_counts": _counter_payload(aggregate_setup_quality),
                "setup_phase_counts": _counter_payload(aggregate_setup_phase),
                "candidate_reason_counts": _counter_payload(aggregate_reasons, limit=reason_limit),
                "traditional_pattern_label_counts": _counter_payload(aggregate_patterns, limit=reason_limit),
                "ai_hold_reason_counts": _counter_payload(aggregate_ai_hold_reasons, limit=reason_limit),
            },
            "windows": windows,
            "promotion_note": "idle_window_diagnostic_only_not_candidate_gate",
        }
