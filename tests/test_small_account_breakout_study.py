from __future__ import annotations

import copy
import unittest

from test_small_account_breakout import fixture, rule
from qount.research.small_account_breakout import Bar, Signal, funding_budget, simulate, size_contract
from qount.research.small_account_breakout_data import timestamp
from qount.research.small_account_breakout_study import (
    confirm_entries, fixed_cost_revaluation, group_events, path_diagnostic,
)


class BreakoutMechanismTests(unittest.TestCase):
    def test_failed_breakout_waits_for_completed_close_and_delay_both_sides(self):
        for side in (1,-1):
            cfg,data,start=fixture()
            cfg["breakout_failure_exit"]=True
            sig=Signal("ETHUSDT","crypto",side,start,100,1,100,100)
            update=start+3600
            updates={"ETHUSDT":{update:(Bar(start,100,100.1,99.9,100),1)}}
            r=simulate(data,cfg,"2026-06-01",[sig],updates)
            t=r["trades"][0]
            self.assertEqual(t["exit_reason"],"breakout_failure")
            self.assertEqual(timestamp(t["exit_time"]),update+60)
            self.assertGreater(timestamp(t["exit_time"]),update)

    def test_protective_stop_wins_during_failure_signal_delay(self):
        cfg,data,start=fixture()
        cfg["breakout_failure_exit"]=True
        sig=Signal("ETHUSDT","crypto",1,start,100,1,100,95)
        t=start+3600
        data.minutes["ETHUSDT"][t]=Bar(t,100,100.1,98,99,10000,1000000)
        updates={"ETHUSDT":{t:(Bar(start,100,100.1,99.9,99.9),1)}}
        r=simulate(data,cfg,"2026-06-01",[sig],updates)
        self.assertEqual(r["trades"][0]["exit_reason"],"initial_stop")
        self.assertEqual(timestamp(r["trades"][0]["exit_time"]),t)

    def test_opening_gap_at_failure_exit_does_not_bypass_stop_stress(self):
        cfg,data,start=fixture()
        cfg["breakout_failure_exit"]=True
        t=start+3660
        data.minutes["ETHUSDT"][t]=Bar(t,98,98.1,97.9,98,10000,1000000)
        updates={"ETHUSDT":{start+3600:(Bar(start,100,100.1,99.9,99.9),1)}}
        r=simulate(data,cfg,"2026-06-01",[Signal("ETHUSDT","crypto",1,start,100,1,100,95)],updates,scenario="stop_gap_1pct")
        self.assertEqual(r["trades"][0]["exit_reason"],"initial_stop")
        self.assertAlmostEqual(r["trades"][0]["exit_price"],98*0.99*0.9995)

    def test_failure_exit_does_not_bypass_opening_mark_liquidation(self):
        cfg,data,start=fixture()
        cfg["breakout_failure_exit"]=True
        t=start+3660
        data.minutes["ETHUSDT"][t]=Bar(t,80,80.1,79.9,80,10000,1000000)
        data.marks["ETHUSDT"][t]=data.minutes["ETHUSDT"][t]
        updates={"ETHUSDT":{start+3600:(Bar(start,100,100.1,99.9,99.9),1)}}
        r=simulate(data,cfg,"2026-06-01",[Signal("ETHUSDT","crypto",1,start,100,1,100,95)],updates)
        self.assertEqual(r["trades"][0]["exit_reason"],"liquidation")

    def test_confirmation_uses_original_boundary_and_only_next_complete_hour(self):
        s=Signal("ETHUSDT","crypto",1,3600,101,2,100,90)
        self.assertEqual(confirm_entries([s],{"ETHUSDT":{7200:(Bar(3600,101,105,99,99),2)}},10000),[])
        confirmed=confirm_entries([s],{"ETHUSDT":{7200:(Bar(3600,101,105,99,101),5)}},10000)
        self.assertEqual(confirmed[0].decision_time,7200)
        self.assertEqual(confirmed[0].original_decision_time,3600)
        self.assertEqual(confirmed[0].breakout_high,100)
        self.assertEqual(confirmed[0].atr,2)
        self.assertEqual(confirm_entries([s],{"ETHUSDT":{}},7200),[])

    def test_funding_intervals_observed_then_known_never_future(self):
        now=timestamp("2026-06-01")
        cfg={"funding_interval_mode":"known_or_observed","funding_interval_fallback_hours":8}
        rows=[{"fundingTime":(now-h*3600)*1000,"fundingRate":"0.0001"} for h in (5,1)]
        rows.append({"fundingTime":(now+3600)*1000,"fundingRate":"0.5"})
        future={"known_at":now+1,"effective_from":now-3600,"fundingIntervalHours":1}
        a=funding_budget(rows,[future],now,24,cfg)
        self.assertEqual(a["interval_hours"],4)
        self.assertAlmostEqual(a["fraction"],0.0006)
        known={**future,"known_at":now-1}
        b=funding_budget(rows,[known],now,24,cfg)
        self.assertEqual(b["interval_source"],"point_in_time_snapshot")
        self.assertAlmostEqual(b["fraction"],0.0024)

    def test_liquidity_is_quantity_bound_not_reason_to_round_up(self):
        cfg,_,start=fixture()
        s=Signal("ETHUSDT","crypto",1,start,100,1)
        c,_=size_contract(s,100,10,0.1,0.002,rule(),cfg,liquidity_quantity=0.1239)
        self.assertEqual(c.quantity,0.123)
        c,reason=size_contract(s,100,10,0.1,0.002,rule(),cfg,liquidity_quantity=0.049)
        self.assertIsNone(c)
        self.assertEqual(reason,"minimum_order")

    def test_mfe_does_not_claim_exit_minute_high_preceded_stop(self):
        cfg,data,start=fixture()
        t=start+120
        data.minutes["ETHUSDT"][t]=Bar(t,100,105,97,100,10000,1000000)
        sig=Signal("ETHUSDT","crypto",1,start,100,1,99.9,90)
        trade=simulate(data,cfg,"2026-06-01",[sig],{"ETHUSDT":{}})["trades"][0]
        data.hours["ETHUSDT"]=[]
        d=path_diagnostic(trade,data,cfg,24)
        self.assertLess(d["mfe_r_confirmed"],0.1)
        self.assertGreater(d["mfe_r_upper_bound"],3)
        self.assertAlmostEqual(d["net_r"],trade["net_pnl_usdt"]/(trade["quantity"]*abs(trade["entry_price"]-trade["initial_stop"])))

    def test_event_grouping_crosses_symbols_without_transitive_chaining(self):
        signals=[Signal(sym,"crypto",1,t,100,1) for sym,t in
                 (("BTCUSDT",0),("ETHUSDT",3600),("SOLUSDT",23*3600),("BTCUSDT",25*3600))]
        events=group_events(signals,24)
        self.assertEqual(events[0].event_id,events[2].event_id)
        self.assertNotEqual(events[2].event_id,events[3].event_id)

    def test_continuous_account_carries_position_across_week_boundary(self):
        cfg,data,start=fixture()
        for key in ("minutes","marks"):
            prices=getattr(data,key)["ETHUSDT"]
            for t in range(start+7*86400,start+9*86400,60):
                prices[t]=Bar(t,100,100.1,99.9,100,10000,1000000)
        cfg["crypto_max_hold_hours"]=48
        decision=start+6*86400+23*3600
        sig=Signal("ETHUSDT","crypto",1,decision,100,1)
        r=simulate(data,cfg,"2026-06-01",[sig],{"ETHUSDT":{}},end_time=start+9*86400)
        self.assertEqual(len(r["trades"]),1)
        self.assertEqual(r["trades"][0]["exit_reason"],"max_hold")
        self.assertGreater(timestamp(r["trades"][0]["exit_time"]),start+7*86400)
        self.assertEqual(len(r["curve"]),9*1440)

    def test_continuous_account_keeps_cooldown_and_realized_equity_across_week(self):
        cfg,data,start=fixture()
        for key in ("minutes","marks"):
            prices=getattr(data,key)["ETHUSDT"]
            for t in range(start+7*86400,start+8*86400,60):
                prices[t]=Bar(t,100,100.1,99.9,100,10000,1000000)
        decisions=[start+7*86400-h*3600 for h in (2,1,-1)]
        for t in decisions[:2]:
            data.minutes["ETHUSDT"][t+60]=Bar(t+60,100,100.1,97,98,10000,1000000)
        sigs=[Signal("ETHUSDT","crypto",1,t,100,1) for t in decisions]
        r=simulate(data,cfg,"2026-06-01",sigs,{"ETHUSDT":{}},end_time=start+8*86400)
        self.assertEqual(len(r["trades"]),2)
        self.assertEqual(r["summary"]["rejections"]["cooldown"],1)
        self.assertLess(r["trades"][1]["risk_budget_usdt"],r["trades"][0]["risk_budget_usdt"])

    def test_fixed_cost_revaluation_preserves_trade_count_and_adds_cost(self):
        trade={"entry_time":"2026-06-01","symbol":"ETHUSDT","net_pnl_usdt":0.2,
               "fees_usdt":0.1,"slippage_usdt":0.2,"diagnostic":{"price_risk_usdt":0.5}}
        original=copy.deepcopy(trade)
        r=fixed_cost_revaluation([trade],2)
        self.assertEqual(r["trade_count"],1)
        self.assertAlmostEqual(r["net_pnl_usdt"],-0.1)
        self.assertAlmostEqual(r["mean_net_r"],-0.2)
        self.assertEqual(trade,original)


if __name__=="__main__": unittest.main()
