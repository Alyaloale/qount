from __future__ import annotations

import datetime as dt
import unittest

from qount.mini_trend.pilot_dispatch_views import float_or_zero
from qount.mini_trend.pilot_dispatch_views import managed_protective_client_id
from qount.mini_trend.pilot_dispatch_views import order_view
from qount.mini_trend.pilot_dispatch_views import position_average_cost
from qount.mini_trend.pilot_dispatch_views import position_contracts
from qount.mini_trend.pilot_dispatch_views import position_side
from qount.mini_trend.pilot_dispatch_views import round_down
from qount.mini_trend.pilot_dispatch_views import source_age_seconds
from qount.mini_trend.pilot_dispatch_views import utc_timestamp
from qount.mini_trend.pilot_dispatcher import _STANDARD_PROTECTIVE_PREFIX


class PilotDispatchViewsTests(unittest.TestCase):
    def test_numeric_and_timestamp_normalization_is_fail_closed(self) -> None:
        self.assertEqual(float_or_zero("2.5"), 2.5)
        self.assertEqual(float_or_zero(None), 0.0)
        self.assertEqual(float_or_zero("not-a-number"), 0.0)
        self.assertEqual(round_down(1.239, 0.01), 1.23)
        self.assertEqual(round_down(1.239, 0.0), 1.239)

        observed_at = dt.datetime(2026, 8, 2, tzinfo=dt.timezone.utc)
        self.assertEqual(
            utc_timestamp("2026-08-01T16:00:00Z"),
            dt.datetime(2026, 8, 1, 16, tzinfo=dt.timezone.utc),
        )
        self.assertIsNone(utc_timestamp("2026-08-01T16:00:00"))
        self.assertEqual(
            source_age_seconds(
                {"created_at": "2026-08-01T23:59:00+00:00"},
                observed_at=observed_at,
            ),
            60.0,
        )
        self.assertIsNone(
            source_age_seconds(
                {"created_at": "2026-08-02T00:02:00+00:00"},
                observed_at=observed_at,
            )
        )

    def test_exchange_position_and_order_views_normalize_ccxt_variants(self) -> None:
        position = {
            "info": {
                "symbol": "BTCUSDT",
                "positionAmt": "-0.25",
                "breakEvenPrice": "61300.5",
            }
        }
        self.assertEqual(position_contracts(position), 0.25)
        self.assertEqual(position_side(position), "short")
        self.assertEqual(position_average_cost(position), 61300.5)

        view = order_view(
            {
                "info": {
                    "orderId": "exchange-order-1",
                    "origType": "STOP_MARKET",
                    "stopPrice": "60000",
                    "clientAlgoId": "qmt-s-btc-1",
                    "reduceOnly": "true",
                    "closePosition": "true",
                    "status": "NEW",
                },
                "side": "SELL",
            },
            ccxt_symbol="BTC/USDT:USDT",
        )

        self.assertEqual(view["id"], "exchange-order-1")
        self.assertEqual(view["client_order_id"], "qmt-s-btc-1")
        self.assertEqual(view["type"], "STOP_MARKET")
        self.assertEqual(view["side"], "sell")
        self.assertEqual(view["trigger_price"], 60000.0)
        self.assertTrue(view["reduce_only"])
        self.assertTrue(view["close_position"])
        self.assertTrue(managed_protective_client_id(view["client_order_id"]))
        self.assertTrue(managed_protective_client_id("q-p-standard-stop"))
        self.assertFalse(managed_protective_client_id("manual-order"))
        self.assertEqual(_STANDARD_PROTECTIVE_PREFIX, "q-p-")


if __name__ == "__main__":
    unittest.main()
