from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any

from .artifacts import mirror_artifact_tree_if_external
from .backtest import BacktestService
from .backtest import HistoricalMarketGateway
from .backtest import parse_backtest_datetime
from .candidate_filter import CandidateFilter
from .journal import Journal
from .models import utc_now
from .settings import Settings
from .setup_model import SetupEdgeModelService
from .setup_model import SETUP_EDGE_MODEL_TIMEFRAME
from .trade_policy import timeframe_to_ms


@dataclass(frozen=True)
class WalkForwardWindow:
    label: str
    start: datetime
    end: datetime


def _sanitize_label(raw: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw.strip())
    return value.strip("-") or "window"


def parse_walk_forward_window(raw: str) -> WalkForwardWindow:
    if "=" in raw:
        label_raw, payload = raw.split("=", 1)
        label = _sanitize_label(label_raw)
    else:
        payload = raw
        label = ""
    parts = [part.strip() for part in payload.split(",", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("walk_forward_window_must_be_label_equals_start_comma_end")
    start = parse_backtest_datetime(parts[0])
    end = parse_backtest_datetime(parts[1])
    if end <= start:
        raise ValueError(f"walk_forward_window_end_must_be_after_start:{raw}")
    if not label:
        label = _sanitize_label(f"{start.strftime('%Y%m%dT%H%M')}-{end.strftime('%Y%m%dT%H%M')}")
    return WalkForwardWindow(label=label, start=start, end=end)


def _performance_summary(backtest_result: dict[str, Any]) -> dict[str, Any]:
    performance = backtest_result.get("performance") or {}
    order_stats = backtest_result.get("order_stats") or {}
    review_aggregate = ((backtest_result.get("review") or {}).get("aggregate") or {})
    review_overall = review_aggregate.get("overall") if isinstance(review_aggregate, dict) else None
    review_metrics = review_overall if isinstance(review_overall, dict) else review_aggregate
    review_by_research_slice_tag = (
        review_aggregate.get("by_research_slice_tag")
        if isinstance(review_aggregate, dict)
        else None
    )
    if not isinstance(review_by_research_slice_tag, dict):
        review_by_research_slice_tag = {}
    setup_model = backtest_result.get("setup_model") or {}
    backtest_window = setup_model.get("backtest_window") if isinstance(setup_model, dict) else None
    backtest_window = backtest_window if isinstance(backtest_window, dict) else {}
    return {
        "paper_filled": order_stats.get("paper_filled"),
        "paper_closed": order_stats.get("paper_closed"),
        "realized_return_pct": performance.get("realized_return_pct"),
        "unrealized_return_pct": performance.get("unrealized_return_pct"),
        "total_return_pct": performance.get("total_return_pct"),
        "open_unrealized_pnl_quote": performance.get("open_unrealized_pnl_quote"),
        "open_positions": performance.get("open_positions"),
        "max_drawdown_pct": performance.get("max_drawdown_pct"),
        "closed_trades": performance.get("closed_trades"),
        "wins": performance.get("wins"),
        "losses": performance.get("losses"),
        "reviewed": review_metrics.get("reviewed"),
        "review_avg_net_edge_pct": review_metrics.get("avg_net_edge_pct"),
        "review_good": review_metrics.get("good"),
        "review_bad": review_metrics.get("bad"),
        "review_flat": review_metrics.get("flat"),
        "review_missed_move": review_metrics.get("missed_move"),
        "review_missed_candidate_move": review_metrics.get("missed_candidate_move"),
        "review_missed_move_not_candidate_aligned": review_metrics.get("missed_move_not_candidate_aligned"),
        "review_avg_candidate_opportunity_edge_pct": review_metrics.get("avg_candidate_opportunity_edge_pct"),
        "review_by_research_slice_tag": review_by_research_slice_tag,
        "setup_model_oos_safe": backtest_window.get("oos_safe"),
    }


def _promotion_blockers(summary: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if summary.get("setup_model_oos_safe") is not True:
        blockers.append("setup_model_not_oos_safe")
    if int(summary.get("open_positions") or 0) > 0:
        blockers.append("open_position_remaining")
    realized_return_pct = summary.get("realized_return_pct")
    if realized_return_pct is None or float(realized_return_pct) <= 0.0:
        blockers.append("non_positive_realized_return")
    reviewed = int(summary.get("reviewed") or 0)
    review_avg_net_edge_pct = summary.get("review_avg_net_edge_pct")
    if reviewed > 0 and review_avg_net_edge_pct is not None and float(review_avg_net_edge_pct) <= 0.0:
        blockers.append("non_positive_review_edge")
    return blockers


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _aggregate_research_slice_tags(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count_fields = (
        "reviewed",
        "good",
        "good_hold",
        "bad",
        "flat",
        "missed_move",
        "actionable_reviewed",
        "hold_reviewed",
        "missed_candidate_move",
        "missed_move_not_candidate_aligned",
    )
    weighted_average_fields = (
        "avg_net_edge_pct",
        "avg_candidate_aligned_future_return_pct",
        "avg_candidate_opportunity_edge_pct",
    )
    accumulators: dict[str, dict[str, Any]] = {}
    for row in rows:
        backtest = row.get("backtest") or {}
        by_tag = backtest.get("review_by_research_slice_tag") or {}
        if not isinstance(by_tag, dict):
            continue
        for tag, summary in by_tag.items():
            if tag == "counts" or not isinstance(summary, dict):
                continue
            reviewed = _as_int(summary.get("reviewed"))
            if reviewed <= 0:
                continue
            accumulator = accumulators.setdefault(
                str(tag),
                {
                    "windows_with_samples": 0,
                    "windows_with_positive_avg_net_edge": 0,
                    "windows_with_negative_avg_net_edge": 0,
                    "windows_with_missed_candidate_move": 0,
                    "counts": {field: 0 for field in count_fields},
                    "weighted_sums": {field: 0.0 for field in weighted_average_fields},
                    "weights": {field: 0 for field in weighted_average_fields},
                },
            )
            accumulator["windows_with_samples"] += 1
            avg_net_edge_pct = _as_float_or_none(summary.get("avg_net_edge_pct"))
            if avg_net_edge_pct is not None and avg_net_edge_pct > 0.0:
                accumulator["windows_with_positive_avg_net_edge"] += 1
            if avg_net_edge_pct is not None and avg_net_edge_pct < 0.0:
                accumulator["windows_with_negative_avg_net_edge"] += 1
            if _as_int(summary.get("missed_candidate_move")) > 0:
                accumulator["windows_with_missed_candidate_move"] += 1
            for field in count_fields:
                accumulator["counts"][field] += _as_int(summary.get(field))
            for field in weighted_average_fields:
                value = _as_float_or_none(summary.get(field))
                if value is None:
                    continue
                accumulator["weighted_sums"][field] += value * reviewed
                accumulator["weights"][field] += reviewed

    tag_summaries: dict[str, Any] = {}
    for tag, accumulator in sorted(accumulators.items()):
        counts = dict(accumulator["counts"])
        reviewed = int(counts.get("reviewed") or 0)
        actionable_reviewed = int(counts.get("actionable_reviewed") or 0)
        summary = {
            "windows_with_samples": accumulator["windows_with_samples"],
            "windows_with_positive_avg_net_edge": accumulator["windows_with_positive_avg_net_edge"],
            "windows_with_negative_avg_net_edge": accumulator["windows_with_negative_avg_net_edge"],
            "windows_with_missed_candidate_move": accumulator["windows_with_missed_candidate_move"],
            **counts,
            "actionable_rate": None if reviewed == 0 else actionable_reviewed / reviewed,
            "win_rate": None if actionable_reviewed == 0 else int(counts.get("good") or 0) / actionable_reviewed,
        }
        for field in weighted_average_fields:
            weight = int(accumulator["weights"][field])
            summary[field] = None if weight == 0 else accumulator["weighted_sums"][field] / weight
        tag_summaries[tag] = summary

    return tag_summaries | {"counts": {tag: summary["reviewed"] for tag, summary in tag_summaries.items()}}


def _aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_filled = sum(int((row["backtest"] or {}).get("paper_filled") or 0) for row in rows)
    total_closed = sum(int((row["backtest"] or {}).get("paper_closed") or 0) for row in rows)
    total_reviewed = sum(int((row["backtest"] or {}).get("reviewed") or 0) for row in rows)
    total_review_missed_move = sum(int((row["backtest"] or {}).get("review_missed_move") or 0) for row in rows)
    total_review_missed_candidate_move = sum(
        int((row["backtest"] or {}).get("review_missed_candidate_move") or 0)
        for row in rows
    )
    total_review_missed_move_not_candidate_aligned = sum(
        int((row["backtest"] or {}).get("review_missed_move_not_candidate_aligned") or 0)
        for row in rows
    )
    realized_values = [
        float((row["backtest"] or {}).get("realized_return_pct"))
        for row in rows
        if (row["backtest"] or {}).get("realized_return_pct") is not None
    ]
    return {
        "oos_safe_windows": sum(1 for row in rows if (row["backtest"] or {}).get("setup_model_oos_safe") is True),
        "positive_realized_windows": sum(
            1
            for row in rows
            if (row["backtest"] or {}).get("realized_return_pct") is not None
            and float((row["backtest"] or {}).get("realized_return_pct")) > 0.0
        ),
        "windows_with_open_positions": sum(1 for row in rows if int((row["backtest"] or {}).get("open_positions") or 0) > 0),
        "total_paper_filled": total_filled,
        "total_paper_closed": total_closed,
        "total_reviewed": total_reviewed,
        "total_review_missed_move": total_review_missed_move,
        "total_review_missed_candidate_move": total_review_missed_candidate_move,
        "total_review_missed_move_not_candidate_aligned": total_review_missed_move_not_candidate_aligned,
        "windows_with_missed_candidate_move": sum(
            1
            for row in rows
            if int((row["backtest"] or {}).get("review_missed_candidate_move") or 0) > 0
        ),
        "sum_realized_return_pct": sum(realized_values),
        "avg_realized_return_pct": None if not realized_values else sum(realized_values) / len(realized_values),
        "by_research_slice_tag": _aggregate_research_slice_tags(rows),
    }


def _build_walk_forward_result(
    *,
    root: Path,
    rows: list[dict[str, Any]],
    symbols: tuple[str, ...],
    setup_phases: list[str] | None,
    train_lookback_days: int,
    horizon_bars: int,
    gap_bars: int,
    review_horizon_bars: int,
    review_threshold_pct: float,
    max_bars_per_window: int | None,
    complete: bool,
    settings: Settings,
    starting_quote: float | None,
    research_profile: str | None,
    holdout_role: str,
    ai_decision_cache_enable: bool,
    setup_model_version: str,
) -> dict[str, Any]:
    return {
        "mode": "walk_forward",
        "holdout_role": holdout_role,
        "artifact_dir": str(root),
        "generated_at": utc_now().isoformat(),
        "complete": complete,
        "symbols": list(symbols),
        "setup_phases": setup_phases,
        "train_lookback_days": train_lookback_days,
        "horizon_bars": horizon_bars,
        "gap_bars": gap_bars,
        "review_horizon_bars": review_horizon_bars,
        "review_threshold_pct": review_threshold_pct,
        "max_bars_per_window": max_bars_per_window,
        "window_count": len(rows),
        "aggregate": _aggregate_rows(rows),
        "windows": rows,
        "audit_context": {
            "rule_mode": settings.rule_mode,
            "market_type": settings.market_type,
            "symbols": list(symbols),
            "hourly_model_enable": settings.hourly_model_enable,
            "setup_model_enable": settings.setup_model_enable,
            "ai_temperature": settings.ai_temperature,
            "trailing_profit_arm_pct": settings.trailing_profit_arm_pct,
            "trailing_profit_retrace_pct": settings.trailing_profit_retrace_pct,
            "research_shadow_candidate_tags": list(settings.research_shadow_candidate_tags),
            "estimated_fee_pct": settings.estimated_fee_pct,
            "estimated_slippage_pct": settings.estimated_slippage_pct,
            "paper_starting_quote": settings.paper_starting_quote,
            "starting_quote_override": starting_quote,
            "research_profile": research_profile,
            "holdout_role": holdout_role,
            "ai_decision_cache_enable": ai_decision_cache_enable,
            "ai_decision_cache_dir": str(settings.ai_decision_cache_dir),
            "setup_model_version": setup_model_version,
        },
    }


def _model_count(train_result: dict[str, Any], min_samples: int) -> int:
    return sum(
        1
        for item in train_result.get("symbols", [])
        if isinstance(item, dict) and int(item.get("samples") or 0) >= max(min_samples, 8)
    )


def _summarize_candidate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "window_count": len(rows),
        "total_cycles": sum(_as_int((row.get("candidate") or {}).get("cycles")) for row in rows),
        "total_selected_cycles": sum(_as_int((row.get("candidate") or {}).get("selected_cycles")) for row in rows),
        "total_filtered_hold_cycles": sum(_as_int((row.get("candidate") or {}).get("filtered_hold_cycles")) for row in rows),
        "total_fresh_entry_selected": sum(_as_int((row.get("candidate") or {}).get("fresh_entry_selected")) for row in rows),
    }


class WalkForwardService:
    def __init__(
        self,
        settings: Settings,
        *,
        public_exchange: Any | None = None,
        orchestrator_factory: Any | None = None,
    ) -> None:
        self.settings = settings
        self.public_exchange = public_exchange
        self.orchestrator_factory = orchestrator_factory

    def _artifact_root(self, explicit: str | None) -> Path:
        if explicit:
            return Path(explicit).expanduser()
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        return self.settings.state_dir / "walk_forward" / stamp

    def _window_model_paths(self, root: Path, index: int, window: WalkForwardWindow) -> tuple[Path, Path]:
        window_dir = root / f"{index:02d}-{_sanitize_label(window.label)}"
        model_path = window_dir / (self.settings.setup_model_path.name or "setup_model.json")
        window_dir.mkdir(parents=True, exist_ok=True)
        return window_dir, model_path

    def _train_window_setup_model(
        self,
        *,
        symbols: tuple[str, ...],
        setup_phases: list[str] | None,
        train_lookback_days: int,
        horizon_bars: int,
        gap_bars: int,
        min_samples: int,
        ridge_alpha: float,
        split_higher_phase: bool,
        setup_model_version: str,
        window: WalkForwardWindow,
        model_path: Path,
    ) -> dict[str, Any]:
        timeframe_ms = timeframe_to_ms(SETUP_EDGE_MODEL_TIMEFRAME)
        training_end = window.start - timedelta(milliseconds=(max(horizon_bars, 0) + max(gap_bars, 0)) * timeframe_ms)
        train_settings = replace(
            self.settings,
            symbols=symbols,
            setup_model_enable=True,
            setup_model_path=model_path,
        )
        return SetupEdgeModelService(
            train_settings,
            public_exchange=self.public_exchange,
        ).train(
            symbols_filter=list(symbols),
            setup_phases=setup_phases,
            lookback_days=train_lookback_days,
            horizon_bars=horizon_bars,
            min_samples=min_samples,
            ridge_alpha=ridge_alpha,
            artifact_path=model_path,
            split_higher_phase=split_higher_phase,
            model_version=setup_model_version,
            training_end=training_end,
        )

    def run_setup_edge(
        self,
        *,
        windows: list[WalkForwardWindow],
        symbols_filter: list[str] | None,
        setup_phases: list[str] | None,
        train_lookback_days: int,
        horizon_bars: int,
        gap_bars: int,
        min_samples: int,
        ridge_alpha: float,
        split_higher_phase: bool,
        setup_model_version: str = "v1",
        artifact_dir: str | None = None,
        research_profile: str | None = None,
        holdout_role: str = "unknown",
    ) -> dict[str, Any]:
        if not windows:
            raise ValueError("setup_edge_walk_forward_requires_at_least_one_window")

        root = self._artifact_root(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        symbols = tuple(symbols_filter) if symbols_filter else self.settings.symbols
        rows: list[dict[str, Any]] = []
        for index, window in enumerate(windows, start=1):
            window_dir, model_path = self._window_model_paths(root, index, window)
            train_result = self._train_window_setup_model(
                symbols=symbols,
                setup_phases=setup_phases,
                train_lookback_days=train_lookback_days,
                horizon_bars=horizon_bars,
                gap_bars=gap_bars,
                min_samples=min_samples,
                ridge_alpha=ridge_alpha,
                split_higher_phase=split_higher_phase,
                setup_model_version=setup_model_version,
                window=window,
                model_path=model_path,
            )
            row = {
                "label": window.label,
                "start_utc": window.start.astimezone(timezone.utc).isoformat(),
                "end_utc": window.end.astimezone(timezone.utc).isoformat(),
                "holdout_role": holdout_role,
                "artifact_dir": str(window_dir),
                "model_path": str(model_path),
                "training": {
                    "training_cutoff_utc": train_result.get("training_cutoff_utc"),
                    "training_window": train_result.get("training_window"),
                    "trained_rows": train_result.get("symbols"),
                    "model_count": _model_count(train_result, min_samples),
                },
            }
            rows.append(row)
            partial = self._build_split_result(
                root=root,
                mode="setup_edge_walk_forward",
                rows=rows,
                symbols=symbols,
                setup_phases=setup_phases,
                train_lookback_days=train_lookback_days,
                horizon_bars=horizon_bars,
                gap_bars=gap_bars,
                min_samples=min_samples,
                ridge_alpha=ridge_alpha,
                split_higher_phase=split_higher_phase,
                setup_model_version=setup_model_version,
                complete=False,
                research_profile=research_profile,
                holdout_role=holdout_role,
            )
            (root / "setup_edge_walk_forward.partial.json").write_text(
                json.dumps(partial, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        result = self._build_split_result(
            root=root,
            mode="setup_edge_walk_forward",
            rows=rows,
            symbols=symbols,
            setup_phases=setup_phases,
            train_lookback_days=train_lookback_days,
            horizon_bars=horizon_bars,
            gap_bars=gap_bars,
            min_samples=min_samples,
            ridge_alpha=ridge_alpha,
            split_higher_phase=split_higher_phase,
            setup_model_version=setup_model_version,
            complete=True,
            research_profile=research_profile,
            holdout_role=holdout_role,
        )
        persistent_root = mirror_artifact_tree_if_external(self.settings, root, kind="setup-edge-walk-forward")
        if persistent_root is not None:
            result["persistent_artifact_dir"] = str(persistent_root)
        (root / "setup_edge_walk_forward.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if persistent_root is not None:
            (persistent_root / "setup_edge_walk_forward.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _build_split_result(
        self,
        *,
        root: Path,
        mode: str,
        rows: list[dict[str, Any]],
        symbols: tuple[str, ...],
        setup_phases: list[str] | None,
        train_lookback_days: int,
        horizon_bars: int,
        gap_bars: int,
        min_samples: int,
        ridge_alpha: float,
        split_higher_phase: bool,
        setup_model_version: str,
        complete: bool,
        research_profile: str | None,
        holdout_role: str,
    ) -> dict[str, Any]:
        aggregate: dict[str, Any] = {
            "window_count": len(rows),
            "total_model_count": sum(_as_int((row.get("training") or {}).get("model_count")) for row in rows),
        }
        if mode == "candidate_walk_forward":
            aggregate |= _summarize_candidate_rows(rows)
        return {
            "mode": mode,
            "holdout_role": holdout_role,
            "artifact_dir": str(root),
            "generated_at": utc_now().isoformat(),
            "complete": complete,
            "symbols": list(symbols),
            "setup_phases": setup_phases,
            "train_lookback_days": train_lookback_days,
            "horizon_bars": horizon_bars,
            "gap_bars": gap_bars,
            "min_samples": min_samples,
            "ridge_alpha": ridge_alpha,
            "split_higher_phase": split_higher_phase,
            "setup_model_version": setup_model_version,
            "aggregate": aggregate,
            "windows": rows,
            "audit_context": {
                "rule_mode": self.settings.rule_mode,
                "market_type": self.settings.market_type,
                "symbols": list(symbols),
                "hourly_model_enable": self.settings.hourly_model_enable,
                "setup_model_enable": self.settings.setup_model_enable,
                "research_profile": research_profile,
                "holdout_role": holdout_role,
                "setup_model_version": setup_model_version,
            },
        }

    def _candidate_window_summary(
        self,
        *,
        settings: Settings,
        window: WalkForwardWindow,
        max_bars_per_window: int | None,
    ) -> dict[str, Any]:
        journal = Journal(settings.db_path)
        journal.ensure_schema()
        candidate_filter = CandidateFilter(settings, journal)
        market_gateway = HistoricalMarketGateway(
            settings,
            journal,
            start=window.start,
            end=window.end,
            review_horizon_bars=0,
            max_bars=max_bars_per_window,
            public_exchange=self.public_exchange,
        )
        status_counts: Counter[str] = Counter()
        selected_symbol_counts: Counter[str] = Counter()
        reason_counts: Counter[str] = Counter()
        setup_phase_counts: Counter[str] = Counter()
        setup_model_quality_counts: Counter[str] = Counter()
        fresh_entry_selected = 0
        cycles = 0

        while market_gateway.has_next():
            bundle = market_gateway.next_bundle()
            candidate_result = candidate_filter.apply(bundle)
            cycles += 1
            status_counts[candidate_result.status] += 1
            selected_symbols = set(candidate_result.summary.get("selected_symbols") or [])
            for symbol_name in selected_symbols:
                selected_symbol_counts[str(symbol_name)] += 1
            for item in candidate_result.summary.get("symbols", []):
                if not isinstance(item, dict):
                    continue
                for reason in item.get("reasons") or []:
                    reason_counts[str(reason)] += 1
                setup_phase = item.get("setup_phase")
                if setup_phase:
                    setup_phase_counts[str(setup_phase)] += 1
                setup_model_signal = item.get("setup_model_signal")
                if isinstance(setup_model_signal, dict):
                    setup_model_quality_counts[str(setup_model_signal.get("quality") or "unknown")] += 1
                if item.get("symbol") in selected_symbols and not bool(item.get("manage_only")) and item.get("setup_phase"):
                    fresh_entry_selected += 1

        return {
            "cycles": cycles,
            "selected_cycles": int(status_counts.get("selected", 0)),
            "filtered_hold_cycles": int(status_counts.get("filtered_hold", 0)),
            "fresh_entry_selected": fresh_entry_selected,
            "selected_symbol_counts": dict(selected_symbol_counts.most_common()),
            "reason_counts": dict(reason_counts.most_common(20)),
            "setup_phase_counts": dict(setup_phase_counts.most_common()),
            "setup_model_quality_counts": dict(setup_model_quality_counts.most_common()),
        }

    def run_candidate(
        self,
        *,
        windows: list[WalkForwardWindow],
        symbols_filter: list[str] | None,
        setup_phases: list[str] | None,
        train_lookback_days: int,
        horizon_bars: int,
        gap_bars: int,
        min_samples: int,
        ridge_alpha: float,
        split_higher_phase: bool,
        setup_model_version: str = "v1",
        max_bars_per_window: int | None = None,
        artifact_dir: str | None = None,
        research_profile: str | None = None,
        holdout_role: str = "unknown",
    ) -> dict[str, Any]:
        if not windows:
            raise ValueError("candidate_walk_forward_requires_at_least_one_window")

        root = self._artifact_root(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        symbols = tuple(symbols_filter) if symbols_filter else self.settings.symbols
        rows: list[dict[str, Any]] = []
        for index, window in enumerate(windows, start=1):
            window_dir, model_path = self._window_model_paths(root, index, window)
            train_result = self._train_window_setup_model(
                symbols=symbols,
                setup_phases=setup_phases,
                train_lookback_days=train_lookback_days,
                horizon_bars=horizon_bars,
                gap_bars=gap_bars,
                min_samples=min_samples,
                ridge_alpha=ridge_alpha,
                split_higher_phase=split_higher_phase,
                setup_model_version=setup_model_version,
                window=window,
                model_path=model_path,
            )
            candidate_dir = window_dir / "candidate"
            candidate_settings = replace(
                self.settings,
                mode="paper",
                live_enable=False,
                symbols=symbols,
                setup_model_enable=True,
                setup_model_path=model_path,
                state_dir=candidate_dir,
                snapshot_dir=candidate_dir / "snapshots",
                decision_dir=candidate_dir / "decisions",
                log_dir=candidate_dir / "logs",
                db_path=candidate_dir / "qount.db",
                notify_webhook_url=None,
            )
            candidate_settings.ensure_directories()
            candidate_summary = self._candidate_window_summary(
                settings=candidate_settings,
                window=window,
                max_bars_per_window=max_bars_per_window,
            )
            row = {
                "label": window.label,
                "start_utc": window.start.astimezone(timezone.utc).isoformat(),
                "end_utc": window.end.astimezone(timezone.utc).isoformat(),
                "holdout_role": holdout_role,
                "artifact_dir": str(window_dir),
                "model_path": str(model_path),
                "training": {
                    "training_cutoff_utc": train_result.get("training_cutoff_utc"),
                    "training_window": train_result.get("training_window"),
                    "trained_rows": train_result.get("symbols"),
                    "model_count": _model_count(train_result, min_samples),
                },
                "candidate": candidate_summary,
            }
            rows.append(row)
            partial = self._build_split_result(
                root=root,
                mode="candidate_walk_forward",
                rows=rows,
                symbols=symbols,
                setup_phases=setup_phases,
                train_lookback_days=train_lookback_days,
                horizon_bars=horizon_bars,
                gap_bars=gap_bars,
                min_samples=min_samples,
                ridge_alpha=ridge_alpha,
                split_higher_phase=split_higher_phase,
                setup_model_version=setup_model_version,
                complete=False,
                research_profile=research_profile,
                holdout_role=holdout_role,
            )
            (root / "candidate_walk_forward.partial.json").write_text(
                json.dumps(partial, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        result = self._build_split_result(
            root=root,
            mode="candidate_walk_forward",
            rows=rows,
            symbols=symbols,
            setup_phases=setup_phases,
            train_lookback_days=train_lookback_days,
            horizon_bars=horizon_bars,
            gap_bars=gap_bars,
            min_samples=min_samples,
            ridge_alpha=ridge_alpha,
            split_higher_phase=split_higher_phase,
            setup_model_version=setup_model_version,
            complete=True,
            research_profile=research_profile,
            holdout_role=holdout_role,
        )
        persistent_root = mirror_artifact_tree_if_external(self.settings, root, kind="candidate-walk-forward")
        if persistent_root is not None:
            result["persistent_artifact_dir"] = str(persistent_root)
        (root / "candidate_walk_forward.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if persistent_root is not None:
            (persistent_root / "candidate_walk_forward.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def run(
        self,
        *,
        windows: list[WalkForwardWindow],
        symbols_filter: list[str] | None,
        setup_phases: list[str] | None,
        train_lookback_days: int,
        horizon_bars: int,
        gap_bars: int,
        min_samples: int,
        ridge_alpha: float,
        split_higher_phase: bool,
        review_horizon_bars: int,
        review_threshold_pct: float,
        starting_quote: float | None,
        max_bars_per_window: int | None = None,
        artifact_dir: str | None = None,
        research_profile: str | None = None,
        holdout_role: str = "unknown",
        ai_decision_cache_enable: bool = False,
        setup_model_version: str = "v1",
    ) -> dict[str, Any]:
        if not windows:
            raise ValueError("walk_forward_requires_at_least_one_window")

        root = self._artifact_root(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        timeframe_ms = timeframe_to_ms(SETUP_EDGE_MODEL_TIMEFRAME)
        symbols = tuple(symbols_filter) if symbols_filter else self.settings.symbols

        rows: list[dict[str, Any]] = []
        for index, window in enumerate(windows, start=1):
            window_dir = root / f"{index:02d}-{_sanitize_label(window.label)}"
            model_path = window_dir / (self.settings.setup_model_path.name or "setup_model.json")
            backtest_dir = window_dir / "backtest"
            window_dir.mkdir(parents=True, exist_ok=True)

            training_end = window.start - timedelta(milliseconds=(max(horizon_bars, 0) + max(gap_bars, 0)) * timeframe_ms)
            train_settings = replace(
                self.settings,
                symbols=symbols,
                setup_model_enable=True,
                setup_model_path=model_path,
            )
            train_result = SetupEdgeModelService(
                train_settings,
                public_exchange=self.public_exchange,
            ).train(
                symbols_filter=list(symbols),
                setup_phases=setup_phases,
                lookback_days=train_lookback_days,
                horizon_bars=horizon_bars,
                min_samples=min_samples,
                ridge_alpha=ridge_alpha,
                artifact_path=model_path,
                split_higher_phase=split_higher_phase,
                model_version=setup_model_version,
                training_end=training_end,
            )

            backtest_settings = replace(
                self.settings,
                symbols=symbols,
                setup_model_enable=True,
                setup_model_path=model_path,
            )
            backtest_result = BacktestService(
                backtest_settings,
                public_exchange=self.public_exchange,
                orchestrator_factory=self.orchestrator_factory,
            ).run(
                start=window.start,
                end=window.end,
                review_horizon_bars=review_horizon_bars,
                review_threshold_pct=review_threshold_pct,
                starting_quote=starting_quote,
                max_bars=max_bars_per_window,
                artifact_dir=str(backtest_dir),
                research_profile=research_profile,
                holdout_role=holdout_role,
                ai_decision_cache_enable=ai_decision_cache_enable,
                mirror_external_artifact_dir=False,
            )
            summary = _performance_summary(backtest_result)
            row = {
                "label": window.label,
                "start_utc": window.start.astimezone(timezone.utc).isoformat(),
                "end_utc": window.end.astimezone(timezone.utc).isoformat(),
                "holdout_role": holdout_role,
                "artifact_dir": str(window_dir),
                "model_path": str(model_path),
                "backtest_artifact_dir": str(backtest_dir),
                "training": {
                    "training_cutoff_utc": train_result.get("training_cutoff_utc"),
                    "training_window": train_result.get("training_window"),
                    "trained_rows": train_result.get("symbols"),
                    "model_count": sum(
                        1
                        for item in train_result.get("symbols", [])
                        if isinstance(item, dict) and int(item.get("samples") or 0) >= max(min_samples, 8)
                    ),
                },
                "backtest": summary,
                "promotion_blockers": _promotion_blockers(summary),
            }
            rows.append(row)
            partial = _build_walk_forward_result(
                root=root,
                rows=rows,
                symbols=symbols,
                setup_phases=setup_phases,
                train_lookback_days=train_lookback_days,
                horizon_bars=horizon_bars,
                gap_bars=gap_bars,
                review_horizon_bars=review_horizon_bars,
                review_threshold_pct=review_threshold_pct,
                max_bars_per_window=max_bars_per_window,
                complete=False,
                settings=self.settings,
                starting_quote=starting_quote,
                research_profile=research_profile,
                holdout_role=holdout_role,
                ai_decision_cache_enable=ai_decision_cache_enable,
                setup_model_version=setup_model_version,
            )
            (root / "walk_forward.partial.json").write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")

        result = _build_walk_forward_result(
            root=root,
            rows=rows,
            symbols=symbols,
            setup_phases=setup_phases,
            train_lookback_days=train_lookback_days,
            horizon_bars=horizon_bars,
            gap_bars=gap_bars,
            review_horizon_bars=review_horizon_bars,
            review_threshold_pct=review_threshold_pct,
            max_bars_per_window=max_bars_per_window,
            complete=True,
            settings=self.settings,
            starting_quote=starting_quote,
            research_profile=research_profile,
            holdout_role=holdout_role,
            ai_decision_cache_enable=ai_decision_cache_enable,
            setup_model_version=setup_model_version,
        )
        persistent_root = mirror_artifact_tree_if_external(self.settings, root, kind="walk-forward")
        if persistent_root is not None:
            result["persistent_artifact_dir"] = str(persistent_root)
        (root / "walk_forward.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if persistent_root is not None:
            (persistent_root / "walk_forward.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
