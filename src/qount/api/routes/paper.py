"""Paper research lines routes."""

from __future__ import annotations

from typing import List
from fastapi import APIRouter, HTTPException, Query

from qount.api.db import get_current_paper_position_snapshot, get_paper_line, get_paper_lines_summary, get_paper_positions, get_paper_trades
from qount.api.schemas import PaperCurrentPositions, PaperLine, PaperLineSummary, PaperPositionRecord, PaperTradeRecord

router = APIRouter(prefix="/paper", tags=["paper"])


@router.get("/lines", response_model=List[PaperLineSummary])
def list_paper_lines() -> List[PaperLineSummary]:
    """Get summaries of all registered paper research lines (lightweight, no nav_series)."""
    return get_paper_lines_summary()


@router.get("/lines/{line_id}", response_model=PaperLine)
def get_paper_line_detail(line_id: str) -> PaperLine:
    """Get full details of a specific paper research line, including nav_series."""
    line = get_paper_line(line_id)
    if not line:
        raise HTTPException(status_code=404, detail=f"Paper line '{line_id}' not found")
    return line


@router.get("/positions", response_model=List[PaperPositionRecord])
def list_paper_positions(
    line_id: str,
    start: str | None = None,
    end: str | None = None,
) -> List[PaperPositionRecord]:
    """Return timestamped simulated holding snapshots for one research line."""
    return get_paper_positions(line_id=line_id, start=start, end=end)


@router.get("/positions/current", response_model=PaperCurrentPositions)
def get_current_positions(line_id: str) -> PaperCurrentPositions:
    """Return current validity and the last valid snapshot together."""
    return PaperCurrentPositions(**get_current_paper_position_snapshot(line_id=line_id))


@router.get("/trades", response_model=List[PaperTradeRecord])
def list_paper_trades(
    line_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    start: str | None = None,
    end: str | None = None,
) -> List[PaperTradeRecord]:
    """Return simulated rebalance events; these are never real exchange fills."""
    return get_paper_trades(line_id=line_id, limit=limit, start=start, end=end)
