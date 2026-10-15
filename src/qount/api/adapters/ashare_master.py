"""Adapter for A-share sector momentum / master strategy research line."""

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
    "高收益结论撤销，研究封存；不再称旗舰或生产推荐，各变体需独立证据，不能互相继承复核数字或准入资格"
)


@register_adapter("ashare_master")
def adapt_ashare_master(line_id: str, name: str, config: Dict[str, Any]) -> PaperLine:
    run_dir = config.get("run", "state/research_runs/ashare_sector_momentum_20261011")
    summary_path = os.path.join(run_dir, "summary.json")

    if not os.path.isfile(summary_path):
        return unavailable_line(
            line_id,
            name,
            "equity",
            summary_path,
            "SOURCE_NOT_FOUND: A-share summary.json is absent; no performance figures are reported.",
            _ADJUDICATION,
            lifecycle_status="STOPPED",
        )

    try:
        with open(summary_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        base_curve = data["four_standard_curves"]["base"]
        annual_returns = data["annual_returns"]
        range_start, separator, range_tail = str(data["data_range"]).partition(" to ")
        range_end = range_tail.split(" ", 1)[0]
        days = int(range_tail.split("(", 1)[1].split(" ", 1)[0])
        if not separator or not annual_returns:
            raise ValueError("summary does not contain a usable date range and annual returns")

        nav = 1.0
        benchmark_nav = 1.0
        nav_series = [NavPoint(date=range_start, nav=nav, benchmark_nav=benchmark_nav)]
        for year in sorted(annual_returns):
            item = annual_returns[year]
            nav *= 1.0 + float(item["sector_momentum_base"])
            benchmark_nav *= 1.0 + float(item["benchmark_csi300"])
            point_date = range_end if year == max(annual_returns) else f"{year}-12-31"
            nav_series.append(
                NavPoint(
                    date=point_date,
                    nav=round(nav, 4),
                    benchmark_nav=round(benchmark_nav, 4),
                )
            )

        metrics = LineMetrics(
            cagr_pct=round(float(base_curve["cagr"]) * 100, 2),
            max_drawdown_pct=None,
            sharpe=round(float(base_curve["sharpe"]), 2),
            calmar=None,
            start_date=range_start,
            days=days,
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError) as exc:
        code = "SOURCE_UNREADABLE" if isinstance(exc, (OSError, json.JSONDecodeError)) else "SUMMARY_EMPTY"
        return unavailable_line(
            line_id,
            name,
            "equity",
            summary_path,
            f"{code}: A-share summary could not provide a complete base curve ({type(exc).__name__}).",
            _ADJUDICATION,
            lifecycle_status="STOPPED",
        )

    return PaperLine(
        line_id=line_id,
        name=name,
        category="equity",
        status="STOPPED",
        adjudication=_ADJUDICATION,
        as_of=range_end,
        freshness=compute_freshness(range_end),
        curve_granularity="YEARLY",
        nav_series=nav_series,
        metrics=metrics,
        positions=[],
        position_status="NOT_APPLICABLE",
        source=LineSource(
            path=summary_path,
            sha256=compute_sha256(summary_path),
            produced_at=data.get("timestamp"),
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
    )
