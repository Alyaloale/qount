"""Observe the existing macro timer/receipt and enqueue incidents, never orders."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from qount.contracts import canonical_hash
from qount.strategies.macro_1atr import STRATEGY_ID

UNITS = ("qount-1atr-auto.timer", "qount-1atr-auto.service", "qount-notification-retry.service")
CATEGORY = "macro_execution"


def _reason(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)?", value) else "execution_blocked"


def _record_incident(runtime, path):
    # Imports and writes remain in the independent observer, outside execution.
    from qount.notifications.contracts import AlertEvent
    from qount.notifications.store import NotificationStore

    if runtime["state"] == "HALTED":
        return "SUPPRESSED_OWNER_HALT"
    store = NotificationStore(Path(path), busy_timeout_ms=1000)
    rows = store.verified_rows()
    attempted = [job for job in rows["jobs"]
                 if job["channel"] == "openclaw_weixin" and job.get("last_attempt_at")]
    runtime["notification_delivery"] = dict(status="NO_ATTEMPTS", last_attempt_at=None,
                                            last_delivered_at=None, last_error=None)
    if attempted:
        latest = max(attempted, key=lambda job: datetime.fromisoformat(job["last_attempt_at"].replace("Z", "+00:00")))
        error = latest.get("last_error")
        safe_error = error if isinstance(error, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?::-?[A-Za-z0-9_]+)?", error) else None
        runtime["notification_delivery"] = dict(
            status="ACCEPTED_BY_PROVIDER" if latest["status"] == "DELIVERED" else "LAST_ATTEMPT_FAILED" if error else "UNKNOWN",
            last_attempt_at=latest["last_attempt_at"], last_error=safe_error,
            last_delivered_at=max((job["delivered_at"] for job in attempted if job.get("delivered_at")), default=None))
    active = [AlertEvent(**payload) for key, payload in rows["events"].items()
              if payload["source_type"] == "system" and payload["category"] == CATEGORY
              and rows["states"][key]["status"] == "OPEN"]
    stamp = runtime["observed_at"]
    reason = runtime["reason"]
    if reason:
        source = canonical_hash(dict(strategy_id=STRATEGY_ID, reason=reason))
        event = next((event for event in active if event.source_id == source), None)
        if event is None:
            critical = any(word in reason for word in ("protection", "stop", "exit", "position", "submission_unknown"))
            event = AlertEvent.create(
                severity="CRITICAL" if critical else "WARNING", category=CATEGORY,
                title="QOUNT 宏观实盘需要检查",
                summary=f"状态 {runtime['state']}；原因 {reason}。请核对实盘页面、真实仓位和保护单。",
                occurred_at=stamp, source_type="system", source_id=source,
                source_hash=canonical_hash(dict(reason=reason, observed_at=stamp)),
                dedupe_key=f"macro:{reason}:{stamp}")
        store.enqueue(event, channels=("openclaw_weixin",), recorded_at=stamp)
        keep = (event.alert_id,)
    else:
        keep = ()
        if active:
            source = canonical_hash(dict(recovered=sorted(e.alert_id for e in active)))
            event = AlertEvent.create(
                severity="INFO", category="macro_execution_recovery",
                title="QOUNT 宏观周期检查已恢复",
                summary="最新周期收据和自动定时器恢复正常；成交及保护状态仍以各自核对结果为准。",
                occurred_at=stamp, source_type="system", source_id=source,
                source_hash=canonical_hash(dict(recovered=source, observed_at=stamp)),
                dedupe_key=f"macro:recovered:{source}")
            store.enqueue(event, channels=("openclaw_weixin",), recorded_at=stamp)
    store.resolve_superseded_alerts(active_alert_ids=keep, source_type="system",
                                   categories=(CATEGORY,), resolved_at=stamp)
    return "INCIDENT_RECORDED" if reason else "RECOVERY_RECORDED" if active else "OK"


def collect_macro_runtime(result_path, halt_path, *, notification_store=None, now=None, runner=None):
    """Read local systemd and a receipt; optionally enqueue, without sending."""
    now = now or datetime.now(timezone.utc)
    runner = runner or subprocess.run
    runtime = dict(observed_at=now.isoformat(), strategy_id=STRATEGY_ID,
                   state="UNKNOWN", reason="runtime_observation_unavailable",
                   halted=Path(halt_path).exists(), units={}, last_result_at=None)
    try:
        proc = runner(["systemctl", "show", *UNITS, "-p", "Id", "-p", "ActiveState",
                       "-p", "SubState", "-p", "Result", "-p", "UnitFileState"],
                      capture_output=True, text=True, timeout=3, check=True)
        for block in proc.stdout.strip().split("\n\n"):
            fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            identity = fields.pop("Id", None)
            if identity in UNITS:
                runtime["units"][identity] = fields
        if set(runtime["units"]) != set(UNITS):
            raise ValueError("runtime_units_incomplete")
        payload = json.loads(Path(result_path).read_text())
        if payload.get("strategy_id") != STRATEGY_ID or payload.get("execution_mode") != "auto_live":
            raise ValueError("runtime_receipt_identity_invalid")
        created = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("runtime_receipt_timezone_missing")
        age = (now-created).total_seconds()
        runtime.update(last_result_at=payload["created_at"], result_age_seconds=age)
        timer, service = (runtime["units"][unit] for unit in UNITS[:2])
        if runtime["halted"]:
            runtime.update(state="HALTED", reason=None)
        elif timer["ActiveState"] != "active":
            runtime.update(state="DISABLED", reason="auto_timer_not_active")
        elif payload.get("auto_action") == "BLOCKED":
            runtime.update(state="BLOCKED", reason=_reason(payload.get("execution_blocker")))
        elif service.get("ActiveState") == "failed" or service.get("Result") not in {"success", ""}:
            runtime.update(state="FAILED", reason="auto_service_failed")
        elif not -60 <= age <= 3900:
            runtime.update(state="STALE", reason="auto_receipt_stale_or_invalid")
        elif payload.get("orders_authorized") is not True:
            runtime.update(state="UNKNOWN", reason="execution_receipt_not_authorized")
        else:
            runtime.update(state="AUTO", reason=None)
    except Exception as exc:
        runtime["observation_error"] = type(exc).__name__
    if runtime["halted"]:
        runtime.update(state="HALTED", reason=None)
    runtime["notification_enqueue_status"] = "NOT_CONFIGURED"
    if notification_store:
        try:
            runtime["notification_enqueue_status"] = _record_incident(runtime, notification_store)
        except Exception as exc:
            runtime["notification_enqueue_status"] = f"ERROR:{type(exc).__name__}"
    return runtime
