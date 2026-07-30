from __future__ import annotations

import unittest

from qount.research_data.market_data import Bar
from qount.mini_trend.tradifi_weekend import TradifiWeekendConfig
from qount.mini_trend.tradifi_weekend import _cash_session_bar_open_ms
from qount.mini_trend.tradifi_weekend import _pooled_event_summary
from qount.mini_trend.tradifi_weekend import build_weekend_events


def _bar(timestamp: int, close: float) -> Bar:
    return Bar(timestamp, close, close, close, close, 1_000.0)


class MiniTrendTradifiWeekendTest(unittest.TestCase):
    def test_negative_weekend_gap_creates_long_only_reversion_trade(self) -> None:
        cash_dates = ["2026-01-02", "2026-01-05", "2026-01-09", "2026-01-12"]
        bars = []
        for previous, following in ((cash_dates[0], cash_dates[1]), (cash_dates[2], cash_dates[3])):
            bars.extend(
                [
                    _bar(_cash_session_bar_open_ms(previous, point="close"), 100.0),
                    _bar(_cash_session_bar_open_ms(following, point="preopen"), 95.0),
                    _bar(_cash_session_bar_open_ms(following, point="close"), 100.0),
                ]
            )
        events = build_weekend_events(
            bars,
            (),
            cash_dates,
            config=TradifiWeekendConfig(bootstrap_samples=100),
        )
        self.assertEqual(len(events), 2)
        self.assertTrue(all(row["long_discount_trade"] for row in events))
        self.assertTrue(all(row["long_discount_net_return"] > 0.0 for row in events))

    def test_positive_weekend_gap_does_not_open_short(self) -> None:
        cash_dates = ["2026-01-02", "2026-01-05"]
        bars = [
            _bar(_cash_session_bar_open_ms(cash_dates[0], point="close"), 100.0),
            _bar(_cash_session_bar_open_ms(cash_dates[1], point="preopen"), 105.0),
            _bar(_cash_session_bar_open_ms(cash_dates[1], point="close"), 100.0),
        ]
        events = build_weekend_events(
            bars,
            (),
            cash_dates,
            config=TradifiWeekendConfig(bootstrap_samples=100),
        )
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["long_discount_trade"])
        self.assertEqual(events[0]["long_discount_net_return"], 0.0)

    def test_new_york_session_conversion_changes_with_dst(self) -> None:
        january = _cash_session_bar_open_ms("2026-01-09", point="close")
        july = _cash_session_bar_open_ms("2026-07-10", point="close")
        self.assertEqual((january // 3_600_000) % 24, 20)
        self.assertEqual((july // 3_600_000) % 24, 19)

    def test_pooled_events_are_clustered_by_cash_date(self) -> None:
        rows = [
            {
                "previous_cash_date": "2026-01-02",
                "next_cash_date": "2026-01-05",
                "weekend_return": -0.02,
                "cash_session_return": 0.01,
                "opposite_sign_reversion": True,
                "long_discount_trade": True,
                "long_discount_net_return": value,
            }
            for value in (0.01, 0.03)
        ]
        summary = _pooled_event_summary(
            rows,
            config=TradifiWeekendConfig(bootstrap_samples=100),
        )
        self.assertEqual(summary["symbol_event_count"], 2)
        self.assertEqual(summary["event_date_count"], 1)
        self.assertAlmostEqual(summary["portfolio_mean_event_return_pct"], 2.0)
        self.assertFalse(summary["cross_sectional_events_treated_as_independent"])


if __name__ == "__main__":
    unittest.main()
