from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path

from qount.alpha_agents.information_events import audit_information_events
from qount.alpha_agents.information_events import build_information_event
from qount.alpha_agents.information_events import information_event_feature_row
from qount.alpha_agents.information_events import validate_information_event


def _event():
    return build_information_event(
        source_url="https://www.sec.gov/Archives/example",
        source_bytes=b"official filing body",
        published_at="2026-07-18T12:00:00+00:00",
        available_at="2026-07-18T12:01:00+00:00",
        observed_at="2026-07-18T12:02:00+00:00",
        entities=("nvda",),
        event_type="regulatory_filing",
        numeric_fields={"reported_revenue_usd": 1_000_000.0},
        source_excerpt="The registrant reported revenue.",
        llm_summary="NVDA published a regulatory filing with reported revenue.",
        llm_confidence=0.9,
        extractor_version="glm-research-v1",
    )


class InformationEventTests(unittest.TestCase):
    def test_valid_event_has_deterministic_id_and_feature_row(self) -> None:
        event = _event()
        self.assertEqual(validate_information_event(event), [])
        self.assertEqual(event.entities, ("NVDA",))
        self.assertEqual(event.event_id, _event().event_id)
        row = information_event_feature_row(event)
        self.assertFalse(row["llm_text_used_as_numeric_feature"])
        self.assertNotIn("llm_summary", row)
        self.assertEqual(row["numeric_fields"]["reported_revenue_usd"], 1_000_000.0)

    def test_future_availability_order_is_rejected(self) -> None:
        event = dataclasses.replace(
            _event(),
            available_at="2026-07-18T11:59:00+00:00",
        )
        self.assertIn("available_before_published", validate_information_event(event))

    def test_forbidden_trade_language_is_rejected(self) -> None:
        event = dataclasses.replace(
            _event(),
            llm_summary="Set leverage to 5x and market buy NVDA now.",
        )
        errors = validate_information_event(event)
        self.assertIn("forbidden_llm_output:set leverage", errors)
        self.assertIn("forbidden_llm_output:market buy", errors)

    def test_duplicates_block_feature_batch(self) -> None:
        event = _event()
        audit = audit_information_events((event, event))
        self.assertEqual(audit["valid_event_count"], 2)
        self.assertFalse(audit["research_feature_rows_allowed"])
        self.assertEqual(audit["duplicate_event_ids"], [event.event_id])
        self.assertFalse(audit["orders_allowed"])

    def test_fixed_information_fixtures_enforce_point_in_time_contract(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "information_event_cases.json"
        rows = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(rows), 5)
        for row in rows:
            event = build_information_event(
                source_url=row["source_url"],
                source_bytes=row["source_text"].encode("utf-8"),
                published_at=row["published_at"],
                available_at=row["available_at"],
                observed_at=row["observed_at"],
                entities=row["entities"],
                event_type=row["event_type"],
                source_excerpt=row["source_excerpt"],
                llm_summary=row["llm_summary"],
                llm_confidence=row["llm_confidence"],
                extractor_version="relay-chatgpt-fixture-v1",
            )
            self.assertEqual(
                validate_information_event(event),
                row["expected_errors"],
                msg=row["case_id"],
            )


if __name__ == "__main__":
    unittest.main()
