"""Unit tests for the GRID-B Binance-vision kline loader (no network)."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile

from qount.grid.data import Bar
from qount.grid.data import Funding
from qount.grid.data import day_url
from qount.grid.data import download_month
from qount.grid.data import funding_url
from qount.grid.data import load_funding
from qount.grid.data import load_klines
from qount.grid.data import month_url
from qount.grid.data import parse_funding_csv
from qount.grid.data import parse_kline_csv
from qount.grid.data import parse_zip_bytes

# A couple of real Binance-vision rows (BTCUSDT 1d, 2021-01) -- header-less layout.
_ROW0 = "1609459200000,28923.63,29600.00,28624.57,29331.69,54182.92,1609545599999,0,0,0,0,0"
_ROW1 = "1609545600000,29331.70,33300.00,28946.53,32178.33,129993.87,1609631999999,0,0,0,0,0"


def _make_zip(csv_text: str, name: str = "k.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


class TestParsing(unittest.TestCase):
    def test_parses_headerless_rows(self) -> None:
        bars = parse_kline_csv("\n".join([_ROW0, _ROW1]))
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].ts_ms, 1609459200000)
        self.assertAlmostEqual(bars[0].open, 28923.63)
        self.assertAlmostEqual(bars[0].high, 29600.00)
        self.assertAlmostEqual(bars[1].close, 32178.33)
        self.assertEqual(bars[0].date, "2021-01-01")

    def test_normalizes_microsecond_timestamps(self) -> None:
        # Binance 2025+ dumps use microseconds; must normalize to ms (else year overflows).
        micro = "1609459200000000,28923.63,29600,28624.57,29331.69,54182.92,0,0,0,0,0,0"
        bars = parse_kline_csv(micro)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].ts_ms, 1609459200000)
        self.assertEqual(bars[0].date, "2021-01-01")

    def test_skips_header_and_blank_lines(self) -> None:
        text = "open_time,open,high,low,close,volume,x\n\n" + _ROW0 + "\n"
        bars = parse_kline_csv(text)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].ts_ms, 1609459200000)

    def test_parse_zip_bytes(self) -> None:
        bars = parse_zip_bytes(_make_zip(_ROW0 + "\n" + _ROW1))
        self.assertEqual(len(bars), 2)

    def test_url_shape(self) -> None:
        self.assertEqual(
            month_url("BTCUSDT", "1d", 2021, 3),
            "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2021-03.zip",
        )

    def test_um_kline_url(self) -> None:
        self.assertEqual(
            month_url("DOGEUSDT", "1h", 2022, 5, market="um"),
            "https://data.binance.vision/data/futures/um/monthly/klines/"
            "DOGEUSDT/1h/DOGEUSDT-1h-2022-05.zip",
        )

    def test_funding_url_shape(self) -> None:
        self.assertEqual(
            funding_url("DOGEUSDT", 2022, 5),
            "https://data.binance.vision/data/futures/um/monthly/fundingRate/"
            "DOGEUSDT/DOGEUSDT-fundingRate-2022-05.zip",
        )

    def test_day_url_shape(self) -> None:
        self.assertEqual(
            day_url("BTCUSDT", "1d", 2026, 6, 12, market="um"),
            "https://data.binance.vision/data/futures/um/daily/klines/"
            "BTCUSDT/1d/BTCUSDT-1d-2026-06-12.zip",
        )


# Real-shape funding rows: calc_time_ms, funding_interval_hours, last_funding_rate
_FROW0 = "1609459200000,8,0.00010000"
_FROW1 = "1609488000000,8,-0.00005000"


class TestFunding(unittest.TestCase):
    def test_parse_funding_csv(self) -> None:
        rows = parse_funding_csv("\n".join([_FROW0, _FROW1]))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].ts_ms, 1609459200000)
        self.assertAlmostEqual(rows[0].rate, 0.0001)
        self.assertAlmostEqual(rows[1].rate, -0.00005)

    def test_parse_funding_skips_header(self) -> None:
        text = "calc_time,funding_interval_hours,last_funding_rate\n" + _FROW0
        rows = parse_funding_csv(text)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].rate, 0.0001)

    def test_parse_funding_normalizes_microseconds(self) -> None:
        micro = "1609459200000000,8,0.0001"
        rows = parse_funding_csv(micro)
        self.assertEqual(rows[0].ts_ms, 1609459200000)

    def test_parse_funding_two_column_layout(self) -> None:
        # older dumps: calc_time, last_funding_rate (no interval column) -> rate is last col
        rows = parse_funding_csv("1609459200000,0.0001")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].rate, 0.0001)

    def test_load_funding_sorted_dedup(self) -> None:
        frow2 = "1612137600000,8,0.0002"

        def fake_fetch(url: str) -> bytes:
            if "2021-01" in url:
                return _make_zip(_FROW0 + "\n" + _FROW1)
            if "2021-02" in url:
                return _make_zip(_FROW1 + "\n" + frow2)  # _FROW1 re-emitted (dup)
            raise FileNotFoundError(url)

        with tempfile.TemporaryDirectory() as d:
            rows = load_funding("DOGEUSDT", start=(2021, 1), end=(2021, 2),
                                cache_dir=d, fetch=fake_fetch)
        ts = [r.ts_ms for r in rows]
        self.assertEqual(ts, sorted(ts))
        self.assertEqual(len(set(ts)), len(ts))
        self.assertEqual(len(rows), 3)


class TestIO(unittest.TestCase):
    def test_download_caches_and_reuses(self) -> None:
        calls: list[str] = []

        def fake_fetch(url: str) -> bytes:
            calls.append(url)
            return _make_zip(_ROW0)

        with tempfile.TemporaryDirectory() as d:
            b1 = download_month("BTCUSDT", "1d", 2021, 1, cache_dir=d, fetch=fake_fetch)
            b2 = download_month("BTCUSDT", "1d", 2021, 1, cache_dir=d, fetch=fake_fetch)
            self.assertEqual(b1, b2)
            self.assertEqual(len(calls), 1)  # second call served from cache

    def test_load_klines_spans_months_sorted_dedup(self) -> None:
        # month 1 has ROW0+ROW1; month 2 re-emits ROW1 (dup) + a later bar
        row2 = "1612137600000,33000,40000,30000,38000,100,1612223999999,0,0,0,0,0"

        def fake_fetch(url: str) -> bytes:
            if "2021-01" in url:
                return _make_zip(_ROW0 + "\n" + _ROW1)
            if "2021-02" in url:
                return _make_zip(_ROW1 + "\n" + row2)
            raise FileNotFoundError(url)

        with tempfile.TemporaryDirectory() as d:
            bars = load_klines("BTCUSDT", "1d", start=(2021, 1), end=(2021, 2),
                               cache_dir=d, fetch=fake_fetch)
        ts = [b.ts_ms for b in bars]
        self.assertEqual(ts, sorted(ts))
        self.assertEqual(len(set(ts)), len(ts))  # deduped
        self.assertEqual(len(bars), 3)

    def test_daily_fallback_when_month_missing(self) -> None:
        # Monthly dump absent (in-progress month); per-day dumps fill it. Using a PAST month
        # so the today-cap iterates the full month deterministically (offline).
        def fake_fetch(url: str) -> bytes:
            if "monthly" in url:
                raise FileNotFoundError(url)  # no monthly zip yet
            if url.endswith("2021-01-01.zip"):
                return _make_zip(_ROW0)
            if url.endswith("2021-01-02.zip"):
                return _make_zip(_ROW1)
            raise FileNotFoundError(url)  # other days not published

        with tempfile.TemporaryDirectory() as d:
            # Even with skip_missing=False the daily fallback yields data -> no raise.
            bars = load_klines("BTCUSDT", "1d", start=(2021, 1), end=(2021, 1),
                               cache_dir=d, fetch=fake_fetch, skip_missing=False)
        ts = [b.ts_ms for b in bars]
        self.assertEqual(len(bars), 2)
        self.assertEqual(ts, sorted(ts))
        self.assertEqual(bars[0].ts_ms, 1609459200000)

    def test_daily_fallback_caches_days(self) -> None:
        calls: list[str] = []

        def fake_fetch(url: str) -> bytes:
            calls.append(url)
            if "monthly" in url:
                raise FileNotFoundError(url)
            if url.endswith("2021-01-01.zip"):
                return _make_zip(_ROW0)
            raise FileNotFoundError(url)

        with tempfile.TemporaryDirectory() as d:
            load_klines("BTCUSDT", "1d", start=(2021, 1), end=(2021, 1),
                        cache_dir=d, fetch=fake_fetch, skip_missing=True)
            n_after_first = len(calls)
            load_klines("BTCUSDT", "1d", start=(2021, 1), end=(2021, 1),
                        cache_dir=d, fetch=fake_fetch, skip_missing=True)
        # The successful day-01 dump is cached -> not re-fetched on the second load.
        day01 = [u for u in calls if u.endswith("2021-01-01.zip")]
        self.assertEqual(len(day01), 1)
        self.assertGreater(n_after_first, 1)

    def test_skip_missing_tolerates_absent_month(self) -> None:
        def fake_fetch(url: str) -> bytes:
            if "2021-01" in url:
                return _make_zip(_ROW0)
            raise FileNotFoundError(url)

        with tempfile.TemporaryDirectory() as d:
            bars = load_klines("BTCUSDT", "1d", start=(2021, 1), end=(2021, 2),
                               cache_dir=d, fetch=fake_fetch, skip_missing=True)
            self.assertEqual(len(bars), 1)
            with self.assertRaises(FileNotFoundError):
                load_klines("BTCUSDT", "1d", start=(2021, 1), end=(2021, 2),
                            cache_dir=d, fetch=fake_fetch, skip_missing=False)


if __name__ == "__main__":
    unittest.main()
