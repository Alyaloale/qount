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
    apply_chandelier_stops,
    chandelier_stop_prices,
    compute_orders,
    fetch_filters,
    fetch_open_stops,
    gate_is_open,
    place_orders,
    plan_stop_orders,
    portfolio_gate_open,
    prepare_swap,
    sync_stop_orders,
    target_weights,
    to_ccxt_symbol,
    unreachable_coins,
)


def _closes_from_rets(start, rets):
    out = [start]
    for r in rets:
        out.append(out[-1] * (1.0 + r))
    return out


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
        # legacy pins: pure BTC gate + no corr penalty + short ATR window (toy series)
        return LiveConfig(universe=("BTCUSDT", "ETHUSDT"), regime_sma=5, fast=2, slow=4,
                          vol_lookback=3, atr_lookback=3, gate_sym="BTCUSDT", gate_sma=5,
                          breadth_gate=None, corr_penalty=False)

    def test_flat_when_gate_shut(self):
        # BTC falling -> master gate shut -> 100% cash
        bars = {"BTCUSDT": _bars([10, 9, 8, 7, 6, 5]), "ETHUSDT": _bars([1, 2, 3, 4, 5, 6])}
        self.assertEqual(target_weights(bars, self._cfg()), [])

    def test_holds_uptrend_coins_equal_when_identical(self):
        # both rising identically: gate open, both held; weights = absolute exposure (vol-parity),
        # equal to each other, positive, and total gross within the leverage cap
        up = [1, 2, 3, 4, 5, 6, 7, 8]
        bars = {"BTCUSDT": _bars(up), "ETHUSDT": _bars(up)}
        tw = target_weights(bars, self._cfg())
        self.assertEqual({t.symbol for t in tw}, {"BTCUSDT", "ETHUSDT"})
        w = {t.symbol: t.weight for t in tw}
        self.assertAlmostEqual(w["BTCUSDT"], w["ETHUSDT"], places=9)
        self.assertGreater(w["BTCUSDT"], 0.0)
        self.assertLessEqual(sum(w.values()), self._cfg().max_leverage + 1e-9)

    def test_excludes_downtrend_coin(self):
        up = [1, 2, 3, 4, 5, 6, 7, 8]
        down = [8, 7, 6, 5, 4, 3, 2, 1]
        # BTC up keeps the master gate open; ETH down must be excluded
        bars = {"BTCUSDT": _bars(up), "ETHUSDT": _bars(down)}
        tw = target_weights(bars, self._cfg())
        self.assertEqual([t.symbol for t in tw], ["BTCUSDT"])
        self.assertGreater(tw[0].weight, 0.0)


class TestComputeOrders(unittest.TestCase):
    def _setup(self, **over):
        # weights are ABSOLUTE exposure fractions now -> target = weight × capital (no renorm/lev)
        kw = dict(universe=("BTCUSDT", "ETHUSDT"), capital_usdt=400.0,
                  rebalance_band=0.25, min_order_usdt=6.0, max_order_usdt=400.0,
                  market_type="spot", max_leverage=2.0)
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

    def test_gross_clamped_to_max_leverage(self):
        # absolute exposures summing above the leverage cap are scaled down proportionally
        cfg, filt, prices = self._setup(max_leverage=1.0)
        tw = [TargetWeight("BTCUSDT", 0.8), TargetWeight("ETHUSDT", 0.8)]   # gross 1.6 > cap 1.0
        res = compute_orders(tw, {}, prices, filt, cfg)
        self.assertLessEqual(sum(res.target_usdt.values()), cfg.max_leverage * cfg.capital_usdt + 1e-6)

    def test_no_renormalize_below_cap(self):
        # gross 1.0 < cap -> weights used as-is (NOT renormalized away): 0.5 -> $200, not rescaled
        cfg, filt, prices = self._setup()
        tw = [TargetWeight("BTCUSDT", 0.3), TargetWeight("ETHUSDT", 0.3)]   # vol-parity ~0.6 gross
        res = compute_orders(tw, {}, prices, filt, cfg)
        self.assertAlmostEqual(res.target_usdt["BTCUSDT"], 120.0, places=2)   # 0.3 × 400, no renorm

    def test_per_order_cap(self):
        cfg, filt, prices = self._setup(max_order_usdt=50.0)
        tw = [TargetWeight("BTCUSDT", 1.0)]
        res = compute_orders(tw, {}, prices, filt, cfg)
        self.assertLessEqual(res.orders[0].quote_amount, 50.0 + 1e-6)

    def test_buy_capped_by_buying_power_when_max_order_stale(self):
        # stale huge max_order_usdt must NOT let a buy exceed capital × leverage (buying power)
        cfg, filt, prices = self._setup(capital_usdt=70.0, max_order_usdt=830.0, max_leverage=2.0)
        tw = [TargetWeight("BTCUSDT", 5.0)]   # absurd weight -> gross clamp to 2.0 -> $140 target
        res = compute_orders(tw, {}, prices, filt, cfg)
        self.assertLessEqual(res.orders[0].quote_amount, 70.0 * 2.0 + 1e-6)   # <= $140, not $830

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
    def __init__(self, positions=None, lev_echo="ACK"):
        self.sent = []
        self.leverage_set = []
        self.margin_set = []
        self.positions = positions   # None -> fetch_positions raises (no key); list -> returned
        # lev_echo mirrors Binance's set_leverage response: "ACK" -> echo the requested leverage
        # (normal success); None -> no leverage in response; int -> echo that value (silent
        # mis-set); "RAISE" -> set_leverage throws.
        self.lev_echo = lev_echo
        self.markets = {
            "BTC/USDT": {"limits": {"amount": {"min": 1e-5}, "cost": {"min": 5.0}},
                         "precision": {"amount": 5}},
            "BTC/USDT:USDT": {"limits": {"amount": {"min": 1e-3}, "cost": {"min": 5.0}},
                              "precision": {"amount": 3}},
        }

    def load_markets(self):
        return self.markets

    def create_order(self, symbol, type_, side, amount, price, params):
        self.sent.append((symbol, type_, side, amount, params))
        return {"id": "mock", "symbol": symbol, "side": side}

    def set_leverage(self, lev, symbol):
        self.leverage_set.append((lev, symbol))
        if self.lev_echo == "RAISE":
            raise RuntimeError("set_leverage failed")
        if self.lev_echo == "ACK":
            return {"leverage": lev, "symbol": symbol}
        if self.lev_echo is None:
            return {"symbol": symbol}
        return {"leverage": self.lev_echo, "symbol": symbol}

    def set_margin_mode(self, mode, symbol):
        self.margin_set.append((mode, symbol))

    def fetch_positions(self, symbols=None):
        if self.positions is None:
            raise RuntimeError("no futures key")
        return self.positions


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


class TestBreadthGate(unittest.TestCase):
    """§21.4 B: risk-on if BTC gate OR breadth broad (or 'and'/'breadth')."""

    def _cfg(self, **over):
        kw = dict(universe=("BTCUSDT", "ETHUSDT"), regime_sma=5, fast=2, slow=4, vol_lookback=3,
                  atr_lookback=3, gate_sym="BTCUSDT", gate_sma=5, corr_penalty=False)
        kw.update(over)
        return LiveConfig(**kw)

    def test_or_opens_on_breadth_when_btc_down(self):
        # BTC falling (master gate SHUT) but ETH trending -> breadth 0.5 >= 0.5 -> OR opens
        bars = {"BTCUSDT": _bars([10, 9, 8, 7, 6, 5]), "ETHUSDT": _bars([1, 2, 3, 4, 5, 6])}
        self.assertTrue(portfolio_gate_open(bars, self._cfg(breadth_gate=0.5, breadth_combine="or")))
        # ... and the trending coin actually gets held even though BTC's gate is shut
        tw = target_weights(bars, self._cfg(breadth_gate=0.5, breadth_combine="or"))
        self.assertEqual([t.symbol for t in tw], ["ETHUSDT"])

    def test_and_stays_shut_when_btc_down(self):
        bars = {"BTCUSDT": _bars([10, 9, 8, 7, 6, 5]), "ETHUSDT": _bars([1, 2, 3, 4, 5, 6])}
        self.assertFalse(portfolio_gate_open(bars, self._cfg(breadth_gate=0.5, breadth_combine="and")))

    def test_none_is_pure_btc_gate(self):
        bars = {"BTCUSDT": _bars([10, 9, 8, 7, 6, 5]), "ETHUSDT": _bars([1, 2, 3, 4, 5, 6])}
        self.assertFalse(portfolio_gate_open(bars, self._cfg(breadth_gate=None)))


class TestCorrPenalty(unittest.TestCase):
    """§21.4 D: inverse-vol ÷ max(avg pairwise corr, floor) -> diversifier gets more weight."""

    def _cfg(self, corr_penalty):
        return LiveConfig(universe=("AUSDT", "BUSDT", "CUSDT"), regime_sma=5, fast=2, slow=4,
                          vol_lookback=5, atr_lookback=5, gate_sym="AUSDT", gate_sma=5,
                          breadth_gate=None, corr_penalty=corr_penalty)

    def test_diversifier_gains_weight(self):
        a = _closes_from_rets(10.0, [0.06, -0.02, 0.06, -0.02, 0.08])   # A
        c = _closes_from_rets(10.0, [-0.02, 0.06, -0.02, 0.06, 0.08])   # C: offset wiggle (low corr)
        bars = {"AUSDT": _bars(a), "BUSDT": _bars(a), "CUSDT": _bars(c)}  # A,B identical (corr 1)
        w_off = {t.symbol: t.weight for t in target_weights(bars, self._cfg(False))}
        w_on = {t.symbol: t.weight for t in target_weights(bars, self._cfg(True))}
        self.assertEqual(set(w_on), {"AUSDT", "BUSDT", "CUSDT"})
        # the low-correlation coin C is up-weighted by the penalty vs plain inverse-vol
        self.assertGreater(w_on["CUSDT"], w_off["CUSDT"])
        # symmetric correlated pair stays equal-weighted
        self.assertAlmostEqual(w_on["AUSDT"], w_on["BUSDT"], places=9)


class TestVolParity(unittest.TestCase):
    """vol-parity sizing (mirror run_directional): per-coin scale = min(max_leverage,
    vol_target/atr_pct) -> low-vol coins get more exposure; scale caps at max_leverage."""

    def _cfg(self, **over):
        kw = dict(universe=("LOWUSDT", "HIGHUSDT"), regime_sma=5, fast=2, slow=4, vol_lookback=5,
                  atr_lookback=5, gate_sym="LOWUSDT", gate_sma=5, breadth_gate=None,
                  corr_penalty=False, vol_target=0.03, max_leverage=2.0)
        kw.update(over)
        return LiveConfig(**kw)

    def test_low_vol_coin_gets_more_exposure(self):
        low = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111]      # smooth -> small ATR
        high = [100, 112, 104, 120, 108, 128, 112, 136, 120, 144, 128, 152]     # choppy -> big ATR
        tw = {t.symbol: t.weight for t in target_weights(
            {"LOWUSDT": _bars(low), "HIGHUSDT": _bars(high)}, self._cfg())}
        self.assertIn("LOWUSDT", tw)
        self.assertIn("HIGHUSDT", tw)
        self.assertGreater(tw["LOWUSDT"], tw["HIGHUSDT"])   # lower vol -> larger vol-parity exposure

    def test_scale_capped_at_max_leverage(self):
        # one ultra-smooth coin -> scale saturates at the cap -> exposure == max_leverage (rel=1.0)
        low = list(range(100, 140))
        cfg = self._cfg(universe=("LOWUSDT",), max_leverage=1.5)
        tw = target_weights({"LOWUSDT": _bars(low)}, cfg)
        self.assertEqual(len(tw), 1)
        self.assertAlmostEqual(tw[0].weight, 1.5, places=6)

    def test_gross_below_one_in_normal_vol(self):
        # typical crypto vol -> gross exposure well under 1x (the validated ~0.5x), NOT a naive full book
        high = [100, 112, 104, 120, 108, 128, 112, 136, 120, 144, 128, 152]
        tw = target_weights({"LOWUSDT": _bars(high), "HIGHUSDT": _bars(high)}, self._cfg())
        self.assertLess(sum(t.weight for t in tw), 1.0)


class TestSwapExecution(unittest.TestCase):
    def test_to_ccxt_swap_suffix(self):
        self.assertEqual(to_ccxt_symbol("BTCUSDT", market_type="swap"), "BTC/USDT:USDT")
        self.assertEqual(to_ccxt_symbol("BTCUSDT", market_type="spot"), "BTC/USDT")

    def test_fetch_filters_swap_market(self):
        f = fetch_filters(_MockExchange(), ["BTCUSDT"], "USDT", "swap")
        self.assertAlmostEqual(f["BTCUSDT"].amount_step, 1e-3, places=12)

    def _swap_cfg(self):
        return LiveConfig(universe=("BTCUSDT",), market_type="swap", max_leverage=2.0,
                          margin_mode="isolated")

    def test_prepare_swap_confirms_leverage(self):
        # set_leverage echoes 2x + read-back shows 2x -> sets called, returns NO unsafe symbols
        ex = _MockExchange(positions=[{"symbol": "BTC/USDT:USDT", "leverage": 2}])
        unsafe = prepare_swap(ex, ["BTCUSDT"], self._swap_cfg())
        self.assertEqual(ex.leverage_set, [(2, "BTC/USDT:USDT")])
        self.assertEqual(ex.margin_set, [("isolated", "BTC/USDT:USDT")])
        self.assertEqual(unsafe, set())

    def test_prepare_swap_confirmed_by_echo_when_flat(self):
        # the real VPS case: FLAT account -> fetch_positions returns [] -> only the set_leverage echo
        # can confirm. With the echo it is SAFE (regression guard against the never-trades deadlock).
        ex = _MockExchange(positions=[])   # flat, no rows
        self.assertEqual(prepare_swap(ex, ["BTCUSDT"], self._swap_cfg()), set())

    def test_prepare_swap_flags_wrong_leverage(self):
        # silent mis-set: echo + read-back both show 20x (the dangerous default) -> flagged unsafe
        ex = _MockExchange(positions=[{"symbol": "BTC/USDT:USDT", "leverage": 20}], lev_echo=20)
        self.assertEqual(prepare_swap(ex, ["BTCUSDT"], self._swap_cfg()), {"BTCUSDT"})

    def test_prepare_swap_flags_missing_position_data(self):
        # no echo AND no position row -> cannot confirm -> unsafe
        ex = _MockExchange(positions=[], lev_echo=None)
        self.assertEqual(prepare_swap(ex, ["BTCUSDT"], self._swap_cfg()), {"BTCUSDT"})

    def test_prepare_swap_unsafe_when_set_raises_and_fetch_fails(self):
        # set_leverage throws AND fetch_positions raises -> no confirmation source -> unsafe
        ex = _MockExchange(positions=None, lev_echo="RAISE")
        self.assertEqual(prepare_swap(ex, ["BTCUSDT"], self._swap_cfg()), {"BTCUSDT"})

    def test_prepare_swap_noop_for_spot(self):
        ex = _MockExchange()
        self.assertEqual(prepare_swap(ex, ["BTCUSDT"], LiveConfig(market_type="spot")), set())
        self.assertEqual(ex.leverage_set, [])

    def test_swap_orders_use_base_and_reduce_only(self):
        import os
        os.environ["QOUNT_X4_LIVE_ENABLE"] = "1"
        try:
            ex = _MockExchange()
            cfg = LiveConfig(market_type="swap")
            orders = [Order("BTC/USDT:USDT", "buy", 0.005, 0.0, 300.0),
                      Order("BTC/USDT:USDT", "sell", 0.002, 0.0, 120.0)]
            place_orders(ex, orders, mode="live", cfg=cfg)
            buy, sell = ex.sent
            self.assertEqual(buy[3], 0.005)        # BUY by base amount (not quoteOrderQty)
            self.assertEqual(buy[4], {})
            self.assertEqual(sell[4], {"reduceOnly": True})   # SELL only closes the long
        finally:
            os.environ.pop("QOUNT_X4_LIVE_ENABLE", None)


class TestChandelierStops(unittest.TestCase):
    """盘中硬止损: intraday trailing-Chandelier overlay (cuts crash + top-giveback)."""

    def _cfg(self, **over):
        kw = dict(chandelier_mult=3.0, chandelier_lookback=3)
        kw.update(over)
        return LiveConfig(**kw)

    def _bars(self):
        return {"ETHUSDT": _bars([100, 101, 102, 103, 104])}   # ATR(3) = 1.0

    def test_disabled_when_mult_zero(self):
        tw = [TargetWeight("ETHUSDT", 0.5)]
        out, st, trig = apply_chandelier_stops(tw, {"ETHUSDT": 50.0}, self._bars(), {},
                                               self._cfg(chandelier_mult=0.0))
        self.assertEqual(out, tw)
        self.assertEqual(trig, [])

    def test_triggers_on_breach(self):
        # trail_high 104, ATR 1, stop = 104 − 3×1 = 101; live 100 <= 101 -> forced flat + latched
        out, st, trig = apply_chandelier_stops([TargetWeight("ETHUSDT", 0.5)], {"ETHUSDT": 100.0},
                                               self._bars(), {"ETHUSDT": {"trail_high": 104.0}}, self._cfg())
        self.assertEqual(trig, ["ETHUSDT"])
        self.assertEqual(out[0].weight, 0.0)
        self.assertTrue(st["ETHUSDT"]["latched"])

    def test_no_trigger_above_stop(self):
        out, st, trig = apply_chandelier_stops([TargetWeight("ETHUSDT", 0.5)], {"ETHUSDT": 103.0},
                                               self._bars(), {"ETHUSDT": {"trail_high": 104.0}}, self._cfg())
        self.assertEqual(trig, [])
        self.assertEqual(out[0].weight, 0.5)
        self.assertEqual(st["ETHUSDT"]["trail_high"], 104.0)   # max(104, 103)

    def test_trail_high_ratchets_up(self):
        out, st, _ = apply_chandelier_stops([TargetWeight("ETHUSDT", 0.5)], {"ETHUSDT": 110.0},
                                            self._bars(), {"ETHUSDT": {"trail_high": 104.0}}, self._cfg())
        self.assertEqual(st["ETHUSDT"]["trail_high"], 110.0)

    def test_latch_blocks_reentry(self):
        # already latched + still in targets -> stays flat even at a high price (no churn re-entry)
        out, st, trig = apply_chandelier_stops([TargetWeight("ETHUSDT", 0.5)], {"ETHUSDT": 200.0},
                                               self._bars(), {"ETHUSDT": {"latched": True}}, self._cfg())
        self.assertEqual(out[0].weight, 0.0)
        self.assertEqual(trig, [])
        self.assertTrue(st["ETHUSDT"]["latched"])

    def test_latch_clears_when_signal_drops(self):
        # coin dropped by the daily signal (not in targets) -> latch not carried -> can re-arm
        out, st, trig = apply_chandelier_stops([], {"ETHUSDT": 200.0}, self._bars(),
                                               {"ETHUSDT": {"latched": True}}, self._cfg())
        self.assertNotIn("ETHUSDT", st)


class TestUnreachableCoins(unittest.TestCase):
    # 3 coins, equal vol so inverse-vol weights ≈ 1/3 each; high price (BTC) -> large min order.
    def _bars(self):
        rets = [0.01, -0.01] * 120   # steady low vol, 240 bars (> regime_sma 200)
        return {s: _bars(_closes_from_rets(start, rets))
                for s, start in (("BTCUSDT", 64_000.0), ("ETHUSDT", 1_800.0), ("SOLUSDT", 70.0))}

    def _filt(self):
        return {
            "BTCUSDT": SymbolFilter(amount_step=1e-3, min_amount=1e-3, min_notional=50.0),  # min 0.001
            "ETHUSDT": SymbolFilter(amount_step=1e-3, min_amount=1e-3, min_notional=20.0),
            "SOLUSDT": SymbolFilter(amount_step=1e-2, min_amount=1e-2, min_notional=5.0),
        }
    _prices = {"BTCUSDT": 64_000.0, "ETHUSDT": 1_800.0, "SOLUSDT": 70.0}

    def _cfg(self, cap):
        return LiveConfig(universe=("BTCUSDT", "ETHUSDT", "SOLUSDT"), capital_usdt=cap,
                          max_leverage=2.0, min_order_usdt=6.0, corr_penalty=False)

    def test_uses_real_weights_not_equal(self):
        # at tiny capital the BTC inverse-vol target (~1/3 × scale × $70) is far below its ~$64 min
        out = unreachable_coins(self._bars(), self._prices, self._filt(), self._cfg(70.0))
        syms = [b["symbol"] for b in out]
        self.assertIn("BTCUSDT", syms)
        self.assertNotIn("SOLUSDT", syms)              # $5 floor cleared by its target
        self.assertIn("target_usdt", out[0])           # reports real target, not just the floor
        self.assertLess(out[0]["target_usdt"], out[0]["min_usdt"])   # shortfall is real

    def test_all_reachable_at_large_capital(self):
        self.assertEqual(unreachable_coins(self._bars(), self._prices, self._filt(), self._cfg(50_000.0)), [])


class TestChandelierStopPrices(unittest.TestCase):
    """T2-2: derive the resting-stop trigger price from the persisted trail_high."""

    def _cfg(self, **over):
        kw = dict(market_type="swap", chandelier_mult=3.0, chandelier_lookback=3)
        kw.update(over)
        return LiveConfig(**kw)

    def _bars(self):
        return {"ETHUSDT": _bars([100, 101, 102, 103, 104])}   # ATR(3) = 1.0

    def test_trail_high_minus_mult_atr(self):
        px = chandelier_stop_prices([TargetWeight("ETHUSDT", 0.5)], self._bars(),
                                    {"ETHUSDT": {"trail_high": 104.0}}, self._cfg())
        self.assertAlmostEqual(px["ETHUSDT"], 101.0)   # 104 − 3×1

    def test_skips_flat_and_latched(self):
        # weight 0 (latched/exited) -> no protective stop needed
        px = chandelier_stop_prices([TargetWeight("ETHUSDT", 0.0)], self._bars(),
                                    {"ETHUSDT": {"latched": True}}, self._cfg())
        self.assertEqual(px, {})

    def test_skips_without_trail_high(self):
        px = chandelier_stop_prices([TargetWeight("ETHUSDT", 0.5)], self._bars(), {}, self._cfg())
        self.assertEqual(px, {})

    def test_disabled_when_mult_zero(self):
        px = chandelier_stop_prices([TargetWeight("ETHUSDT", 0.5)], self._bars(),
                                    {"ETHUSDT": {"trail_high": 104.0}}, self._cfg(chandelier_mult=0.0))
        self.assertEqual(px, {})


class TestPlanStopOrders(unittest.TestCase):
    """T2-2: idempotent diff of desired resting stops vs what's already on the exchange."""

    SYM = "ETH/USDT:USDT"

    def _cfg(self, **over):
        kw = dict(market_type="swap", stop_amend_band=0.01)
        kw.update(over)
        return LiveConfig(**kw)

    def test_place_when_none_existing(self):
        plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 1.0}, {}, self._cfg())
        self.assertEqual(len(plan.to_place), 1)
        self.assertEqual(plan.to_place[0].symbol, self.SYM)
        self.assertAlmostEqual(plan.to_place[0].stop_price, 101.0)
        self.assertEqual(plan.to_cancel, [])

    def test_within_band_is_noop(self):
        existing = {"ETHUSDT": {"id": "1", "symbol": self.SYM, "stopPrice": 101.2}}
        plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 1.0}, existing, self._cfg())
        self.assertEqual(plan.to_place, [])   # |101-101.2| < 1% of 101.2 -> leave it (no churn)
        self.assertEqual(plan.to_cancel, [])

    def test_amends_when_trail_ratchets_beyond_band(self):
        existing = {"ETHUSDT": {"id": "1", "symbol": self.SYM, "stopPrice": 95.0}}
        plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 1.0}, existing, self._cfg())
        self.assertEqual(len(plan.to_cancel), 1)            # cancel old first
        self.assertEqual(plan.to_cancel[0].order_id, "1")
        self.assertEqual(len(plan.to_place), 1)             # then replace higher
        self.assertAlmostEqual(plan.to_place[0].stop_price, 101.0)

    def test_cancels_when_no_longer_held(self):
        # daily signal dropped / latched -> not in stop_prices -> cancel the stale resting stop
        existing = {"ETHUSDT": {"id": "9", "symbol": self.SYM, "stopPrice": 101.0}}
        plan = plan_stop_orders({}, {"ETHUSDT": 1.0}, existing, self._cfg())
        self.assertEqual(len(plan.to_cancel), 1)
        self.assertEqual(plan.to_cancel[0].order_id, "9")
        self.assertEqual(plan.to_place, [])

    def test_no_place_without_position(self):
        plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 0.0}, {}, self._cfg())
        self.assertEqual(plan.to_place, [])

    def test_exchange_stops_off_tears_down(self):
        existing = {"ETHUSDT": {"id": "1", "symbol": self.SYM, "stopPrice": 101.0}}
        plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 1.0}, existing,
                                self._cfg(exchange_stops=False))
        self.assertEqual(len(plan.to_cancel), 1)
        self.assertEqual(plan.to_place, [])

    def test_spot_is_empty(self):
        plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 1.0}, {}, self._cfg(market_type="spot"))
        self.assertEqual(plan.to_place, [])
        self.assertEqual(plan.to_cancel, [])


class _StopMockExchange:
    def __init__(self, open_orders=None):
        self._open = open_orders or {}      # ccxt_sym -> list[order dict]
        self.created = []
        self.cancelled = []

    def fetch_open_orders(self, symbol):
        return self._open.get(symbol, [])

    def cancel_order(self, order_id, symbol):
        self.cancelled.append((order_id, symbol))
        return {"id": order_id}

    def create_order(self, symbol, type_, side, amount, price, params):
        self.created.append((symbol, type_, side, amount, params))
        return {"id": "stop1", "symbol": symbol}


class TestStopExchangeLayer(unittest.TestCase):
    SYM = "ETH/USDT:USDT"

    def _cfg(self, **over):
        kw = dict(market_type="swap")
        kw.update(over)
        return LiveConfig(**kw)

    def test_fetch_open_stops_parses_stop(self):
        ex = _StopMockExchange({self.SYM: [
            {"id": "7", "type": "limit", "stopPrice": None, "reduceOnly": False},
            {"id": "8", "type": "STOP_MARKET", "stopPrice": "99.5", "info": {"closePosition": "true"}},
        ]})
        out = fetch_open_stops(ex, ["ETHUSDT"], self._cfg())
        self.assertIn("ETHUSDT", out)
        self.assertEqual(out["ETHUSDT"]["id"], "8")
        self.assertAlmostEqual(out["ETHUSDT"]["stopPrice"], 99.5)

    def test_fetch_open_stops_spot_empty(self):
        ex = _StopMockExchange()
        self.assertEqual(fetch_open_stops(ex, ["ETHUSDT"], self._cfg(market_type="spot")), {})

    def test_sync_dry_sends_nothing(self):
        ex = _StopMockExchange()
        plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 1.0}, {}, self._cfg())
        sync_stop_orders(ex, plan, mode="dry", cfg=self._cfg())
        self.assertEqual(ex.created, [])
        self.assertEqual(ex.cancelled, [])

    def test_sync_blocked_without_env(self):
        import os
        os.environ.pop("QOUNT_X4_LIVE_ENABLE", None)
        ex = _StopMockExchange()
        plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 1.0}, {}, self._cfg())
        sync_stop_orders(ex, plan, mode="live", cfg=self._cfg())
        self.assertEqual(ex.created, [])

    def test_sync_live_cancels_then_places_closeposition(self):
        import os
        os.environ["QOUNT_X4_LIVE_ENABLE"] = "1"
        try:
            ex = _StopMockExchange()
            existing = {"ETHUSDT": {"id": "1", "symbol": self.SYM, "stopPrice": 95.0}}
            plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 1.0}, existing, self._cfg())
            sync_stop_orders(ex, plan, mode="live", cfg=self._cfg())
            self.assertEqual(ex.cancelled, [("1", self.SYM)])        # old stop cancelled first
            self.assertEqual(len(ex.created), 1)
            sym, type_, side, amount, params = ex.created[0]
            self.assertEqual((sym, type_, side), (self.SYM, "STOP_MARKET", "sell"))
            self.assertIsNone(amount)                                # closePosition -> no amount
            self.assertTrue(params["closePosition"])
            self.assertAlmostEqual(params["stopPrice"], 101.0)
        finally:
            os.environ.pop("QOUNT_X4_LIVE_ENABLE", None)


if __name__ == "__main__":
    unittest.main()
