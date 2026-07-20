from __future__ import annotations

import unittest
from unittest import mock

from qount.mini_trend.forward import TOP3
from qount.mini_trend.pilot_preflight import build_pilot_account_preflight
from qount.settings import Settings


def _settings() -> Settings:
    with mock.patch.dict(
        "os.environ",
        {
            "QOUNT_MARKET_TYPE": "future",
            "QOUNT_BINANCE_API_KEY": "test-key",
            "QOUNT_BINANCE_API_SECRET": "test-secret",
        },
    ):
        return Settings.from_env()


class _FakeExchange:
    def __init__(
        self,
        *,
        positions: list[dict] | None = None,
        private_error: Exception | None = None,
        configured_leverage: float = 1.0,
        configured_margin_mode: str = "isolated",
        open_orders: list[dict] | None = None,
        spot_margin_enabled: bool = False,
    ):
        self.positions = positions or []
        self.private_error = private_error
        self.configured_leverage = configured_leverage
        self.configured_margin_mode = configured_margin_mode
        self.open_orders = open_orders or []
        self.spot_margin_enabled = spot_margin_enabled
        self.mutating_calls = []
        self.options = {}
        self.open_orders_warning_acknowledged = False
        self.markets = {
            f"{symbol[:-4]}/USDT:USDT": {
                "symbol": f"{symbol[:-4]}/USDT:USDT",
                "base": symbol[:-4],
                "quote": "USDT",
                "settle": "USDT",
                "contract": True,
                "linear": True,
                "swap": True,
            }
            for symbol in TOP3
        }

    def load_time_difference(self):
        return 0

    def load_markets(self):
        return self.markets

    def fetch_balance(self):
        if self.private_error is not None:
            raise self.private_error
        return {
            "free": {"USDT": 300.0},
            "used": {"USDT": 0.0},
            "total": {"USDT": 300.0},
            "info": {
                "assets": [
                    {
                        "asset": "USDT",
                        "walletBalance": "300",
                        "marginBalance": "300",
                        "availableBalance": "300",
                    }
                ]
            },
        }

    def fetch_position_mode(self, params=None):
        return {"hedged": False}

    def fetch_positions(self, symbols=None):
        return list(self.positions)

    def fetch_leverages(self, symbols, params=None):
        return {
            symbol: {
                "symbol": symbol,
                "longLeverage": self.configured_leverage,
                "shortLeverage": self.configured_leverage,
            }
            for symbol in symbols
        }

    def fetch_margin_modes(self, symbols, params=None):
        return {
            symbol: {
                "symbol": symbol,
                "marginMode": self.configured_margin_mode,
            }
            for symbol in symbols
        }

    def fetch_open_orders(self):
        self.open_orders_warning_acknowledged = (
            self.options.get("warnOnFetchOpenOrdersWithoutSymbol") is False
        )
        if not self.open_orders_warning_acknowledged:
            raise RuntimeError("all-symbol open-order warning not acknowledged")
        return list(self.open_orders)

    def sapiGetAccountApiRestrictions(self):
        return {
            "enableReading": True,
            "enableSpotAndMarginTrading": self.spot_margin_enabled,
            "enableFutures": True,
            "enableWithdrawals": False,
            "ipRestrict": True,
        }

    def set_leverage(self, *args, **kwargs):
        self.mutating_calls.append("set_leverage")

    def set_margin_mode(self, *args, **kwargs):
        self.mutating_calls.append("set_margin_mode")

    def create_order(self, *args, **kwargs):
        self.mutating_calls.append("create_order")


class MiniTrendPilotPreflightTest(unittest.TestCase):
    def test_flat_configured_account_passes_without_mutation(self) -> None:
        exchange = _FakeExchange()
        report = build_pilot_account_preflight(_settings(), exchange=exchange)
        self.assertEqual(report["diagnostics"]["verdict"], "account_preflight_pass")
        self.assertEqual(report["account"]["balance"]["quote_free"], 300.0)
        self.assertTrue(report["evidence"]["isolated_one_x_verified"])
        self.assertTrue(exchange.open_orders_warning_acknowledged)
        self.assertNotIn("warnOnFetchOpenOrdersWithoutSymbol", exchange.options)
        self.assertEqual(exchange.mutating_calls, [])
        self.assertFalse(report["meta"]["private_api_order_attempted"])

    def test_spot_margin_permission_is_recorded_but_not_blocked(self) -> None:
        exchange = _FakeExchange(spot_margin_enabled=True)
        report = build_pilot_account_preflight(_settings(), exchange=exchange)
        self.assertFalse(report["evidence"]["api_key_spot_margin_disabled"])
        self.assertNotIn("spot_margin_disabled", report["diagnostics"]["gates"])
        self.assertEqual(report["diagnostics"]["verdict"], "account_preflight_pass")
        self.assertEqual(exchange.mutating_calls, [])

    def test_two_x_configuration_and_open_orders_remain_blocked(self) -> None:
        exchange = _FakeExchange(
            configured_leverage=2.0,
            open_orders=[{"id": "read-only-order"}],
        )
        report = build_pilot_account_preflight(_settings(), exchange=exchange)
        self.assertFalse(report["evidence"]["isolated_one_x_verified"])
        self.assertTrue(report["evidence"]["open_order_audit_complete"])
        self.assertEqual(report["evidence"]["open_order_count"], 1)
        self.assertIn("isolated_one_x_verified", report["diagnostics"]["blockers"])
        self.assertIn("no_open_orders", report["diagnostics"]["blockers"])
        self.assertEqual(
            {
                row["leverage"]
                for row in report["account"]["top3_configuration"].values()
            },
            {2.0},
        )
        self.assertEqual(exchange.mutating_calls, [])

    def test_private_authentication_failure_is_blocked(self) -> None:
        report = build_pilot_account_preflight(
            _settings(),
            exchange=_FakeExchange(private_error=RuntimeError("-2015 invalid key")),
        )
        self.assertEqual(report["diagnostics"]["verdict"], "blocked_account_preflight")
        self.assertIn("private_credentials", report["diagnostics"]["blockers"])
        self.assertIn("balance", report["diagnostics"]["errors"])

    def test_private_error_does_not_persist_credentials(self) -> None:
        report = build_pilot_account_preflight(
            _settings(),
            exchange=_FakeExchange(
                private_error=RuntimeError("request test-key signed with test-secret")
            ),
        )
        error = report["diagnostics"]["errors"]["balance"]
        self.assertNotIn("test-key", error)
        self.assertNotIn("test-secret", error)
        self.assertEqual(error.count("[REDACTED]"), 2)

    def test_existing_top3_long_is_not_a_flat_pilot_start(self) -> None:
        report = build_pilot_account_preflight(
            _settings(),
            exchange=_FakeExchange(
                positions=[
                    {
                        "symbol": "BTC/USDT:USDT",
                        "contracts": 0.001,
                        "side": "long",
                        "leverage": 1.0,
                        "marginMode": "isolated",
                    }
                ]
            ),
        )
        self.assertFalse(report["evidence"]["account_flat"])
        self.assertIn("account_flat", report["diagnostics"]["blockers"])


if __name__ == "__main__":
    unittest.main()
