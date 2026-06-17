"""Unit tests for RV-C cash-and-carry LIVE execution (线 C 实盘腿).

Two-leg real-money order math + the quarterly roll are the risk surface, so the pure functions get
the coverage: active-dated PIT selection, delta-neutral leg sizing, reconciliation (band / min / the
roll-out of an expiring contract), and the dry/blocked/route safety of the (mocked) ccxt layer.
"""
import datetime as dt
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qount.rv.data import quarterly_contracts  # noqa: E402
from qount.rv.live import (  # noqa: E402
    _DAY_MS,
    CarryConfig,
    CarryLeg,
    CarryOrder,
    active_dated,
    compute_carry_orders,
    from_ccxt_dated,
    place_carry_orders,
    rv_live_enabled,
    target_legs,
    to_ccxt_dated,
    to_ccxt_spot,
)


def _ms(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=dt.UTC).timestamp() * 1000)


class TestActiveDated(unittest.TestCase):
    def test_picks_future_quarterly_beyond_buffer(self):
        now = _ms(2026, 1, 15)
        ad = active_dated("BTCUSD", now, CarryConfig())
        self.assertIsNotNone(ad)
        sym, exp = ad
        self.assertTrue(sym.startswith("BTCUSD_"))
        self.assertGreater(exp - now, CarryConfig().roll_buffer_days * _DAY_MS)

    def test_rolls_to_next_inside_buffer(self):
        # sit 2 days before the nearest quarterly's expiry (inside the 5d buffer) -> pick the NEXT one
        q = quarterly_contracts((2026, 1), (2027, 6), base="BTCUSD")
        first_exp, second_exp = q[0][1], q[1][1]
        now = first_exp - 2 * _DAY_MS
        sym, exp = active_dated("BTCUSD", now, CarryConfig(roll_buffer_days=5.0))
        self.assertEqual(exp, second_exp)        # rolled past the near, pinned contract
        self.assertNotEqual(exp, first_exp)


class TestTargetLegs(unittest.TestCase):
    def test_delta_neutral_legs_and_sizing(self):
        cfg = CarryConfig(capital_usdt=1_000.0, liq_leverage=3.0)   # 2 pairs -> 500 each -> N=375
        legs = target_legs(_ms(2026, 1, 15), cfg)
        self.assertEqual(len(legs), 4)                              # spot+dated per pair
        spots = [l for l in legs if l.kind == "spot"]
        dated = [l for l in legs if l.kind == "dated"]
        self.assertEqual(len(spots), 2)
        self.assertEqual(len(dated), 2)
        for l in spots:
            self.assertAlmostEqual(l.notional_usdt, 375.0, places=6)   # +long, 500×3/4
        for l in dated:
            self.assertAlmostEqual(l.notional_usdt, -375.0, places=6)  # −short, equal -> Δ≈0

    def test_skips_btc_when_below_one_contract(self):
        # $200 carry slice -> 100 each pair -> N=75 short. BTCUSD=$100/contract -> can't fund 1 ->
        # skip BTC entirely (no naked spot); ETHUSD=$10/contract -> 75 funds 7 contracts -> kept.
        cfg = CarryConfig(capital_usdt=200.0, liq_leverage=3.0)
        legs = target_legs(_ms(2026, 1, 15), cfg)
        self.assertFalse(any(l.symbol == "BTCUSDT" for l in legs))          # BTC pair dropped
        self.assertFalse(any(l.symbol.startswith("BTCUSD_") for l in legs))
        self.assertTrue(any(l.symbol == "ETHUSDT" for l in legs))           # ETH pair kept
        self.assertTrue(any(l.symbol.startswith("ETHUSD_") for l in legs))
        self.assertEqual(len(legs), 2)                                      # only ETH spot+dated

    def test_skips_both_when_capital_too_small(self):
        # $20 carry slice -> 10 each pair -> N=7.5 short -> below ETHUSD $10 too -> both skipped.
        cfg = CarryConfig(capital_usdt=20.0, liq_leverage=3.0)
        self.assertEqual(target_legs(_ms(2026, 1, 15), cfg), [])


class TestComputeCarryOrders(unittest.TestCase):
    def _cfg(self):
        return CarryConfig(capital_usdt=1_000.0, liq_leverage=3.0, rebalance_band=0.10,
                           min_order_usdt=10.0)

    def test_opens_both_legs_from_flat(self):
        cfg = self._cfg()
        legs = target_legs(_ms(2026, 1, 15), cfg)
        res = compute_carry_orders(legs, {}, cfg)
        spot = [o for o in res.orders if "_" not in o.symbol]
        dated = [o for o in res.orders if "_" in o.symbol]
        self.assertTrue(all(o.side == "buy" for o in spot))    # open long spot
        self.assertTrue(all(o.side == "sell" for o in dated))  # open short dated
        self.assertEqual(len(res.orders), 4)

    def test_idempotent_on_target(self):
        cfg = self._cfg()
        legs = target_legs(_ms(2026, 1, 15), cfg)
        cur = {l.symbol: l.notional_usdt for l in legs}        # already exactly at target
        res = compute_carry_orders(legs, cur, cfg)
        self.assertEqual(res.orders, [])

    def test_band_suppresses_small_drift(self):
        cfg = self._cfg()
        legs = target_legs(_ms(2026, 1, 15), cfg)
        cur = {l.symbol: l.notional_usdt * (0.96 if l.kind == "spot" else 1.0) for l in legs}  # 4% off
        res = compute_carry_orders(legs, cur, cfg)
        self.assertEqual(res.orders, [])                       # 4% < 10% band

    def test_roll_covers_expiring_and_opens_new(self):
        cfg = self._cfg()
        now = _ms(2026, 1, 15)
        legs = target_legs(now, cfg)
        active_btc_dated = next(l.symbol for l in legs if l.kind == "dated" and l.symbol.startswith("BTCUSD"))
        # currently short an OLD btc quarterly (not the active target) + holding the spot long
        old = "BTCUSD_251226"
        cur = {"BTCUSDT": 375.0, old: -375.0,
               "ETHUSDT": 375.0, next(l.symbol for l in legs if l.symbol.startswith("ETHUSD_")): -375.0}
        res = compute_carry_orders(legs, cur, cfg)
        self.assertIn(old, res.rolled)                         # expiring leg flagged as a roll
        cover = next(o for o in res.orders if o.symbol == old)
        self.assertEqual(cover.side, "buy")                    # buy back to cover the old short
        self.assertTrue(cover.is_roll)
        opened = next(o for o in res.orders if o.symbol == active_btc_dated)
        self.assertEqual(opened.side, "sell")                  # open the new active short


class TestCcxtLayer(unittest.TestCase):
    def test_symbol_maps(self):
        self.assertEqual(to_ccxt_spot("BTCUSDT"), "BTC/USDT")
        self.assertEqual(to_ccxt_dated("BTCUSD_260626"), "BTC/USD:BTC-260626")
        self.assertEqual(to_ccxt_dated("ETHUSD_260925"), "ETH/USD:ETH-260925")
        self.assertEqual(from_ccxt_dated("BTC/USD:BTC-260626"), "BTCUSD_260626")  # round-trips
        self.assertEqual(from_ccxt_dated(to_ccxt_dated("ETHUSD_260925")), "ETHUSD_260925")

    def test_dry_sends_nothing(self):
        sp, cm = _Mock(), _Mock()
        place_carry_orders(sp, cm, [CarryOrder("BTCUSDT", "buy", 300.0)], mode="dry")
        self.assertEqual(sp.sent + cm.sent, [])

    def test_live_blocked_without_env(self):
        os.environ.pop("QOUNT_RV_LIVE_ENABLE", None)
        sp, cm = _Mock(), _Mock()
        place_carry_orders(sp, cm, [CarryOrder("BTCUSDT", "buy", 300.0)], mode="live")
        self.assertEqual(sp.sent + cm.sent, [])

    def test_live_routes_each_leg_to_its_venue(self):
        os.environ["QOUNT_RV_LIVE_ENABLE"] = "1"
        try:
            sp, cm = _Mock(), _Mock()
            orders = [CarryOrder("BTCUSDT", "buy", 300.0), CarryOrder("BTCUSD_260626", "sell", 300.0)]
            place_carry_orders(sp, cm, orders, mode="live", cfg=CarryConfig())
            self.assertEqual(len(sp.sent), 1)                  # spot leg -> spot venue
            self.assertEqual(sp.sent[0][0], "BTC/USDT")
            self.assertEqual(len(cm.sent), 1)                  # dated leg -> COIN-M venue
            self.assertEqual(cm.sent[0][0], "BTC/USD:BTC-260626")
        finally:
            os.environ.pop("QOUNT_RV_LIVE_ENABLE", None)


class _Mock:
    def __init__(self):
        self.sent = []

    def create_order(self, symbol, type_, side, amount, price, params):
        self.sent.append((symbol, type_, side, amount, params))
        return {"id": "mock", "symbol": symbol}


if __name__ == "__main__":
    unittest.main()
