"""RV-C market data: Binance COIN-M dated quarterly futures (data.binance.vision).

The cash-and-carry short leg is a **dated quarterly** COIN-M contract, e.g. ``BTCUSD_210625``
(settles 2021-06-25). Binance lists quarterly futures expiring 08:00 UTC on the **last Friday
of Mar/Jun/Sep/Dec**. Their public monthly kline dumps live under the ``futures/cm`` tree:

    data/futures/cm/monthly/klines/{SYMBOL}/{interval}/{SYMBOL}-{interval}-{YYYY}-{MM}.zip

We reuse line B's pure parsers (``grid.data.parse_zip_bytes`` / ``Bar``) and its cached,
injectable-fetcher download (tests never hit the network). The spot leg uses ``grid.data``'s
spot loader directly (``BTCUSDT`` etc.). Caches live under ``state/rv_c/`` so line B's
``state/grid_b/`` glob is never touched (研究用独立缓存, per the cross-line discipline).
"""

from __future__ import annotations

import calendar as _cal
import datetime as _dt
from typing import Callable

from qount.grid.data import Bar
from qount.grid.data import _cached_download
from qount.grid.data import parse_zip_bytes

DEFAULT_CACHE_DIR = "state/rv_c/klines"
_BASE = "https://data.binance.vision/data"
_CM = "futures/cm"


def last_friday(year: int, month: int) -> _dt.date:
    """Date of the last Friday of ``year``/``month`` (Binance quarterly settlement day)."""

    if month == 12:
        first_next = _dt.date(year + 1, 1, 1)
    else:
        first_next = _dt.date(year, month + 1, 1)
    d = first_next - _dt.timedelta(days=1)
    while d.weekday() != 4:  # Mon=0 .. Fri=4
        d -= _dt.timedelta(days=1)
    return d


def expiry_ms(expiry_date: _dt.date) -> int:
    """Epoch-ms of an 08:00 UTC settlement on ``expiry_date``."""

    dt = _dt.datetime(
        expiry_date.year, expiry_date.month, expiry_date.day, 8, 0, 0, tzinfo=_dt.UTC
    )
    return int(dt.timestamp() * 1000)


def dated_symbol(base: str, expiry_date: _dt.date) -> str:
    """COIN-M dated symbol, e.g. ``BTCUSD`` + 2021-06-25 -> ``BTCUSD_210625``."""

    return f"{base}_{expiry_date.strftime('%y%m%d')}"


def quarterly_contracts(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    base: str = "BTCUSD",
) -> list[tuple[str, int]]:
    """Quarterly contracts whose expiry falls in ``[start, end]`` (inclusive ``(year, month)``).

    Returns ``[(symbol, expiry_ms), ...]`` ascending. Quarterly = Mar/Jun/Sep/Dec, last Friday.
    """

    out: list[tuple[str, int]] = []
    (sy, sm), (ey, em) = start, end
    for year in range(sy, ey + 1):
        for month in (3, 6, 9, 12):
            if (year, month) < (sy, sm) or (year, month) > (ey, em):
                continue
            exp = last_friday(year, month)
            out.append((dated_symbol(base, exp), expiry_ms(exp)))
    return out


def dated_month_url(symbol: str, interval: str, year: int, month: int) -> str:
    name = f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
    return f"{_BASE}/{_CM}/monthly/klines/{symbol}/{interval}/{name}"


def dated_day_url(symbol: str, interval: str, year: int, month: int, day: int) -> str:
    name = f"{symbol}-{interval}-{year:04d}-{month:02d}-{day:02d}.zip"
    return f"{_BASE}/{_CM}/daily/klines/{symbol}/{interval}/{name}"


def download_dated_day(
    symbol: str,
    interval: str,
    year: int,
    month: int,
    day: int,
    *,
    cache_dir: str = DEFAULT_CACHE_DIR,
    fetch: Callable[[str], bytes] | None = None,
) -> bytes:
    """Return one dated contract's per-day kline zip bytes, caching to ``cache_dir``.

    Fills the in-progress month, whose monthly dump only publishes after month-end (Binance DOES
    publish per-day dated dumps -- verified 2026-06). A past day's dump is immutable -> cacheable.
    """

    name = f"cm-{symbol}-{interval}-{year:04d}-{month:02d}-{day:02d}.zip"
    return _cached_download(
        dated_day_url(symbol, interval, year, month, day), name, cache_dir, fetch
    )


def _download_dated_month_daily(
    symbol: str,
    interval: str,
    year: int,
    month: int,
    *,
    cache_dir: str,
    fetch: Callable[[str], bytes] | None,
) -> list[Bar]:
    """Assemble a dated contract's month from per-day dumps (fallback when the monthly zip is absent).

    Mirrors line B's ``grid.data._download_month_daily`` (§18). Iterates only days up to today (UTC);
    future days and today-before-publish 404 and are skipped. Returns ``[]`` when nothing is available
    (e.g. an unlisted month), so ``load_dated_klines`` falls back to its normal missing handling.
    """

    today = _dt.datetime.now(_dt.UTC).date()
    if (year, month) > (today.year, today.month):
        return []
    last_day = today.day if (year, month) == (today.year, today.month) else _cal.monthrange(year, month)[1]
    bars: list[Bar] = []
    for day in range(1, last_day + 1):
        try:
            blob = download_dated_day(symbol, interval, year, month, day,
                                      cache_dir=cache_dir, fetch=fetch)
        except Exception:
            continue  # this day's dump not published yet (or genuinely missing)
        bars.extend(parse_zip_bytes(blob))
    return bars


def _iter_months(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    ey, em = end
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def load_dated_klines(
    symbol: str,
    *,
    start: tuple[int, int],
    end: tuple[int, int],
    interval: str = "1d",
    cache_dir: str = DEFAULT_CACHE_DIR,
    fetch: Callable[[str], bytes] | None = None,
    skip_missing: bool = True,
) -> list[Bar]:
    """Load one dated COIN-M contract's bars over ``[start, end]`` months (ascending, dedup).

    A quarterly only trades for a window before its expiry, so months outside its listing are
    expected to 404 -- ``skip_missing`` defaults ``True`` here (unlike spot/um).
    """

    today = _dt.datetime.now(_dt.UTC).date()
    seen: dict[int, Bar] = {}
    for year, month in _iter_months(start, end):
        name = f"cm-{symbol}-{interval}-{year:04d}-{month:02d}.zip"
        try:
            blob = _cached_download(
                dated_month_url(symbol, interval, year, month), name, cache_dir, fetch
            )
        except Exception:
            # The in-progress current month has no monthly dump yet -> assemble from per-day dumps
            # (§18 pattern). Only the current month; past 404s are unlisted contract months, where the
            # daily fallback would just 404 too. A genuinely-listed current month gives daily refresh.
            if (year, month) == (today.year, today.month):
                for bar in _download_dated_month_daily(symbol, interval, year, month,
                                                       cache_dir=cache_dir, fetch=fetch):
                    seen[bar.ts_ms] = bar
                continue
            if skip_missing:
                continue
            raise
        for bar in parse_zip_bytes(blob):
            seen[bar.ts_ms] = bar
    return [seen[ts] for ts in sorted(seen)]


def load_contract_set(
    *,
    start: tuple[int, int],
    end: tuple[int, int],
    base: str = "BTCUSD",
    listing_lookback_months: int = 7,
    interval: str = "1d",
    cache_dir: str = DEFAULT_CACHE_DIR,
    fetch: Callable[[str], bytes] | None = None,
) -> dict[int, list[Bar]]:
    """Load every quarterly contract expiring in ``[start, end]`` -> ``{expiry_ms: bars}``.

    Each contract is pulled over the ``listing_lookback_months`` months ending at its expiry
    month (covering its full listed life), ready for :func:`qount.rv.basis.build_active_series`.
    """

    out: dict[int, list[Bar]] = {}
    for symbol, exp_ms in quarterly_contracts(start, end, base=base):
        exp_date = _dt.datetime.fromtimestamp(exp_ms / 1000, _dt.UTC).date()
        first = exp_date.year * 12 + (exp_date.month - 1) - (listing_lookback_months - 1)
        c_start = (first // 12, first % 12 + 1)
        bars = load_dated_klines(
            symbol,
            start=c_start,
            end=(exp_date.year, exp_date.month),
            interval=interval,
            cache_dir=cache_dir,
            fetch=fetch,
        )
        if bars:
            out[exp_ms] = bars
    return out
