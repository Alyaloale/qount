from __future__ import annotations

import unittest

from qount.mini_trend.external_pit_source_capacity import (
    ALL_EXTERNAL_PIT_FAMILIES,
    NETWORK_FAMILY,
    STABLECOIN_FAMILY,
    TOKEN_SUPPLY_FAMILY,
    VENUE_RULE_FAMILY,
    build_external_pit_source_capacity_report,
)


class ExternalPitSourceCapacityTests(unittest.TestCase):
    def test_four_families_defined(self) -> None:
        families = {f.family for f in ALL_EXTERNAL_PIT_FAMILIES}
        self.assertEqual(families, {
            "stablecoin_liquidity_impulse_v1",
            "token_supply_event_v1",
            "network_adoption_quality_v1",
            "venue_rule_event_v1",
        })

    def test_selection_priority_is_pit_vintage_first(self) -> None:
        report = build_external_pit_source_capacity_report("2026-07-25T00:00:00+00:00")
        self.assertEqual(report["selection_priority"], "pit_vintage_availability_first")

    def test_report_produces_no_pnl_or_direction(self) -> None:
        report = build_external_pit_source_capacity_report("2026-07-25T00:00:00+00:00")
        self.assertFalse(report["meta"]["direction_produced"])
        self.assertFalse(report["meta"]["pnl_evaluated"])
        self.assertFalse(report["meta"]["candidate_pnl_ready"])

    def test_at_most_one_family_selected_for_g0(self) -> None:
        report = build_external_pit_source_capacity_report("2026-07-25T00:00:00+00:00")
        selected = report["selected_for_g0"]
        passing = [f for f in report["families"] if f["verdict"] == "pass_to_g0"]
        self.assertLessEqual(len(passing), 4)
        if selected is not None:
            self.assertEqual(len(passing), 1)
            self.assertEqual(passing[0]["family"], selected)

    def test_local_negative_evidence_is_documented(self) -> None:
        self.assertIn("aggregate_stablecoin_supply", STABLECOIN_FAMILY.local_negative_evidence)
        self.assertIn("hashrate", NETWORK_FAMILY.local_negative_evidence)

    def test_contract_hashes_are_distinct(self) -> None:
        hashes = {f.contract_hash for f in ALL_EXTERNAL_PIT_FAMILIES}
        self.assertEqual(len(hashes), 4)


if __name__ == "__main__":
    unittest.main()
