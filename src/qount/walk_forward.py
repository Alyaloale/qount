from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any

from .backtest import BacktestService
from .backtest import parse_backtest_datetime
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


def _aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_filled = sum(int((row["backtest"] or {}).get("paper_filled") or 0) for row in rows)
    total_closed = sum(int((row["backtest"] or {}).get("paper_closed") or 0) for row in rows)
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
        "sum_realized_return_pct": sum(realized_values),
        "avg_realized_return_pct": None if not realized_values else sum(realized_values) / len(realized_values),
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
) -> dict[str, Any]:
    return {
        "mode": "walk_forward",
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
            "estimated_fee_pct": settings.estimated_fee_pct,
            "estimated_slippage_pct": settings.estimated_slippage_pct,
            "paper_starting_quote": settings.paper_starting_quote,
            "starting_quote_override": starting_quote,
            "research_profile": research_profile,
        },
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
        return self.settings.project_root / "state" / "walk_forward" / stamp

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
            )
            summary = _performance_summary(backtest_result)
            row = {
                "label": window.label,
                "start_utc": window.start.astimezone(timezone.utc).isoformat(),
                "end_utc": window.end.astimezone(timezone.utc).isoformat(),
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
        )
        (root / "walk_forward.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
