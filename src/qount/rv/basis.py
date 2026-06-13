"""RV-C basis primitives: annualized basis + point-in-time roll selection (pure, no IO).

This is the StatArb命门 (杀手 1/4 in ``docs/rv-c-plan.md`` §2). Two things must be
**point-in-time clean** or the whole kill-test is a look-ahead artefact:

1. **Roll selection** -- which quarterly contract we are short on a given day. The decision
   at ``ts`` uses only the *fixed* quarterly expiry calendar (known years in advance) and
   whether the contract is actually trading at ``ts`` (data presence). It never peeks at a
   future price. We roll *out* of a contract once it is within ``roll_buffer_days`` of expiry
   (avoid the thin, settlement-pinned final days) into the nearest still-distant quarterly.

2. **Splicing** -- ``build_active_series`` stitches per-contract bars into one continuous
   ``ActiveBar`` stream aligned 1:1 with spot, flagging the bar where the active contract
   changes (``is_roll``). The backtest must *not* book the price gap across a roll as
   directional PnL; the flag is how it knows.

The basis itself (``annualized_basis``) is the edge signal: ``(F/S − 1)`` annualized by days
to expiry. In contango it is the premium a long pays for leverage; the dated future's expiry
convergence (F→S) is what mechanically realizes it into the short leg -- the hard anchor that
H3's perpetual lacked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from typing import Mapping
from typing import Sequence

from qount.grid.data import Bar

_DAY_MS = 86_400_000
_YEAR_DAYS = 365.0


def annualized_basis(
    spot_close: float,
    dated_close: float,
    days_to_expiry: float,
    *,
    year_days: float = _YEAR_DAYS,
) -> float:
    """Annualized basis ``(F/S − 1) × (year_days / days_to_expiry)``.

    Positive = contango (future rich; the long-spot/short-future carry earns it as F→S).
    Returns the raw, *un*-annualized ``F/S − 1`` collapses to ~0 at expiry, so for
    ``days_to_expiry <= 0`` (at/after settlement, convergence forced) we return ``0.0``.
    """

    if spot_close <= 0.0:
        raise ValueError(f"spot_close must be > 0, got {spot_close}")
    if days_to_expiry <= 0.0:
        return 0.0
    raw = dated_close / spot_close - 1.0
    return raw * (year_days / days_to_expiry)


def raw_basis(spot_close: float, dated_close: float) -> float:
    """Un-annualized basis ``F/S − 1``. At expiry this must converge to ~0 (the anchor)."""

    if spot_close <= 0.0:
        raise ValueError(f"spot_close must be > 0, got {spot_close}")
    return dated_close / spot_close - 1.0


def days_to_expiry(ts_ms: int, expiry_ms: int) -> float:
    """Fractional days from bar open ``ts_ms`` to contract ``expiry_ms`` (may be negative)."""

    return (expiry_ms - ts_ms) / _DAY_MS


def active_expiry(
    ts_ms: int,
    expiries: Sequence[int],
    roll_buffer_days: float,
    *,
    is_listed: Callable[[int, int], bool] | None = None,
) -> int | None:
    """The expiry of the contract to hold short at ``ts_ms`` (point-in-time roll rule).

    Picks the **nearest** quarterly whose expiry is more than ``roll_buffer_days`` away (so we
    are never pinned into the illiquid settlement window) and, if ``is_listed`` is given, is
    actually trading at ``ts_ms`` (``is_listed(expiry_ms, ts_ms) -> bool``). Returns ``None``
    when no such contract exists (e.g. past the end of the data). Decision depends only on the
    fixed expiry calendar + listing presence -- never on a future price.
    """

    buf_ms = roll_buffer_days * _DAY_MS
    for e in sorted(expiries):
        if e - ts_ms > buf_ms and (is_listed is None or is_listed(e, ts_ms)):
            return e
    return None


@dataclass(frozen=True)
class ActiveBar:
    """One aligned spot/dated observation for the currently-short quarterly contract.

    ``is_roll`` is ``True`` on the first bar where the active contract differs from the
    previous bar's -- the boundary across which the backtest must close the expiring future
    and open the new one (never booking the price gap as PnL).
    """

    spot: Bar
    dated: Bar
    expiry_ms: int
    is_roll: bool

    @property
    def days_to_expiry(self) -> float:
        return days_to_expiry(self.spot.ts_ms, self.expiry_ms)

    @property
    def annualized_basis(self) -> float:
        return annualized_basis(self.spot.close, self.dated.close, self.days_to_expiry)


def build_active_series(
    spot_bars: Sequence[Bar],
    contracts: Mapping[int, Sequence[Bar]],
    *,
    roll_buffer_days: float = 5.0,
) -> list[ActiveBar]:
    """Splice per-contract dated bars into one continuous active series aligned to spot.

    ``contracts`` maps ``expiry_ms -> bars`` (one quarterly each). For every spot bar we pick
    the active contract via :func:`active_expiry` (point-in-time, requiring a dated bar present
    at that timestamp), and emit an :class:`ActiveBar`. Spot bars with no tradeable contract
    (start of history before any listing, or end past the last roll) are dropped. ``is_roll``
    marks each contract change. No look-ahead: selection uses only ``ts_ms`` + listing presence.
    """

    indexed: dict[int, dict[int, Bar]] = {
        exp: {b.ts_ms: b for b in bars} for exp, bars in contracts.items()
    }
    expiries = sorted(indexed)

    def _listed(expiry_ms: int, ts_ms: int) -> bool:
        return ts_ms in indexed[expiry_ms]

    out: list[ActiveBar] = []
    prev_expiry: int | None = None
    for sb in spot_bars:
        exp = active_expiry(sb.ts_ms, expiries, roll_buffer_days, is_listed=_listed)
        if exp is None:
            continue
        db = indexed[exp][sb.ts_ms]
        out.append(
            ActiveBar(
                spot=sb,
                dated=db,
                expiry_ms=exp,
                is_roll=(prev_expiry is not None and exp != prev_expiry),
            )
        )
        prev_expiry = exp
    return out
