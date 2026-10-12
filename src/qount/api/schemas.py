"""Pydantic schemas for the qount simplified API."""

from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, Field


class NavPoint(BaseModel):
    date: str
    nav: float
    benchmark_nav: float = 1.0
    # Zero-cost signal NAV when the source distinguishes it from the executable NAV. The gap
    # between the two is the part of a headline return that costs and lot sizes remove, so the
    # UI shows both rather than only the flattering one.
    signal_nav: Optional[float] = None


class LineMetrics(BaseModel):
    ytd_return_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    current_drawdown_pct: Optional[float] = None
    sharpe: Optional[float] = None
    calmar: Optional[float] = None
    cagr_pct: Optional[float] = None
    trade_count: Optional[int] = None
    start_date: Optional[str] = None
    days: Optional[int] = None
    signal_nav: Optional[float] = None
    executable_nav: Optional[float] = None
    cumulative_cost: Optional[float] = None


class PositionItem(BaseModel):
    symbol: str
    weight: float
    entry_date: Optional[str] = None
    quantity: Optional[float] = None
    market_value: Optional[float] = None


class LineSource(BaseModel):
    path: str
    sha256: Optional[str] = None
    produced_at: Optional[str] = None


class LineSafety(BaseModel):
    research_only: bool = True
    orders_authorized: bool = False


class PaperLine(BaseModel):
    line_id: str
    name: str
    category: str = "assistant"  # equity | crypto | macro | assistant
    status: str = "ACTIVE_PAPER"  # ACTIVE_PAPER | ARCHIVED | STOPPED
    adjudication: str = ""
    as_of: str
    freshness: str = "FRESH"  # FRESH | STALE | MISSING
    nav_series: List[NavPoint] = Field(default_factory=list)
    # None when the source could not be read. A missing source must never be papered over
    # with placeholder figures: an advisory line reporting a fabricated return is worse than
    # one reporting nothing, because the number is indistinguishable from a real one.
    metrics: Optional[LineMetrics] = None
    positions: List[PositionItem] = Field(default_factory=list)
    source: LineSource
    safety: LineSafety = Field(default_factory=LineSafety)
    # Set when the source is unreadable; the UI renders this instead of figures.
    error: Optional[str] = None


class PaperLineSummary(BaseModel):
    line_id: str
    name: str
    category: str
    status: str
    adjudication: str
    as_of: str
    freshness: str
    metrics: Optional[LineMetrics] = None
    positions: List[PositionItem] = Field(default_factory=list)
    source: LineSource
    safety: LineSafety = Field(default_factory=LineSafety)
    error: Optional[str] = None


class BalanceItem(BaseModel):
    asset: str
    free: float
    locked: float = 0.0


class AccountSnapshot(BaseModel):
    as_of: str
    # PAPER: a research reconciliation package (simulation, not assets).
    # LIVE_READONLY: a real exchange balance read through a read-only key.
    # The two must never be summed or averaged: one is a simulation result, the other is money.
    mode: str = "PAPER"
    source_kind: str = "local_snapshot"  # local_snapshot | binance_api
    nav: float
    cash: float
    positions: List[PositionItem] = Field(default_factory=list)
    currency: str = "CNY"
    # LIVE_READONLY only: real balances as reported by the exchange.
    balances: List[BalanceItem] = Field(default_factory=list)
    # The key's own permissions. Distinct from safety.orders_authorized, which is this
    # system's authority: a read-only key does not by itself mean no order path exists.
    read_only: Optional[bool] = None
    source: LineSource
    safety: LineSafety = Field(default_factory=LineSafety)
    # Set when the live read failed; the UI shows this instead of a balance.
    error: Optional[str] = None


class MarketKlinesBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketCoverage(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    gaps: List[str] = Field(default_factory=list)


class MarketKlinesResponse(BaseModel):
    symbol: str
    interval: str = "1d"
    source: str = "cache"  # cache | live
    bars: List[MarketKlinesBar] = Field(default_factory=list)
    coverage: MarketCoverage = Field(default_factory=MarketCoverage)


class HealthResponse(BaseModel):
    status: str = "ok"
    db_connected: bool = True
    last_ingest_at: Optional[str] = None
    paper_lines_count: int = 0
    safety: LineSafety = Field(default_factory=LineSafety)
