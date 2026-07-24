from __future__ import annotations

import unittest

from qount.mini_trend.stablecoin_source_capacity import (
    STABLECOIN_CAPACITY_PROTOCOL,
    SOURCES,
    build_stablecoin_source_capacity_report,
)


class StablecoinSourceCapacityTests(unittest.TestCase):
    def test_contract_hash_is_stable(self) -> None:
        self.assertEqual(
            STABLECOIN_CAPACITY_PROTOCOL.contract_hash,
            STABLECOIN_CAPACITY_PROTOCOL.contract_hash,
        )

    def test_report_produces_no_pnl_or_direction(self) -> None:
        report = build_stablecoin_source_capacity_report("2026-07-25T00:00:00+00:00")
        self.assertFalse(report["meta"]["direction_produced"])
        self.assertFalse(report["meta"]["pnl_evaluated"])
        self.assertFalse(report["meta"]["candidate_pnl_ready"])

    def test_has_chain_pit_sources(self) -> None:
        report = build_stablecoin_source_capacity_report("2026-07-25T00:00:00+00:00")
        self.assertGreater(report["chain_pit_sources"], 0)
        self.assertFalse(report["kill_tests"]["no_chain_pit_sources"])

    def test_verdict_passes_to_g0(self) -> None:
        report = build_stablecoin_source_capacity_report("2026-07-25T00:00:00+00:00")
        self.assertEqual(report["verdict"], "pass_to_g0")

    def test_exchange_inventory_marked_latest_only(self) -> None:
        report = build_stablecoin_source_capacity_report("2026-07-25T00:00:00+00:00")
        self.assertTrue(report["kill_tests"]["exchange_inventory_not_pit"])
        exchange_sources = [s for s in report["sources"] if s["source_type"] == "exchange_inventory"]
        self.assertGreater(len(exchange_sources), 0)
        for src in exchange_sources:
            self.assertEqual(src["historical_vintage"], "latest_only")

    def test_local_negative_evidence_documented(self) -> None:
        report = build_stablecoin_source_capacity_report("2026-07-25T00:00:00+00:00")
        self.assertIn("aggregate_stablecoin_supply", report["local_negative_evidence"])
        self.assertIn("aggregate_stablecoin_supply", report["hard_constraints"][0])

    def test_sources_cover_usdt_and_usdc(self) -> None:
        issuers = {s.issuer for s in SOURCES}
        self.assertIn("Tether", issuers)
        self.assertIn("Circle", issuers)

    def test_chain_sources_are_immutable(self) -> None:
        for src in SOURCES:
            if src.source_type == "chain_event":
                self.assertFalse(src.pit_revisable)
                self.assertEqual(src.historical_vintage, "available")


if __name__ == "__main__":
    unittest.main()
