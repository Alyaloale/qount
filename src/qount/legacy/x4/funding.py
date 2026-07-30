"""Funding alignment helpers for completed-bar directional backtests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from qount.research_data.market_data import Bar, Funding


_INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def holding_period_funding(
    rows: Sequence[Funding], bars: Sequence[Bar], interval: str
) -> Mapping[int, float]:
    """Map each completed bar to funding in its subsequent close-to-close holding period.

    A target produced from bar ``t`` is traded at that completed bar's close and held until the next
    completed bar.  Binance funding at the next bar boundary belongs to that holding period.  The
    final bar has no subsequent marked holding period and therefore accrues no funding.
    """

    try:
        step_ms = _INTERVAL_MS[interval]
    except KeyError as exc:
        raise ValueError(f"unsupported funding interval: {interval}") from exc
    if not bars:
        return {}
    rates = sorted(rows, key=lambda row: row.ts_ms)
    out: dict[int, float] = {}
    cursor = 0
    for bar in bars[:-1]:
        start_ms = bar.ts_ms + step_ms
        end_ms = start_ms + step_ms
        while cursor < len(rates) and rates[cursor].ts_ms < start_ms:
            cursor += 1
        index = cursor
        total = 0.0
        while index < len(rates) and rates[index].ts_ms < end_ms:
            total += rates[index].rate
            index += 1
        out[bar.ts_ms] = total
    out[bars[-1].ts_ms] = 0.0
    return out
