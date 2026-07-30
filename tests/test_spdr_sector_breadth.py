from __future__ import annotations

import unittest

from qount.l3_information_edge import SupplyPoint
from qount.spdr_sector_breadth import SPDR_SECTOR_ETFS, build_spdr_sector_breadth_report


class SpdrSectorBreadthTests(unittest.TestCase):
    def _series(self) -> dict[str, list[SupplyPoint]]:
        return {
            ticker: [
                SupplyPoint(1_700_000_000_000 + day * 86_400_000, 100.0 + offset + day * (1.0 + offset / 20.0))
                for day in range(30)
            ]
            for offset, ticker in enumerate(SPDR_SECTOR_ETFS)
        }

    def test_report_is_no_pnl_and_has_exact_universe(self) -> None:
        report = build_spdr_sector_breadth_report(self._series(), cache_manifest=[])
        self.assertEqual(report["contract"]["universe"], list(SPDR_SECTOR_ETFS))
        self.assertFalse(report["meta"]["pnl_evaluated"])
        self.assertFalse(report["meta"]["ml_allowed"])
        self.assertFalse(report["meta"]["orders_authorized"])

    def test_missing_ticker_fails_closed(self) -> None:
        series = self._series()
        series.pop("XLC")
        with self.assertRaisesRegex(ValueError, "universe must be exact"):
            build_spdr_sector_breadth_report(series, cache_manifest=[])


if __name__ == "__main__":
    unittest.main()
