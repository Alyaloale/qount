"""Clock, mechanism and funded-ledger checks for the offline cross-asset study."""
import unittest

import numpy as np

from qount.research.g20_cross_asset import Mechanism, causal_features, choose, replay
from qount.research_data.bars import Bar


def f(momentum=.3, sigma=.6, trend=True, carry=0.):
    return dict(available=0, annual_momentum=momentum, sigma=sigma, trend=trend, annual_carry=carry)


def panel():
    return dict(symbols=("SPYUSDT",), groups={"SPYUSDT": "equity"}, times=np.array([3600, 90000, 176400]),
                decision_times=np.array([3600, 90000, 176400]), open=np.array([[100.], [110.], [120.]]),
                mark_low=np.array([[99.], [109.]]), funding_value=np.array([[.5], [.2]]),
                funding_debit=np.array([[.5], [.2]]), features=[{"SPYUSDT": f()}, {"SPYUSDT": f()}],
                capacity=np.full((2, 1), 1000.))


class CrossAssetTest(unittest.TestCase):
    def test_elapsed_calendar_features_are_prefix_causal(self):
        days = [i for i in range(180) if i % 7 < 5]
        bars = [Bar((i + 1) * 86400, 100 + i, 101 + i, 99 + i, 100 + i) for i in days]
        a, b = causal_features(bars), causal_features(bars[:100])
        self.assertEqual([r for r in a if r["available"] <= bars[99].t], b)
        last = a[-1]
        anchor = max(i for i in days if (i + 1) * 86400 <= last['available'] - 63 * 86400)
        expected = np.log(bars[-1].c / (100 + anchor)) * 365.25 / (days[-1] - anchor)
        self.assertAlmostEqual(last['annual_momentum'], expected)

    def test_local_regime_preserves_commodity_opportunity(self):
        fs = {"BTCUSDT": f(trend=False), "SPYUSDT": f(trend=False), "XAUUSDT": f()}
        g = {"BTCUSDT": "crypto", "SPYUSDT": "equity", "XAUUSDT": "commodity"}
        self.assertIsNone(choose(fs, g, Mechanism(regime="btc")))
        self.assertEqual(choose(fs, g, Mechanism()), "XAUUSDT")

    def test_qualification_before_ranking_can_choose_valid_second_asset(self):
        fs = {"SPYUSDT": f(.4), "XAUUSDT": f(.8, trend=False)}
        g = {"SPYUSDT": "equity", "XAUUSDT": "commodity"}
        self.assertIsNone(choose(fs, g, Mechanism(eligible_first=False, normalize=False)))
        self.assertEqual(choose(fs, g, Mechanism(normalize=False)), "SPYUSDT")

    def test_normalization_compares_return_per_risk(self):
        fs = {"SPYUSDT": f(.2, .1), "XAUUSDT": f(.5, .5)}
        g = {"SPYUSDT": "equity", "XAUUSDT": "commodity"}
        self.assertEqual(choose(fs, g, Mechanism(normalize=False)), "XAUUSDT")
        self.assertEqual(choose(fs, g, Mechanism()), "SPYUSDT")

    def test_retention_preserves_qualification_and_carry_hurdle(self):
        fs = {"SPYUSDT": f(.2), "XAUUSDT": f(.5, carry=.7)}
        g = {"SPYUSDT": "equity", "XAUUSDT": "commodity"}
        self.assertEqual(choose(fs, g, Mechanism(retain=True), held="SPYUSDT"), "SPYUSDT")
        self.assertEqual(choose(fs, g, Mechanism(retain=True, net_carry=True), held="XAUUSDT"), "SPYUSDT")

    def test_cash_funding_and_two_sided_fee_identity_with_resize(self):
        p = panel()
        r = replay(p, Mechanism(), capital=1000, cap=1, cost_bp=30)
        q0 = 1000 / (100 * 1.003)
        e1 = 1000 - q0 * .3 + q0 * 10 - q0 * .5
        q1 = e1 / (110 * 1.003)
        expected = e1 - abs(q1-q0) * 110 * .003 + q1 * 10 - q1 * .2 - q1 * 120 * .003
        self.assertAlmostEqual(r['summary']['final'], expected)
        self.assertAlmostEqual(r['summary']['funding_pnl'], -q0 * .5 - q1 * .2)

    def test_capacity_uses_ex_ante_quantity_and_does_not_substitute(self):
        p = panel()
        p['capacity'][:] = 0
        r = replay(p, Mechanism(), capital=1000, capacity=True)
        self.assertEqual(r['summary']['final'], 1000)
        self.assertEqual(r['summary']['counts']['capacity_skip'], 2)
        self.assertEqual(r['fills'], [])

    def test_future_signal_and_real_mark_extreme(self):
        p = panel()
        p['features'][0]['SPYUSDT']['available'] = 3590
        with self.assertRaises(AssertionError):
            replay(p, Mechanism())
        p['features'][0]['SPYUSDT']['available'] = 0
        p['features'][0]['SPYUSDT']['sigma'] = .3
        p['mark_low'][0] = 40.
        r = replay(p, Mechanism(), capital=1000)
        self.assertEqual(r['summary']['final'], 0)
        self.assertEqual(r['summary']['counts']['liquidations'], 1)

    def test_affordability_does_not_remove_market_signal_reference(self):
        fs = {"BTCUSDT": f(.2), "ETHUSDT": f(.3)}
        g = {"BTCUSDT": "crypto", "ETHUSDT": "crypto"}
        m = Mechanism(tradable_first=True)
        self.assertEqual(choose(fs, g, m, tradable={"BTCUSDT": False, "ETHUSDT": True}), "ETHUSDT")
        self.assertIsNone(choose(fs, g, m, tradable={"BTCUSDT": False, "ETHUSDT": False}))

    def test_macro_only_excludes_crypto_without_erasing_regime_features(self):
        fs = {"BTCUSDT": f(10.), "SPYUSDT": f(.3)}
        g = {"BTCUSDT": "crypto", "SPYUSDT": "equity"}
        self.assertEqual(choose(fs, g, Mechanism(universe="macro")), "SPYUSDT")

    def test_carrier_risk_changes_sizing_and_requires_history(self):
        p = panel()
        rule = Mechanism(carrier_risk=True)
        empty = replay(p, rule, capital=1000)
        self.assertEqual(empty['summary']['final'], 1000)
        for fs in p['features']:
            fs['SPYUSDT']['carrier_sigma'] = 1.2
        r = replay(p, rule, capital=1000)
        self.assertAlmostEqual(r['curve'][0]['gross'], .5)

    def test_allocation_score_respects_binding_exposure_cap(self):
        fs={'SPYUSDT':f(.2,.1),'XAUUSDT':f(.3,.3)}
        g={'SPYUSDT':'equity','XAUUSDT':'commodity'}
        self.assertEqual(choose(fs,g,Mechanism(),cap=1),'SPYUSDT')
        self.assertEqual(choose(fs,g,Mechanism(allocation_score=True),cap=1),'XAUUSDT')

    def test_replacement_requires_advantage_to_cover_both_sides(self):
        fs={'SPYUSDT':f(.2,.2),'XAUUSDT':f(.21,.2)}
        g={'SPYUSDT':'equity','XAUUSDT':'commodity'}
        m=Mechanism(retain=True,allocation_score=True,replacement='cost')
        self.assertEqual(choose(fs,g,m,held='SPYUSDT',cap=1,cost=.003),'SPYUSDT')
        fs['XAUUSDT']['annual_momentum']=.3
        self.assertEqual(choose(fs,g,m,held='SPYUSDT',cap=1,cost=.003),'XAUUSDT')

    def test_entry_qualification_is_separate_from_hold_invalidation(self):
        fs={'SPYUSDT':f(.3),'XAUUSDT':dict(f(-.1,trend=False),above_mean=True)}
        g={'SPYUSDT':'equity','XAUUSDT':'commodity'}
        m=Mechanism(retain=True,hold_condition='price')
        self.assertEqual(choose(fs,g,m,held='XAUUSDT'),'XAUUSDT')
        self.assertEqual(choose(fs,g,m),'SPYUSDT')
        fs['XAUUSDT']['above_mean']=False
        self.assertEqual(choose(fs,g,m,held='XAUUSDT'),'SPYUSDT')

    def test_own_regime_does_not_depend_on_other_asset_trend(self):
        fs={'SPYUSDT':f(trend=False),'XLEUSDT':f(.3)}
        g={'SPYUSDT':'equity','XLEUSDT':'equity'}
        self.assertIsNone(choose(fs,g,Mechanism()))
        self.assertEqual(choose(fs,g,Mechanism(regime='own')),'XLEUSDT')

    def test_core_priority_and_distinct_driver_fallback(self):
        fs={'SPYUSDT':dict(f(.2),above_mean=True),'XLEUSDT':dict(f(2.),above_mean=True),
            'XAUUSDT':dict(f(.3),above_mean=True)}
        g={'SPYUSDT':'equity','XLEUSDT':'equity','XAUUSDT':'commodity'}
        m=Mechanism(retain=True,entry_condition='price',regime='own',core_symbol='SPYUSDT')
        self.assertEqual(choose(fs,g,m,held='XAUUSDT'),'SPYUSDT')
        fs['SPYUSDT']['above_mean']=False
        self.assertEqual(choose(fs,g,m),'XAUUSDT')
        self.assertIsNone(choose(fs,g,Mechanism(entry_condition='price',regime='own',core_symbol='SPYUSDT',core_defensive=False)))

    def test_capacity_clips_entries_without_implicit_borrowing(self):
        p=panel();p['funding_value'][:]=0;p['funding_debit'][:]=0
        p['capacity'][:]=2.;p['terminal_capacity']=np.array([100.])
        r=replay(p,Mechanism(capacity_mode='clip'),capital=1000,cap=1,cost_bp=0,capacity=True)
        self.assertAlmostEqual(r['summary']['final'],1060.)
        self.assertEqual([x['quantity'] for x in r['fills']],[2.,2.,-4.])

    def test_unfilled_exit_keeps_old_risk_and_blocks_new_position(self):
        p=panel();p['symbols']=('SPYUSDT','XAUUSDT');p['groups']['XAUUSDT']='commodity'
        p['open']=np.column_stack([p['open'][:,0],np.full(3,100.)])
        for k in ('mark_low','funding_value','funding_debit','capacity'):
            p[k]=np.column_stack([p[k][:,0],np.full(2,99. if k=='mark_low' else 0. if k.startswith('funding') else 100.)])
        p['funding_value'][:]=0;p['funding_debit'][:]=0
        p['features']=[{'SPYUSDT':f(.4),'XAUUSDT':f(.2)},
                       {'SPYUSDT':f(.4,trend=False),'XAUUSDT':f(.2)}]
        p['capacity'][1,0]=3.;p['terminal_capacity']=np.array([100.,100.])
        r=replay(p,Mechanism(retain=True,capacity_mode='clip'),capital=1000,cap=1,cost_bp=0,capacity=True)
        self.assertAlmostEqual(r['summary']['final'],1170.)
        self.assertFalse(any(x['symbol']=='XAUUSDT' for x in r['fills']))
        self.assertEqual(r['summary']['counts']['exit_capacity_deferred'],1)

    def test_terminal_unfilled_position_is_marked_not_fictitiously_closed(self):
        p=panel();p['terminal_capacity']=np.array([0.])
        r=replay(p,Mechanism(capacity_mode='clip'),capital=1000,cap=1,cost_bp=0,capacity=True)
        self.assertGreater(r['summary']['terminal_position']['quantity'],0.)
        self.assertFalse(any(x['reason']=='terminal_exit' for x in r['fills']))

    def test_dual_failure_exit_does_not_relax_fresh_entry(self):
        fs={'SPYUSDT':dict(f(.3,trend=False),above_mean=False)}
        g={'SPYUSDT':'equity'}
        m=Mechanism(retain=True,hold_condition='dual_failure',entry_condition='price',regime='own',core_symbol='SPYUSDT',core_defensive=False)
        self.assertEqual(choose(fs,g,m,held='SPYUSDT'),'SPYUSDT')
        self.assertIsNone(choose(fs,g,m))
        fs['SPYUSDT']['annual_momentum']=0.
        self.assertIsNone(choose(fs,g,m,held='SPYUSDT'))


if __name__ == '__main__':
    unittest.main()
