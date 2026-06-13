"""Unit tests for RV-C COIN-M dated-futures data layer (线 C). Plan: §4.

Offline only: the quarterly expiry calendar (last Friday), symbol/URL construction, and the
cached loader driven by an injected fetcher (never hits the network) with 404 tolerance.
"""

from __future__ import annotations

import datetime as _dt
import io
import tempfile
import unittest
import zipfile

from qount.rv.data import dated_month_url
from qount.rv.data import dated_symbol
from qount.rv.data import expiry_ms
from qount.rv.data import last_friday
from qount.rv.data import load_dated_klines
from qount.rv.data import quarterly_contracts


def _kline_zip(rows: list[tuple[int, float]]) -> bytes:
    """Build a Binance-vision-style kline zip (open_time_ms, o,h,l,c,v,...) from (ts, close)."""

    lines = [f"{ts},{c},{c},{c},{c},1.0,{ts + 1},0,0,0,0,0" for ts, c in rows]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.csv", "\n".join(lines))
    return buf.getvalue()


class TestQuarterlyCalendar(unittest.TestCase):
    def test_last_friday_known_dates(self) -> None:
        # Binance quarterlies: BTCUSD_210625, _210924, _211231, _220325
        self.assertEqual(last_friday(2021, 6), _dt.date(2021, 6, 25))
        self.assertEqual(last_friday(2021, 9), _dt.date(2021, 9, 24))
        self.assertEqual(last_friday(2021, 12), _dt.date(2021, 12, 31))
        self.assertEqual(last_friday(2022, 3), _dt.date(2022, 3, 25))

    def test_dated_symbol_format(self) -> None:
        self.assertEqual(dated_symbol("BTCUSD", _dt.date(2021, 6, 25)), "BTCUSD_210625")
        self.assertEqual(dated_symbol("ETHUSD", _dt.date(2021, 12, 31)), "ETHUSD_211231")

    def test_expiry_ms_is_0800_utc(self) -> None:
        ms = expiry_ms(_dt.date(2021, 6, 25))
        dt = _dt.datetime.fromtimestamp(ms / 1000, _dt.UTC)
        self.assertEqual((dt.hour, dt.minute), (8, 0))
        self.assertEqual(dt.date(), _dt.date(2021, 6, 25))

    def test_quarterly_contracts_range(self) -> None:
        cs = quarterly_contracts((2021, 1), (2021, 12), base="BTCUSD")
        syms = [s for s, _ in cs]
        self.assertEqual(syms, ["BTCUSD_210326", "BTCUSD_210625", "BTCUSD_210924", "BTCUSD_211231"])
        # ascending expiries
        exps = [e for _, e in cs]
        self.assertEqual(exps, sorted(exps))


class TestUrlConstruction(unittest.TestCase):
    def test_dated_month_url(self) -> None:
        url = dated_month_url("BTCUSD_210625", "1d", 2021, 5)
        self.assertEqual(
            url,
            "https://data.binance.vision/data/futures/cm/monthly/klines/"
            "BTCUSD_210625/1d/BTCUSD_210625-1d-2021-05.zip",
        )


class TestLoadDatedKlines(unittest.TestCase):
    def test_injected_fetch_parses_and_dedups(self) -> None:
        t0 = 1_609_459_200_000
        calls: list[str] = []

        def fake_fetch(url: str) -> bytes:
            calls.append(url)
            # one bar per month requested
            return _kline_zip([(t0, 100.0)])

        with tempfile.TemporaryDirectory() as d:
            bars = load_dated_klines(
                "BTCUSD_210625", start=(2021, 1), end=(2021, 2),
                cache_dir=d, fetch=fake_fetch,
            )
        self.assertEqual(len(bars), 1)  # dedup on ts_ms across the two months
        self.assertEqual(bars[0].close, 100.0)
        self.assertEqual(len(calls), 2)  # two months fetched

    def test_skip_missing_tolerates_404(self) -> None:
        def boom(url: str) -> bytes:
            raise RuntimeError("404")

        with tempfile.TemporaryDirectory() as d:
            bars = load_dated_klines(
                "BTCUSD_210625", start=(2021, 1), end=(2021, 3),
                cache_dir=d, fetch=boom, skip_missing=True,
            )
        self.assertEqual(bars, [])

    def test_caches_blob(self) -> None:
        t0 = 1_609_459_200_000
        calls: list[str] = []

        def fake_fetch(url: str) -> bytes:
            calls.append(url)
            return _kline_zip([(t0, 100.0)])

        with tempfile.TemporaryDirectory() as d:
            load_dated_klines("BTCUSD_210625", start=(2021, 1), end=(2021, 1),
                              cache_dir=d, fetch=fake_fetch)
            load_dated_klines("BTCUSD_210625", start=(2021, 1), end=(2021, 1),
                              cache_dir=d, fetch=fake_fetch)
        self.assertEqual(len(calls), 1)  # second load hits the cache


if __name__ == "__main__":
    unittest.main()
