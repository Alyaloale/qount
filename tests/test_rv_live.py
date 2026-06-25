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
    execute_funding,
    from_ccxt_dated,
    neutralize_spot_targets,
    place_carry_orders,
    plan_funding,
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
        # 2 pairs -> 500 each -> short N=375 (500×3/4); spot long = N(L−1)/L = 375×2/3 = 250;
        # margin coin = N/L = 125; total long 250+125 = 375 == short => Δ≈0.
        cfg = CarryConfig(capital_usdt=1_000.0, liq_leverage=3.0)
        legs = target_legs(_ms(2026, 1, 15), cfg)
        self.assertEqual(len(legs), 4)                              # spot+dated per pair
        spots = [l for l in legs if l.kind == "spot"]
        dated = [l for l in legs if l.kind == "dated"]
        self.assertEqual((len(spots), len(dated)), (2, 2))
        L = cfg.liq_leverage
        for l in spots:
            self.assertAlmostEqual(l.notional_usdt, 250.0, places=6)   # +long = N(L−1)/L
        for l in dated:
            self.assertAlmostEqual(l.notional_usdt, -375.0, places=6)  # −short N
        # the key invariant: spot long + COIN-M margin coin (N/L) == short notional -> net Δ ≈ 0
        for sl, dl in zip(spots, dated):
            short_n = abs(dl.notional_usdt)
            total_long = sl.notional_usdt + short_n / L              # spot + margin coin
            self.assertAlmostEqual(total_long, short_n, places=6)    # Δ ≈ 0

    def test_skips_btc_and_reallocates_its_capital_to_eth(self):
        # $200 carry slice: split 2 ways -> N=75, BTCUSD=$100/contract can't fund 1 -> BTC dropped.
        # Its half is REALLOCATED to ETH (2026-06-19): ETH-only -> N = 200×3/4 = 150 (NOT the old 75),
        # so the carry deploys the FULL slice instead of stranding the BTC half idle.
        cfg = CarryConfig(capital_usdt=200.0, liq_leverage=3.0)
        legs = target_legs(_ms(2026, 1, 15), cfg)
        self.assertFalse(any(l.symbol == "BTCUSDT" for l in legs))          # BTC pair dropped
        self.assertFalse(any(l.symbol.startswith("BTCUSD_") for l in legs))
        self.assertEqual(len(legs), 2)                                      # only ETH spot+dated
        dated = next(l for l in legs if l.kind == "dated")
        spot = next(l for l in legs if l.kind == "spot")
        self.assertAlmostEqual(dated.notional_usdt, -150.0, places=6)       # full slice -> N=150 (not 75)
        self.assertAlmostEqual(spot.notional_usdt, 100.0, places=6)         # 150×2/3 = 100
        # Δ≈0 invariant still holds after reallocation: spot + margin (N/L) == short N
        self.assertAlmostEqual(spot.notional_usdt + abs(dated.notional_usdt) / 3.0,
                               abs(dated.notional_usdt), places=6)

    def test_skips_both_when_capital_too_small(self):
        # $12 carry slice -> even ETH-only (after dropping BTC) N = 12×3/4 = 9 < ETHUSD $10 -> both
        # skipped (the reallocation can't conjure a fundable leg out of too little capital).
        cfg = CarryConfig(capital_usdt=12.0, liq_leverage=3.0)
        self.assertEqual(target_legs(_ms(2026, 1, 15), cfg), [])


class TestNeutralizeSpotTargets(unittest.TestCase):
    def test_floors_short_and_reaims_spot_to_zero_delta(self):
        # the live $133/ETH-only case: model short −99.75 floors to −90 (9× $10 ETHUSD contracts);
        # margin coin = $39.29 of ETH in the COIN-M wallet. Spot must re-aim to 90 − 39.29 = 50.71 so
        # long (spot+margin) == short == 90 => Δ≈0 (vs the un-fixed model spot 66.5 -> +12.5 drift).
        cfg = CarryConfig(capital_usdt=133.0, liq_leverage=3.0)
        legs = [CarryLeg("spot", "ETHUSDT", 66.5),
                CarryLeg("dated", "ETHUSD_260925", -99.75, base="ETHUSD")]
        out = neutralize_spot_targets(legs, {"ETHUSDT": 39.29}, cfg)
        dated = next(l for l in out if l.kind == "dated")
        spot = next(l for l in out if l.kind == "spot")
        self.assertAlmostEqual(dated.notional_usdt, -90.0, places=6)     # floored 99.75 -> 90 (9 contracts)
        self.assertAlmostEqual(spot.notional_usdt, 50.71, places=6)      # 90 − 39.29
        # Δ≈0: spot + margin == |short|
        self.assertAlmostEqual(spot.notional_usdt + 39.29, abs(dated.notional_usdt), places=6)

    def test_clamps_spot_at_zero_when_margin_exceeds_short(self):
        cfg = CarryConfig(capital_usdt=133.0, liq_leverage=3.0)
        legs = [CarryLeg("spot", "ETHUSDT", 66.5),
                CarryLeg("dated", "ETHUSD_260925", -90.0, base="ETHUSD")]
        out = neutralize_spot_targets(legs, {"ETHUSDT": 150.0}, cfg)     # margin > short
        spot = next(l for l in out if l.kind == "spot")
        self.assertEqual(spot.notional_usdt, 0.0)                        # clamped, never negative

    def test_no_margin_reading_leaves_legs_untouched(self):
        # dry / pre-key: empty margin map -> dated still floored (cosmetic), spot keeps the model target.
        cfg = CarryConfig(capital_usdt=133.0, liq_leverage=3.0)
        legs = [CarryLeg("spot", "ETHUSDT", 66.5),
                CarryLeg("dated", "ETHUSD_260925", -90.0, base="ETHUSD")]
        out = neutralize_spot_targets(legs, {}, cfg)
        spot = next(l for l in out if l.kind == "spot")
        self.assertAlmostEqual(spot.notional_usdt, 66.5, places=6)       # untouched without a margin read


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
    def __init__(self, raises=False):
        self.sent = []
        self._raises = raises

    def create_order(self, symbol, type_, side, amount, price, params):
        self.sent.append((symbol, type_, side, amount, params))
        if self._raises:
            raise RuntimeError("simulated venue error")
        return {"id": "mock", "symbol": symbol}


class TestCarryExecutionSafety(unittest.TestCase):
    """2026-06-19 incident fixes: COIN-M contract quantity (-1102), spot-first, per-leg non-fatal."""

    def setUp(self):
        os.environ["QOUNT_RV_LIVE_ENABLE"] = "1"

    def tearDown(self):
        os.environ.pop("QOUNT_RV_LIVE_ENABLE", None)

    def test_coinm_order_uses_integer_contract_quantity(self):
        sp, cm = _Mock(), _Mock()
        # BTCUSD $100/contract; $300 short -> 3 contracts (NOT notional/quoteOrderQty -> was the -1102)
        place_carry_orders(sp, cm, [CarryOrder("BTCUSD_260626", "sell", 300.0)], mode="live", cfg=CarryConfig())
        self.assertEqual(len(cm.sent), 1)
        sym, type_, side, amount, params = cm.sent[0]
        self.assertEqual((sym, side, amount), ("BTC/USD:BTC-260626", "sell", 3))   # 3 whole contracts
        self.assertNotIn("quoteOrderQty", params)

    def test_contract_quantity_floors_not_rounds(self):
        sp, cm = _Mock(), _Mock()
        # ETHUSD $10/contract; $75 short -> 7 (floor of 7.5), NOT 8 (round-up over-sizes past margin = -2019)
        place_carry_orders(sp, cm, [CarryOrder("ETHUSD_260626", "sell", 75.0)], mode="live", cfg=CarryConfig())
        self.assertEqual(cm.sent[0][3], 7)   # floor(7.5) = 7

    def test_below_one_contract_skips(self):
        sp, cm = _Mock(), _Mock()
        place_carry_orders(sp, cm, [CarryOrder("BTCUSD_260626", "sell", 50.0)], mode="live", cfg=CarryConfig())
        self.assertEqual(cm.sent, [])   # $50 < $100 contract -> nothing sent

    def test_spot_placed_before_short(self):
        # SPOT-FIRST: the safe-residual ordering (a partial leaves a naked LONG, never a naked short)
        order_log = []
        sp, cm = _Mock(), _Mock()
        sp.create_order = lambda *a, **k: (order_log.append("spot"), {"id": "s"})[1]
        cm.create_order = lambda *a, **k: (order_log.append("dated"), {"id": "d"})[1]
        orders = [CarryOrder("ETHUSD_260626", "sell", 75.0), CarryOrder("ETHUSDT", "buy", 50.0)]  # dated first in list
        place_carry_orders(sp, cm, orders, mode="live", cfg=CarryConfig())
        self.assertEqual(order_log, ["spot", "dated"])   # spot still placed FIRST regardless of input order

    def test_short_failure_is_non_fatal_and_spot_still_placed(self):
        # short fails -> non-fatal (no crash), spot long WAS placed (safe naked long, re-hedged next run)
        sp, cm = _Mock(), _Mock(raises=True)
        orders = [CarryOrder("ETHUSDT", "buy", 50.0), CarryOrder("ETHUSD_260626", "sell", 75.0)]
        res = place_carry_orders(sp, cm, orders, mode="live", cfg=CarryConfig())   # must not raise
        self.assertEqual(len(sp.sent), 1)                       # spot long opened
        self.assertTrue(any("error" in r for r in res))         # short failure recorded, non-fatal


class TestPlanFunding(unittest.TestCase):
    """Auto-funding: pull idle UMFUTURE USDT -> spot longs + COIN-M margin coins (cfg.autofund)."""

    def _legs(self):
        # one pair, spot long N=$300 (-> COIN-M short margin N/L = $100 at L=3)
        return [CarryLeg("spot", "BTCUSDT", +300.0), CarryLeg("dated", "BTCUSD_260626", -300.0, base="BTCUSD")]

    def _cfg(self, **o):
        kw = dict(autofund=True, liq_leverage=3.0, um_buffer_usdt=200.0, min_order_usdt=10.0)
        kw.update(o)
        return CarryConfig(**kw)

    def test_off_by_default_empty_plan(self):
        p = plan_funding(self._legs(), 0.0, {}, {"BTCUSDT": 60000.0}, 1000.0, CarryConfig())  # autofund off
        self.assertEqual(p.actions, [])

    def test_transfers_and_buys_margin_from_flat(self):
        # flat: need spot 300 (long) + 100 (margin coin) = 400 USDT; transfer from UMFUTURE (avail 1000, buf 200 -> cap 800)
        p = plan_funding(self._legs(), 0.0, {}, {"BTCUSDT": 60000.0}, 1000.0, self._cfg())
        kinds = [a.kind for a in p.actions]
        self.assertEqual(kinds, ["transfer_usdt_to_spot", "buy_margin_coin", "transfer_coin_to_cm"])
        self.assertAlmostEqual(p.actions[0].amount, 400.0)      # 300 long + 100 margin
        self.assertAlmostEqual(p.um_draw_usdt, 400.0)
        self.assertAlmostEqual(p.actions[1].amount, 100.0)      # buy $100 BTC margin
        self.assertAlmostEqual(p.actions[2].amount, 100.0 / 60000.0)  # coin units to COIN-M

    def test_respects_um_buffer_skips_when_insufficient(self):
        # avail 250, buffer 200 -> cap 50 < need 400 -> skip (never drain the trend leg)
        p = plan_funding(self._legs(), 0.0, {}, {"BTCUSDT": 60000.0}, 250.0, self._cfg())
        self.assertEqual(p.actions, [])
        self.assertTrue(p.skipped and "缓冲" in p.skipped[0])

    def test_uses_existing_spot_usdt_and_margin(self):
        # already 350 USDT in spot + $100 margin coin already in COIN-M -> only 300-? ; need 300 long +0 margin =300, have 350 -> no transfer
        p = plan_funding(self._legs(), 350.0, {"BTCUSDT": 100.0}, {"BTCUSDT": 60000.0}, 1000.0, self._cfg())
        self.assertFalse(any(a.kind == "transfer_usdt_to_spot" for a in p.actions))  # spot already funded
        self.assertFalse(any(a.kind == "buy_margin_coin" for a in p.actions))        # margin already there

    def test_credits_held_spot_no_bleed_when_at_target(self):
        # at target: spot long $300 already HELD + $100 margin already in COIN-M -> no incremental need,
        # so NOTHING is transferred even with idle UMFUTURE available (was the bleed bug: full-N need each
        # run topped spot USDT toward $300 and drained the trend wallet into idle cash).
        p = plan_funding(self._legs(), 0.0, {"BTCUSDT": 100.0}, {"BTCUSDT": 60000.0}, 1000.0, self._cfg(),
                         cur_spot_usdt={"BTCUSDT": 300.0})
        self.assertEqual(p.actions, [])
        self.assertAlmostEqual(p.um_draw_usdt, 0.0)

    def test_held_spot_funds_only_the_shortfall(self):
        # $120 of the $300 spot long already held -> only $180 incremental spot + $100 margin = $280 need
        p = plan_funding(self._legs(), 0.0, {}, {"BTCUSDT": 60000.0}, 1000.0, self._cfg(),
                         cur_spot_usdt={"BTCUSDT": 120.0})
        self.assertAlmostEqual(p.actions[0].amount, 280.0)     # 180 incremental long + 100 margin
        self.assertAlmostEqual(p.um_draw_usdt, 280.0)

    def test_execute_dry_sends_nothing(self):
        p = plan_funding(self._legs(), 0.0, {}, {"BTCUSDT": 60000.0}, 1000.0, self._cfg())
        ex = _FundMock()
        execute_funding(ex, p, mode="dry", cfg=self._cfg())
        self.assertEqual(ex.transfers, [])
        self.assertEqual(ex.sent, [])

    def test_execute_live_routes_transfer_buy_transfer(self):
        os.environ["QOUNT_RV_LIVE_ENABLE"] = "1"
        try:
            p = plan_funding(self._legs(), 0.0, {}, {"BTCUSDT": 60000.0}, 1000.0, self._cfg())
            ex = _FundMock(free={"BTC": 0.002})   # margin BTC available after the buy (free-balance read)
            execute_funding(ex, p, mode="live", cfg=self._cfg())
            self.assertEqual(ex.transfers[0], ("USDT", 400.0, "future", "spot"))   # UMFUTURE->SPOT
            self.assertEqual(ex.sent[0][:3], ("BTC/USDT", "market", "buy"))         # buy margin coin
            self.assertEqual(ex.transfers[1][0], "BTC")                              # SPOT->COIN-M
            self.assertEqual(ex.transfers[1][2:], ("spot", "delivery"))
        finally:
            os.environ.pop("QOUNT_RV_LIVE_ENABLE", None)


class _FundMock:
    def __init__(self, free=None):
        self.transfers = []
        self.sent = []
        self._free = free or {}     # asset -> free balance (for the coin-transfer free-balance read)

    def transfer(self, code, amount, fromAccount, toAccount):
        self.transfers.append((code, amount, fromAccount, toAccount))
        return {"id": "t"}

    def create_order(self, symbol, type_, side, amount, price, params):
        self.sent.append((symbol, type_, side, amount, params))
        return {"id": "o", "symbol": symbol}

    def fetch_balance(self):
        return {"free": dict(self._free)}


class TestExecuteFundingTransfer(unittest.TestCase):
    """coin->COIN-M transfer must use ACTUAL free balance (pre-fee estimate > filled -> insufficient)."""

    def test_coin_transfer_uses_free_not_estimate(self):
        os.environ["QOUNT_RV_LIVE_ENABLE"] = "1"
        try:
            from qount.rv.live import FundingAction, FundingPlan
            # plan wants to move 0.0146 ETH, but only 0.0140 actually filled (fees) -> must cap to free
            plan = FundingPlan(actions=[FundingAction("transfer_coin_to_cm", "ETH", 0.0146,
                                                      reason="margin SPOT->COIN-M")])
            ex = _FundMock(free={"ETH": 0.0140})
            execute_funding(ex, plan, mode="live", cfg=CarryConfig())
            self.assertEqual(len(ex.transfers), 1)
            code, amt, frm, to = ex.transfers[0]
            self.assertEqual((code, frm, to), ("ETH", "spot", "delivery"))
            self.assertLessEqual(amt, 0.0140)            # capped to free, not the 0.0146 estimate
            self.assertGreater(amt, 0.0139)              # ~free × 0.999
        finally:
            os.environ.pop("QOUNT_RV_LIVE_ENABLE", None)


if __name__ == "__main__":
    unittest.main()
