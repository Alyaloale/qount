from __future__ import annotations

from .models import AgentReport


ALLOWED_REPORT_STATUSES = frozenset({"ok", "blocked", "needs_research"})

FORBIDDEN_OUTPUT_PATTERNS: tuple[str, ...] = (
    "place order",
    "submit order",
    "market buy",
    "market sell",
    "limit buy",
    "limit sell",
    "target_weight",
    "target weight",
    "position_size",
    "set leverage",
    "increase leverage",
    "arm live",
    "enable live",
    "QOUNT_X4_LIVE_ENABLE=true",
    "QOUNT_LIVE_ENABLE=true",
    # Direct Chinese action language is blocked as well. Reports may describe
    # evidence and propose deterministic research, but must not issue an order
    # or change live risk controls in either language.
    "立即下单",
    "建议下单",
    "直接下单",
    "请下单",
    "立即买入",
    "建议买入",
    "直接买入",
    "请买入",
    "立即卖出",
    "建议卖出",
    "直接卖出",
    "请卖出",
    "立即开仓",
    "建议开仓",
    "直接开仓",
    "请开仓",
    "立即加仓",
    "建议加仓",
    "直接加仓",
    "请加仓",
    "立即减仓",
    "建议减仓",
    "直接减仓",
    "请减仓",
    "立即平仓",
    "建议平仓",
    "直接平仓",
    "请平仓",
    "立即做多",
    "建议做多",
    "直接做多",
    "请做多",
    "立即做空",
    "建议做空",
    "直接做空",
    "请做空",
    "直接开多",
    "直接开空",
    "设置杠杆",
    "提高杠杆",
    "增加杠杆",
    "启用实盘",
    "开启实盘",
    "恢复实盘",
    "启用交易",
    "开启交易",
    "恢复交易",
    "调整目标权重",
    "设置目标权重",
    "增加仓位",
    "提高仓位",
)


def find_forbidden_output(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(pattern for pattern in FORBIDDEN_OUTPUT_PATTERNS if pattern.lower() in lowered)


def validate_agent_report(report: AgentReport) -> tuple[str, ...]:
    errors: list[str] = []
    if report.status not in ALLOWED_REPORT_STATUSES:
        errors.append(f"invalid_status:{report.status}")
    if not report.role_id:
        errors.append("missing_role_id")
    if not report.task_id:
        errors.append("missing_task_id")
    if not report.summary:
        errors.append("missing_summary")
    serialized = " ".join(
        (
            report.summary,
            " ".join(report.findings),
            " ".join(report.proposals),
            " ".join(report.risks),
            report.raw_response or "",
        )
    )
    errors.extend(f"forbidden_output:{hit}" for hit in find_forbidden_output(serialized))
    return tuple(errors)
