"""Unit tests for X4 unified independent account/ledger (线 D). Plan: §3/§5.

The bake-off's fairness hinges on every strategy running the *same* ledger: identical
fee + slippage + funding model, equity-normalized, and crucially **independent** (no shared
margin). ``X4Account`` is the signed-position generalization of ``grid.perp.PerpHedgeLeg``
(which is short-only); these tests pin the accounting so all four strategies are apples-to-apples.
"""

from __future__ import annotations

import unittest

from qount.x4.account import X4Account

_CAP = 100_000.0


class TestOpenAndMark(unittest.TestCase):
    def test_flat_account_equity_is_capital(self) -> None:
        a = X4Account(initial_capital=_CAP)
        self.assertEqual(a.equity(100.0), _CAP)

    def test_long_gains_when_price_rises(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        a.trade(target_base=10.0, fill_price=100.0)  # long 10 @ 100
        self.assertAlmostEqual(a.equity(110.0), _CAP + 10.0 * 10.0)   # +100
        self.assertAlmostEqual(a.equity(90.0), _CAP - 10.0 * 10.0)    # -100

    def test_short_loses_when_price_rises(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        a.trade(target_base=-10.0, fill_price=100.0)  # short 10 @ 100
        self.assertAlmostEqual(a.equity(110.0), _CAP - 10.0 * 10.0)
        self.assertAlmostEqual(a.equity(90.0), _CAP + 10.0 * 10.0)


class TestWalletBalance(unittest.TestCase):
    def test_flat_wallet_equals_capital(self) -> None:
        a = X4Account(initial_capital=_CAP)
        self.assertEqual(a.wallet_balance(), _CAP)

    def test_wallet_excludes_open_unrealized(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        a.trade(target_base=-10.0, fill_price=100.0)  # short 10 @ 100
        # marked equity swings with price; walletBalance ignores the open MTM
        self.assertAlmostEqual(a.equity(90.0), _CAP + 100.0)   # short wins on the drop
        self.assertAlmostEqual(a.wallet_balance(), _CAP)        # but realized-only is unchanged
        self.assertAlmostEqual(a.equity(110.0), _CAP - 100.0)
        self.assertAlmostEqual(a.wallet_balance(), _CAP)

    def test_wallet_moves_only_on_realized_pnl(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        a.trade(target_base=-10.0, fill_price=100.0)   # short 10 @ 100
        a.trade(target_base=0.0, fill_price=90.0)      # cover @ 90 -> realize +100
        self.assertAlmostEqual(a.realized_pnl, 100.0)
        self.assertAlmostEqual(a.wallet_balance(), _CAP + 100.0)  # now it moves (booked)


class TestFeesAndSlippage(unittest.TestCase):
    def test_fee_charged_on_notional(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0005, slippage=0.0)
        a.trade(target_base=10.0, fill_price=100.0)  # notional 1000, fee 0.5
        self.assertAlmostEqual(a.fees_paid, 1000.0 * 0.0005)
        self.assertAlmostEqual(a.equity(100.0), _CAP - 0.5)

    def test_slippage_adverse_on_both_sides(self) -> None:
        # buy fills higher, sell fills lower
        a = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.01)
        a.trade(target_base=10.0, fill_price=100.0)   # buy @ 101
        self.assertAlmostEqual(a.avg_price, 101.0)
        b = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.01)
        b.trade(target_base=-10.0, fill_price=100.0)  # sell @ 99
        self.assertAlmostEqual(b.avg_price, 99.0)


class TestRoundTripRealization(unittest.TestCase):
    def test_long_round_trip_realizes_spread(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        a.trade(target_base=10.0, fill_price=100.0)
        a.trade(target_base=0.0, fill_price=120.0)  # close long @ 120
        self.assertAlmostEqual(a.position_base, 0.0)
        self.assertAlmostEqual(a.realized_pnl, 10.0 * 20.0)  # +200
        self.assertAlmostEqual(a.equity(999.0), _CAP + 200.0)  # flat: mark irrelevant

    def test_short_round_trip_realizes_spread(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        a.trade(target_base=-10.0, fill_price=100.0)
        a.trade(target_base=0.0, fill_price=80.0)  # cover short @ 80
        self.assertAlmostEqual(a.realized_pnl, 10.0 * 20.0)  # short profits as price fell

    def test_partial_close_keeps_avg_price(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        a.trade(target_base=10.0, fill_price=100.0)
        a.trade(target_base=4.0, fill_price=110.0)  # sell 6 @ 110
        self.assertAlmostEqual(a.position_base, 4.0)
        self.assertAlmostEqual(a.avg_price, 100.0)         # avg unchanged on reduction
        self.assertAlmostEqual(a.realized_pnl, 6.0 * 10.0)  # +60 on closed 6


class TestFlip(unittest.TestCase):
    def test_long_to_short_realizes_then_reopens(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        a.trade(target_base=10.0, fill_price=100.0)
        a.trade(target_base=-5.0, fill_price=120.0)  # close 10 long @120 (+200), open 5 short @120
        self.assertAlmostEqual(a.position_base, -5.0)
        self.assertAlmostEqual(a.avg_price, 120.0)
        self.assertAlmostEqual(a.realized_pnl, 10.0 * 20.0)
        # now price up to 130: short of 5 loses 50
        self.assertAlmostEqual(a.equity(130.0), _CAP + 200.0 - 5.0 * 10.0)


class TestFunding(unittest.TestCase):
    def test_long_pays_short_receives_positive_rate(self) -> None:
        # positive funding rate: longs pay shorts
        lo = X4Account(initial_capital=_CAP, taker_fee=0.0)
        lo.trade(target_base=10.0, fill_price=100.0)
        amt = lo.accrue_funding(0.0001, 100.0)
        self.assertAlmostEqual(amt, -0.0001 * 10.0 * 100.0)  # pays
        sh = X4Account(initial_capital=_CAP, taker_fee=0.0)
        sh.trade(target_base=-10.0, fill_price=100.0)
        self.assertAlmostEqual(sh.accrue_funding(0.0001, 100.0), +0.0001 * 10.0 * 100.0)

    def test_flat_account_no_funding(self) -> None:
        a = X4Account(initial_capital=_CAP)
        self.assertEqual(a.accrue_funding(0.01, 100.0), 0.0)


class TestIndependence(unittest.TestCase):
    def test_two_accounts_do_not_share_state(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0)
        b = X4Account(initial_capital=_CAP, taker_fee=0.0)
        a.trade(target_base=10.0, fill_price=100.0)
        self.assertEqual(b.position_base, 0.0)
        self.assertEqual(b.equity(100.0), _CAP)


class TestWeight(unittest.TestCase):
    def test_weight_is_signed_exposure_fraction(self) -> None:
        a = X4Account(initial_capital=_CAP, taker_fee=0.0)
        a.trade(target_base=1000.0, fill_price=100.0)  # notional 100k = 1x at cap
        self.assertAlmostEqual(a.weight(100.0), 1.0)


if __name__ == "__main__":
    unittest.main()
