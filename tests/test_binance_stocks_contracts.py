from __future__ import annotations

import unittest

from qount.venue import BINANCE_STOCKS_API_PREFIX
from qount.venue import BINANCE_STOCKS_DISCLAIMER_REQUIRED_CODE
from qount.venue import BinanceStockOrderRequest
from qount.venue import BinanceStocksContractError
from qount.venue import build_binance_stock_capability
from qount.venue import build_binance_stock_instrument
from qount.venue import parse_binance_stock_exchange_info
from qount.venue import validate_binance_stock_order_for_execution


OBSERVED_AT = "2026-07-26T12:00:00+00:00"
SOURCE_HASH = "a" * 64


def _row(**updates):
    value = {
        "symbol": "AAPL",
        "tradability": "BUY_SELL",
        "tradabilityUpdateTime": 1_735_900_000_000,
        "overnightSupported": True,
        "fractionable": True,
        "fractionableEh": True,
        "extendedSession": True,
        "maxNumOrders": 200,
        "stepSize": "0.000000001",
        "multiplierUp": "1.10",
        "multiplierDown": "0.90",
        "minQty": "0.000000001",
        "maxQty": "100000.00000000",
        "minNotional": "1.00",
        "maxNotional": "1000000.00",
        "listingTime": 1_700_000_000_000,
        "delistingTime": None,
    }
    value.update(updates)
    return value


def _rule(**updates):
    return parse_binance_stock_exchange_info(
        {"timezone": "UTC", "symbols": [_row(**updates)]}
    )[0]


class BinanceStocksContractTest(unittest.TestCase):
    def test_official_prefix_rule_parser_and_sell_close_capability(self) -> None:
        self.assertEqual(BINANCE_STOCKS_API_PREFIX, "/sapi/v1/equity")
        self.assertEqual(BINANCE_STOCKS_DISCLAIMER_REQUIRED_CODE, 486410)
        rule = _rule()
        cash = build_binance_stock_instrument(
            rule, asset_class="equity", tokenize=False
        )
        tokenized = build_binance_stock_instrument(
            rule, asset_class="equity", tokenize=True
        )
        capability = build_binance_stock_capability(
            rule,
            cash,
            observed_at=OBSERVED_AT,
            source_hash=SOURCE_HASH,
        )

        self.assertNotEqual(cash.instrument_key, tokenized.instrument_key)
        self.assertEqual(cash.product_kind, "cash_equity")
        self.assertEqual(tokenized.product_kind, "tokenized_equity")
        self.assertTrue(capability.long_allowed)
        self.assertFalse(capability.short_allowed)
        self.assertTrue(capability.sell_close_only)
        self.assertFalse(capability.reduce_only_supported)
        self.assertEqual(capability.trading_sessions, ("RTH", "EXTENDED", "24H"))
        self.assertEqual(
            rule.planner_rule(),
            {
                "step_size": 1e-9,
                "minimum_quantity": 1e-9,
                "minimum_notional": 1.0,
            },
        )

    def test_all_four_official_order_field_combinations(self) -> None:
        requests = (
            BinanceStockOrderRequest.create(
                symbol="AAPL",
                side="BUY",
                order_type="LIMIT",
                price="180.50",
                quantity="1",
                trading_session="RTH",
            ),
            BinanceStockOrderRequest.create(
                symbol="AAPL",
                side="SELL",
                order_type="LIMIT",
                price="180.50",
                quantity="1",
                trading_session="EXTENDED",
            ),
            BinanceStockOrderRequest.create(
                symbol="AAPL",
                side="BUY",
                order_type="MARKET",
                notional="100.00",
            ),
            BinanceStockOrderRequest.create(
                symbol="AAPL",
                side="SELL",
                order_type="MARKET",
                quantity="1",
            ),
        )
        for request in requests:
            with self.subTest(side=request.side, order_type=request.order_type):
                self.assertEqual(request.validate(rule=_rule()), ())
                self.assertNotIn("fee", request.as_sapi_params())

    def test_invalid_field_matrix_and_price_precision_fail_closed(self) -> None:
        cases = (
            {
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "price": "180.50",
                "quantity": "1",
            },
            {
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "MARKET",
                "quantity": "1",
            },
            {
                "symbol": "AAPL",
                "side": "SELL",
                "order_type": "MARKET",
                "quantity": "1",
                "notional": "100",
            },
            {
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "price": "180.501",
                "quantity": "1",
                "trading_session": "RTH",
            },
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(BinanceStocksContractError):
                    BinanceStockOrderRequest.create(**values)

    def test_fractional_gtc_requires_extended_or_24h_session(self) -> None:
        with self.assertRaisesRegex(
            BinanceStocksContractError,
            "fractional_gtc_session_invalid",
        ):
            BinanceStockOrderRequest.create(
                symbol="AAPL",
                side="BUY",
                order_type="LIMIT",
                price="180.50",
                quantity="0.5",
                time_in_force="GTC",
                trading_session="RTH",
            )

        request = BinanceStockOrderRequest.create(
            symbol="AAPL",
            side="BUY",
            order_type="LIMIT",
            price="180.50",
            quantity="0.5",
            time_in_force="GTC",
            trading_session="EXTENDED",
        )
        self.assertEqual(request.validate(rule=_rule()), ())
        self.assertIn(
            "fractional_order_not_supported",
            request.validate(rule=_rule(fractionableEh=False)),
        )

    def test_execution_validation_requires_disclaimer_identity_and_sell_inventory(self) -> None:
        rule = _rule()
        cash = build_binance_stock_instrument(
            rule, asset_class="equity", tokenize=False
        )
        sell = BinanceStockOrderRequest.create(
            symbol="AAPL",
            side="SELL",
            order_type="MARKET",
            quantity="1",
            tokenize=False,
        )
        missing = validate_binance_stock_order_for_execution(
            sell,
            rule=rule,
            instrument=cash,
            disclaimer_accepted=False,
            available_to_sell=None,
        )
        self.assertIn("sell_inventory_unavailable", missing)
        self.assertIn("stock_disclaimer_not_accepted", missing)

        too_large = validate_binance_stock_order_for_execution(
            sell,
            rule=rule,
            instrument=cash,
            disclaimer_accepted=True,
            available_to_sell="0.5",
        )
        self.assertIn("sell_quantity_exceeds_inventory", too_large)
        self.assertEqual(
            validate_binance_stock_order_for_execution(
                sell,
                rule=rule,
                instrument=cash,
                disclaimer_accepted=True,
                available_to_sell="1",
            ),
            (),
        )

        tokenized_buy = BinanceStockOrderRequest.create(
            symbol="AAPL",
            side="BUY",
            order_type="MARKET",
            notional="100",
            tokenize=True,
        )
        self.assertIn(
            "stock_order_instrument_mismatch",
            validate_binance_stock_order_for_execution(
                tokenized_buy,
                rule=rule,
                instrument=cash,
                disclaimer_accepted=True,
                available_to_sell=None,
            ),
        )

    def test_exchange_info_rejects_duplicate_or_unknown_shape(self) -> None:
        with self.assertRaisesRegex(
            BinanceStocksContractError, "symbol_duplicate"
        ):
            parse_binance_stock_exchange_info(
                {"timezone": "UTC", "symbols": [_row(), _row()]}
            )
        invalid = _row()
        invalid["unknown"] = True
        with self.assertRaisesRegex(
            BinanceStocksContractError, "fields_invalid"
        ):
            parse_binance_stock_exchange_info(
                {"timezone": "UTC", "symbols": [invalid]}
            )


if __name__ == "__main__":
    unittest.main()
