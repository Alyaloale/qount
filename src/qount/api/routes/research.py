"""Research registry route."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Query

from qount.api.adapters import get_adapter, list_adapters
from qount.binance_assets import asset_mapping_payload
from qount.api.db import (
    get_paper_lines_summary, get_paper_line, get_paper_positions,
    get_current_paper_position_snapshot, get_paper_trades,
)
from qount.api.schemas import PaperLine, PaperLineSummary, PaperCurrentPositions, PaperPositionRecord, PaperTradeRecord

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/lines", response_model=list[PaperLineSummary])
def list_research_lines():
    """Historical research remains visible when forward simulation is disabled."""
    return get_paper_lines_summary(forward_only=False)


@router.get("/lines/{line_id}", response_model=PaperLine)
def research_detail(line_id: str, run_id: str | None = None):
    line = get_paper_line(line_id, forward_only=False)
    if line is None:
        raise HTTPException(status_code=404, detail="Research line not found")
    if run_id:
        from qount.api.adapters.experiment import adapt_experiment
        candidate = adapt_experiment(line_id, line.name, {**_experiment_config(line_id), "run_id":run_id})
        if candidate.data_status != "AVAILABLE":
            raise HTTPException(status_code=404, detail="Complete experiment not found")
        line = candidate.model_copy(update={"presentation":line.presentation, "research_status":line.research_status})
    return line


def _experiment_config(line_id):
    path = Path(os.environ.get("QOUNT_PAPER_LINES_REGISTRY", "config/paper-lines.json"))
    try:
        entries = json.loads(path.read_text())["lines"]
        return next(entry["config"] for entry in entries if entry["id"] == line_id
                    and entry.get("adapter") == "experiment" and entry.get("display", True))
    except (OSError, ValueError, KeyError, StopIteration):
        raise HTTPException(status_code=404, detail="Experiment line not found")


@router.get("/lines/{line_id}/runs")
def research_runs(line_id: str):
    config = _experiment_config(line_id)
    runs = []
    for path in sorted(Path(config["root"]).glob("*/summary.json")):
        try:
            from qount.api.adapters.experiment import read_experiment
            _, summary, _, _ = read_experiment(line_id, config, path.parent.name)
            runs.append({key: summary.get(key) for key in ("run_id", "parameters", "total_return_pct",
                "max_drawdown_pct", "trade_count", "sample_kind", "conclusion")})
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return {"selected_run_id": config.get("run_id"), "runs": runs}


@router.get("/lines/{line_id}/runs/{run_id}")
def research_run(line_id: str, run_id: str):
    from qount.api.adapters.experiment import read_experiment
    try:
        _, summary, nav, trades = read_experiment(line_id, _experiment_config(line_id), run_id)
        return dict(summary=summary, nav=nav, trades=trades)
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(status_code=404, detail="Complete experiment not found")


@router.get("/positions", response_model=list[PaperPositionRecord])
def research_positions(line_id: str, start: str | None = None, end: str | None = None, run_id: str | None = None):
    if run_id:
        research_detail(line_id, run_id)
        return []
    return get_paper_positions(line_id, start=start, end=end, forward_only=False)


@router.get("/positions/current", response_model=PaperCurrentPositions)
def research_current_positions(line_id: str):
    return get_current_paper_position_snapshot(line_id, forward_only=False)


@router.get("/trades", response_model=list[PaperTradeRecord])
def research_trades(line_id: str, limit: int = Query(default=100, ge=1, le=1000),
                    start: str | None = None, end: str | None = None, run_id: str | None = None):
    if run_id:
        from qount.api.adapters.experiment import experiment_trade_events
        research_detail(line_id, run_id)
        events = experiment_trade_events(line_id, _experiment_config(line_id), run_id)
        rows = [PaperTradeRecord(line_id=line_id, date=e["date"], symbol=e["symbol"], side=e["side"],
                quantity=e["quantity"], price=e["price"], cost=e["cost"], note=e["note"], record_kind="historical_backtest")
                for e in events if (not start or e["date"][:10] >= start[:10]) and (not end or e["date"][:10] <= end[:10])]
        return sorted(rows, key=lambda r:r.date, reverse=True)[:limit]
    return get_paper_trades(line_id, limit=limit, start=start, end=end, forward_only=False)


@router.get("/assets")
def get_binance_assets() -> Dict[str, Any]:
    """Return the validated Binance identity map shared by research and UI clients."""
    return asset_mapping_payload()

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
