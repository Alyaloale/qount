"""Adapter for the personal trading assistant research line."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from qount.api.adapters import register_adapter
from qount.api.adapters.utils import compute_freshness, compute_sha256, format_date_str
from qount.api.schemas import (
    LineMetrics,
    LineSafety,
    LineSource,
    NavPoint,
    PaperLine,
    PositionItem,
)


@register_adapter("personal_assistant")
def adapt_personal_assistant(line_id: str, name: str, config: Dict[str, Any]) -> PaperLine:
    run_dir = config.get("run", "state/research_runs/personal_assistant_reconciled_20261012")
    summary_path = os.path.join(run_dir, "summary.json")
    replay_path = os.path.join(run_dir, "baseline-replay.json")

    as_of = "2026-10-09"
    produced_at = None
    sha256_val = compute_sha256(summary_path)

    metrics = LineMetrics(
        cagr_pct=12.05,
        max_drawdown_pct=28.16,
        calmar=0.43,
        trade_count=38,
        start_date="2013-05-15",
        days=3256,
        ytd_return_pct=11.6,
    )
    positions = [
        PositionItem(symbol="513100.SH", weight=1.0, entry_date="2026-04-24")
    ]

    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_data = json.load(f)
            produced_at = summary_data.get("generated_at")
            asset_513100 = summary_data.get("assets", {}).get("513100.SH", {})
            baselines = asset_513100.get("baselines", [])
            ma120 = next((b for b in baselines if b.get("model_name") == "MA120_Band1.5pct"), None)
            if ma120:
                metrics.cagr_pct = round(float(ma120.get("cagr_pct", 12.05)), 2)
                metrics.max_drawdown_pct = round(float(ma120.get("max_drawdown_pct", 28.16)), 2)
                metrics.calmar = round(float(ma120.get("calmar_ratio", 0.43)), 2)
                metrics.trade_count = int(ma120.get("trade_count", 38))
                metrics.days = int(ma120.get("trading_days", 3256))
                if ma120.get("start_date"):
                    metrics.start_date = format_date_str(str(ma120["start_date"]))
                if ma120.get("end_date"):
                    as_of = format_date_str(str(ma120["end_date"]))
        except Exception:
            pass

    nav_series: list[NavPoint] = []
    if os.path.exists(replay_path):
        try:
            with open(replay_path, "r", encoding="utf-8") as f:
                replay_data = json.load(f)
            ma120_replay = replay_data.get("513100.SH", {}).get("MA120_Band1.5pct", {})
            bh_replay = replay_data.get("000300.SH", {}).get("Buy_and_Hold", {})

            ma120_nav_list = ma120_replay.get("nav", [])
            bh_nav_list = bh_replay.get("nav", [])
            bh_map = {row[0]: float(row[1]) for row in bh_nav_list if len(row) >= 2}

            # Downsample if more than 500 points to keep payload snappy, but retain first and last
            step = max(1, len(ma120_nav_list) // 400)
            sampled_rows = [ma120_nav_list[i] for i in range(0, len(ma120_nav_list), step)]
            if ma120_nav_list and sampled_rows[-1] != ma120_nav_list[-1]:
                sampled_rows.append(ma120_nav_list[-1])

            first_val = float(sampled_rows[0][1]) if sampled_rows else 1000000.0
            bh_first = bh_map.get(sampled_rows[0][0], 1000000.0) if sampled_rows else 1000000.0

            for row in sampled_rows:
                d_str = format_date_str(row[0])
                nav_val = round(float(row[1]) / first_val, 4)
                bench_val = round(bh_map.get(row[0], bh_first) / bh_first, 4) if bh_first > 0 else 1.0
                nav_series.append(NavPoint(date=d_str, nav=nav_val, benchmark_nav=bench_val))
        except Exception:
            pass

    freshness = compute_freshness(as_of)

    return PaperLine(
        line_id=line_id,
        name=name,
        category="assistant",
        status="ACTIVE_PAPER",
        adjudication="大周期趋势择时已完成S1时钟/测试与S2调和基线；日频收盘复盘已闭合INCOMPLETE_BAR并交付确定性日报；无实盘下单授权",
        as_of=as_of,
        freshness=freshness,
        nav_series=nav_series,
        metrics=metrics,
        positions=positions,
        source=LineSource(
            path=summary_path,
            sha256=sha256_val,
            produced_at=produced_at,
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
    )
