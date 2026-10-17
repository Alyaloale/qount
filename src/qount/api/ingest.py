"""Ingestion script: reads registry -> invokes adapters -> writes SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from qount.api.adapters import get_adapter
from qount.api.db import init_db, log_ingest, log_ingest_run, mark_line_data_error, prune_unregistered_paper_lines, save_paper_line
from qount.api.schemas import PaperLine

DEFAULT_REGISTRY_PATH = "config/paper-lines.json"


def run_ingest(
    registry_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    reg_file = registry_path or os.environ.get("QOUNT_PAPER_LINES_REGISTRY", DEFAULT_REGISTRY_PATH)
    if not os.path.exists(reg_file):
        return {
            "ok": False,
            "error": f"Registry file not found: {reg_file}",
            "processed": 0,
            "lines": {},
        }

    with open(reg_file, "r", encoding="utf-8") as f:
        registry_data = json.load(f)

    lines_config: List[Dict[str, Any]] = registry_data.get("lines", [])
    results: Dict[str, Any] = {}
    init_db(db_path)
    registered_line_ids = {
        str(entry["id"])
        for entry in lines_config
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and entry["id"]
            and entry.get("display", True) is not False
        )
    }
    prune_unregistered_paper_lines(registered_line_ids, db_path=db_path)

    processed_count = 0
    failed_lines: list[str] = []
    for entry in lines_config:
        line_id = entry.get("id")
        adapter_name = entry.get("adapter")
        name = entry.get("name", line_id)
        enabled = entry.get("enabled", True)
        config = entry.get("config", {})

        if entry.get("display", True) is False:
            results[line_id] = {"status": "SKIPPED_HIDDEN"}
            continue

        adapter = get_adapter(adapter_name)
        if not adapter:
            msg = f"Adapter '{adapter_name}' not found for line '{line_id}'"
            log_ingest(line_id, ok=False, message=msg, db_path=db_path)
            results[line_id] = {"status": "ERROR", "message": msg}
            failed_lines.append(str(line_id))
            mark_line_data_error(line_id, "ADAPTER_NOT_FOUND", db_path)
            continue

        try:
            line_obj: PaperLine = adapter(line_id, name, config)
            line_obj = line_obj.model_copy(update={
                "paper_enabled": bool(enabled),
                "research_status": entry.get("research_status", "archived" if line_obj.status in {"ARCHIVED", "STOPPED"} else "research"),
                "sample_kind": entry.get("sample_kind", "historical"),
                "presentation": entry.get("presentation", {}),
            })
            trade_events = None
            if adapter_name == "experiment" and line_obj.data_status == "AVAILABLE":
                from qount.api.adapters.experiment import experiment_trade_events
                trade_events = experiment_trade_events(line_id, config)
            elif adapter_name == "dual_engine":
                from qount.api.adapters.dual_engine import load_rebalance_trade_events

                if line_obj.source.path:
                    trade_events = load_rebalance_trade_events(line_id, line_obj.source.path)
            elif adapter_name == "personal_assistant":
                from qount.api.adapters.personal_assistant import load_personal_assistant_trade_events

                try:
                    trade_events = load_personal_assistant_trade_events(config)
                except FileNotFoundError:
                    trade_events = None
            save_paper_line(line_obj, db_path=db_path, trade_events=trade_events)
            unavailable = bool(line_obj.error) or line_obj.data_status == "MISSING"
            message = line_obj.error or "Source unavailable"
            log_ingest(line_id, ok=not unavailable, message=message if unavailable else "Ingested successfully", db_path=db_path)
            results[line_id] = {
                "status": "MISSING" if unavailable else "OK",
                "as_of": line_obj.as_of,
                "freshness": line_obj.freshness,
                "nav_points_count": len(line_obj.nav_series),
                "message": line_obj.error,
            }
            if not unavailable:
                processed_count += 1
            else:
                failed_lines.append(str(line_id))
        except Exception as e:
            err_msg = f"Failed to adapt line '{line_id}': {str(e)}"
            mark_line_data_error(line_id, f"ADAPTER_FAILED: {type(e).__name__}", db_path)
            log_ingest(line_id, ok=False, message=err_msg, db_path=db_path)
            results[line_id] = {"status": "ERROR", "message": err_msg}
            failed_lines.append(str(line_id))

    run_status = "ok" if not failed_lines else ("partial" if processed_count else "failed")
    run_at = datetime.now(timezone.utc).isoformat()
    log_ingest_run(run_status, failed_lines, db_path=db_path, ran_at=run_at)
    return {
        "ok": run_status == "ok",
        "status": run_status,
        "failed_lines": sorted(set(failed_lines)),
        "ran_at": run_at,
        "processed": processed_count,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest paper research lines into SQLite.")
    parser.add_argument("--registry", default=None, help="Path to paper-lines.json")
    parser.add_argument("--db", default=None, help="Path to SQLite db")
    args = parser.parse_args()

    res = run_ingest(args.registry, args.db)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    if not res.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
