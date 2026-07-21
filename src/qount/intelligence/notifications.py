"""Notification projection for daily intelligence reports."""

from __future__ import annotations

from qount.notifications import AlertEvent

from .contracts import DailyIntelligenceReport


def alert_from_daily_intelligence(
    report: DailyIntelligenceReport,
) -> AlertEvent:
    report.validate()
    severity = {
        "clear": "INFO",
        "attention_required": "WARNING",
        "incomplete": "WARNING",
    }[report.status]
    market = report.market_pulse["symbols"]
    changes = ", ".join(
        f"{row['symbol']} {float(row['change_24h_pct']):+.2f}%"
        for row in market
    )
    summary = (
        f"{report.executive_summary} 行情：{changes}。"
        f"已验证来源 {len(report.sources)} 条，"
        f"研究建议 {len(report.research_proposals)} 条。"
    )[:1_000]
    return AlertEvent.create(
        severity=severity,
        category="daily_intelligence",
        title=f"Qount 每日情报复盘：{report.report_date}",
        summary=summary,
        occurred_at=report.created_at,
        source_type="intelligence",
        source_id=report.report_id,
        source_hash=report.report_hash,
        dedupe_key=f"daily_intelligence:{report.report_date}:{report.report_id}",
        trace_id_value=report.report_id,
    )


__all__ = ["alert_from_daily_intelligence"]
