"""Adapter for Binance global macro strategy research line."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import compute_freshness, compute_sha256, unavailable_line
from qount.api.schemas import (
    LineMetrics,
    LineSafety,
    LineSource,
    NavPoint,
    PaperLine,
)


_ADJUDICATION = (
    "未通过准入，研究封存；修复逻辑后利润集中、成本与撮合仍需逐情景绑定收据，不继续历史调参救援"
)


@register_adapter("binance_macro")
def adapt_binance_macro(line_id: str, name: str, config: Dict[str, Any]) -> PaperLine:
    run_dir = config.get("run", "state/research_runs/binance_global_macro_20261011")
    summary_path = os.path.join(run_dir, "summary.json")

    if not os.path.isfile(summary_path):
        return unavailable_line(
            line_id,
            name,
            "macro",
            summary_path,
            "SOURCE_NOT_FOUND: Binance macro summary.json is absent; no performance figures are reported.",
            _ADJUDICATION,
            lifecycle_status="ARCHIVED",
        )

    try:
        with open(summary_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        base_curve = data["strategy_curves"]["base"]
        dataset = data["dataset"]
        period_start, separator, period_end = str(dataset["period"]).partition(" to ")
        yearly_breakdown = data["yearly_breakdown"]
        initial_equity = float(yearly_breakdown[min(yearly_breakdown)]["start_equity"])
        if not separator or not yearly_breakdown or initial_equity <= 0:
            raise ValueError("summary does not contain a usable period and equity curve")

        nav_series = []
        for year in sorted(yearly_breakdown):
            row = yearly_breakdown[year]
            end_equity = float(row["end_equity"])
            point_date = period_end if year == max(yearly_breakdown) else f"{year}-12-31"
            nav_series.append(
                NavPoint(
                    date=point_date,
                    nav=round(end_equity / initial_equity, 4),
                )
            )

        metrics = LineMetrics(
            cagr_pct=round(float(base_curve["cagr"]), 2),
            # The source summary does not provide a dated daily NAV path here. Do not expose
            # daily drawdown-derived metrics alongside annual observations.
            max_drawdown_pct=None,
            sharpe=round(float(base_curve["sharpe"]), 2),
            calmar=None,
            trade_count=int(base_curve["trades_count"]),
            start_date=period_start,
            days=int(dataset["days"]),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        code = "SOURCE_UNREADABLE" if isinstance(exc, (OSError, json.JSONDecodeError)) else "SUMMARY_EMPTY"
        return unavailable_line(
            line_id,
            name,
            "macro",
            summary_path,
            f"{code}: Binance macro summary could not provide a complete base curve ({type(exc).__name__}).",
            _ADJUDICATION,
            lifecycle_status="ARCHIVED",
        )

    return PaperLine(
        line_id=line_id,
        name=name,
        category="macro",
        status="ARCHIVED",
        adjudication=_ADJUDICATION,
        as_of=period_end,
        freshness=compute_freshness(period_end),
        curve_granularity="YEARLY",
        nav_series=nav_series,
        metrics=metrics,
        positions=[],
        position_status="NOT_APPLICABLE",
        source=LineSource(
            path=summary_path,
            sha256=compute_sha256(summary_path),
            produced_at=None,
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
    )
