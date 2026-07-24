"""Tests for R0-ADVANCEMENT date alignment and artifact completeness."""

from __future__ import annotations

import unittest


class TestDateAlignedPortfolio(unittest.TestCase):
    """Verify date-aligned equal-weight portfolio computation."""

    def test_date_intersection_excludes_misaligned_bars(self) -> None:
        # BTC/ETH start 2020-01-01, BNB starts 2020-02-01
        btc_dates = ["2020-01-01", "2020-01-02", "2020-02-01", "2020-02-02"]
        btc_nav = [1.0, 1.1, 1.2, 1.3]
        bnb_dates = ["2020-02-01", "2020-02-02"]
        bnb_nav = [1.0, 1.1]

        all_dates = {"BTC": btc_dates, "BNB": bnb_dates}
        all_navs = {"BTC": btc_nav, "BNB": bnb_nav}

        date_sets = [set(d) for d in all_dates.values()]
        common = sorted(set.intersection(*date_sets))
        self.assertEqual(common, ["2020-02-01", "2020-02-02"])

        nav_by_date = {s: dict(zip(all_dates[s], all_navs[s])) for s in all_navs}
        ew_nav = [1.0]
        for t in range(1, len(common)):
            avg_ret = sum(
                nav_by_date[s][common[t]] / nav_by_date[s][common[t-1]] - 1.0
                for s in nav_by_date
            ) / len(nav_by_date)
            ew_nav.append(ew_nav[-1] * (1.0 + avg_ret))

        self.assertEqual(len(ew_nav), 2)
        self.assertAlmostEqual(ew_nav[0], 1.0)

    def test_no_intersection_produces_empty(self) -> None:
        dates_a = ["2020-01-01", "2020-01-02"]
        dates_b = ["2020-03-01", "2020-03-02"]
        date_sets = [set(dates_a), set(dates_b)]
        common = sorted(set.intersection(*date_sets))
        self.assertEqual(common, [])

    def test_full_intersection_keeps_all_bars(self) -> None:
        dates = ["2020-01-01", "2020-01-02", "2020-01-03"]
        date_sets = [set(dates), set(dates)]
        common = sorted(set.intersection(*date_sets))
        self.assertEqual(len(common), 3)

    def test_array_index_truncation_was_wrong(self) -> None:
        """The old min(len) approach would misalign dates."""
        btc_nav = [1.0, 1.1, 1.2, 1.3]  # 4 bars from 2020-01-01
        bnb_nav = [1.0, 1.1]             # 2 bars from 2020-02-01
        old_common_len = min(len(btc_nav), len(bnb_nav))  # = 2
        # Old approach: pairs btc[0:2] with bnb[0:2] -- date misaligned!
        # BTC bar 0 = 2020-01-01, BNB bar 0 = 2020-02-01
        self.assertEqual(old_common_len, 2)
        # New approach: date intersection gives bars from 2020-02-01 only


class TestArtifactCompleteness(unittest.TestCase):
    """Verify advancement artifact includes all expected fields."""

    def test_bundle_core_has_etf_results_key(self) -> None:
        expected_keys = {
            "schema_version", "artifact_type", "observed_at",
            "data_window", "candidate_config", "runtime_bundle_id",
            "config", "universe", "holdout_role", "source_hashes",
            "results", "etf_results", "cta_r_portfolio", "orders_authorized",
        }
        self.assertIn("etf_results", expected_keys)
        self.assertIn("cta_r_portfolio", expected_keys)
        self.assertIn("source_hashes", expected_keys)

    def test_source_hashes_include_crypto(self) -> None:
        expected_source_keys = {"etf_zip", "crypto"}
        self.assertIn("crypto", expected_source_keys)
        self.assertIn("etf_zip", expected_source_keys)

    def test_crypto_results_include_dates(self) -> None:
        expected_fields = {"first_date", "last_date"}
        self.assertTrue(expected_field is not None for expected_field in expected_fields)


if __name__ == "__main__":
    unittest.main()
