"""Independent shadow accounting contracts.

These types are intentionally independent of qount.ledger position
aggregation, qount.execution, and qount.mini_trend.pilot_dispatcher.
They represent the shadow accountant's own view of positions, cost,
NAV, and reconciliation diff, rebuilt from raw exchange responses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from qount.contracts.hashing import canonical_hash


CASH_EVENT_TYPES = (
    "commission",
    "funding",
    "transfer",
    "realized_pnl",
    "unknown_income",
)

BLOCKING_LEVELS = ("pass", "warn", "block")


@dataclass(frozen=True)
class ShadowPosition:
    """One symbol's position rebuilt by the shadow accountant."""

    symbol: str
    quantity: float
    cost_basis: float
    realized_pnl: float
    unrealized_pnl: float
    position_hash: str

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        quantity: float,
        cost_basis: float,
        realized_pnl: float,
        unrealized_pnl: float,
    ) -> ShadowPosition:
        core = {
            "symbol": symbol,
            "quantity": float(quantity),
            "cost_basis": float(cost_basis),
            "realized_pnl": float(realized_pnl),
            "unrealized_pnl": float(unrealized_pnl),
        }
        return cls(
            symbol=symbol,
            quantity=float(quantity),
            cost_basis=float(cost_basis),
            realized_pnl=float(realized_pnl),
            unrealized_pnl=float(unrealized_pnl),
            position_hash=canonical_hash(core),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.symbol:
            errors.append("shadow_position_symbol_empty")
        for name in ("quantity", "cost_basis", "realized_pnl", "unrealized_pnl"):
            value = getattr(self, name)
            try:
                float(value)
            except (TypeError, ValueError):
                errors.append(f"shadow_position_{name}_invalid")
                continue
            if not math.isfinite(float(value)):
                errors.append(f"shadow_position_{name}_not_finite")
        if self.quantity < 0:
            errors.append("shadow_position_short_forbidden")
        expected = canonical_hash(
            {
                "symbol": self.symbol,
                "quantity": self.quantity,
                "cost_basis": self.cost_basis,
                "realized_pnl": self.realized_pnl,
                "unrealized_pnl": self.unrealized_pnl,
            }
        )
        if self.position_hash != expected:
            errors.append("shadow_position_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class ShadowCashEvent:
    """One cash event (commission, funding, transfer, etc.)."""

    event_type: str
    symbol: str
    amount: float
    timestamp: str
    income_type: str
    event_hash: str

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        symbol: str,
        amount: float,
        timestamp: str,
        income_type: str = "",
    ) -> ShadowCashEvent:
        core = {
            "event_type": event_type,
            "symbol": symbol,
            "amount": float(amount),
            "timestamp": timestamp,
            "income_type": income_type,
        }
        return cls(
            event_type=event_type,
            symbol=symbol,
            amount=float(amount),
            timestamp=timestamp,
            income_type=income_type,
            event_hash=canonical_hash(core),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.event_type not in CASH_EVENT_TYPES:
            errors.append("shadow_cash_event_type_invalid")
        if not self.symbol:
            errors.append("shadow_cash_event_symbol_empty")
        try:
            float(self.amount)
        except (TypeError, ValueError):
            errors.append("shadow_cash_event_amount_invalid")
        if not self.timestamp:
            errors.append("shadow_cash_event_timestamp_empty")
        expected = canonical_hash(
            {
                "event_type": self.event_type,
                "symbol": self.symbol,
                "amount": self.amount,
                "timestamp": self.timestamp,
                "income_type": self.income_type,
            }
        )
        if self.event_hash != expected:
            errors.append("shadow_cash_event_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class ShadowNavMark:
    """NAV mark with identity equation verification.

    identity_verified is True only when:
      equity == initial_equity + realized + unrealized_delta
                  + funding - commission + transfer
    """

    equity: float
    initial_equity: float
    realized_pnl: float
    unrealized_pnl: float
    funding: float
    commission: float
    transfer: float
    residual: float
    identity_verified: bool
    nav_hash: str

    @classmethod
    def create(
        cls,
        *,
        equity: float,
        initial_equity: float,
        realized_pnl: float,
        unrealized_pnl: float,
        funding: float,
        commission: float,
        transfer: float,
        residual_tolerance: float = 1e-8,
    ) -> ShadowNavMark:
        equity_f = float(equity)
        initial_f = float(initial_equity)
        realized_f = float(realized_pnl)
        unrealized_f = float(unrealized_pnl)
        funding_f = float(funding)
        commission_f = float(commission)
        transfer_f = float(transfer)
        expected_equity = (
            initial_f
            + realized_f
            + unrealized_f
            + funding_f
            - commission_f
            + transfer_f
        )
        residual = equity_f - expected_equity
        identity_verified = abs(residual) <= residual_tolerance
        core = {
            "equity": equity_f,
            "initial_equity": initial_f,
            "realized_pnl": realized_f,
            "unrealized_pnl": unrealized_f,
            "funding": funding_f,
            "commission": commission_f,
            "transfer": transfer_f,
            "residual": residual,
            "identity_verified": identity_verified,
        }
        return cls(
            equity=equity_f,
            initial_equity=initial_f,
            realized_pnl=realized_f,
            unrealized_pnl=unrealized_f,
            funding=funding_f,
            commission=commission_f,
            transfer=transfer_f,
            residual=residual,
            identity_verified=identity_verified,
            nav_hash=canonical_hash(core),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        for name in (
            "equity",
            "initial_equity",
            "realized_pnl",
            "unrealized_pnl",
            "funding",
            "commission",
            "transfer",
            "residual",
        ):
            value = getattr(self, name)
            try:
                float(value)
            except (TypeError, ValueError):
                errors.append(f"shadow_nav_{name}_invalid")
                return tuple(errors)
            if not math.isfinite(float(value)):
                errors.append(f"shadow_nav_{name}_not_finite")
        if not isinstance(self.identity_verified, bool):
            errors.append("shadow_nav_identity_verified_invalid")
        expected = canonical_hash(
            {
                "equity": self.equity,
                "initial_equity": self.initial_equity,
                "realized_pnl": self.realized_pnl,
                "unrealized_pnl": self.unrealized_pnl,
                "funding": self.funding,
                "commission": self.commission,
                "transfer": self.transfer,
                "residual": self.residual,
                "identity_verified": self.identity_verified,
            }
        )
        if self.nav_hash != expected:
            errors.append("shadow_nav_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class ShadowReconciliationDiff:
    """One field-level diff between shadow and primary ledger."""

    field: str
    primary_value: Any
    shadow_value: Any
    tolerance: float
    blocking_level: str
    diff_hash: str

    @classmethod
    def create(
        cls,
        *,
        field: str,
        primary_value: Any,
        shadow_value: Any,
        tolerance: float = 0.0,
        blocking_level: str = "pass",
    ) -> ShadowReconciliationDiff:
        core = {
            "field": field,
            "primary_value": primary_value,
            "shadow_value": shadow_value,
            "tolerance": float(tolerance),
            "blocking_level": blocking_level,
        }
        return cls(
            field=field,
            primary_value=primary_value,
            shadow_value=shadow_value,
            tolerance=float(tolerance),
            blocking_level=blocking_level,
            diff_hash=canonical_hash(core),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.field:
            errors.append("shadow_diff_field_empty")
        if self.blocking_level not in BLOCKING_LEVELS:
            errors.append("shadow_diff_blocking_level_invalid")
        expected = canonical_hash(
            {
                "field": self.field,
                "primary_value": self.primary_value,
                "shadow_value": self.shadow_value,
                "tolerance": self.tolerance,
                "blocking_level": self.blocking_level,
            }
        )
        if self.diff_hash != expected:
            errors.append("shadow_diff_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class ShadowCoverageWindow:
    """Query coverage window with gap detection."""

    earliest_recoverable_time: str
    latest_observed_time: str
    gaps: tuple[tuple[str, str], ...]
    window_hash: str

    @classmethod
    def create(
        cls,
        *,
        earliest_recoverable_time: str,
        latest_observed_time: str,
        gaps: tuple[tuple[str, str], ...] = (),
    ) -> ShadowCoverageWindow:
        core = {
            "earliest_recoverable_time": earliest_recoverable_time,
            "latest_observed_time": latest_observed_time,
            "gaps": [list(gap) for gap in gaps],
        }
        return cls(
            earliest_recoverable_time=earliest_recoverable_time,
            latest_observed_time=latest_observed_time,
            gaps=tuple(tuple(gap) for gap in gaps),
            window_hash=canonical_hash(core),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.earliest_recoverable_time:
            errors.append("shadow_window_earliest_empty")
        if not self.latest_observed_time:
            errors.append("shadow_window_latest_empty")
        for i, gap in enumerate(self.gaps):
            if len(gap) != 2:
                errors.append(f"shadow_window_gap_{i}_invalid")
        expected = canonical_hash(
            {
                "earliest_recoverable_time": self.earliest_recoverable_time,
                "latest_observed_time": self.latest_observed_time,
                "gaps": [list(gap) for gap in self.gaps],
            }
        )
        if self.window_hash != expected:
            errors.append("shadow_window_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class QueryMetadata:
    """Metadata for a single exchange API query session.

    Records the query window, pagination cursor, retry count, and
    source hash so the shadow accountant can independently verify
    coverage completeness (section 4.3).
    """

    endpoint: str
    symbol: str
    query_start_ms: int
    query_end_ms: int
    observed_at: str
    page_count: int
    retry_count: int
    result_count: int
    source_hash: str
    coverage_complete: bool
    metadata_hash: str

    @classmethod
    def create(
        cls,
        *,
        endpoint: str,
        symbol: str,
        query_start_ms: int,
        query_end_ms: int,
        observed_at: str,
        page_count: int,
        retry_count: int,
        result_count: int,
        source_hash: str,
        coverage_complete: bool,
    ) -> QueryMetadata:
        core = {
            "endpoint": endpoint,
            "symbol": symbol,
            "query_start_ms": int(query_start_ms),
            "query_end_ms": int(query_end_ms),
            "observed_at": observed_at,
            "page_count": int(page_count),
            "retry_count": int(retry_count),
            "result_count": int(result_count),
            "source_hash": source_hash,
            "coverage_complete": bool(coverage_complete),
        }
        return cls(
            endpoint=endpoint,
            symbol=symbol,
            query_start_ms=int(query_start_ms),
            query_end_ms=int(query_end_ms),
            observed_at=observed_at,
            page_count=int(page_count),
            retry_count=int(retry_count),
            result_count=int(result_count),
            source_hash=source_hash,
            coverage_complete=bool(coverage_complete),
            metadata_hash=canonical_hash(core),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.endpoint:
            errors.append("query_metadata_endpoint_empty")
        if self.query_start_ms < 0:
            errors.append("query_metadata_start_invalid")
        if self.query_end_ms < 0:
            errors.append("query_metadata_end_invalid")
        if self.query_end_ms < self.query_start_ms:
            errors.append("query_metadata_window_inverted")
        if not self.observed_at:
            errors.append("query_metadata_observed_at_empty")
        if self.page_count < 0:
            errors.append("query_metadata_page_count_invalid")
        if self.retry_count < 0:
            errors.append("query_metadata_retry_count_invalid")
        if self.result_count < 0:
            errors.append("query_metadata_result_count_invalid")
        if not self.source_hash:
            errors.append("query_metadata_source_hash_empty")
        if not isinstance(self.coverage_complete, bool):
            errors.append("query_metadata_coverage_complete_invalid")
        expected = canonical_hash(
            {
                "endpoint": self.endpoint,
                "symbol": self.symbol,
                "query_start_ms": self.query_start_ms,
                "query_end_ms": self.query_end_ms,
                "observed_at": self.observed_at,
                "page_count": self.page_count,
                "retry_count": self.retry_count,
                "result_count": self.result_count,
                "source_hash": self.source_hash,
                "coverage_complete": self.coverage_complete,
            }
        )
        if self.metadata_hash != expected:
            errors.append("query_metadata_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class FetchResult:
    """Result of fetching one data type from the exchange.

    Contains raw Binance USD-M dicts plus per-query metadata.
    """

    data_type: str
    records: tuple[Mapping[str, Any], ...]
    queries: tuple[QueryMetadata, ...]
    fetch_hash: str

    @classmethod
    def create(
        cls,
        *,
        data_type: str,
        records: Sequence[Mapping[str, Any]],
        queries: Sequence[QueryMetadata],
    ) -> FetchResult:
        records_t = tuple(
            dict(r) if isinstance(r, Mapping) else r for r in records
        )
        core = {
            "data_type": data_type,
            "records": [dict(r) for r in records_t],
            "queries": [q.metadata_hash for q in queries],
        }
        return cls(
            data_type=data_type,
            records=records_t,
            queries=tuple(queries),
            fetch_hash=canonical_hash(core),
        )

    def validate(self) -> tuple[str, str, ...]:
        errors: list[str] = []
        if self.data_type not in ("trades", "income_history", "open_orders"):
            errors.append("fetch_result_data_type_invalid")
        if not isinstance(self.records, tuple):
            errors.append("fetch_result_records_not_tuple")
        for q in self.queries:
            errs = q.validate()
            if errs:
                errors.append("fetch_result_query_invalid")
                break
        expected = canonical_hash(
            {
                "data_type": self.data_type,
                "records": [dict(r) for r in self.records],
                "queries": [q.metadata_hash for q in self.queries],
            }
        )
        if self.fetch_hash != expected:
            errors.append("fetch_result_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class WatermarkContract:
    """Main/shadow fetch watermark contract (section 4.3).

    Records the delay between live cycle completion and shadow fetch
    start, plus the shadow's coverage window.  This prevents the
    "consistently missing the same instant" failure mode.
    """

    live_cycle_completed_at: str
    shadow_fetch_started_at: str
    min_delay_seconds: float
    delay_satisfied: bool
    shadow_coverage_start: str
    shadow_coverage_end: str
    watermark_hash: str

    @classmethod
    def create(
        cls,
        *,
        live_cycle_completed_at: str,
        shadow_fetch_started_at: str,
        min_delay_seconds: float,
        delay_satisfied: bool,
        shadow_coverage_start: str,
        shadow_coverage_end: str,
    ) -> WatermarkContract:
        core = {
            "live_cycle_completed_at": live_cycle_completed_at,
            "shadow_fetch_started_at": shadow_fetch_started_at,
            "min_delay_seconds": float(min_delay_seconds),
            "delay_satisfied": bool(delay_satisfied),
            "shadow_coverage_start": shadow_coverage_start,
            "shadow_coverage_end": shadow_coverage_end,
        }
        return cls(
            live_cycle_completed_at=live_cycle_completed_at,
            shadow_fetch_started_at=shadow_fetch_started_at,
            min_delay_seconds=float(min_delay_seconds),
            delay_satisfied=bool(delay_satisfied),
            shadow_coverage_start=shadow_coverage_start,
            shadow_coverage_end=shadow_coverage_end,
            watermark_hash=canonical_hash(core),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.live_cycle_completed_at:
            errors.append("watermark_live_cycle_completed_at_empty")
        if not self.shadow_fetch_started_at:
            errors.append("watermark_shadow_fetch_started_at_empty")
        if not math.isfinite(self.min_delay_seconds):
            errors.append("watermark_min_delay_not_finite")
        if self.min_delay_seconds < 0:
            errors.append("watermark_min_delay_negative")
        if not isinstance(self.delay_satisfied, bool):
            errors.append("watermark_delay_satisfied_invalid")
        if not self.shadow_coverage_start:
            errors.append("watermark_coverage_start_empty")
        if not self.shadow_coverage_end:
            errors.append("watermark_coverage_end_empty")
        expected = canonical_hash(
            {
                "live_cycle_completed_at": self.live_cycle_completed_at,
                "shadow_fetch_started_at": self.shadow_fetch_started_at,
                "min_delay_seconds": self.min_delay_seconds,
                "delay_satisfied": self.delay_satisfied,
                "shadow_coverage_start": self.shadow_coverage_start,
                "shadow_coverage_end": self.shadow_coverage_end,
            }
        )
        if self.watermark_hash != expected:
            errors.append("watermark_hash_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class ShadowRun:
    """One complete shadow accountant run (section 4.2 output).

    Aggregates fetch results, rebuilt positions/NAV, coverage window,
    reconciliation diffs, and the watermark contract into a single
    immutable artifact.
    """

    run_id: str
    observed_at: str
    venue: str
    symbols: tuple[str, ...]
    fetch_hashes: tuple[str, ...]
    position_hashes: tuple[str, ...]
    nav_hash: str
    coverage_window_hash: str
    unknown_income_count: int
    diff_hashes: tuple[str, ...]
    has_blocking_diff: bool
    watermark_hash: str
    run_hash: str

    @classmethod
    def create(
        cls,
        *,
        observed_at: str,
        venue: str,
        symbols: Sequence[str],
        fetch_results: Sequence[FetchResult],
        position_hashes: Sequence[str],
        nav_hash: str,
        coverage_window_hash: str,
        unknown_income_count: int,
        diff_hashes: Sequence[str],
        has_blocking_diff: bool,
        watermark: WatermarkContract,
    ) -> ShadowRun:
        core = {
            "observed_at": observed_at,
            "venue": venue,
            "symbols": list(symbols),
            "fetch_hashes": [f.fetch_hash for f in fetch_results],
            "position_hashes": list(position_hashes),
            "nav_hash": nav_hash,
            "coverage_window_hash": coverage_window_hash,
            "unknown_income_count": int(unknown_income_count),
            "diff_hashes": list(diff_hashes),
            "has_blocking_diff": bool(has_blocking_diff),
            "watermark_hash": watermark.watermark_hash,
        }
        run_hash = canonical_hash(core)
        return cls(
            run_id=canonical_hash(
                {"type": "shadow_run", "run_hash": run_hash}
            ),
            observed_at=observed_at,
            venue=venue,
            symbols=tuple(symbols),
            fetch_hashes=tuple(f.fetch_hash for f in fetch_results),
            position_hashes=tuple(position_hashes),
            nav_hash=nav_hash,
            coverage_window_hash=coverage_window_hash,
            unknown_income_count=int(unknown_income_count),
            diff_hashes=tuple(diff_hashes),
            has_blocking_diff=bool(has_blocking_diff),
            watermark_hash=watermark.watermark_hash,
            run_hash=run_hash,
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.observed_at:
            errors.append("shadow_run_observed_at_empty")
        if not self.venue:
            errors.append("shadow_run_venue_empty")
        if not isinstance(self.symbols, tuple):
            errors.append("shadow_run_symbols_not_tuple")
        if not isinstance(self.fetch_hashes, tuple):
            errors.append("shadow_run_fetch_hashes_not_tuple")
        if not self.nav_hash:
            errors.append("shadow_run_nav_hash_empty")
        if not self.coverage_window_hash:
            errors.append("shadow_run_coverage_window_hash_empty")
        if self.unknown_income_count < 0:
            errors.append("shadow_run_unknown_income_count_invalid")
        if not isinstance(self.diff_hashes, tuple):
            errors.append("shadow_run_diff_hashes_not_tuple")
        if not isinstance(self.has_blocking_diff, bool):
            errors.append("shadow_run_has_blocking_diff_invalid")
        if not self.watermark_hash:
            errors.append("shadow_run_watermark_hash_empty")
        expected = canonical_hash(
            {
                "observed_at": self.observed_at,
                "venue": self.venue,
                "symbols": list(self.symbols),
                "fetch_hashes": list(self.fetch_hashes),
                "position_hashes": list(self.position_hashes),
                "nav_hash": self.nav_hash,
                "coverage_window_hash": self.coverage_window_hash,
                "unknown_income_count": self.unknown_income_count,
                "diff_hashes": list(self.diff_hashes),
                "has_blocking_diff": self.has_blocking_diff,
                "watermark_hash": self.watermark_hash,
            }
        )
        if self.run_hash != expected:
            errors.append("shadow_run_hash_invalid")
        return tuple(errors)
