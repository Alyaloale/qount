"""Carrier risk equivalence, bounded funding and causal price availability."""
from dataclasses import replace
from datetime import date,timedelta
import math
import json
from pathlib import Path
from statistics import variance
import sys
import tempfile
import unittest
from unittest.mock import patch

from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.research.dual_engine_optimization import EquityPanel
from qount.research.dual_engine_structural import replay_units
from qount.research.g20_carriers import match_portfolio_risk,proxy_schedule


class G20CarrierTests(unittest.TestCase):
    def test_three_times_returns_need_three_times_capital_not_same_weight(self):
        p=[-.02,.01,.03,-.01,.005]
        r=match_portfolio_risk([3*x for x in p],p,[0.]*len(p),.2)
        self.assertAlmostEqual(r["weight"],.6)
        self.assertTrue(r["matched"])

    def test_bil_covariance_is_included_in_full_portfolio_match(self):
        p=[-.02,.01,.03,-.01,.005];b=[.001,-.002,.003,.001,-.001]
        l=[2*x+.002 for x in p]
        r=match_portfolio_risk(l,p,b,.2)
        target=variance([.2*x+.8*y for x,y in zip(l,b)])
        actual=variance([r["weight"]*x+(1-r["weight"])*y for x,y in zip(p,b)])
        self.assertAlmostEqual(target,actual,places=14)
        self.assertNotAlmostEqual(r["weight"],.4,places=5)

    def test_impossible_risk_match_never_borrows_or_claims_equivalence(self):
        p=[-.02,.01,.03,-.01,.005]
        r=match_portfolio_risk([3*x for x in p],p,[0.]*len(p),.6)
        self.assertEqual(r["weight"],1.)
        self.assertFalse(r["matched"])
        self.assertEqual(r["status"],"cap_under_target")
        self.assertLess(r["achieved_volatility"],r["target_volatility"])

    def test_zero_anchor_keeps_cash_even_when_hedging_has_second_solution(self):
        p=[-.02,.01,.03,-.01,.005];b=[-x*.1 for x in p]
        r=match_portfolio_risk([3*x for x in p],p,b,0.)
        self.assertEqual(r["weight"],0.)
        self.assertTrue(r["matched"])

    def test_invalid_returns_are_rejected(self):
        for bad in ([-1.,.01],[float("nan"),.01],[float("inf"),.01]):
            with self.assertRaises(ValueError):match_portfolio_risk(bad,[.01,.02],[0.,0.],.2)
        with self.assertRaises(ValueError):match_portfolio_risk([.01,.02],[.01],[0.,0.],.2)

    def test_explicit_semiconductor_proxy_does_not_change_selection_or_global_mapping(self):
        p=[100.]
        for i in range(30):p.append(p[-1]*(1+.01*math.sin(i)))
        values={"SOXL":tuple(100*(x/100)**3 for x in p),"SOXX":tuple(p),"BIL":tuple(100. for _ in p)}
        before=dict(G20_EXECUTION_TO_PROXY)
        targets,diag=proxy_schedule(tuple(str(i) for i in range(len(p))),values,
            {25:{"SOXL":.2,"BIL":.8}},proxy_mapping=dict(before,SOXL="SOXX"))
        self.assertEqual(set(targets[25]),{"SOXX","BIL"})
        self.assertEqual(diag[0]["selected"],"SOXL")
        self.assertEqual(G20_EXECUTION_TO_PROXY,before)

    def test_extra_soxx_input_requires_complete_calendar_and_valid_prices(self):
        with patch.object(sys,"path",[str(Path(__file__).resolve().parents[2]/"scripts/research"),*sys.path]):
            from compare_g20_semiconductors import append_soxx
        from datetime import datetime,timezone
        dates=("2026-01-02","2026-01-05")
        panel=EquityPanel(dates,{"BIL":(100.,100.)},{"BIL":(100.,100.)},{"BIL":(100.,100.)})
        node=dict(meta=dict(symbol="SOXX"),timestamp=[int(datetime.fromisoformat(d+"T15:00:00").replace(tzinfo=timezone.utc).timestamp()) for d in dates],
            indicators=dict(quote=[dict(open=[10.,12.],high=[11.,13.],low=[9.,11.],close=[10.,12.])],adjclose=[dict(adjclose=[5.,6.])]))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"SOXX.json"
            def write():path.write_text(json.dumps(dict(chart=dict(result=[node]))))
            write();result=append_soxx(panel,path)
            self.assertEqual(result.total_opens["SOXX"],(5.,6.))
            self.assertNotIn("SOXX",panel.closes)
            with self.assertRaisesRegex(ValueError,"calendar"):
                append_soxx(replace(panel,dates=dates+("2026-01-06",)),path)
            node["indicators"]["quote"][0]["close"][1]=None;write()
            with self.assertRaisesRegex(ValueError,"invalid_price"):append_soxx(panel,path)

    def test_future_returns_do_not_change_known_weights_or_prior_nav(self):
        days=[date(2020,1,1)+timedelta(days=i) for i in range(400)]
        dates=tuple(d.isoformat() for d in days if d.weekday()<5)
        values={}
        for symbol in {*G20_EXECUTION_TO_PROXY,*G20_EXECUTION_TO_PROXY.values(),"BIL"}:
            level=[100.]
            for i in range(1,len(dates)):
                r=.0001 if symbol=="BIL" else (.001+.01*math.sin(i/9))*(3 if symbol in G20_EXECUTION_TO_PROXY else 1)
                level.append(level[-1]*(1+r))
            values[symbol]=tuple(level)
        panel=EquityPanel(dates,values,values,values)
        cut=160
        changed={s:v[:cut]+tuple(x*2 for x in v[cut:]) for s,v in values.items()}
        changed_panel=replace(panel,total_closes=changed,total_opens=changed)
        anchor={i:{"TQQQ":.2,"BIL":.8} for i in range(63,len(dates),5)}
        targets=[];runs=[]
        for p in (panel,changed_panel):
            schedule,_=proxy_schedule(dates,p.total_closes,anchor)
            targets.append(schedule)
            closes={s:dict(zip(dates,v)) for s,v in p.total_closes.items()}
            opens={s:dict(zip(dates,v)) for s,v in p.total_opens.items()}
            runs.append(replay_units(dates,closes,opens,schedule,start=dates[64],lag=1,cost_bps=20,cash_asset="BIL"))
        self.assertEqual({i:v for i,v in targets[0].items() if i<cut},{i:v for i,v in targets[1].items() if i<cut})
        self.assertEqual([r for r in runs[0]["records"] if r["date"]<dates[cut]],
                         [r for r in runs[1]["records"] if r["date"]<dates[cut]])


if __name__=="__main__":unittest.main()
