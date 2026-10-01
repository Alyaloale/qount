from __future__ import annotations

import unittest

from qount.reporting.read_model_validation import DashboardReadModelError
from qount.reporting.read_model_validation import exact_keys
from qount.reporting.read_model_validation import finite
from qount.reporting.read_model_validation import finite_nonnegative
from qount.reporting.read_model_validation import freshness
from qount.reporting.read_model_validation import gross
from qount.reporting.read_model_validation import mapping
from qount.reporting.read_model_validation import string_list


class DashboardReadModelValidationTests(unittest.TestCase):
    def test_mapping_and_exact_keys_report_stable_schema_errors(self) -> None:
        with self.assertRaisesRegex(
            DashboardReadModelError,
            "dashboard_payload_must_be_object",
        ):
            mapping([], name="dashboard_payload")

        with self.assertRaisesRegex(
            DashboardReadModelError,
            "dashboard_payload_fields_mismatch:missing=expected:unexpected=extra",
        ):
            exact_keys(
                {"extra": True},
                {"expected"},
                name="dashboard_payload",
            )

    def test_numeric_and_collection_validation_rejects_invalid_values(self) -> None:
        self.assertEqual(finite("-1.5", name="pnl"), -1.5)
        self.assertEqual(finite_nonnegative("2.5", name="weight"), 2.5)
        self.assertEqual(gross({"BTCUSDT": 0.25, "ETHUSDT": 0.5}), 0.75)
        self.assertEqual(string_list(["one", "two"], name="blockers"), ["one", "two"])

        for value in (float("inf"), float("nan"), "invalid"):
            with self.assertRaisesRegex(DashboardReadModelError, "pnl_invalid"):
                finite(value, name="pnl")
        with self.assertRaisesRegex(DashboardReadModelError, "weight_invalid"):
            finite_nonnegative(-0.1, name="weight")
        with self.assertRaisesRegex(DashboardReadModelError, "blockers_invalid"):
            string_list(["duplicate", "duplicate"], name="blockers")

    def test_freshness_derives_source_and_aggregate_status_without_io(self) -> None:
        value = freshness(
            source_updated_at="2026-08-02T00:00:00+00:00",
            evaluated_at="2026-08-02T00:05:00+00:00",
            stale_after_seconds=300,
            sources={
                "ledger": "2026-08-02T00:00:00+00:00",
                "registry": "2026-08-02T00:04:00+00:00",
            },
        )

        self.assertEqual(value["status"], "stale")
        self.assertEqual(value["stale_at"], "2026-08-02T00:05:00+00:00")
        self.assertEqual(value["sources"]["ledger"]["status"], "stale")
        self.assertEqual(value["sources"]["registry"]["status"], "fresh")


if __name__ == "__main__":
    unittest.main()
