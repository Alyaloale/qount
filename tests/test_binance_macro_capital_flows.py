import unittest

from qount.research.binance_etf_leverage import replay
from test_binance_macro_attack import macro_fixture


class TestMacroCapitalFlows(unittest.TestCase):
    def test_flat_deposits_withdrawals_are_not_profit_or_drawdown(self):
        data,features=macro_fixture()
        for rows in features.values():
            for f in rows:f["entry_tactical"]=False
        times=[b.t for b in data['SPYUSDT']['trade']]
        result=replay(data,features,strategy='macro_tactical',account_controls=False,
                      capital_flows=[dict(time=times[2],amount=90),dict(time=times[4],amount=-95)])
        s=result['summary']
        self.assertEqual(s['final_equity'],5)
        self.assertEqual(s['net_return'],0)
        self.assertEqual(s['max_drawdown'],0)
        self.assertEqual(s['strategy_pnl'],0)
        self.assertTrue(all(r['unit_nav']==1 for r in result['curve']))
        self.assertTrue(all(r==0 for r in s['monthly_returns'].values()))

    def test_next_entry_risk_uses_updated_equity(self):
        data,features=macro_fixture()
        params=dict(strategy='macro_tactical',account_controls=False,risk_fraction=.5,gross_cap=3)
        baseline=replay(data,features,**params)
        first=baseline['trades'][0]
        changed=replay(data,features,**params,capital_flows=[dict(time=first['entry_time']-3600,amount=20)])
        t=changed['trades'][0]
        self.assertEqual(t['entry_time'],first['entry_time'])
        self.assertEqual(t['equity_before_entry'],30)
        self.assertEqual(t['risk_budget_usdt'],15)
        self.assertGreater(t['quantity'],first['quantity'])
        self.assertAlmostEqual(changed['summary']['final_equity'],30+sum(t['net_pnl'] for t in changed['trades']))

    def test_held_cashflow_needs_reconciliation(self):
        data,features=macro_fixture()
        params=dict(strategy='macro_tactical',account_controls=False,risk_fraction=.5,gross_cap=3)
        first=replay(data,features,**params)['trades'][0]
        with self.assertRaisesRegex(ValueError,'requires_flat_reconciled'):
            replay(data,features,**params,capital_flows=[dict(time=first['entry_time']+3600,amount=20)])

    def test_invalid_cashflow_clock_or_overdraft_fails(self):
        data,features=macro_fixture();start=data['SPYUSDT']['trade'][0].t
        params=dict(strategy='macro_tactical',account_controls=False)
        for flow in (dict(time=start+1,amount=10),dict(time=start,amount=float('nan')),
                     dict(time=start,amount=True),dict(time=start,amount=-10)):
            with self.assertRaises(ValueError):replay(data,features,**params,capital_flows=[flow])

    def test_absent_or_empty_flows_preserve_old_output(self):
        data,features=macro_fixture()
        params=dict(strategy='macro_tactical',account_controls=False)
        self.assertEqual(replay(data,features,**params),replay(data,features,**params,capital_flows=[]))
