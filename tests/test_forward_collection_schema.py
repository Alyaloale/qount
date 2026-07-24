from __future__ import annotations

import unittest

from qount.mini_trend.forward_collection_schema import (
    ALL_FORWARD_CONTRACTS,
    BASIS_CURVE_FORWARD,
    CROSS_VENUE_FORWARD,
    LIQUIDATION_CASCADE_FORWARD,
    OI_FLOW_FORWARD,
    build_forward_schema_report,
)


class ForwardCollectionSchemaTests(unittest.TestCase):
    def test_four_families_defined(self) -> None:
        families = {c.family for c in ALL_FORWARD_CONTRACTS}
        self.assertEqual(families, {
            "oi_flow_forward_v1",
            "basis_curve_dislocation_v1",
            "liquidation_cascade_forward_v1",
            "cross_venue_price_discovery_v1",
        })

    def test_no_results_read_before_window(self) -> None:
        for contract in ALL_FORWARD_CONTRACTS:
            self.assertFalse(contract.read_results_before_window)

    def test_cross_venue_includes_bybit_and_okx(self) -> None:
        self.assertIn("binance", CROSS_VENUE_FORWARD.venues)
        self.assertIn("bybit", CROSS_VENUE_FORWARD.venues)
        self.assertIn("okx", CROSS_VENUE_FORWARD.venues)

    def test_liquidation_has_no_official_archive(self) -> None:
        self.assertIn("no official historical archive", LIQUIDATION_CASCADE_FORWARD.official_history_limit)

    def test_oi_history_limit_is_one_month(self) -> None:
        self.assertIn("1 month", OI_FLOW_FORWARD.official_history_limit)

    def test_basis_history_limit_is_30_days(self) -> None:
        self.assertIn("30 days", BASIS_CURVE_FORWARD.official_history_limit)

    def test_report_produces_no_pnl_or_direction(self) -> None:
        report = build_forward_schema_report("2026-07-25T00:00:00+00:00")
        self.assertFalse(report["meta"]["direction_produced"])
        self.assertFalse(report["meta"]["pnl_evaluated"])
        self.assertFalse(report["meta"]["candidate_pnl_ready"])
        self.assertEqual(len(report["contracts"]), 4)
        for contract in report["contracts"]:
            self.assertEqual(contract["verdict"], "continue_collection")

    def test_contract_hashes_are_stable_and_distinct(self) -> None:
        hashes = {c.contract_hash for c in ALL_FORWARD_CONTRACTS}
        self.assertEqual(len(hashes), 4)


if __name__ == "__main__":
    unittest.main()
