"""Read an explicitly configured, completed deterministic daily package. Never run it."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/daily")
def get_assistant_daily() -> dict:
    run = os.environ.get("QOUNT_ASSISTANT_DAILY_RUN")
    base = {
        "read_at": datetime.now(timezone.utc).isoformat(),
        "safety": {"research_only": True, "orders_authorized": False},
    }
    if not run:
        return {**base, "status": "MISSING", "reason": "最新日报未接入", "report": None}
    root = Path(run).expanduser()
    try:
        if not (root / "_COMPLETE").is_file():
            raise ValueError("PACKAGE_INCOMPLETE")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        report_bytes = (root / "daily-report.json").read_bytes()
        digest = hashlib.sha256(report_bytes).hexdigest()
        artifact = manifest["output_artifacts"]["daily_report_json"]
        if artifact["file"] != "daily-report.json" or artifact["sha256"] != digest:
            raise ValueError("REPORT_HASH_MISMATCH")
        report = json.loads(report_bytes)
        boundary = report["risk_and_evidence"]["safety_boundary"]
        manifest_boundary = manifest["boundary"]
        for safety in (boundary, manifest_boundary):
            if (
                not isinstance(safety, dict)
                or safety.get("research_only") is not True
                or safety.get("orders_authorized") is not False
            ):
                raise ValueError("INVALID_RESEARCH_BOUNDARY")
        inputs = report["input_status"]
        if inputs["source_data_hash"] != manifest["input_files"]["data_sha256"]:
            raise ValueError("INPUT_HASH_MISMATCH")
        as_of = str(inputs["as_of_date"])
        normalized_date = datetime.strptime(as_of.replace("-", ""), "%Y%m%d").date()
        tool = report["tool_status"]
        assets = report["rule_status"]["assets"]
        qualifications = inputs["assets_qualification"]
        if (
            not isinstance(assets, dict)
            or not assets
            or not isinstance(qualifications, dict)
        ):
            raise ValueError("RULE_EVIDENCE_MISSING")
        if not all(
            key in qualifications
            and asset["symbol"] == qualifications[key]["symbol"]
            and asset["as_of_date"] == qualifications[key]["as_of_date"]
            for key, asset in assets.items()
        ):
            raise ValueError("RULE_QUALIFICATION_MISMATCH")
        actionable = any(
            asset.get("is_actionable") is True
            and qualifications[key].get("is_actionable") is True
            for key, asset in assets.items()
        )
        expected_date = inputs.get("expected_as_of_date")
        expected_is_met = (
            expected_date is not None
            and normalized_date
            >= datetime.strptime(str(expected_date).replace("-", ""), "%Y%m%d").date()
        )
        qualified = (
            tool["report_generation_status"] == "SUCCESS"
            and tool["evidence_qualification_status"] == "QUALIFIED"
            and inputs["freshness_status"] == "FRESH"
            and actionable
            and expected_is_met
        )
        status = "QUALIFIED" if qualified else "DISQUALIFIED"
        if qualified and normalized_date != datetime.now(timezone.utc).date():
            status = "HISTORICAL"
        return {
            **base,
            "status": status,
            "report": report,
            "source": {"path": str(root / "daily-report.json"), "sha256": digest},
            "verification": "completed_package_and_manifest_hash_matched",
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {
            **base,
            "status": "ERROR",
            "reason": "日报包未完成或来源校验失败",
            "report": None,
        }
