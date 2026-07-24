"""Unit tests for R0-DATA universe revision builder (no network)."""

from __future__ import annotations

import unittest

from qount.governance.research_records import PointInTimeSymbolLifecycle
from qount.research_data.universe import build_exclusion_reasons
from qount.research_data.universe import build_revision
from qount.research_data.universe import build_revision_series
from qount.research_data.universe import monthly_schedule
from qount.research_data.universe import quarterly_schedule
from qount.research_data.universe import summarize_revisions


SOURCE_HASH = "a" * 64


def _make_lifecycle(
    symbol: str,
    venue: str,
    valid_from: str,
    state: str = "active",
    valid_to: str | None = None,
) -> PointInTimeSymbolLifecycle:
    return PointInTimeSymbolLifecycle.create(
        symbol=symbol,
        venue=venue,
        valid_from=valid_from,
        valid_to=valid_to,
        state=state,
        rules_hash="b" * 64,
        source_hash=SOURCE_HASH,
    )


LIFECYCLES = [
    _make_lifecycle("BTCUSDT", "binance_um", "2019-09-25T00:00:00+00:00"),
    _make_lifecycle("ETHUSDT", "binance_um", "2019-09-25T00:00:00+00:00"),
    _make_lifecycle("LATEUSDT", "binance_um", "2022-06-15T00:00:00+00:00"),
    _make_lifecycle("DEADUSDT", "binance_um", "2020-01-01T00:00:00+00:00",
                     valid_to="2021-12-31T00:00:00+00:00", state="delisted"),
    _make_lifecycle("BREAKUSDT", "binance_um", "2020-06-01T00:00:00+00:00", state="suspended"),
    _make_lifecycle("BTCUSDT", "binance_spot", "2017-08-17T00:00:00+00:00"),
]


class TestSchedules(unittest.TestCase):
    def test_quarterly_schedule(self) -> None:
        dates = quarterly_schedule("2020-01-01T00:00:00+00:00", "2021-01-01T00:00:00+00:00")
        self.assertEqual(len(dates), 5)  # 2020 Q1-Q4 + 2021 Q1
        self.assertTrue(dates[0].startswith("2020-01-01"))
        self.assertTrue(dates[1].startswith("2020-04-01"))
        self.assertTrue(dates[2].startswith("2020-07-01"))
        self.assertTrue(dates[3].startswith("2020-10-01"))
        self.assertTrue(dates[4].startswith("2021-01-01"))

    def test_quarterly_schedule_aligns_to_quarter_start(self) -> None:
        dates = quarterly_schedule("2020-02-15T00:00:00+00:00", "2020-06-15T00:00:00+00:00")
        self.assertTrue(dates[0].startswith("2020-01-01"))
        self.assertTrue(dates[1].startswith("2020-04-01"))

    def test_quarterly_schedule_empty_when_end_before_start(self) -> None:
        dates = quarterly_schedule("2021-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00")
        self.assertEqual(dates, [])

    def test_monthly_schedule(self) -> None:
        dates = monthly_schedule("2020-01-01T00:00:00+00:00", "2020-04-01T00:00:00+00:00")
        self.assertEqual(len(dates), 4)
        self.assertTrue(dates[0].startswith("2020-01-01"))
        self.assertTrue(dates[3].startswith("2020-04-01"))

    def test_monthly_schedule_crosses_year(self) -> None:
        dates = monthly_schedule("2020-11-01T00:00:00+00:00", "2021-02-01T00:00:00+00:00")
        self.assertEqual(len(dates), 4)
        self.assertTrue(dates[0].startswith("2020-11-01"))
        self.assertTrue(dates[3].startswith("2021-02-01"))


class TestBuildExclusionReasons(unittest.TestCase):
    def test_not_yet_listed(self) -> None:
        reasons = build_exclusion_reasons(
            LIFECYCLES,
            as_of="2020-01-01T00:00:00+00:00",
            venue="binance_um",
        )
        self.assertIn("LATEUSDT", reasons)
        self.assertEqual(reasons["LATEUSDT"], "not_yet_listed")

    def test_delisted_or_expired(self) -> None:
        reasons = build_exclusion_reasons(
            LIFECYCLES,
            as_of="2022-01-01T00:00:00+00:00",
            venue="binance_um",
        )
        self.assertIn("DEADUSDT", reasons)
        self.assertEqual(reasons["DEADUSDT"], "delisted_or_expired")

    def test_suspended(self) -> None:
        reasons = build_exclusion_reasons(
            LIFECYCLES,
            as_of="2021-01-01T00:00:00+00:00",
            venue="binance_um",
        )
        self.assertIn("BREAKUSDT", reasons)
        self.assertEqual(reasons["BREAKUSDT"], "state_suspended")

    def test_active_not_excluded(self) -> None:
        reasons = build_exclusion_reasons(
            LIFECYCLES,
            as_of="2021-01-01T00:00:00+00:00",
            venue="binance_um",
        )
        self.assertNotIn("BTCUSDT", reasons)
        self.assertNotIn("ETHUSDT", reasons)

    def test_other_venue_excluded(self) -> None:
        reasons = build_exclusion_reasons(
            LIFECYCLES,
            as_of="2021-01-01T00:00:00+00:00",
            venue="binance_um",
        )
        # BTCUSDT in binance_spot should not appear in binance_um exclusions.
        # (There's a separate BTCUSDT in binance_spot, but it's a different venue.)


class TestBuildRevision(unittest.TestCase):
    def test_revision_includes_active_symbols(self) -> None:
        rev = build_revision(
            LIFECYCLES,
            as_of="2021-01-01T00:00:00+00:00",
            venue="binance_um",
            source_hashes={"exchange_info_um": SOURCE_HASH},
        )
        self.assertIn("BTCUSDT", rev.included_symbols)
        self.assertIn("ETHUSDT", rev.included_symbols)
        self.assertNotIn("LATEUSDT", rev.included_symbols)
        self.assertNotIn("DEADUSDT", rev.included_symbols)
        self.assertNotIn("BREAKUSDT", rev.included_symbols)
        errors = rev.validate()
        self.assertEqual(errors, ())

    def test_revision_at_listing_time(self) -> None:
        rev = build_revision(
            LIFECYCLES,
            as_of="2022-06-15T00:00:00+00:00",
            venue="binance_um",
            source_hashes={"exchange_info_um": SOURCE_HASH},
        )
        self.assertIn("LATEUSDT", rev.included_symbols)

    def test_revision_before_listing_excludes(self) -> None:
        rev = build_revision(
            LIFECYCLES,
            as_of="2022-06-14T00:00:00+00:00",
            venue="binance_um",
            source_hashes={"exchange_info_um": SOURCE_HASH},
        )
        self.assertNotIn("LATEUSDT", rev.included_symbols)

    def test_revision_with_extra_exclusions(self) -> None:
        rev = build_revision(
            LIFECYCLES,
            as_of="2021-01-01T00:00:00+00:00",
            venue="binance_um",
            source_hashes={"exchange_info_um": SOURCE_HASH},
            extra_exclusions={"ETHUSDT": "no_kline_data"},
        )
        self.assertIn("BTCUSDT", rev.included_symbols)
        self.assertNotIn("ETHUSDT", rev.included_symbols)
        self.assertIn("ETHUSDT", rev.exclusion_reasons)

    def test_revision_only_includes_matching_venue(self) -> None:
        rev = build_revision(
            LIFECYCLES,
            as_of="2021-01-01T00:00:00+00:00",
            venue="binance_spot",
            source_hashes={"exchange_info_spot": SOURCE_HASH},
        )
        # Only the binance_spot BTCUSDT should be included.
        self.assertIn("BTCUSDT", rev.included_symbols)
        self.assertNotIn("ETHUSDT", rev.included_symbols)


class TestBuildRevisionSeries(unittest.TestCase):
    def test_series_sizes_change_over_time(self) -> None:
        dates = quarterly_schedule("2020-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00")
        revisions = build_revision_series(
            LIFECYCLES,
            as_of_dates=dates,
            venue="binance_um",
            source_hashes={"exchange_info_um": SOURCE_HASH},
        )
        self.assertEqual(len(revisions), len(dates))
        # At 2020-01-01: BTCUSDT, ETHUSDT, DEADUSDT, BREAKUSDT (LATEUSDT not listed)
        self.assertIn("BTCUSDT", revisions[0].included_symbols)
        self.assertNotIn("LATEUSDT", revisions[0].included_symbols)
        # At 2022-Q3: LATEUSDT is listed
        q3_idx = next(i for i, d in enumerate(dates) if d.startswith("2022-07"))
        self.assertIn("LATEUSDT", revisions[q3_idx].included_symbols)
        # All revisions validate
        for rev in revisions:
            self.assertEqual(rev.validate(), ())


class TestSummarizeRevisions(unittest.TestCase):
    def test_summary(self) -> None:
        dates = quarterly_schedule("2020-01-01T00:00:00+00:00", "2021-01-01T00:00:00+00:00")
        revisions = build_revision_series(
            LIFECYCLES,
            as_of_dates=dates,
            venue="binance_um",
            source_hashes={"exchange_info_um": SOURCE_HASH},
        )
        summary = summarize_revisions(revisions, venue="binance_um")
        self.assertEqual(len(summary), len(dates))
        for item in summary:
            self.assertIn("as_of", item)
            self.assertIn("included_count", item)
            self.assertIn("excluded_count", item)
            self.assertIn("revision_id", item)


if __name__ == "__main__":
    unittest.main()
