import copy
from types import SimpleNamespace
import unittest

from qount.research.ashare_absorption import features, make_entry, open_quote, simulate


def fixture(n=100):
    s = SimpleNamespace(symbol='000001.SZ', valid=bytearray([1]*n), history=[300]*n,
                        raw_open=[10.]*n, raw_close=[10.]*n, raw_high=[10.5]*n,
                        raw_low=[9.5]*n, pre_close=[10.]*n, factor=[1.]*n,
                        adj_open=[10.]*n, adj_close=[10.]*n, amount_cny=[100_000_000.]*n)
    dates=[f'2020{i//28+1:02d}{i%28+1:02d}' for i in range(n)]
    return s, dates


class AbsorptionTests(unittest.TestCase):
    def test_normalized_adjusted_scale_preserves_signals_and_pnl(self):
        s,dates=fixture()
        s.adj_close[70]=s.raw_close[70]=11.;s.raw_high[70]=11.2
        normalized=copy.deepcopy(s)
        normalized.adj_open=[x*.1 for x in s.adj_open]
        normalized.adj_close=[x*.1 for x in s.adj_close]
        normalized.factor=[5.]*len(dates)
        original=list(features(s,dates));changed=list(features(normalized,dates))
        self.assertEqual(original,changed)
        a,_=make_entry(s,dates,original[0]);b,_=make_entry(normalized,dates,changed[0])
        for policy in ['fixed10','price','price_plus_stall']:
            x=simulate(s,dates,a,policy);y=simulate(normalized,dates,b,policy)
            self.assertAlmostEqual(x['return_pct'],y['return_pct'],places=10)
            self.assertEqual(x['exit_j'],y['exit_j'])

    def test_flat_stock_does_not_lose_capital_from_factor_normalization(self):
        s,dates=fixture();s.factor=[5.]*len(dates)
        s.adj_open=[20.]*len(dates);s.adj_close=[20.]*len(dates)
        entry,_=make_entry(s,dates,dict(signal_j=60,adv20=100_000_000.))
        result=simulate(s,dates,entry,'fixed10')
        self.assertLess(result['return_pct'],0.)
        self.assertGreater(result['return_pct'],-1.)

    def test_pre_breakout_score_excludes_breakout_candle_and_future(self):
        s, dates=fixture()
        s.adj_close[70]=11.;s.raw_high[70]=11.2
        original=list(features(s,dates))[0]
        changed=copy.deepcopy(s);changed.raw_low[70]=1.
        changed.adj_close[90]=30.;changed.raw_high[90]=31.
        self.assertEqual(original,list(features(changed,dates))[0])
        self.assertAlmostEqual(original['score'],.5)

    def test_open_fill_does_not_look_at_full_day_activity_or_close(self):
        s,_=fixture();before=open_quote(s,10,'buy',.001)
        s.amount_cny[10]=0.;s.raw_high[10]=999.;s.raw_low[10]=0.;s.adj_close[10]=float('nan')
        self.assertEqual(before,open_quote(s,10,'buy',.001))

    def test_exit_from_entry_day_close_is_tplus1(self):
        s,dates=fixture();event=dict(signal_j=60,adv20=100_000_000.)
        entry,_=make_entry(s,dates,event)
        s.adj_close[entry.day]=9.
        result=simulate(s,dates,entry,'price')
        self.assertEqual(result['exit_j'],entry.day+1)

    def test_blocked_exit_persists_to_a_later_open(self):
        s,dates=fixture();entry,_=make_entry(s,dates,dict(signal_j=60,adv20=100_000_000.))
        s.raw_open[entry.day+10]=9.
        result=simulate(s,dates,entry,'fixed10')
        self.assertEqual(result['blocked_exit_opens'],1)
        self.assertEqual(result['exit_j'],entry.day+11)

    def test_unresolved_exit_is_not_dropped_or_forced_filled(self):
        s,dates=fixture(75);entry,_=make_entry(s,dates,dict(signal_j=60,adv20=100_000_000.))
        for j in range(entry.day+10,len(dates)):
            s.raw_open[j]=float('nan')
        result=simulate(s,dates,entry,'fixed10')
        self.assertEqual(result['status'],'unresolved')
        self.assertIsNone(result['exit_j'])
        self.assertLess(result['lower_return_pct'],result['return_pct'])

    def test_new_stall_rule_can_exit_before_price_rule(self):
        s,dates=fixture();entry,_=make_entry(s,dates,dict(signal_j=60,adv20=100_000_000.))
        s.adj_close[entry.day]=s.raw_close[entry.day]=10.6;s.raw_high[entry.day]=10.7
        j=entry.day+1;s.adj_close[j]=s.raw_close[j]=10.6;s.raw_high[j]=11.5;s.raw_low[j]=10.5
        s.amount_cny[j]=200_000_000.
        flow=simulate(s,dates,entry,'price_plus_stall');price=simulate(s,dates,entry,'price')
        self.assertEqual(flow['reason'],'high_volume_low_close_after_profit')
        self.assertEqual(flow['exit_j'],entry.day+2)
        self.assertGreater(price['exit_j'],flow['exit_j'])


if __name__=='__main__':unittest.main()
