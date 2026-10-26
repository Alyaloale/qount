"""Cash funding, fee-floor separation, dividend rights and delay initialization."""
import copy
import datetime as dt
from functools import partial
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from qount.dual_engine.contracts import DualEnginePaperContract
from qount.dual_engine.paper import _rebalance_layer
from qount.dual_engine.g20_cash import new_account,normalize_cache,step,NY
from qount.research.g20_cash_execution import CashFriction,rebalance_cash


def layer(cash,positions=None):
    return dict(cumulative_cost=0.,cumulative_stress_cost=0.,sleeves={"g20":dict(cash=cash,positions=positions or {})})


def rebalance(book,target,prices,friction=CashFriction()):
    return rebalance_cash(book,sleeve_budgets={"g20":1.},sleeve_targets={"g20":target},marks=prices,fills=prices,
        rules={},contract=DualEnginePaperContract.frozen_v1(),signal=False,friction=friction)


class G20CashExecutionTests(unittest.TestCase):
    def test_minimum_commission_does_not_replace_slippage(self):
        self.assertAlmostEqual(CashFriction(minimum_commission=1).fee(100),1.15)
        self.assertAlmostEqual(CashFriction().fee(100),.2)
        self.assertEqual(CashFriction(minimum_commission=1).fee(0),0)

    def test_integer_purchase_is_funded_including_floor_and_slippage(self):
        f=CashFriction(minimum_commission=1)
        b=layer(100.)
        cost,events=rebalance(b,{"SMH":1.},{"SMH":10.},f)
        self.assertEqual(events[0]["quantity"],9.)
        self.assertAlmostEqual(cost,1.135)
        self.assertAlmostEqual(b["sleeves"]["g20"]["cash"],8.865)
        funded=layer(101.15)
        _,events=rebalance(funded,{"SMH":1.},{"SMH":10.},f)
        self.assertEqual(events[0]["quantity"],10.)
        self.assertAlmostEqual(funded["sleeves"]["g20"]["cash"],0.)

    def test_no_order_has_no_minimum_fee(self):
        b=layer(30.,{"SMH":7.})
        cost,events=rebalance(b,{"SMH":.7},{"SMH":10.},CashFriction(minimum_commission=1))
        self.assertEqual(events,[]);self.assertEqual(cost,0.)

    def test_zero_floor_reproduces_published_rebalancer(self):
        prices={"SOXL":72.31,"BIL":91.7}
        for initial in (layer(10000.),layer(1000.,{"SOXL":5.,"BIL":80.})):
            for target in ({"SOXL":.2,"BIL":.8},{"BIL":1.}):
                a,b=copy.deepcopy(initial),copy.deepcopy(initial)
                rebalance(a,target,prices)
                _rebalance_layer(b,sleeve_budgets={"g20":1.},sleeve_targets={"g20":target},marks=prices,fills=prices,
                    rules={s:dict(step_size=1.,minimum_notional=0.) for s in prices},
                    contract=DualEnginePaperContract.frozen_v1(),signal=False)
                self.assertEqual(a,b)

    def test_extra_issuer_does_not_inherit_direxion_pay_dates(self):
        rows=[dict(date=d,open=10.,high=10.,low=10.,close=10.,adjClose=10.) for d in ("2026-01-02","2026-01-05")]
        stamp=int(dt.datetime(2026,1,2,9,30,tzinfo=NY).timestamp())
        cache={"BIL":dict(rows=rows),"SMH":dict(rows=rows,events=dict(dividends={str(stamp):dict(date=stamp,amount=1.)}))}
        policy=dict(verified_actions=[],sources={"vaneck":"issuer"},pay_dates={"vaneck":{"2026-01-02":"2026-01-06"}})
        _,actions,_=normalize_cache(cache,policy,execution_symbols=("SMH","BIL"),issuer_groups={"SMH":"vaneck"})
        self.assertEqual(actions["2026-01-02"][0]["pay_date"],"2026-01-06")

    def test_smh_ex_date_sale_retains_right_and_payment_is_not_double_profit(self):
        d=new_account("2026-01-02T23:00:00+00:00");d["initial_equity"]=100.
        d["layer"]=layer(0.,{"SMH":10.})
        d["pending"]=dict(target={"BIL":1.},decision_date="2025-12-31",available_at="2025-12-31T22:00:00+00:00")
        bar={s:dict(open=10.,close=10.) for s in ("SMH","BIL")}
        event=dict(kind="dividend",symbol="SMH",amount=1.,pay_date="2026-01-06",amount_source="fixture",source="issuer")
        kwargs=dict(bar=bar,decision=None,observed_at="2026-01-07T00:00:00+00:00",historical_replay=True,
            execution_symbols=("SMH","BIL"),rebalance=partial(rebalance_cash,friction=CashFriction(cost_bps=0,commission_bps=0)))
        d=step(d,day="2026-01-02",actions=[event],opening=dt.datetime(2026,1,2,9,30,tzinfo=NY),**kwargs)
        self.assertEqual(d["income"][0]["quantity"],10.)
        self.assertEqual(d["observations"][-1]["receivable"],10.)
        self.assertEqual(d["layer"]["sleeves"]["g20"]["positions"],{"BIL":10.})
        equity=d["observations"][-1]["equity"]
        d=step(d,day="2026-01-06",actions=[],opening=dt.datetime(2026,1,6,9,30,tzinfo=NY),**kwargs)
        self.assertEqual(d["observations"][-1]["equity"],equity)
        self.assertEqual(d["observations"][-1]["cash"],10.)

    def test_delayed_fresh_account_does_not_trade_stale_previous_signal(self):
        with patch.object(sys,"path",[str(Path(__file__).resolve().parents[2]/"scripts/research"),*sys.path]):
            from compare_g20_cash_carriers import simulate,SYMBOLS
        from qount.research.dual_engine_optimization import EquityPanel
        dates=("2025-12-29","2025-12-30","2025-12-31","2026-01-02","2026-01-05")
        p=EquityPanel(dates,{},{},{})
        prices={s:{d:dict(open=10.,close=10.) for d in dates} for s in SYMBOLS}
        r=simulate(p,prices,{}, {0:{"SOXL":1.},2:{"SOXL":.2,"BIL":.8}},
                   capital=1000.,friction=CashFriction(),delay=2)
        self.assertEqual(r["records"][0]["positions"],[])
        self.assertTrue(r["trades"])
        self.assertTrue(all(t["date"]=="2026-01-05" and t["decision_date"]=="2025-12-31" for t in r["trades"]))


if __name__=="__main__":unittest.main()
