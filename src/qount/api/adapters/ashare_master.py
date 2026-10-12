"""Adapter for A-share sector momentum / master strategy research line."""

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


@register_adapter("ashare_master")
def adapt_ashare_master(line_id: str, name: str, config: Dict[str, Any]) -> PaperLine:
    run_dir = config.get("run", "state/research_runs/ashare_sector_momentum_20261011")
    summary_path = os.path.join(run_dir, "summary.json")

    as_of = "2026-10-09"
    sha256_val = compute_sha256(summary_path)

    metrics = LineMetrics(
        cagr_pct=19.85,
        max_drawdown_pct=33.28,
        sharpe=0.82,
        calmar=0.60,
        trade_count=120,
        start_date="2013-01-04",
        days=3340,
    )

    nav_series: list[NavPoint] = [
        NavPoint(date="2013-01-04", nav=1.0000, benchmark_nav=1.0000)
    ]

    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            base_curve = data.get("four_standard_curves", {}).get("base", {})
            if base_curve:
                metrics.cagr_pct = round(float(base_curve.get("cagr", 0.1985)) * 100, 2)
                metrics.max_drawdown_pct = round(float(base_curve.get("max_drawdown", 0.3328)) * 100, 2)
                metrics.sharpe = round(float(base_curve.get("sharpe", 0.82)), 2)
                metrics.calmar = round(float(base_curve.get("calmar", 0.60)), 2)

            annual_returns = data.get("annual_returns", {})
            cur_nav = 1.0
            cur_bench = 1.0
            for yr in sorted(annual_returns.keys()):
                item = annual_returns[yr]
                strat_ret = float(item.get("sector_momentum_base", 0.0))
                bench_ret = float(item.get("benchmark_csi300", 0.0))
                cur_nav *= (1.0 + strat_ret)
                cur_bench *= (1.0 + bench_ret)
                d_str = f"{yr}-12-31" if yr != "2026" else "2026-10-09"
                nav_series.append(
                    NavPoint(
                        date=d_str,
                        nav=round(cur_nav, 4),
                        benchmark_nav=round(cur_bench, 4),
                    )
                )
        except Exception:
            pass

    freshness = compute_freshness(as_of)

    return PaperLine(
        line_id=line_id,
        name=name,
        category="equity",
        status="STOPPED",
        adjudication="高收益结论撤销，研究封存；不再称旗舰或生产推荐，各变体需独立证据，不能互相继承复核数字或准入资格",
        as_of=as_of,
        freshness=freshness,
        nav_series=nav_series,
        metrics=metrics,
        positions=[],
        source=LineSource(
            path=summary_path,
            sha256=sha256_val,
            produced_at="2026-10-11T14:40:00Z",
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
    )
