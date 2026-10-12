"""Research registry route."""

from __future__ import annotations

import json
import os
from typing import Any, Dict
from fastapi import APIRouter

from qount.api.adapters import get_adapter, list_adapters

router = APIRouter(prefix="/research", tags=["research"])

DEFAULT_REGISTRY_PATH = "config/paper-lines.json"


@router.get("/registry")
def get_research_registry() -> Dict[str, Any]:
    """Return raw paper lines registry and current adapter registration status."""
    reg_path = os.environ.get("QOUNT_PAPER_LINES_REGISTRY", DEFAULT_REGISTRY_PATH)
    raw_registry = {}
    if os.path.exists(reg_path):
        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                raw_registry = json.load(f)
        except Exception:
            raw_registry = {}

    available_adapters = list_adapters()
    adapter_status = {}
    for item in raw_registry.get("lines", []):
        adapter_name = item.get("adapter")
        adapter_status[item.get("id")] = {
            "adapter": adapter_name,
            "registered": get_adapter(adapter_name) is not None,
            "enabled": item.get("enabled", True),
        }

    return {
        "registry": raw_registry,
        "available_adapters": available_adapters,
        "lines_adapter_status": adapter_status,
    }
