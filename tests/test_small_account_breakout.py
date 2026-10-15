from __future__ import annotations

import copy
import datetime as dt
import json
import unittest
from pathlib import Path

from qount.contracts import StrategyIntent
from qount.research.small_account_breakout import (
    Bar, MarketData, Signal, aggregate, atr, funding_estimate, generate_signals,
    session, simulate, size_contract,
)
from qount.research.small_account_breakout_data import selected_weeks, timestamp

ROOT = Path(__file__).resolve().parents[1]


def config() -> dict:
    return json.loads((ROOT / "config/small-account-breakout-v01.json").read_text())


def rule(symbol: str = "ETHUSDT", minimum: float = 5) -> dict:
    return {"symbol":symbol,"liquidationFee":"0.015",
            "filters":[{"filterType":"LOT_SIZE","stepSize":"0.001","minQty":"0.001","maxQty":"100000"},
                       {"filterType":"MIN_NOTIONAL","notional":str(minimum)},
                       {"filterType":"PRICE_FILTER","tickSize":"0.01"}]}


def fixture() -> tuple[dict,MarketData,int]:
    cfg = config()
    cfg["crypto_symbols"] = ["ETHUSDT"]
    cfg["stock_symbols"] = []
    start = timestamp("2026-06-01")
    bars = {t:Bar(t,100,100.1,99.9,100,10000,1000000)
            for t in range(start-60,start+7*86400,60)}
    funding = [{"fundingTime":t*1000+1,"fundingRate":"0","markPrice":"100"}
               for t in range(start-3*86400,start+7*86400,8*3600)]
    return cfg,MarketData({"ETHUSDT":bars},{"ETHUSDT":dict(bars)},{},
                          {"ETHUSDT":funding},{"ETHUSDT":rule()},{}),start


class BreakoutCorrectnessTests(unittest.TestCase):
    def test_sampling_preserves_first_draw_and_is_without_replacement(self):
        cfg = config()
        weeks = selected_weeks(cfg["as_of"],cfg["random_seed"],5)
        self.assertEqual(weeks,cfg["draw_order"])
        self.assertEqual(len(set(weeks)),5)
        self.assertEqual(weeks[0],"2026-10-05")
        for week in weeks:
            day = dt.date.fromisoformat(week)
            self.assertEqual(day.weekday(),0)
            self.assertLessEqual(day+dt.timedelta(days=7),dt.date(2026,10,13))

    def test_minimum_order_is_never_rounded_up(self):
        sig = Signal("BTCUSDT","crypto",1,timestamp("2026-10-05"),90000,900)
        result,reason = size_contract(sig,90000,10,0.1,0.002,rule("BTCUSDT",50),config())
        self.assertIsNone(result)
        self.assertEqual(reason,"minimum_order")

    def test_historical_btc_minimum_is_100_before_april_change(self):
        cfg = config()
        sig = Signal("BTCUSDT","crypto",1,timestamp("2026-03-30"),50000,500)
        result,reason = size_contract(sig,50000,10,0.1,0.002,rule("BTCUSDT",50),cfg)
        self.assertIsNone(result)
        self.assertEqual(reason,"minimum_order")

    def test_gross_margin_risk_and_liquidation_constraints(self):
        cfg = config()
        for side in (1,-1):
            for equity in (10,20,50):
                for volatility in (1,2,4):
                    sig = Signal("ETHUSDT","crypto",side,0,100,volatility)
                    c,reason = size_contract(sig,100,equity,0.1,0.002,rule(),cfg)
                    self.assertEqual(reason,"allowed")
                    self.assertLessEqual(c.notional_usdt,6*equity)
                    self.assertLessEqual(c.isolated_margin_usdt,0.6*equity+1e-8)
                    self.assertLessEqual(c.planned_stop_risk_usdt,0.1*equity+1e-8)
                    self.assertGreaterEqual(c.liquidation_distance_fraction,
                                            3*abs(c.initial_stop-100)/100)
                    self.assertGreater(c.actual_gross,1)
                    self.assertFalse(c.orders_authorized)

    def test_friction_gate_blocks_tight_stock_stop(self):
        sig = Signal("AMZNUSDT","stock",1,0,200,0.2)
        c,reason = size_contract(sig,200,10,0.1,0.003,rule("AMZNUSDT"),config())
        self.assertIsNone(c)
        self.assertEqual(reason,"friction_budget")

    def test_funding_forecast_cannot_read_future(self):
        now = timestamp("2026-06-01")
        prior = [{"fundingTime":(now-3600)*1000,"fundingRate":"0.0001"}]
        future = [{"fundingTime":(now+3600)*1000,"fundingRate":"0.5"}]
        self.assertAlmostEqual(funding_estimate(prior+future,now,72),0.0009)

    def test_calendar_good_friday_and_dst(self):
        self.assertIsNone(session(timestamp("2026-04-03T14:00:00")))
        self.assertEqual(session(timestamp("2026-03-30T13:30:00"))[1],570)
        self.assertEqual(session(timestamp("2026-02-02T14:30:00"))[1],570)
        self.assertEqual(session(timestamp("2026-11-27T17:00:00"))[2],780)

    def test_incomplete_bar_not_aggregated_and_atr_seed(self):
        bars = [Bar(i*60,100,102,99,101) for i in range(15)]
        self.assertEqual(len(aggregate(bars,900,60)),1)
        self.assertEqual(aggregate(bars[:-1],900,60),[])
        self.assertIsNone(atr(bars)[12])
        self.assertEqual(atr(bars)[13],3)

    def test_stop_in_entry_minute_is_not_missed_and_one_position(self):
        cfg,data,start = fixture()
        t = start+60
        data.minutes["ETHUSDT"][t] = Bar(t,100,100.1,97,98,10000,1000000)
        data.marks["ETHUSDT"][t] = data.minutes["ETHUSDT"][t]
        sig = Signal("ETHUSDT","crypto",1,start,100,1)
        result = simulate(data,cfg,"2026-06-01",[sig,sig],{"ETHUSDT":{}})
        self.assertEqual(result["summary"]["trade_count"],1)
        self.assertEqual(result["trades"][0]["exit_reason"],"initial_stop")
        self.assertEqual(result["trades"][0]["entry_time"],result["trades"][0]["exit_time"])
        self.assertEqual(result["summary"]["rejections"]["exit_same_minute"],1)

    def test_gap_stop_uses_adverse_open_and_ledger_fees(self):
        cfg,data,start = fixture()
        t = start+120
        data.minutes["ETHUSDT"][t] = Bar(t,95,96,94,95,10000,1000000)
        data.marks["ETHUSDT"][t] = data.minutes["ETHUSDT"][t]
        sig = Signal("ETHUSDT","crypto",1,start,100,1)
        result = simulate(data,cfg,"2026-06-01",[sig],{"ETHUSDT":{}})
        trade = result["trades"][0]
        self.assertAlmostEqual(trade["exit_price"],95*(1-cfg["crypto_slippage_per_side"]))
        self.assertGreater(-trade["net_pnl_usdt"],trade["risk_budget_usdt"])
        self.assertAlmostEqual(result["summary"]["final_equity_usdt"],10+trade["net_pnl_usdt"])
        expected = trade["quantity"]*(trade["exit_price"]-trade["entry_price"])-trade["fees_usdt"]
        self.assertAlmostEqual(trade["net_pnl_usdt"],expected)

    def test_two_initial_stops_start_24h_cooldown(self):
        cfg,data,start = fixture()
        sigs = [Signal("ETHUSDT","crypto",1,start+hour*3600,100,1) for hour in (0,1,2,26)]
        for hour in (0,1):
            t = start+hour*3600+60
            data.minutes["ETHUSDT"][t] = Bar(t,100,100.1,97,98,10000,1000000)
            data.marks["ETHUSDT"][t] = data.minutes["ETHUSDT"][t]
        result = simulate(data,cfg,"2026-06-01",sigs,{"ETHUSDT":{}})
        self.assertEqual(result["summary"]["trade_count"],3)
        self.assertEqual(result["summary"]["rejections"]["cooldown"],1)
        self.assertLess(result["trades"][1]["notional_usdt"],result["trades"][0]["notional_usdt"])

    def test_funding_is_charged_using_settlement_mark_and_side(self):
        cfg,data,start = fixture()
        settlement = start+8*3600
        for row in data.funding["ETHUSDT"]:
            if row["fundingTime"] == settlement*1000+1:
                row["fundingRate"] = "0.001"
                row["markPrice"] = "101"
        sig = Signal("ETHUSDT","crypto",1,start,100,1)
        result = simulate(data,cfg,"2026-06-01",[sig],{"ETHUSDT":{}})
        trade = result["trades"][0]
        self.assertAlmostEqual(trade["funding_net_usdt"],-trade["quantity"]*101*0.001)

    def test_trailing_update_never_retroactively_stops_previous_bar(self):
        cfg,data,start = fixture()
        update = start+2*3600
        data.minutes["ETHUSDT"][update] = Bar(update,104.5,104.6,103.5,104,10000,1000000)
        data.marks["ETHUSDT"][update] = data.minutes["ETHUSDT"][update]
        data.minutes["ETHUSDT"][update+60] = Bar(update+60,102,102.5,101.5,102,10000,1000000)
        data.marks["ETHUSDT"][update+60] = data.minutes["ETHUSDT"][update+60]
        updates = {"ETHUSDT":{update:(Bar(update-3600,100,105,100,104),1)}}
        sig = Signal("ETHUSDT","crypto",1,start,100,1)
        result = simulate(data,cfg,"2026-06-01",[sig],updates)
        self.assertEqual(result["trades"][0]["exit_reason"],"trailing_stop")
        self.assertAlmostEqual(result["trades"][0]["exit_price"],102*(1-0.0005))

    def test_first_hour_trailing_uses_only_minutes_after_entry(self):
        cfg,data,start = fixture()
        for offset,values in {1800:(100,105,99.9,104),3540:(104,104.1,103.9,104),
                              3600:(104.5,104.6,103.5,104),3660:(102,102.5,101.5,102)}.items():
            t = start+offset
            data.minutes["ETHUSDT"][t] = Bar(t,*values,10000,1000000)
            data.marks["ETHUSDT"][t] = data.minutes["ETHUSDT"][t]
        # A pre-entry spike to 150 must not tighten the post-entry stop to 148.
        updates = {"ETHUSDT":{start+3600:(Bar(start,100,150,99.9,104),1)}}
        sig = Signal("ETHUSDT","crypto",1,start,100,1)
        result = simulate(data,cfg,"2026-06-01",[sig],updates)
        trade = result["trades"][0]
        self.assertEqual(trade["exit_reason"],"trailing_stop")
        self.assertEqual(trade["exit_time"],"2026-06-01T01:01:00+00:00")
        self.assertAlmostEqual(trade["exit_price"],102*(1-0.0005))

    def test_production_intent_gross_guard_still_present(self):
        intent = StrategyIntent("research","2026-06-01T00:00:00Z",
            "2026-06-01T00:00:00Z",{"ETHUSDT":6.0},1,0.1,"a"*64,"b"*64)
        self.assertIn("standalone_target_gross_exceeds_one",intent.validate())

    def test_signal_prefix_is_identical_when_future_is_removed(self):
        cfg = config()
        cfg["stock_symbols"] = []
        start = timestamp("2026-06-01")
        end,cut = start+7*86400,start+3*86400
        hours = {}
        for symbol in cfg["crypto_symbols"]:
            hours[symbol] = []
            for i,t in enumerate(range(start-35*86400,end,3600)):
                price = 100+0.2*i
                hours[symbol].append(Bar(t,price-0.1,price+0.05,price-0.15,price,
                                        1,3 if i%24==0 else 1))
        full = MarketData({}, {},hours,{}, {},{})
        prefix = copy.deepcopy(full)
        prefix.hours = {symbol:[b for b in bars if b.t+3600 <= cut]
                        for symbol,bars in hours.items()}
        a,_ = generate_signals(full,cfg,start,end)
        b,_ = generate_signals(prefix,cfg,start,cut)
        self.assertTrue(b)
        self.assertEqual([s for s in a if s.decision_time < cut],b)

    def test_stock_position_closes_before_regular_session_end(self):
        cfg,data,start = fixture()
        cfg["crypto_symbols"],cfg["stock_symbols"] = [],["AMZNUSDT"]
        for mapping in (data.minutes,data.marks,data.funding,data.rules):
            mapping["AMZNUSDT"] = mapping.pop("ETHUSDT")
        decision = timestamp("2026-06-01T14:15:00")
        sig = Signal("AMZNUSDT","stock",1,decision,100,2)
        result = simulate(data,cfg,"2026-06-01",[sig],{"AMZNUSDT":{}})
        self.assertEqual(result["summary"]["stock_trades"],1)
        self.assertEqual(result["trades"][0]["exit_reason"],"session_close")
        self.assertEqual(result["trades"][0]["exit_time"],"2026-06-01T19:45:00+00:00")

    def test_account_stop_waits_for_next_minute_instead_of_using_future_price(self):
        cfg,data,start = fixture()
        cfg["equity_floor_usdt"] = 9.99
        t = start+120
        data.minutes["ETHUSDT"][t] = Bar(t,101,101.1,100.9,101,10000,1000000)
        data.marks["ETHUSDT"][t] = data.minutes["ETHUSDT"][t]
        sig = Signal("ETHUSDT","crypto",1,start,100,1)
        result = simulate(data,cfg,"2026-06-01",[sig],{"ETHUSDT":{}})
        trade = result["trades"][0]
        self.assertEqual(trade["exit_reason"],"account_stop")
        self.assertEqual(trade["exit_time"],"2026-06-01T00:02:00+00:00")
        self.assertNotEqual(result["curve"][1]["equity_usdt"],trade["equity_after"])

    def test_profit_compounds_and_risk_downshift_survives_drawdown(self):
        cfg,data,start = fixture()
        cfg["crypto_max_hold_hours"] = 1
        cfg["risk_downshift_equity_usdt"] = 12.0
        exit_t = start+3660
        data.minutes["ETHUSDT"][exit_t] = Bar(exit_t,104,104.1,103.9,104,10000,1000000)
        data.marks["ETHUSDT"][exit_t] = data.minutes["ETHUSDT"][exit_t]
        stop_t = start+2*3600+60
        data.minutes["ETHUSDT"][stop_t] = Bar(stop_t,100,100.1,97,98,10000,1000000)
        data.marks["ETHUSDT"][stop_t] = data.minutes["ETHUSDT"][stop_t]
        sigs = [Signal("ETHUSDT","crypto",1,start+h*3600,100,1) for h in (0,2,4)]
        result = simulate(data,cfg,"2026-06-01",sigs,{"ETHUSDT":{}})
        a,b,c = result["trades"]
        self.assertGreater(a["equity_after"],12)
        self.assertAlmostEqual(b["risk_budget_usdt"],a["equity_after"]*0.05)
        self.assertLess(b["equity_after"],12)
        self.assertAlmostEqual(c["risk_budget_usdt"],b["equity_after"]*0.05)
        self.assertTrue(result["summary"]["downshift_reached"])


if __name__ == "__main__":
    unittest.main()
