from __future__ import annotations

import unittest

from qount.small_account.fomc_market_rules import FomcLiveError
from qount.small_account.fomc_market_rules import market_rules
from qount.small_account.fomc_market_rules import number


class FomcMarketRulesTests(unittest.TestCase):
    def test_number_uses_the_first_finite_exchange_value(self) -> None:
        self.assertEqual(number("invalid", "0.01"), 0.01)
        self.assertEqual(number(float("nan"), 2.0), 2.0)
        self.assertTrue(number("invalid") != number("invalid"))

    def test_market_rules_normalize_ccxt_and_raw_binance_fields(self) -> None:
        result = market_rules(
            {
                "id": "btcusdt",
                "settle": "usdt",
                "linear": True,
                "swap": True,
                "active": True,
                "contractSize": "1",
                "info": {
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ]
                },
            }
        )

        self.assertEqual(result["symbol"], "BTCUSDT")
        self.assertEqual(result["settle"], "USDT")
        self.assertEqual(result["price_tick"], 0.1)
        self.assertEqual(result["quantity_step"], 0.001)
        self.assertEqual(result["minimum_notional_usdt"], 5.0)
        self.assertEqual(len(result["exchange_rules_hash"]), 64)

    def test_market_rules_reject_missing_quantity_geometry(self) -> None:
        with self.assertRaisesRegex(FomcLiveError, "fomc_live_market_rules_invalid"):
            market_rules(
                {
                    "id": "BTCUSDT",
                    "contractSize": 1.0,
                    "linear": True,
                    "swap": True,
                    "info": {"filters": []},
                }
            )


if __name__ == "__main__":
    unittest.main()
