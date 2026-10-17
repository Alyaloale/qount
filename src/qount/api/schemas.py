"""Pydantic schemas for the qount simplified API."""

from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, Field


class NavPoint(BaseModel):
    date: str
    nav: float
    benchmark_nav: Optional[float] = None
    # Zero-cost signal NAV when the source distinguishes it from the executable NAV. The gap
    # between the two is the part of a headline return that costs and lot sizes remove, so the
    # UI shows both rather than only the flattering one.
    signal_nav: Optional[float] = None


class LineMetrics(BaseModel):
    total_return_pct: Optional[float] = None
    cagr_basis: Optional[str] = None
    benchmark_cagr_pct: Optional[float] = None
    benchmark_max_drawdown_pct: Optional[float] = None
    exposure_pct: Optional[float] = None
    initial_equity: Optional[float] = None
    observation_count: Optional[int] = None
    trading_days: Optional[int] = None
    corporate_action_count: Optional[int] = None
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
    asset_id: Optional[str] = None
    signal_symbol: Optional[str] = None
    execution_symbol: Optional[str] = None
    venue: Optional[str] = None
    weight: Optional[float] = None
    entry_date: Optional[str] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    market_value: Optional[float] = None
    side: Optional[str] = None


class PaperPositionRecord(BaseModel):
    line_id: str
    date: str
    symbol: str
    quantity: Optional[float] = None
    weight: Optional[float] = None
    price: Optional[float] = None
    market_value: Optional[float] = None
    action: str  # OPEN | CLOSE | ADJUST | HOLD
    record_kind: str = "simulated_not_realized"


class PaperTradeRecord(BaseModel):
    line_id: str
    date: str
    symbol: str
    side: str  # BUY | SELL | SPLIT
    quantity: Optional[float] = None
    price: Optional[float] = None
    cost: Optional[float] = None
    note: str = ""
    record_kind: str = "simulated_not_realized"


class LineSource(BaseModel):
    path: str
    sha256: Optional[str] = None
    produced_at: Optional[str] = None
    # Forward paper inputs must identify the venue and contract family explicitly.
    # A filename or a relabeled spot/proxy NAV is not provenance.
    venue: Optional[str] = None
    instrument_type: Optional[str] = None
    price_source: Optional[str] = None
    observation_kind: Optional[str] = None
    execution_symbols: List[str] = Field(default_factory=list)


class LineSafety(BaseModel):
    research_only: bool = True
    orders_authorized: bool = False


class PaperLine(BaseModel):
    line_id: str
    run_id: Optional[str] = None
    name: str
    research_status: str = "research"
    paper_enabled: bool = True
    sample_kind: str = "historical"
    presentation: dict[str, str] = Field(default_factory=dict)
    category: str = "assistant"  # equity | crypto | macro | assistant
    status: str = "ACTIVE_PAPER"  # ACTIVE_PAPER | ARCHIVED | STOPPED
    data_status: str = "AVAILABLE"  # AVAILABLE | MISSING | ERROR
    adjudication: str = ""
    as_of: str
    freshness: str = "FRESH"  # FRESH | STALE | MISSING
    curve_granularity: str = "OBSERVATION"  # DAILY | SNAPSHOT | YEARLY | OBSERVATION
    nav_series: List[NavPoint] = Field(default_factory=list)
    # None when the source could not be read. A missing source must never be papered over
    # with placeholder figures: an advisory line reporting a fabricated return is worse than
    # one reporting nothing, because the number is indistinguishable from a real one.
    metrics: Optional[LineMetrics] = None
    positions: List[PositionItem] = Field(default_factory=list)
    position_status: str = "UNKNOWN"  # KNOWN | UNKNOWN | MISSING | NOT_APPLICABLE
    source: LineSource
    safety: LineSafety = Field(default_factory=LineSafety)
    # Set when the source is unreadable; the UI renders this instead of figures.
    error: Optional[str] = None
    # Only source-backed assumptions; an empty object means coverage is unconfirmed.
    last_attempt_at: Optional[str] = None
    last_attempt_status: Optional[str] = None
    last_attempt_error: Optional[str] = None
    last_attempt_source: Optional[LineSource] = None
    position_error: Optional[str] = None
    cost_assumptions: dict[str, Any] = Field(default_factory=dict)
    execution_constraints: List[str] = Field(default_factory=list)


class PaperLineSummary(BaseModel):
    line_id: str
    run_id: Optional[str] = None
    name: str
    research_status: str = "research"
    paper_enabled: bool = True
    sample_kind: str = "historical"
    presentation: dict[str, str] = Field(default_factory=dict)
    category: str
    status: str
    data_status: str = "AVAILABLE"
    adjudication: str
    as_of: str
    freshness: str
    curve_granularity: str = "OBSERVATION"
    metrics: Optional[LineMetrics] = None
    positions: List[PositionItem] = Field(default_factory=list)
    position_status: str = "UNKNOWN"
    source: LineSource
    safety: LineSafety = Field(default_factory=LineSafety)
    error: Optional[str] = None
    last_attempt_at: Optional[str] = None
    last_attempt_status: Optional[str] = None
    last_attempt_error: Optional[str] = None
    last_attempt_source: Optional[LineSource] = None
    position_error: Optional[str] = None
    cost_assumptions: dict[str, Any] = Field(default_factory=dict)
    execution_constraints: List[str] = Field(default_factory=list)


class PaperCurrentPositions(BaseModel):
    line_id: str
    status: str  # KNOWN | UNKNOWN | MISSING | NOT_APPLICABLE
    as_of: Optional[str] = None
    last_valid_as_of: Optional[str] = None
    positions: List[PaperPositionRecord] = Field(default_factory=list)
    error: Optional[str] = None


class BalanceItem(BaseModel):
    asset: str
    free: float
    locked: float = 0.0


class AccountSnapshot(BaseModel):
    initial_equity: Optional[float] = None
    observation_interval_seconds: Optional[int] = None
    as_of: str
    # PAPER: a research reconciliation package (simulation, not assets).
    # LIVE_READONLY: a real exchange balance read through a read-only key.
    # The two must never be summed or averaged: one is a simulation result, the other is money.
    mode: str = "PAPER"
    source_kind: str = "local_snapshot"  # local_snapshot | binance_api
    nav: float
    cash: Optional[float] = None
    positions: List[PositionItem] = Field(default_factory=list)
    positions_status: str = "UNKNOWN"  # KNOWN | UNKNOWN | MISSING | NOT_APPLICABLE
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
    research_lines_count: int = 0
    ingest_status: str = "unknown"  # ok | failed | never | partial
    stale_line_count: int = 0
    missing_source_count: int = 0
    safety: LineSafety = Field(default_factory=LineSafety)
