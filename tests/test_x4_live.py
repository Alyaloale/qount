"""Unit tests for X4 small-cap LIVE spot execution (线 D §21).

Real-money order math is the risk surface, so the pure functions get the coverage: target-weight
derivation (gates + inverse-vol), reconciliation diff (band / caps / lot rounding / min-notional),
idempotency, and the dry/blocked safety gates of the ccxt layer (with a mock exchange — no network).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qount.grid.data import Bar  # noqa: E402
from qount.x4.live import (  # noqa: E402
    LiveConfig,
    Order,
    SymbolFilter,
    TargetWeight,
    compute_orders,
    fetch_filters,
    gate_is_open,
    place_orders,
    target_weights,
    to_ccxt_symbol,
)


def _bars(closes):
    return [Bar(ts_ms=i * 86_400_000, open=c, high=c, low=c, close=c, volume=1.0)
            for i, c in enumerate(closes)]


class TestSymbolMap(unittest.TestCase):
    def test_to_ccxt(self):
        self.assertEqual(to_ccxt_symbol("BTCUSDT"), "BTC/USDT")
        self.assertEqual(to_ccxt_symbol("LINKUSDT"), "LINK/USDT")

    def test_to_ccxt_bad_quote(self):
        with self.assertRaises(ValueError):
            to_ccxt_symbol("BTCBUSD", quote="USDT")


class TestGate(unittest.TestCase):
    def test_open_above_sma(self):
        self.assertTrue(gate_is_open(list(range(1, 11)), gate_sma=5))   # rising -> last > SMA

    def test_shut_below_sma(self):
        self.assertFalse(gate_is_open(list(range(10, 0, -1)), gate_sma=5))  # falling -> last < SMA

    def test_warmup_shut(self):
        self.assertFalse(gate_is_open([1, 2, 3], gate_sma=5))


class TestTargetWeights(unittest.TestCase):
    def _cfg(self):
        return LiveConfig(universe=("BTCUSDT", "ETHUSDT"), regime_sma=5, fast=2, slow=4,
                          vol_lookback=3, gate_sym="BTCUSDT", gate_sma=5)

    def test_flat_when_gate_shut(self):
        # BTC falling -> master gate shut -> 100% cash
        bars = {"BTCUSDT": _bars([10, 9, 8, 7, 6, 5]), "ETHUSDT": _bars([1, 2, 3, 4, 5, 6])}
        self.assertEqual(target_weights(bars, self._cfg()), [])

    def test_holds_uptrend_coins_inverse_vol(self):
        # both rising: gate open, both pass close>SMA & fastSMA>slowSMA -> weights sum to 1
        up = [1, 2, 3, 4, 5, 6, 7, 8]
        bars = {"BTCUSDT": _bars(up), "ETHUSDT": _bars(up)}
        tw = target_weights(bars, self._cfg())
        self.assertEqual({t.symbol for t in tw}, {"BTCUSDT", "ETHUSDT"})
        self.assertAlmostEqual(sum(t.weight for t in tw), 1.0, places=9)

    def test_excludes_downtrend_coin(self):
        up = [1, 2, 3, 4, 5, 6, 7, 8]
        down = [8, 7, 6, 5, 4, 3, 2, 1]
        # BTC up keeps the master gate open; ETH down must be excluded
        bars = {"BTCUSDT": _bars(up), "ETHUSDT": _bars(down)}
        tw = target_weights(bars, self._cfg())
        self.assertEqual([t.symbol for t in tw], ["BTCUSDT"])
        self.assertAlmostEqual(tw[0].weight, 1.0, places=9)


class TestComputeOrders(unittest.TestCase):
    def _setup(self, **over):
        kw = dict(universe=("BTCUSDT", "ETHUSDT"), capital_usdt=400.0,
                  rebalance_band=0.25, min_order_usdt=6.0, max_order_usdt=400.0)
        kw.update(over)
        cfg = LiveConfig(**kw)
        filt = {
            "BTCUSDT": SymbolFilter(amount_step=1e-5, min_amount=1e-5, min_notional=5.0),
            "ETHUSDT": SymbolFilter(amount_step=1e-4, min_amount=1e-4, min_notional=5.0),
        }
        prices = {"BTCUSDT": 60_000.0, "ETHUSDT": 3_000.0}
        return cfg, filt, prices

    def test_buys_from_all_cash(self):
        cfg, filt, prices = self._setup()
        tw = [TargetWeight("BTCUSDT", 0.5), TargetWeight("ETHUSDT", 0.5)]
        res = compute_orders(tw, {}, prices, filt, cfg)
        sides = {o.symbol: o for o in res.orders}
        self.assertEqual(set(sides), {"BTC/USDT", "ETH/USDT"})
        self.assertTrue(all(o.side == "buy" for o in res.orders))
        # each target = 0.5 * 400 = $200, buy uses quoteOrderQty
        self.assertAlmostEqual(sides["BTC/USDT"].quote_amount, 200.0, places=2)

    def test_idempotent_when_on_target(self):
        # already holding exactly target -> within band -> no orders
        cfg, filt, prices = self._setup()
        tw = [TargetWeight("BTCUSDT", 0.5), TargetWeight("ETHUSDT", 0.5)]
        balances = {"BTCUSDT": 200.0 / 60_000.0, "ETHUSDT": 200.0 / 3_000.0}
        res = compute_orders(tw, balances, prices, filt, cfg)
        self.assertEqual(res.orders, [])

    def test_band_suppresses_small_drift(self):
        cfg, filt, prices = self._setup()
        tw = [TargetWeight("BTCUSDT", 1.0)]
        # target $400; hold $360 (10% under, < 25% band) -> skip
        res = compute_orders(tw, {"BTCUSDT": 360.0 / 60_000.0}, prices, filt, cfg)
        self.assertEqual(res.orders, [])

    def test_sell_when_overweight(self):
        cfg, filt, prices = self._setup()
        tw = [TargetWeight("BTCUSDT", 0.0)]   # exit BTC entirely
        res = compute_orders(tw, {"BTCUSDT": 300.0 / 60_000.0}, prices, filt, cfg)
        self.assertEqual(len(res.orders), 1)
        self.assertEqual(res.orders[0].side, "sell")
        self.assertGreater(res.orders[0].base_amount, 0)

    def test_total_deployment_capped_at_capital(self):
        # weights summing >1 are normalized; total target never exceeds capital_usdt
        cfg, filt, prices = self._setup()
        tw = [TargetWeight("BTCUSDT", 0.8), TargetWeight("ETHUSDT", 0.8)]
        res = compute_orders(tw, {}, prices, filt, cfg)
        self.assertLessEqual(sum(res.target_usdt.values()), cfg.capital_usdt + 1e-6)

    def test_per_order_cap(self):
        cfg, filt, prices = self._setup(max_order_usdt=50.0)
        tw = [TargetWeight("BTCUSDT", 1.0)]
        res = compute_orders(tw, {}, prices, filt, cfg)
        self.assertLessEqual(res.orders[0].quote_amount, 50.0 + 1e-6)

    def test_min_notional_skips_dust(self):
        cfg, filt, prices = self._setup(capital_usdt=8.0)   # 2 coins -> $4 each < $5 notional
        tw = [TargetWeight("BTCUSDT", 0.5), TargetWeight("ETHUSDT", 0.5)]
        res = compute_orders(tw, {}, prices, filt, cfg)
        self.assertEqual(res.orders, [])

    def test_sell_not_more_than_held(self):
        cfg, filt, prices = self._setup()
        tw = [TargetWeight("BTCUSDT", 0.0)]
        held = 100.0 / 60_000.0   # only $100 held though "diff" might imply more
        res = compute_orders(tw, {"BTCUSDT": held}, prices, filt, cfg)
        self.assertLessEqual(res.orders[0].base_amount, held + 1e-12)

    def test_lot_rounding_down(self):
        # capital/cap large enough that the sell isn't cap-clipped -> isolates lot rounding
        cfg, filt, prices = self._setup(capital_usdt=1000.0, max_order_usdt=1000.0)
        filt["BTCUSDT"] = SymbolFilter(amount_step=1e-3, min_amount=1e-3, min_notional=5.0)
        tw = [TargetWeight("BTCUSDT", 0.0)]
        res = compute_orders(tw, {"BTCUSDT": 0.0123456}, prices, filt, cfg)
        # 0.0123456 rounded down to 1e-3 step -> 0.012
        self.assertAlmostEqual(res.orders[0].base_amount, 0.012, places=9)


class _MockExchange:
    def __init__(self):
        self.sent = []
        self.markets = {
            "BTC/USDT": {"limits": {"amount": {"min": 1e-5}, "cost": {"min": 5.0}},
                         "precision": {"amount": 5}},
        }

    def load_markets(self):
        return self.markets

    def create_order(self, symbol, type_, side, amount, price, params):
        self.sent.append((symbol, type_, side, amount, params))
        return {"id": "mock", "symbol": symbol, "side": side}


class TestExchangeLayer(unittest.TestCase):
    def test_fetch_filters(self):
        ex = _MockExchange()
        f = fetch_filters(ex, ["BTCUSDT"])
        self.assertIn("BTCUSDT", f)
        self.assertEqual(f["BTCUSDT"].min_notional, 5.0)
        self.assertAlmostEqual(f["BTCUSDT"].amount_step, 1e-5, places=12)

    def test_dry_mode_sends_nothing(self):
        ex = _MockExchange()
        orders = [Order("BTC/USDT", "buy", 0.001, 60.0, 60.0)]
        place_orders(ex, orders, mode="dry")
        self.assertEqual(ex.sent, [])

    def test_live_blocked_without_env(self, ):
        import os
        os.environ.pop("QOUNT_X4_LIVE_ENABLE", None)
        ex = _MockExchange()
        orders = [Order("BTC/USDT", "buy", 0.001, 60.0, 60.0)]
        place_orders(ex, orders, mode="live")
        self.assertEqual(ex.sent, [])   # blocked: switch off

    def test_live_sends_when_enabled(self):
        import os
        os.environ["QOUNT_X4_LIVE_ENABLE"] = "1"
        try:
            ex = _MockExchange()
            orders = [Order("BTC/USDT", "buy", 0.001, 60.0, 60.0),
                      Order("BTC/USDT", "sell", 0.002, 0.0, 120.0)]
            place_orders(ex, orders, mode="live")
            self.assertEqual(len(ex.sent), 2)
            buy = ex.sent[0]
            self.assertEqual(buy[2], "buy")
            self.assertEqual(buy[4], {"quoteOrderQty": 60.0})   # BUY by quote
            sell = ex.sent[1]
            self.assertEqual(sell[3], 0.002)                    # SELL by base amount
        finally:
            os.environ.pop("QOUNT_X4_LIVE_ENABLE", None)


if __name__ == "__main__":
    unittest.main()
