"""Observe the G20-LP v3 receipt/HALT and enqueue alerts, never orders.

Channel: ServerChan (serverchan) — service-account push without the personal-
bot conversation window.  Granularity (owner decision 2026-11-03): exception
alerts are pushed as they occur, plus one daily receipt summary per signal
date.  Delivery happens in the retry worker / immediate delivery pass; this
module only observes and enqueues.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from qount.contracts import canonical_hash
from qount.execution.g20_v3_live import STRATEGY_ID

CATEGORY = "g20_v3_execution"
CHANNEL = "serverchan"
# Daily cycle at 00:00 UTC: a receipt older than 30h means a cycle was missed.
STALE_AFTER_SECONDS = 30 * 3600


def _reason(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)?", value) else "execution_blocked"


def _text(value: object) -> str:
    # AlertEvent contract: non-empty, stripped, no control characters.
    rendered = str(value)
    return "".join(char for char in rendered if ord(char) >= 32)[:1_000].strip() or "空"


def _record_incident(runtime, path):
    if runtime["state"] == "WAITING":
        # Fresh plan-only/non-live receipt: nothing known yet, say nothing and
        # leave existing alerts untouched.
        return "WAITING_SILENT"
    from qount.notifications.contracts import AlertEvent
    from qount.notifications.store import NotificationStore

    store = NotificationStore(Path(path), busy_timeout_ms=1000)
    rows = store.verified_rows()
    active = [AlertEvent(**payload) for key, payload in rows["events"].items()
              if payload["source_type"] == "system" and payload["category"] == CATEGORY
              and rows["states"][key]["status"] == "OPEN"]
    stamp = runtime["observed_at"]
    source, severity, title, summary, dedupe = None, None, None, None, None
    if runtime["state"] == "HALTED":
        source = canonical_hash(dict(strategy_id=STRATEGY_ID, reason="owner_halt"))
        severity, title = "HALT", "QOUNT G20-LP v3 已停机"
        summary = "HALT 文件生效，自动周期不会执行。确认后移除 HALT 文件恢复。"
        dedupe = "v3:halt:active"
    elif runtime["reason"]:
        reason = runtime["reason"]
        source = canonical_hash(dict(strategy_id=STRATEGY_ID, reason=reason,
                                    signal_date=runtime.get("signal_date")))
        critical = any(word in reason for word in
                       ("protection", "stop", "exit", "position", "submission_unknown"))
        severity = "CRITICAL" if critical else "WARNING"
        title = "QOUNT G20-LP v3 周期异常"
        summary = _text(f"状态 {runtime['state']}；原因 {reason}。"
                        f"请核对实盘页面、真实仓位与收据 {runtime.get('signal_date')}。")
        dedupe = f"v3:exception:{reason}:{runtime.get('signal_date')}"
    else:
        signal_date = runtime.get("signal_date") or "unknown"
        source = canonical_hash(dict(strategy_id=STRATEGY_ID, signal_date=signal_date))
        severity, title = "INFO", "QOUNT G20-LP v3 每日收据"
        summary = _text(
            f"信号 {signal_date}；动作 {runtime.get('auto_action')}；"
            f"权益 {runtime.get('capital_usdt')}U；下单 {runtime.get('order_counts') or '无'}；"
            f"周期 {runtime.get('cycle_count')}；排程再平衡 {runtime.get('scheduled_resize')}。")
        dedupe = f"v3:summary:{signal_date}"
    event = next((event for event in active if event.source_id == source), None)
    if event is None:
        event = AlertEvent.create(
            severity=severity, category=CATEGORY, title=title, summary=summary,
            occurred_at=stamp, source_type="system", source_id=source,
            source_hash=canonical_hash(dict(summary=summary, observed_at=stamp)),
            dedupe_key=dedupe)
        store.enqueue(event, channels=(CHANNEL,), recorded_at=stamp)
    store.resolve_superseded_alerts(active_alert_ids=(event.alert_id,),
                                    source_type="system", categories=(CATEGORY,),
                                    resolved_at=stamp)
    return "INCIDENT_RECORDED" if runtime["reason"] else "HALT_RECORDED" if runtime["state"] == "HALTED" else "SUMMARY_RECORDED"


def collect_v3_runtime(result_path, halt_path, *, notification_store=None, now=None):
    """Read the v3 receipt and HALT state; optionally enqueue, without sending."""
    now = now or datetime.now(timezone.utc)
    runtime = dict(observed_at=now.isoformat(), strategy_id=STRATEGY_ID,
                   state="UNKNOWN", reason="runtime_observation_unavailable",
                   halted=Path(halt_path).exists(), signal_date=None,
                   auto_action=None, capital_usdt=None, order_counts=None,
                   cycle_count=None, scheduled_resize=None)
    try:
        result_file = Path(result_path)
        if not result_file.is_file():
            raise ValueError("runtime_receipt_missing")
        payload = json.loads(result_file.read_text())
        created = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("runtime_receipt_timezone_missing")
        age = (now - created).total_seconds()
        runtime.update(last_result_at=payload.get("created_at"),
                       result_age_seconds=age,
                       signal_date=payload.get("signal_date"),
                       auto_action=payload.get("auto_action"),
                       capital_usdt=payload.get("capital_usdt"),
                       order_counts=payload.get("order_counts"),
                       cycle_count=payload.get("cycle_count"),
                       scheduled_resize=payload.get("scheduled_resize"))
        identity_ok = (payload.get("strategy_id") == STRATEGY_ID
                       and payload.get("execution_mode") == "auto_live")
        if runtime["halted"]:
            runtime.update(state="HALTED", reason=None)
        elif not identity_ok:
            # Fresh plan-only or foreign receipt: wait silently for the first
            # real cycle; a receipt this old means the cycle never came.
            if age > STALE_AFTER_SECONDS:
                runtime.update(state="STALE", reason="auto_receipt_stale_or_non_live")
            else:
                runtime.update(state="WAITING", reason=None)
        elif age > STALE_AFTER_SECONDS:
            runtime.update(state="STALE", reason="auto_receipt_stale")
        elif payload.get("auto_action") == "BLOCKED":
            runtime.update(state="BLOCKED", reason=_reason(payload.get("execution_blocker")))
        elif payload.get("auto_action") in {"RESIZE", "NO_ACTION"}:
            runtime.update(state="AUTO", reason=None)
        else:
            runtime.update(state="UNKNOWN", reason="runtime_receipt_action_invalid")
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
