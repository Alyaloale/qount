"""Adapter for Binance global macro strategy research line."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import compute_freshness, compute_sha256
from qount.api.schemas import (
    LineMetrics,
    LineSafety,
    LineSource,
    NavPoint,
    PaperLine,
)


@register_adapter("binance_macro")
def adapt_binance_macro(line_id: str, name: str, config: Dict[str, Any]) -> PaperLine:
    run_dir = config.get("run", "state/research_runs/binance_global_macro_20261011")
    summary_path = os.path.join(run_dir, "summary.json")

    as_of = "2026-06-30"
    sha256_val = compute_sha256(summary_path)

    metrics = LineMetrics(
        cagr_pct=41.29,
        max_drawdown_pct=36.63,
        sharpe=0.90,
        calmar=1.13,
        trade_count=156,
        start_date="2021-01-01",
        days=2007,
    )

    nav_series: list[NavPoint] = [
        NavPoint(date="2021-01-01", nav=1.0000, benchmark_nav=1.0000),
        NavPoint(date="2021-12-31", nav=1.0748, benchmark_nav=1.5982),
        NavPoint(date="2022-12-31", nav=1.2830, benchmark_nav=0.5562),
        NavPoint(date="2023-12-31", nav=3.6809, benchmark_nav=1.4241),
        NavPoint(date="2024-12-31", nav=5.2328, benchmark_nav=2.0620),
        NavPoint(date="2025-12-31", nav=6.5928, benchmark_nav=2.1530),
        NavPoint(date="2026-06-30", nav=6.6798, benchmark_nav=1.9976),
    ]

    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            base_curve = data.get("strategy_curves", {}).get("base", {})
            if base_curve:
                metrics.cagr_pct = round(float(base_curve.get("cagr", 41.29)), 2)
                metrics.max_drawdown_pct = round(float(base_curve.get("max_drawdown", 36.63)), 2)
                metrics.sharpe = round(float(base_curve.get("sharpe", 0.90)), 2)
                metrics.calmar = round(float(base_curve.get("calmar", 1.13)), 2)
                metrics.trade_count = int(base_curve.get("trades_count", 156))

            ds = data.get("dataset", {})
            metrics.days = int(ds.get("days", 2007))
        except Exception:
            pass

    freshness = compute_freshness(as_of)

    return PaperLine(
        line_id=line_id,
        name=name,
        category="macro",
        status="ARCHIVED",
        adjudication="未通过准入，研究封存；修复逻辑后利润集中、成本与撮合仍需逐情景绑定收据，不继续历史调参救援",
        as_of=as_of,
        freshness=freshness,
        nav_series=nav_series,
        metrics=metrics,
        positions=[],
        source=LineSource(
            path=summary_path,
            sha256=sha256_val,
            produced_at="2026-10-11T12:09:00Z",
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
    )
