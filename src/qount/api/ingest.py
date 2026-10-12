"""Ingestion script: reads registry -> invokes adapters -> writes SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from qount.api.adapters import get_adapter
from qount.api.db import init_db, log_ingest, save_paper_line
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

    processed_count = 0
    for entry in lines_config:
        line_id = entry.get("id")
        adapter_name = entry.get("adapter")
        name = entry.get("name", line_id)
        enabled = entry.get("enabled", True)
        config = entry.get("config", {})

        if not enabled:
            results[line_id] = {"status": "SKIPPED_DISABLED"}
            continue

        adapter = get_adapter(adapter_name)
        if not adapter:
            msg = f"Adapter '{adapter_name}' not found for line '{line_id}'"
            log_ingest(line_id, ok=False, message=msg, db_path=db_path)
            results[line_id] = {"status": "ERROR", "message": msg}
            continue

        try:
            line_obj: PaperLine = adapter(line_id, name, config)
            save_paper_line(line_obj, db_path=db_path)
            log_ingest(line_id, ok=True, message="Ingested successfully", db_path=db_path)
            results[line_id] = {
                "status": "OK",
                "as_of": line_obj.as_of,
                "freshness": line_obj.freshness,
                "nav_points_count": len(line_obj.nav_series),
            }
            processed_count += 1
        except Exception as e:
            err_msg = f"Failed to adapt line '{line_id}': {str(e)}"
            log_ingest(line_id, ok=False, message=err_msg, db_path=db_path)
            results[line_id] = {"status": "ERROR", "message": err_msg}

    return {
        "ok": True,
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
