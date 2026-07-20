"""Shared MiniTrend dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass(frozen=True)
class GateState:
    risk_on: bool
    btc_close: float | None
    btc_sma200: float | None
    breadth: float
    btc_gate: bool = False
    breadth_gate: bool = False


@dataclass(frozen=True)
class SignalResult:
    schema_version: int
    strategy: str
    bar: str | None
    universe: tuple[str, ...]
    gate: GateState
    targets: dict[str, float]
    diagnostics: dict[str, float | int | str | bool]


@dataclass(frozen=True)
class SymbolFilter:
    amount_step: float
    min_amount: float
    min_notional: float


@dataclass(frozen=True)
class Position:
    symbol: str
    base_amount: float
    liability: float = 0.0


@dataclass(frozen=True)
class BlockedSymbol:
    symbol: str
    target_usdt: float
    min_notional_usdt: float
    reason: str


@dataclass(frozen=True)
class RiskResult:
    schema_version: int
    allow: bool
    halt: bool
    reasons: list[str]
    limits: dict[str, float]
    blocked_symbols: list[BlockedSymbol]
    targets: dict[str, float]
    min_notional_coverage: float
    latch_reset_symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str
    type: str
    base_qty: float
    quote_qty: float
    est_usdt: float
    reduce_only: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ExecutionPlan:
    schema_version: int
    mode: str
    armed: bool
    orders: list[Order]
    no_order_reasons: list[str]
    target_usdt: dict[str, float]
    current_usdt: dict[str, float]


@dataclass(frozen=True)
class Scorecard:
    schema_version: int
    strategy: str
    mode: str
    window: dict[str, str]
    metrics: dict[str, float | int]
    blocked_symbols: list[dict]
    missing_fields: list[str]
    verdict: str
