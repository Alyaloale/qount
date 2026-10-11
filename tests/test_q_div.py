import copy
import datetime as dt
import math
import statistics
import unittest

from qount.research.q_div import (
    DataUnknown, dividends, exit_reason, fundamentals, historical_readiness,
    ivol, liquid_codes, low_turnover_codes, price_features, report_map,
    select_candidates, target_weights, ttm,
)
from tests.test_ashare_strategy import series


def report(period, **values):
    return {'end_date':period,'ann_date':'20260801','f_ann_date':'20260801',
            'report_type':'1','comp_type':'1',**values}


def dividend(year, paid, cash=1., shares=100.):
    return {'end_date':str(year)+'1231','div_proc':'实施','imp_ann_date':'20260601',
            'ex_date':paid,'pay_date':paid,'cash_div_tax':cash,'base_share':shares}


def candidate(j, industry=None, iv=.1, dy=.04):
    return {'symbol':str(j),'industry':industry or str(j),'IVOL':iv,'yield_TTM':dy}


class QDivTests(unittest.TestCase):
    def test_announcements_strictly_precede_signal_and_factual_date_wins(self):
        a = report('20260630',n_income_attr_p=10.)
        a['f_ann_date']='20260930'
        self.assertEqual(report_map([a],'20260930',['n_income_attr_p']),{})
        self.assertIn('20260630',report_map([a],'20261001',['n_income_attr_p']))

    def test_identical_original_and_latest_rows_collapse_but_conflict_fails(self):
        a = report('20260630',n_income_attr_p=10.,update_flag='0')
        b = {**a,'update_flag':'1'}
        self.assertEqual(len(report_map([a,b],'20260930',['n_income_attr_p'])),1)
        b['n_income_attr_p']=11.
        with self.assertRaisesRegex(DataUnknown,'ambiguous_same_date'):
            report_map([a,b],'20260930',['n_income_attr_p'])

    def test_restatement_available_later_does_not_rewrite_earlier_value(self):
        a = report('20260630',n_income_attr_p=10.)
        b = {**a,'ann_date':'20261010','f_ann_date':'20261010','n_income_attr_p':30.}
        self.assertEqual(report_map([a,b],'20260930',['n_income_attr_p'])['20260630']['n_income_attr_p'],10.)
        self.assertEqual(report_map([a,b],'20261011',['n_income_attr_p'])['20260630']['n_income_attr_p'],30.)

    def test_TTM_uses_YTD_difference_and_does_not_add_quarters(self):
        r = {p:{'x':v} for p,v in [('20260630',80),('20251231',120),('20250630',50)]}
        self.assertEqual(ttm(r,'20260630','x'),150.)
        self.assertEqual(ttm(r,'20251231','x'),120.)
        del r['20250630']
        with self.assertRaises(DataUnknown):ttm(r,'20260630','x')

    def quality_data(self):
        inc=[report(p,n_income_attr_p=v) for p,v in [('20260630',80),('20251231',120),('20250630',50)]]
        cf=[report(p,n_cashflow_act=v) for p,v in [('20260630',100),('20251231',130),('20250630',60)]]
        bal=[report(p,total_hldr_eqy_exc_min_int=e,total_liab=600,total_assets=1000)
             for p,e in [('20260630',700),('20250630',600)]]
        return inc,cf,bal

    def test_quality_denominator_is_parent_profit_and_average_parent_equity(self):
        x=fundamentals(*self.quality_data(),'20260930')
        self.assertTrue(x['passed']);self.assertAlmostEqual(x['ROE_TTM'],150/650)
        self.assertAlmostEqual(x['CFO_to_parent_profit_TTM'],170/150)
        self.assertFalse(x['historical_vintage_certified'])

    def test_financial_companies_not_evaluated_with_industrial_cashflow_ratio(self):
        inc,cf,bal=self.quality_data();inc[0]['comp_type']='2'
        self.assertEqual(fundamentals(inc,cf,bal,'20260930')['reason'],'financial_or_nonindustrial_excluded')

    def test_latest_report_missing_does_not_fall_back_to_stale_better_report(self):
        inc,cf,bal=self.quality_data();cf=cf[1:]
        with self.assertRaisesRegex(DataUnknown,'not_aligned'):
            fundamentals(inc,cf,bal,'20260930')

    def test_negative_profit_fails_instead_of_inverting_cash_ratio(self):
        inc,cf,bal=self.quality_data();inc[0]['n_income_attr_p']=-1000
        x=fundamentals(inc,cf,bal,'20260930')
        self.assertFalse(x['passed']);self.assertIsNone(x['CFO_to_parent_profit_TTM'])

    def test_paid_implemented_dividend_units_and_three_years(self):
        rows=[dividend(2023,'20240610'),dividend(2024,'20250610'),dividend(2025,'20260610')]
        x=dividends(rows,'20260930',2000)
        self.assertTrue(x['passed']);self.assertAlmostEqual(x['yield_TTM'],.05)
        self.assertEqual(x['implemented_fiscal_years'],[2023,2024,2025])

    def test_proposal_future_payment_and_duplicate_do_not_inflate_yield(self):
        a=dividend(2025,'20260610')
        proposal={**a,'div_proc':'预案','cash_div_tax':100}
        future={**a,'ex_date':'20261010','pay_date':'20261010'}
        x=dividends([a,copy.deepcopy(a),proposal,future],'20260930',2000)
        self.assertAlmostEqual(x['yield_TTM'],.05);self.assertFalse(x['passed'])

    def test_old_dividend_missing_capital_base_not_required_for_current_TTM(self):
        old=dividend(2000,'20010610');old['base_share']=None
        older=dividend(2023,'20240610');older['base_share']=None
        x=dividends([old,older,dividend(2024,'20250610'),dividend(2025,'20260610')],'20260930',2000)
        self.assertTrue(x['passed'])
        with self.assertRaises(DataUnknown):
            dividends([dividend(2025,'20260610',shares=None)],'20260930',2000)

    def test_conflicting_implemented_event_fails_closed(self):
        a=dividend(2025,'20260610')
        with self.assertRaisesRegex(DataUnknown,'ambiguous'):
            dividends([a,{**a,'cash_div_tax':2}],'20260930',2000)

    def test_IVOL_removes_beta_and_intercept_with_population_residual(self):
        m=[.01*math.sin(k) for k in range(120)]
        rf=[.0001]*120;eps=[.002*math.cos(2*k) for k in range(120)]
        y=[.001+1.5*(x-r)+r+e for x,r,e in zip(m,rf,eps)]
        result=ivol(y,m,rf)
        residual=[(s-r)-result['alpha_daily']-result['beta']*(x-r) for s,x,r in zip(y,m,rf)]
        self.assertAlmostEqual(result['IVOL'],statistics.pstdev(residual)*math.sqrt(252))
        self.assertAlmostEqual(sum(residual),0)
        with self.assertRaises(DataUnknown):ivol(y[:-1],m,rf)
        with self.assertRaises(DataUnknown):ivol(y,[.01]*120,rf)

    def test_price_windows_use_exchange_dates_and_future_cannot_change_asof(self):
        s=series(300)
        for j in range(300):
            s.adj_close[j]=10+j*.01;s.volume[j]=1000
        for j in range(275,280):s.volume[j]=500
        before=price_features(s,279)
        self.assertTrue(before['trend_pass']);self.assertTrue(before['entry_pass'])
        s.adj_close[290]=100000
        self.assertEqual(before,price_features(s,279))
        s.valid[70]=0
        with self.assertRaises(DataUnknown):price_features(s,279)

    def test_relative_liquidity_and_turnover_boundaries_deterministic(self):
        f={str(j):{'ADV20_cny':1e8+j} for j in range(10)}
        self.assertEqual(len(liquid_codes(f)),8);self.assertNotIn('0',liquid_codes(f))
        self.assertEqual(len(low_turnover_codes({str(j):j for j in range(20)})),17)

    def test_industry_and_name_weight_caps_keep_unallocatable_cash(self):
        rows=[candidate(j,'I' if j<3 else 'J') for j in range(6)]
        w=target_weights(rows)
        self.assertAlmostEqual(sum(w.values()),.4)
        self.assertTrue(all(v<=.08+1e-12 for v in w.values()))
        self.assertAlmostEqual(sum(w[str(j)] for j in range(3)),.2)
        self.assertEqual(target_weights([]),{})

    def test_weights_redistribute_after_saturating_big_score(self):
        rows=[candidate(j,iv=.001 if j==0 else .1) for j in range(20)]
        w=target_weights(rows)
        self.assertAlmostEqual(w['0'],.08);self.assertAlmostEqual(sum(w.values()),1.)
        self.assertEqual(w,target_weights(list(reversed(rows))))

    def test_control_equal_industry_then_equal_name(self):
        rows=[candidate(0,'I'),candidate(1,'I'),candidate(2,'J')]
        w=target_weights(rows,control=True)
        self.assertAlmostEqual(w['0'],.08);self.assertAlmostEqual(w['1'],.08)
        self.assertAlmostEqual(w['2'],.08)

    def test_rank_buffer_keeps_rank35_but_does_not_buy_it(self):
        rows=[candidate(j,iv=.01+j*.001) for j in range(40)]
        held=['34','35']
        selected=select_candidates(rows,held)
        self.assertIn('34',[r['symbol'] for r in selected]);self.assertNotIn('35',[r['symbol'] for r in selected])
        self.assertEqual(len(selected),20)

    def test_three_confirmed_closes_missing_breaks_confirmation(self):
        args=dict(fundamental_bad=False,dividend_yield=.04,bias60=0,rank=1,review=False)
        self.assertIsNone(exit_reason(below_ma97=[True,None,True],**args))
        self.assertEqual(exit_reason(below_ma97=[True]*3,**args),'confirmed_MA200_break')
        args['fundamental_bad']=True
        self.assertEqual(exit_reason(below_ma97=[True]*3,**args),'known_fundamental_or_ST_event')

    def test_announcement_filter_is_not_historical_qualification(self):
        x=historical_readiness({'financial_vintages':True})
        self.assertIn('financial_vintages',x['missing']);self.assertFalse(x['returns_produced'])


if __name__=='__main__':unittest.main()
