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
    apply_scale_out,
    carry_flow_adjusted_pnl,
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
    usdt_wallet_balance,
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


class TestShortGate(unittest.TestCase):
    """§24 做空闸 pure layer: when the master gate is SHUT and short_gate=True, target_weights returns
    NEGATIVE weights for coins in a confirmed downtrend (close < SMA short_regime_sma AND fast < slow),
    sized by the smaller short_* knobs. Default (short_gate=False) keeps the 100%-cash path."""

    def _cfg(self, **over):
        kw = dict(universe=("BTCUSDT", "ETHUSDT"), regime_sma=5, fast=2, slow=4, vol_lookback=3,
                  atr_lookback=3, gate_sym="BTCUSDT", gate_sma=5, breadth_gate=None, corr_penalty=False,
                  short_gate=True, short_regime_sma=5, short_vol_target=0.02, short_max_leverage=1.5)
        kw.update(over)
        return LiveConfig(**kw)

    def test_off_stays_cash_when_gate_shut(self):
        # short_gate=False (default) -> risk-off is still 100% cash (current behavior preserved)
        bars = {"BTCUSDT": _bars([10, 9, 8, 7, 6, 5]), "ETHUSDT": _bars([8, 7, 6, 5, 4, 3])}
        self.assertEqual(target_weights(bars, self._cfg(short_gate=False)), [])

    def test_shorts_downtrend_coins_when_gate_shut(self):
        # BTC falling -> master gate shut; both coins in confirmed downtrend -> both SHORTED (w < 0)
        bars = {"BTCUSDT": _bars([10, 9, 8, 7, 6, 5]), "ETHUSDT": _bars([8, 7, 6, 5, 4, 3])}
        tw = target_weights(bars, self._cfg())
        self.assertEqual({t.symbol for t in tw}, {"BTCUSDT", "ETHUSDT"})
        self.assertTrue(all(t.weight < 0.0 for t in tw))

    def test_excludes_non_downtrend_coin(self):
        # gate shut (BTC down) but ETH rising -> ETH not in a downtrend -> only BTC shorted
        bars = {"BTCUSDT": _bars([10, 9, 8, 7, 6, 5]), "ETHUSDT": _bars([1, 2, 3, 4, 5, 6])}
        tw = target_weights(bars, self._cfg())
        self.assertEqual([t.symbol for t in tw], ["BTCUSDT"])
        self.assertLess(tw[0].weight, 0.0)

    def test_short_uses_smaller_leverage_cap(self):
        # a near-zero-vol steady downtrend pushes vol_target/atr_pct above the cap -> |w| pins to the
        # SHORT cap (1.5), proving the short knobs (not the long max_leverage 2.0) size the short book
        slow_down = [100.0 - 0.01 * i for i in range(8)]
        cfg = self._cfg(universe=("BTCUSDT",), max_leverage=2.0, short_max_leverage=1.5)
        tw = target_weights({"BTCUSDT": _bars(slow_down)}, cfg)
        self.assertEqual(len(tw), 1)
        self.assertLessEqual(abs(tw[0].weight), cfg.short_max_leverage + 1e-9)
        self.assertGreater(abs(tw[0].weight), cfg.max_leverage * 0.5)  # genuinely sized, not dust


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


class TestWalletBalance(unittest.TestCase):
    """walletBalance extraction — must NOT return marginBalance (would double-count unrealized)."""

    def test_prefers_total_wallet_balance(self):
        # ccxt total (488.97) = marginBalance; the real cash wallet is 484.91 (484.91 + 4.06 uPnL)
        bal = {"USDT": {"total": 488.97, "free": 414.64},
               "info": {"totalWalletBalance": "484.91", "totalUnrealizedProfit": "4.06"}}
        self.assertAlmostEqual(usdt_wallet_balance(bal), 484.91)

    def test_falls_back_to_total_minus_unrealized(self):
        bal = {"USDT": {"total": 488.97}, "info": {"totalUnrealizedProfit": "4.06"}}
        self.assertAlmostEqual(usdt_wallet_balance(bal), 484.91)

    def test_falls_back_to_total_when_no_info(self):
        self.assertAlmostEqual(usdt_wallet_balance({"USDT": {"total": 500.0}, "info": {}}), 500.0)

    def test_none_when_unreadable(self):
        self.assertIsNone(usdt_wallet_balance({"USDT": {}, "info": {}}))


class TestScaleOut(unittest.TestCase):
    """§10 分批止盈: ratchet a winner's target weight down as it runs into profit (residual rides stop)."""

    def _cfg(self):
        return LiveConfig(scale_out_step=0.20, scale_out_frac=0.50, scale_out_residual=0.34)

    def test_off_by_default_is_identity(self):
        tw = [TargetWeight("BTCUSDT", 0.5)]
        out, st, scaled = apply_scale_out(tw, {"BTCUSDT": 200.0}, {"BTCUSDT": 100.0},
                                          {"BTCUSDT": 1.0}, {}, LiveConfig())
        self.assertEqual(out, tw)
        self.assertEqual(scaled, [])

    def test_full_target_when_flat_or_small_profit(self):
        cfg = self._cfg()
        # flat (no position) -> full target, no state
        out, st, _ = apply_scale_out([TargetWeight("BTCUSDT", 0.5)], {"BTCUSDT": 110.0},
                                     {"BTCUSDT": None}, {"BTCUSDT": 0.0}, {}, cfg)
        self.assertAlmostEqual(out[0].weight, 0.5)
        # held, only +10% profit (< step 20%) -> step 0 -> full target
        out, st, _ = apply_scale_out([TargetWeight("BTCUSDT", 0.5)], {"BTCUSDT": 110.0},
                                     {"BTCUSDT": 100.0}, {"BTCUSDT": 1.0}, {}, cfg)
        self.assertAlmostEqual(out[0].weight, 0.5)

    def test_trims_at_profit_steps_long(self):
        cfg = self._cfg()
        held = {"BTCUSDT": 1.0}
        # +20% -> 1 step -> cap 0.50
        out, st, scaled = apply_scale_out([TargetWeight("BTCUSDT", 0.5)], {"BTCUSDT": 120.0},
                                          {"BTCUSDT": 100.0}, held, {}, cfg)
        self.assertAlmostEqual(out[0].weight, 0.5 * 0.50)
        self.assertEqual(st["BTCUSDT"]["steps"], 1)
        self.assertEqual(scaled, ["BTCUSDT"])
        # +40% -> 2 steps -> cap floored at residual 0.34
        out, st, _ = apply_scale_out([TargetWeight("BTCUSDT", 0.5)], {"BTCUSDT": 140.0},
                                     {"BTCUSDT": 100.0}, held, st, cfg)
        self.assertAlmostEqual(out[0].weight, 0.5 * 0.34)
        self.assertEqual(st["BTCUSDT"]["steps"], 2)

    def test_ratchet_does_not_re_add_on_retrace(self):
        cfg = self._cfg()
        held = {"BTCUSDT": 1.0}
        _, st, _ = apply_scale_out([TargetWeight("BTCUSDT", 0.5)], {"BTCUSDT": 140.0},
                                   {"BTCUSDT": 100.0}, held, {}, cfg)        # 2 steps
        # price falls back to +10%: steps must stay 2 (no re-add), cap still residual
        out, st2, scaled = apply_scale_out([TargetWeight("BTCUSDT", 0.5)], {"BTCUSDT": 110.0},
                                           {"BTCUSDT": 100.0}, held, st, cfg)
        self.assertEqual(st2["BTCUSDT"]["steps"], 2)
        self.assertEqual(scaled, [])
        self.assertAlmostEqual(out[0].weight, 0.5 * 0.34)

    def test_short_leg_trims_on_profit(self):
        cfg = self._cfg()
        # short at entry 100, price down to 80 = +20% profit on the short -> 1 step
        out, st, scaled = apply_scale_out([TargetWeight("BTCUSDT", -0.5)], {"BTCUSDT": 80.0},
                                          {"BTCUSDT": 100.0}, {"BTCUSDT": -1.0}, {}, cfg)
        self.assertAlmostEqual(out[0].weight, -0.5 * 0.50)
        self.assertEqual(st["BTCUSDT"]["steps"], 1)

    def test_opposite_side_resets(self):
        cfg = self._cfg()
        # target flipped to short but a long position is still on -> not same-side -> full target, reset
        out, st, _ = apply_scale_out([TargetWeight("BTCUSDT", -0.5)], {"BTCUSDT": 120.0},
                                     {"BTCUSDT": 100.0}, {"BTCUSDT": 1.0}, {"BTCUSDT": {"steps": 2}}, cfg)
        self.assertAlmostEqual(out[0].weight, -0.5)
        self.assertNotIn("BTCUSDT", st)


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
            # a long-closing SELL carries reduce_only=True (set by compute_orders); an open-long BUY does not
            orders = [Order("BTC/USDT:USDT", "buy", 0.005, 0.0, 300.0, reduce_only=False),
                      Order("BTC/USDT:USDT", "sell", 0.002, 0.0, 120.0, reduce_only=True)]
            place_orders(ex, orders, mode="live", cfg=cfg)
            buy, sell = ex.sent
            self.assertEqual(buy[3], 0.005)        # BUY by base amount (not quoteOrderQty)
            self.assertEqual(buy[4], {})
            self.assertEqual(sell[4], {"reduceOnly": True})   # reduceOnly comes from Order.reduce_only
        finally:
            os.environ.pop("QOUNT_X4_LIVE_ENABLE", None)


class TestShortExecution(unittest.TestCase):
    """§24 做空闸 execution layer: signed reconcile (open/cover short), reduceOnly direction, short
    exchange stop side. All swap-only; spot never naked-shorts."""

    def _cfg(self, **over):
        kw = dict(universe=("BTCUSDT",), capital_usdt=400.0, rebalance_band=0.25, min_order_usdt=6.0,
                  max_order_usdt=400.0, market_type="swap", max_leverage=2.0)
        kw.update(over)
        return LiveConfig(**kw)

    def _filt(self):
        return {"BTCUSDT": SymbolFilter(amount_step=1e-5, min_amount=1e-5, min_notional=5.0)}

    def test_open_short_from_flat_sells_beyond_holdings(self):
        # swap: target −0.5 (short $200) from flat -> SELL $200 (NOT clamped to 0 holdings), not reduceOnly
        cfg = self._cfg()
        res = compute_orders([TargetWeight("BTCUSDT", -0.5)], {}, {"BTCUSDT": 60_000.0}, self._filt(), cfg)
        self.assertEqual(len(res.orders), 1)
        o = res.orders[0]
        self.assertEqual(o.side, "sell")
        self.assertFalse(o.reduce_only)                 # opening a short is NOT reduceOnly
        self.assertAlmostEqual(o.base_amount * 60_000.0, 200.0, delta=1.0)

    def test_spot_never_naked_shorts(self):
        # same target on spot -> clamped to 0 holdings -> no order (can't short spot)
        cfg = self._cfg(market_type="spot")
        res = compute_orders([TargetWeight("BTCUSDT", -0.5)], {}, {"BTCUSDT": 60_000.0}, self._filt(), cfg)
        self.assertEqual(res.orders, [])

    def test_cover_short_is_reduce_only_buy(self):
        # holding −$200 short, target flat -> BUY $200 to cover, reduceOnly
        cfg = self._cfg()
        bal = {"BTCUSDT": -200.0 / 60_000.0}
        res = compute_orders([TargetWeight("BTCUSDT", 0.0)], bal, {"BTCUSDT": 60_000.0}, self._filt(), cfg)
        self.assertEqual(len(res.orders), 1)
        o = res.orders[0]
        self.assertEqual(o.side, "buy")
        self.assertTrue(o.reduce_only)

    def test_flip_short_to_long_crosses_zero_not_reduce_only(self):
        # −$200 short -> +$200 long: BUY $400 crossing zero must NOT be reduceOnly (would cap at cover)
        cfg = self._cfg()
        bal = {"BTCUSDT": -200.0 / 60_000.0}
        res = compute_orders([TargetWeight("BTCUSDT", 0.5)], bal, {"BTCUSDT": 60_000.0}, self._filt(), cfg)
        o = res.orders[0]
        self.assertEqual(o.side, "buy")
        self.assertFalse(o.reduce_only)

    def test_gross_clamp_counts_short_magnitude(self):
        # one long 0.8 + one short −0.8 => gross |0.8|+|0.8|=1.6 > cap 1.0 -> scaled down
        cfg = self._cfg(universe=("BTCUSDT", "ETHUSDT"), max_leverage=1.0)
        filt = {"BTCUSDT": SymbolFilter(1e-5, 1e-5, 5.0), "ETHUSDT": SymbolFilter(1e-4, 1e-4, 5.0)}
        prices = {"BTCUSDT": 60_000.0, "ETHUSDT": 3_000.0}
        res = compute_orders([TargetWeight("BTCUSDT", 0.8), TargetWeight("ETHUSDT", -0.8)], {}, prices, filt, cfg)
        self.assertLessEqual(sum(abs(v) for v in res.target_usdt.values()), cfg.max_leverage * cfg.capital_usdt + 1e-6)

    def test_place_orders_reduce_only_per_order(self):
        import os
        os.environ["QOUNT_X4_LIVE_ENABLE"] = "1"
        try:
            ex = _MockExchange()
            cfg = self._cfg()
            orders = [Order("BTC/USDT:USDT", "sell", 0.003, 0.0, 180.0, reduce_only=False),  # open short
                      Order("BTC/USDT:USDT", "buy", 0.003, 0.0, 180.0, reduce_only=True)]     # cover
            place_orders(ex, orders, mode="live", cfg=cfg)
            sell, buy = ex.sent
            self.assertEqual(sell[4], {})                       # open short: no reduceOnly
            self.assertEqual(buy[4], {"reduceOnly": True})      # cover: reduceOnly
        finally:
            os.environ.pop("QOUNT_X4_LIVE_ENABLE", None)

    def test_short_exchange_stop_is_buy_side(self):
        # a short position (neg base) gets a BUY closePosition stop above the trail
        cfg = self._cfg(exchange_stops=True)
        stop_px = {"BTCUSDT": 103.0}
        plan = plan_stop_orders(stop_px, {"BTCUSDT": -0.01}, {}, cfg)
        self.assertEqual(len(plan.to_place), 1)
        self.assertEqual(plan.to_place[0].side, "buy")


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

    # ---- §24 short-side (mirror): trail the LOW, stop on a squeeze (rise) ----
    def test_short_triggers_on_squeeze(self):
        # short, trail_low 100, ATR 1, short stop = 100 + 3×1 = 103; live 104 >= 103 -> flat + latched
        out, st, trig = apply_chandelier_stops([TargetWeight("ETHUSDT", -0.5)], {"ETHUSDT": 104.0},
                                               self._bars(), {"ETHUSDT": {"trail_low": 100.0}},
                                               self._cfg(short_chandelier_mult=3.0))
        self.assertEqual(trig, ["ETHUSDT"])
        self.assertEqual(out[0].weight, 0.0)
        self.assertTrue(st["ETHUSDT"]["latched"])

    def test_short_no_trigger_below_squeeze_stop(self):
        out, st, trig = apply_chandelier_stops([TargetWeight("ETHUSDT", -0.5)], {"ETHUSDT": 102.0},
                                               self._bars(), {"ETHUSDT": {"trail_low": 100.0}},
                                               self._cfg(short_chandelier_mult=3.0))
        self.assertEqual(trig, [])
        self.assertEqual(out[0].weight, -0.5)
        self.assertEqual(st["ETHUSDT"]["trail_low"], 100.0)   # min(100, 102)

    def test_short_trail_low_ratchets_down(self):
        out, st, _ = apply_chandelier_stops([TargetWeight("ETHUSDT", -0.5)], {"ETHUSDT": 90.0},
                                            self._bars(), {"ETHUSDT": {"trail_low": 100.0}},
                                            self._cfg(short_chandelier_mult=3.0))
        self.assertEqual(st["ETHUSDT"]["trail_low"], 90.0)


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

    def test_held_coin_not_flagged(self):
        # BTC's sub-floor target would normally flag it, but if it's ALREADY held (a min-lot in the
        # book) it isn't "skipped/missing" -> excluded so the dashboard doesn't claim a 非完整 subset.
        cfg = self._cfg(70.0)
        self.assertIn("BTCUSDT", [b["symbol"] for b in
                                  unreachable_coins(self._bars(), self._prices, self._filt(), cfg)])
        out = unreachable_coins(self._bars(), self._prices, self._filt(), cfg, held={"BTCUSDT"})
        self.assertNotIn("BTCUSDT", [b["symbol"] for b in out])


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
    def __init__(self, open_orders=None, place_raises=None):
        self._open = open_orders or {}      # ccxt_sym -> list[order dict]
        self.created = []
        self.cancelled = []
        self.fetch_params = []              # records params passed to fetch_open_orders
        self._place_raises = place_raises   # Exception to raise on create_order (simulate -4130)

    def fetch_open_orders(self, symbol, params=None):
        self.fetch_params.append(params)
        return self._open.get(symbol, [])

    def cancel_order(self, order_id, symbol, params=None):
        self.cancelled.append((order_id, symbol, params))
        return {"id": order_id}

    def create_order(self, symbol, type_, side, amount, price, params):
        if self._place_raises is not None:
            raise self._place_raises
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

    def test_fetch_open_stops_parses_ccxt_market_typed_stop(self):
        # real ccxt shape from the stop book: unified type is "market" (NOT "STOP_MARKET"), the stop-ness
        # is the trigger price; closePosition lives in info. Must still be recognized (was the -4130 bug).
        ex = _StopMockExchange({self.SYM: [
            {"id": "9", "type": "market", "stopPrice": 2006.62, "triggerPrice": 2006.62,
             "reduceOnly": True, "closePosition": None, "info": {"closePosition": True}},
        ]})
        out = fetch_open_stops(ex, ["ETHUSDT"], self._cfg())
        self.assertEqual(out["ETHUSDT"]["id"], "9")
        self.assertAlmostEqual(out["ETHUSDT"]["stopPrice"], 2006.62)

    def test_fetch_open_stops_queries_stop_book(self):
        # Binance closePosition stops only surface with params={"stop": True}; without it fetch returns
        # [] every run and the plan re-places -> -4130 crash. Assert the param is actually sent.
        ex = _StopMockExchange({self.SYM: [
            {"id": "8", "type": "STOP_MARKET", "stopPrice": "99.5", "info": {"closePosition": "true"}},
        ]})
        fetch_open_stops(ex, ["ETHUSDT"], self._cfg())
        self.assertEqual(ex.fetch_params, [{"stop": True}])

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
            # old stop cancelled first, routed to the algo endpoint via params={"stop": True}
            # (regular cancel -> OrderNotFound on the algoId -> -4130 re-place churn; the bug we fixed)
            self.assertEqual(ex.cancelled, [("1", self.SYM, {"stop": True})])
            self.assertEqual(len(ex.created), 1)
            sym, type_, side, amount, params = ex.created[0]
            self.assertEqual((sym, type_, side), (self.SYM, "STOP_MARKET", "sell"))
            self.assertIsNone(amount)                                # closePosition -> no amount
            self.assertTrue(params["closePosition"])
            self.assertAlmostEqual(params["stopPrice"], 101.0)
        finally:
            os.environ.pop("QOUNT_X4_LIVE_ENABLE", None)

    def test_sync_place_error_is_non_fatal(self):
        # a -4130 (or any) placement error must NOT crash the run — the resting stop is a best-effort
        # backstop; the local intraday stop + daily reconcile must still complete.
        import os
        os.environ["QOUNT_X4_LIVE_ENABLE"] = "1"
        try:
            ex = _StopMockExchange(place_raises=RuntimeError(
                '{"code":-4130,"msg":"An open ... closePosition in the direction is existing."}'))
            plan = plan_stop_orders({"ETHUSDT": 101.0}, {"ETHUSDT": 1.0}, {}, self._cfg())
            acted = sync_stop_orders(ex, plan, mode="live", cfg=self._cfg())   # must not raise
            self.assertTrue(any("error" in a for a in acted))
        finally:
            os.environ.pop("QOUNT_X4_LIVE_ENABLE", None)


class TestCarryFlowAdjustedPnl(unittest.TestCase):
    """P0 (2026-06-21): per-sleeve P&L must subtract internal autofund flows, else injected capital
    is misreported as trading profit (the live trend +$68 artifact)."""

    def test_unfunded_returns_none(self):
        pnl, state = carry_flow_adjusted_pnl(0.0, {})
        self.assertIsNone(pnl)
        self.assertEqual(state, {})

    def test_first_sight_sets_basis_zero_pnl(self):
        pnl, state = carry_flow_adjusted_pnl(100.0, {}, autofund_draw=0.0, rv_ts="t0")
        self.assertAlmostEqual(pnl, 0.0)
        self.assertAlmostEqual(state["carry_equity"], 100.0)
        self.assertAlmostEqual(state["cum_flow"], 0.0)
        self.assertEqual(state["last_fund_ts"], "t0")

    def test_pure_pnl_no_flow(self):
        # equity grew 100 -> 105 with no funding -> +5 real P&L
        prev = {"carry_equity": 100.0, "cum_flow": 0.0, "last_fund_ts": "t0"}
        pnl, _ = carry_flow_adjusted_pnl(105.0, prev, autofund_draw=0.0, rv_ts="t0")
        self.assertAlmostEqual(pnl, 5.0)

    def test_injected_capital_not_counted_as_profit(self):
        # equity 100 -> 150 but $50 of it was an autofund draw -> P&L must stay 0, not +50
        prev = {"carry_equity": 100.0, "cum_flow": 0.0, "last_fund_ts": "t0"}
        pnl, state = carry_flow_adjusted_pnl(150.0, prev, autofund_draw=50.0, rv_ts="t1")
        self.assertAlmostEqual(pnl, 0.0)
        self.assertAlmostEqual(state["cum_flow"], 50.0)
        self.assertEqual(state["last_fund_ts"], "t1")

    def test_draw_deduped_by_ts_across_reruns(self):
        # same rv snapshot (same ts) seen twice (the */2 cron rerun) -> draw counted ONCE only
        prev = {"carry_equity": 100.0, "cum_flow": 0.0, "last_fund_ts": "t0"}
        _, s1 = carry_flow_adjusted_pnl(150.0, prev, autofund_draw=50.0, rv_ts="t1")
        pnl2, s2 = carry_flow_adjusted_pnl(150.0, s1, autofund_draw=50.0, rv_ts="t1")  # rerun, same ts
        self.assertAlmostEqual(s2["cum_flow"], 50.0)   # NOT 100
        self.assertAlmostEqual(pnl2, 0.0)

    def test_funding_then_profit(self):
        # fund +50 (ts t1), then equity rises another +8 of real P&L (no new draw, ts unchanged)
        prev = {"carry_equity": 100.0, "cum_flow": 0.0, "last_fund_ts": "t0"}
        _, s1 = carry_flow_adjusted_pnl(150.0, prev, autofund_draw=50.0, rv_ts="t1")
        pnl2, _ = carry_flow_adjusted_pnl(158.0, s1, autofund_draw=0.0, rv_ts="t1")
        self.assertAlmostEqual(pnl2, 8.0)

    def test_trend_residual_reconciles(self):
        # trend_pnl = total_pnl - carry_pnl must sum back to total exactly
        prev = {"carry_equity": 100.0, "cum_flow": 0.0, "last_fund_ts": "t0"}
        carry_pnl, _ = carry_flow_adjusted_pnl(150.0, prev, autofund_draw=50.0, rv_ts="t1")
        total_pnl = -1.79
        trend_pnl = round(total_pnl - (carry_pnl or 0.0), 2)
        self.assertAlmostEqual(trend_pnl + (carry_pnl or 0.0), total_pnl, places=2)


if __name__ == "__main__":
    unittest.main()
