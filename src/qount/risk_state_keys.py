"""Deterministic runtime-state keys used by the legacy risk engine.

Keeping key construction separate from journal access makes persisted-state
names explicit, reusable, and testable without a Settings or Journal object.
"""

from __future__ import annotations


def day_start_equity_key(
    mode: str,
    exchange_id: str,
    market_type: str,
    quote_currency: str,
    date_key: str,
) -> str:
    """Return the equity checkpoint key for one exchange day."""
    return (
        f"day_start_equity:{mode}:{exchange_id}:{market_type}:"
        f"{quote_currency}:{date_key}"
    )


def trailing_profit_peak_key(
    *,
    mode: str,
    exchange_id: str,
    market_type: str,
    symbol: str,
    open_run_id: int,
) -> str:
    """Return the trailing-profit peak key for one open position run."""
    return (
        f"trailing_profit_peak:{mode}:{exchange_id}:{market_type}:"
        f"{symbol}:{open_run_id}"
    )


def partial_take_profit_done_key(
    *,
    mode: str,
    exchange_id: str,
    market_type: str,
    symbol: str,
    open_run_id: int,
) -> str:
    """Return the partial-take-profit progress key for one open position run."""
    return (
        f"partial_tp_done:{mode}:{exchange_id}:{market_type}:"
        f"{symbol}:{open_run_id}"
    )


def breakeven_stop_armed_key(
    *,
    mode: str,
    exchange_id: str,
    market_type: str,
    symbol: str,
    open_run_id: int,
) -> str:
    """Return the breakeven-stop state key for one open position run."""
    return (
        f"breakeven_stop_armed:{mode}:{exchange_id}:{market_type}:"
        f"{symbol}:{open_run_id}"
    )
