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
