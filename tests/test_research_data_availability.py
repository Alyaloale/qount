"""Unit tests for R0-DATA availability scanning (no network)."""

from __future__ import annotations

import unittest

from qount.research_data.availability import DataAvailability
from qount.research_data.availability import build_availability_manifest
from qount.research_data.availability import probe_funding_month
from qount.research_data.availability import probe_kline_month
from qount.research_data.availability import probe_oi_month
from qount.research_data.availability import scan_funding_availability
from qount.research_data.availability import scan_kline_availability
from qount.research_data.availability import scan_oi_availability


class TestProbes(unittest.TestCase):
    def test_probe_kline_month_true(self) -> None:
        self.assertTrue(probe_kline_month("BTCUSDT", 2024, 1, market="spot", fetch=lambda url: b"data"))

    def test_probe_kline_month_false_on_exception(self) -> None:
        self.assertFalse(probe_kline_month("BTCUSDT", 2024, 1, market="spot", fetch=lambda url: (_ for _ in ()).throw(Exception("404"))))

    def test_probe_kline_month_false_on_empty(self) -> None:
        self.assertFalse(probe_kline_month("BTCUSDT", 2024, 1, market="spot", fetch=lambda url: b""))

    def test_probe_funding_month_true(self) -> None:
        self.assertTrue(probe_funding_month("BTCUSDT", 2024, 1, fetch=lambda url: b"data"))

    def test_probe_oi_month_true(self) -> None:
        self.assertTrue(probe_oi_month("BTCUSDT", 2024, 1, fetch=lambda url: b"data"))


class TestDataAvailability(unittest.TestCase):
    def test_has_data_false_when_no_first(self) -> None:
        avail = DataAvailability(
            symbol="X", market="spot", data_type="klines",
            first_month=None, last_month=None, gaps=(), total_available_months=0,
        )
        self.assertFalse(avail.has_data)
        self.assertIsNone(avail.first_month_iso)

    def test_has_data_true_with_first(self) -> None:
        avail = DataAvailability(
            symbol="X", market="spot", data_type="klines",
            first_month=(2021, 1), last_month=(2024, 6), gaps=(), total_available_months=42,
        )
        self.assertTrue(avail.has_data)
        self.assertEqual(avail.first_month_iso, "2021-01-01T00:00:00+00:00")

    def test_to_dict(self) -> None:
        avail = DataAvailability(
            symbol="BTCUSDT", market="spot", data_type="klines",
            first_month=(2021, 1), last_month=(2024, 6),
            gaps=((2022, 3),), total_available_months=41,
        )
        d = avail.to_dict()
        self.assertEqual(d["symbol"], "BTCUSDT")
        self.assertEqual(d["first_month"], [2021, 1])
        self.assertEqual(d["last_month"], [2024, 6])
        self.assertEqual(d["gaps"], [[2022, 3]])
        self.assertTrue(d["has_data"])


class TestScanKlineAvailability(unittest.TestCase):
    def test_scan_with_continuous_data(self) -> None:
        def fetch(url: str) -> bytes:
            if any(m in url for m in ["2021-01", "2021-02", "2021-03"]):
                return b"data"
            raise Exception("404")

        avail = scan_kline_availability(
            "BTCUSDT", market="spot",
            start=(2021, 1), end=(2021, 3),
            fetch=fetch, use_binary_search=False,
        )
        self.assertEqual(avail.first_month, (2021, 1))
        self.assertEqual(avail.last_month, (2021, 3))
        self.assertEqual(avail.gaps, ())
        self.assertEqual(avail.total_available_months, 3)

    def test_scan_with_gap(self) -> None:
        def fetch(url: str) -> bytes:
            if any(m in url for m in ["2021-01", "2021-03"]):
                return b"data"
            raise Exception("404")

        avail = scan_kline_availability(
            "BTCUSDT", market="spot",
            start=(2021, 1), end=(2021, 3),
            fetch=fetch, use_binary_search=False,
        )
        self.assertEqual(avail.first_month, (2021, 1))
        self.assertEqual(avail.last_month, (2021, 3))
        self.assertEqual(avail.gaps, ((2021, 2),))
        self.assertEqual(avail.total_available_months, 2)

    def test_scan_no_data(self) -> None:
        avail = scan_kline_availability(
            "NOSUCH", market="spot",
            start=(2021, 1), end=(2021, 3),
            fetch=lambda url: (_ for _ in ()).throw(Exception("404")),
            use_binary_search=False,
        )
        self.assertFalse(avail.has_data)
        self.assertIsNone(avail.first_month)

    def test_scan_with_binary_search(self) -> None:
        def fetch(url: str) -> bytes:
            if any(m in url for m in ["2021-03", "2021-04", "2021-05", "2021-06"]):
                return b"data"
            raise Exception("404")

        avail = scan_kline_availability(
            "BTCUSDT", market="spot",
            start=(2021, 1), end=(2021, 6),
            fetch=fetch, use_binary_search=True,
        )
        self.assertEqual(avail.first_month, (2021, 3))
        self.assertEqual(avail.last_month, (2021, 6))

    def test_trailing_months_not_counted_as_gaps(self) -> None:
        def fetch(url: str) -> bytes:
            if any(m in url for m in ["2021-01", "2021-02"]):
                return b"data"
            raise Exception("404")

        avail = scan_kline_availability(
            "BTCUSDT", market="spot",
            start=(2021, 1), end=(2021, 6),
            fetch=fetch, use_binary_search=False,
        )
        self.assertEqual(avail.first_month, (2021, 1))
        self.assertEqual(avail.last_month, (2021, 2))
        # Months 3-6 are after last available, not interior gaps.
        self.assertEqual(avail.gaps, ())


class TestScanFundingAvailability(unittest.TestCase):
    def test_scan_funding(self) -> None:
        def fetch(url: str) -> bytes:
            if any(m in url for m in ["2020-01", "2020-02"]):
                return b"data"
            raise Exception("404")

        avail = scan_funding_availability(
            "BTCUSDT", start=(2020, 1), end=(2020, 3), fetch=fetch,
        )
        self.assertEqual(avail.first_month, (2020, 1))
        self.assertEqual(avail.last_month, (2020, 2))
        self.assertEqual(avail.data_type, "funding")
        self.assertEqual(avail.market, "um")


class TestScanOiAvailability(unittest.TestCase):
    def test_scan_oi(self) -> None:
        def fetch(url: str) -> bytes:
            if "2020-06" in url:
                return b"data"
            raise Exception("404")

        avail = scan_oi_availability(
            "BTCUSDT", start=(2020, 1), end=(2020, 6), fetch=fetch,
        )
        self.assertEqual(avail.first_month, (2020, 6))
        self.assertEqual(avail.data_type, "oi")


class TestBuildAvailabilityManifest(unittest.TestCase):
    def test_manifest(self) -> None:
        klines = [
            DataAvailability("BTCUSDT", "spot", "klines", (2021, 1), (2024, 6), (), 42),
            DataAvailability("ETHUSDT", "spot", "klines", (2017, 8), (2024, 6), ((2018, 3),), 80),
            DataAvailability("NOSUCH", "spot", "klines", None, None, (), 0),
        ]
        funding = [
            DataAvailability("BTCUSDT", "um", "funding", (2019, 9), (2024, 6), (), 58),
        ]
        oi = [
            DataAvailability("BTCUSDT", "um", "oi", (2019, 12), (2024, 6), (), 55),
        ]
        manifest = build_availability_manifest(klines, funding, oi)
        self.assertEqual(manifest["klines"]["total_symbols"], 3)
        self.assertEqual(manifest["klines"]["symbols_with_data"], 2)
        self.assertEqual(manifest["klines"]["symbols_without_data"], 1)
        self.assertEqual(manifest["klines"]["symbols_with_gaps"], 1)
        self.assertEqual(manifest["funding"]["total_symbols"], 1)
        self.assertEqual(manifest["oi"]["total_symbols"], 1)
        self.assertEqual(len(manifest["details"]["klines"]), 3)


if __name__ == "__main__":
    unittest.main()
