"""Observe the existing macro timer/receipt, never orders.

The macro incident/alert path is retired (2026-11-04 owner decision): the macro
line was replaced by G20-LP v3 on 2026-11-03 and its runtime panel keeps
observation only.  No events are enqueued or resolved from this module.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from qount.strategies.macro_1atr import STRATEGY_ID

UNITS = ("qount-1atr-auto.timer", "qount-1atr-auto.service", "qount-notification-retry.service")


def _reason(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)?", value) else "execution_blocked"


def collect_macro_runtime(result_path, halt_path, *, now=None, runner=None):
    """Read local systemd and a receipt; observation only, never sends."""
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
    runtime["notification_enqueue_status"] = "RETIRED"
    runtime["notification_delivery"] = dict(status="RETIRED", last_attempt_at=None,
                                            last_delivered_at=None, last_error=None)
    return runtime
