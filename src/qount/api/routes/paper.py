"""Paper research lines routes."""

from __future__ import annotations

from typing import List
from fastapi import APIRouter, HTTPException

from qount.api.db import get_paper_line, get_paper_lines_summary
from qount.api.schemas import PaperLine, PaperLineSummary

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
