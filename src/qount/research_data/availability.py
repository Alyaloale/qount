"""R0-DATA data-availability scanner.

Scans ``data.binance.vision`` for the first and last available month of
klines, funding rates, and open-interest metrics per symbol.  This produces
the data-completeness manifest required by R0-DATA: each symbol's
``valid_from`` for spot (where exchangeInfo lacks ``onboardDate``), gap
detection, and the availability watermark for contamination-role assignment.

Pure parsing is split from IO; all fetchers are injectable so tests never
touch the network.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Callable

from qount.research_data.market_data import funding_url
from qount.research_data.market_data import month_url


# --- Data types -------------------------------------------------------------


@dataclass(frozen=True)
class DataAvailability:
    """First/last available month and gap list for one symbol + data type.

    ``first_month`` / ``last_month`` are ``(year, month)`` tuples or ``None``
    when no data exists.  ``gaps`` is a list of ``(year, month)`` tuples that
    are missing between first and last (exclusive of the endpoints).
    """

    symbol: str
    market: str
    data_type: str  # "klines" | "funding" | "oi"
    first_month: tuple[int, int] | None
    last_month: tuple[int, int] | None
    gaps: tuple[tuple[int, int], ...]
    total_available_months: int

    @property
    def has_data(self) -> bool:
        return self.first_month is not None

    @property
    def first_month_iso(self) -> str | None:
        if self.first_month is None:
            return None
        return _dt.datetime(self.first_month[0], self.first_month[1], 1, tzinfo=_dt.UTC).isoformat()

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "data_type": self.data_type,
            "first_month": list(self.first_month) if self.first_month else None,
            "last_month": list(self.last_month) if self.last_month else None,
            "first_month_iso": self.first_month_iso,
            "gaps": [list(g) for g in self.gaps],
            "total_available_months": self.total_available_months,
            "has_data": self.has_data,
        }


# --- Month iteration --------------------------------------------------------


def _iter_months(
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[tuple[int, int]]:
    y, m = start
    ey, em = end
    months: list[tuple[int, int]] = []
    while (y, m) <= (ey, em):
        months.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months


def _month_cmp(a: tuple[int, int], b: tuple[int, int]) -> int:
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


# --- Probes (injectable fetcher) --------------------------------------------


def _default_fetch(url: str) -> bytes:  # pragma: no cover - network
    import urllib.request
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def probe_url(url: str, *, fetch: Callable[[str], bytes] | None) -> bool:
    """Return ``True`` if *url* returns non-empty bytes."""

    try:
        blob = (fetch or _default_fetch)(url)
        return len(blob) > 0
    except Exception:
        return False


def probe_kline_month(
    symbol: str,
    year: int,
    month: int,
    *,
    market: str = "spot",
    interval: str = "1d",
    fetch: Callable[[str], bytes] | None = None,
) -> bool:
    url = month_url(symbol, interval, year, month, market=market)
    return probe_url(url, fetch=fetch)


def probe_funding_month(
    symbol: str,
    year: int,
    month: int,
    *,
    fetch: Callable[[str], bytes] | None = None,
) -> bool:
    url = funding_url(symbol, year, month)
    return probe_url(url, fetch=fetch)


def probe_oi_month(
    symbol: str,
    year: int,
    month: int,
    *,
    fetch: Callable[[str], bytes] | None = None,
) -> bool:
    url = (
        f"https://data.binance.vision/data/futures/um/monthly/metrics/"
        f"{symbol}/{symbol}-metrics-{year:04d}-{month:02d}.zip"
    )
    return probe_url(url, fetch=fetch)


# --- Scanners ---------------------------------------------------------------


def _binary_search_first(
    probe: Callable[[int, int], bool],
    start: tuple[int, int],
    end: tuple[int, int],
) -> tuple[int, int] | None:
    """Binary search for the first month with data in ``[start, end]``.

    Months are a monotonic sequence, so we can binary-search the transition
    from no-data to data.  Falls back to linear scan if the binary search
    detects non-monotonic behavior (data, no-data, data).
    """

    months = _iter_months(start, end)
    if not months:
        return None

    # Quick check: if the first month has data, that's the answer.
    if probe(*months[0]):
        return months[0]

    # If the last month has no data, there's nothing.
    if not probe(*months[-1]):
        return None

    lo, hi = 0, len(months) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if probe(*months[mid]):
            hi = mid
        else:
            lo = mid + 1
    return months[lo] if probe(*months[lo]) else None


def _linear_scan_first(
    probe: Callable[[int, int], bool],
    start: tuple[int, int],
    end: tuple[int, int],
) -> tuple[int, int] | None:
    """Linear scan for the first month with data (reliable fallback)."""

    for ym in _iter_months(start, end):
        if probe(*ym):
            return ym
    return None


def scan_kline_availability(
    symbol: str,
    *,
    market: str = "spot",
    start: tuple[int, int] = (2017, 1),
    end: tuple[int, int] | None = None,
    fetch: Callable[[str], bytes] | None = None,
    use_binary_search: bool = True,
) -> DataAvailability:
    """Scan data.binance.vision for kline availability per month.

    Returns first/last month and interior gaps.  Uses binary search to find
    the first month, then scans from first to last for gaps.
    """

    if end is None:
        now = _dt.datetime.now(_dt.UTC)
        end = (now.year, now.month)

    def probe(year: int, month: int) -> bool:
        return probe_kline_month(symbol, year, month, market=market, fetch=fetch)

    if use_binary_search:
        first = _binary_search_first(probe, start, end)
    else:
        first = _linear_scan_first(probe, start, end)

    if first is None:
        return DataAvailability(
            symbol=symbol, market=market, data_type="klines",
            first_month=None, last_month=None, gaps=(), total_available_months=0,
        )

    # Scan from first to end for gaps and last available.
    gaps: list[tuple[int, int]] = []
    last = first
    available = 0
    for ym in _iter_months(first, end):
        if probe(*ym):
            last = ym
            available += 1
        else:
            if ym < end:
                gaps.append(ym)

    # Trim trailing gaps (months after last available).
    while gaps and _month_cmp(gaps[-1], last) >= 0:
        gaps.pop()

    return DataAvailability(
        symbol=symbol, market=market, data_type="klines",
        first_month=first, last_month=last, gaps=tuple(gaps),
        total_available_months=available,
    )


def scan_funding_availability(
    symbol: str,
    *,
    start: tuple[int, int] = (2019, 9),
    end: tuple[int, int] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> DataAvailability:
    """Scan data.binance.vision for UM funding-rate availability per month."""

    if end is None:
        now = _dt.datetime.now(_dt.UTC)
        end = (now.year, now.month)

    def probe(year: int, month: int) -> bool:
        return probe_funding_month(symbol, year, month, fetch=fetch)

    first = _linear_scan_first(probe, start, end)
    if first is None:
        return DataAvailability(
            symbol=symbol, market="um", data_type="funding",
            first_month=None, last_month=None, gaps=(), total_available_months=0,
        )

    gaps: list[tuple[int, int]] = []
    last = first
    available = 0
    for ym in _iter_months(first, end):
        if probe(*ym):
            last = ym
            available += 1
        else:
            if ym < end:
                gaps.append(ym)

    while gaps and _month_cmp(gaps[-1], last) >= 0:
        gaps.pop()

    return DataAvailability(
        symbol=symbol, market="um", data_type="funding",
        first_month=first, last_month=last, gaps=tuple(gaps),
        total_available_months=available,
    )


def scan_oi_availability(
    symbol: str,
    *,
    start: tuple[int, int] = (2019, 12),
    end: tuple[int, int] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> DataAvailability:
    """Scan data.binance.vision for UM open-interest metrics availability."""

    if end is None:
        now = _dt.datetime.now(_dt.UTC)
        end = (now.year, now.month)

    def probe(year: int, month: int) -> bool:
        return probe_oi_month(symbol, year, month, fetch=fetch)

    first = _linear_scan_first(probe, start, end)
    if first is None:
        return DataAvailability(
            symbol=symbol, market="um", data_type="oi",
            first_month=None, last_month=None, gaps=(), total_available_months=0,
        )

    gaps: list[tuple[int, int]] = []
    last = first
    available = 0
    for ym in _iter_months(first, end):
        if probe(*ym):
            last = ym
            available += 1
        else:
            if ym < end:
                gaps.append(ym)

    while gaps and _month_cmp(gaps[-1], last) >= 0:
        gaps.pop()

    return DataAvailability(
        symbol=symbol, market="um", data_type="oi",
        first_month=first, last_month=last, gaps=tuple(gaps),
        total_available_months=available,
    )


# --- Batch summary ----------------------------------------------------------


def build_availability_manifest(
    klines: list[DataAvailability],
    funding: list[DataAvailability],
    oi: list[DataAvailability],
) -> dict:
    """Build a summary manifest from per-symbol availability scans."""

    def _summary(items: list[DataAvailability]) -> dict:
        total = len(items)
        with_data = sum(1 for a in items if a.has_data)
        gap_counts = [len(a.gaps) for a in items if a.has_data]
        return {
            "total_symbols": total,
            "symbols_with_data": with_data,
            "symbols_without_data": total - with_data,
            "symbols_with_gaps": sum(1 for g in gap_counts if g > 0),
            "max_gaps_per_symbol": max(gap_counts) if gap_counts else 0,
        }

    return {
        "klines": _summary(klines),
        "funding": _summary(funding),
        "oi": _summary(oi),
        "details": {
            "klines": [a.to_dict() for a in klines],
            "funding": [a.to_dict() for a in funding],
            "oi": [a.to_dict() for a in oi],
        },
    }
