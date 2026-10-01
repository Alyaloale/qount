from __future__ import annotations

import unittest

from qount.risk_state_keys import breakeven_stop_armed_key
from qount.risk_state_keys import day_start_equity_key
from qount.risk_state_keys import partial_take_profit_done_key
from qount.risk_state_keys import trailing_profit_peak_key


class RiskStateKeyTests(unittest.TestCase):
    def test_day_start_key_is_stable_and_scoped_to_runtime_identity(self) -> None:
        self.assertEqual(
            day_start_equity_key(
                mode="paper",
                exchange_id="binance",
                market_type="future",
                quote_currency="USDT",
                date_key="2026-08-02",
            ),
            "day_start_equity:paper:binance:future:USDT:2026-08-02",
        )

    def test_position_management_keys_include_the_open_run_identity(self) -> None:
        scope = {
            "mode": "paper",
            "exchange_id": "binance",
            "market_type": "future",
            "symbol": "ETH/USDT:USDT",
            "open_run_id": 42,
        }
        self.assertEqual(
            trailing_profit_peak_key(**scope),
            "trailing_profit_peak:paper:binance:future:ETH/USDT:USDT:42",
        )
        self.assertEqual(
            partial_take_profit_done_key(**scope),
            "partial_tp_done:paper:binance:future:ETH/USDT:USDT:42",
        )
        self.assertEqual(
            breakeven_stop_armed_key(**scope),
            "breakeven_stop_armed:paper:binance:future:ETH/USDT:USDT:42",
        )


if __name__ == "__main__":
    unittest.main()
