import copy
import math
import statistics
import unittest
from array import array
from unittest.mock import patch

from tests.test_ashare_strategy import series
from qount.research.ashare_strategy import Position
from qount.research.ashare_quality_momentum import (
    GATE, RULES, QualityMomentumBook, diversify, evaluate_gate, quality_features, rolling, select, validate_contract,
)


def trending(n=280):
    s = series(n)
    for j in range(n):
        s.adj_close[j] = 10 * math.exp(.002*j + .01*math.sin(j))
    return s


class QualityMomentumTests(unittest.TestCase):
    def test_exact_window_and_population_volatility(self):
        s = trending(); f = quality_features(s)
        changes = [math.log(s.adj_close[k]/s.adj_close[k-1]) for k in range(154,280)]
        self.assertAlmostEqual(f.vol126[-1], statistics.pstdev(changes)*math.sqrt(252))
        self.assertAlmostEqual(f.ma120[-1], statistics.fmean(s.adj_close[160:280]))
        changes60 = changes[-60:]
        self.assertAlmostEqual(f.score[-1], (s.adj_close[-1]/s.adj_close[-61]-1)/(statistics.pstdev(changes60)*math.sqrt(252)))
        self.assertTrue(math.isnan(f.vol126[125])); self.assertTrue(math.isfinite(f.vol126[126]))

    def test_missing_session_not_compressed(self):
        s = trending(); s.valid[230] = 0; f = quality_features(s)
        self.assertTrue(math.isnan(f.vol126[-1])); self.assertTrue(math.isnan(f.ma120[-1]))
        self.assertTrue(math.isnan(f.score[-1]))

    def test_future_does_not_change_past_features_or_selection(self):
        s = trending(); f = quality_features(s)
        before = select(270, {'X':s}, {'X':f}, {})
        s.adj_close[279] = 10000
        later = quality_features(s)
        for key in ('ma120','vol126','vol60','score'):
            self.assertEqual(getattr(f,key)[270], getattr(later,key)[270])
        self.assertEqual(before, select(270, {'X':s}, {'X':later}, {}))

    def test_zero_vol_not_ranked_primary_but_allowed_control(self):
        s = series(); f = quality_features(s); f.ma120[-1] = 9; f.base.ma60[-1] = 9.5
        self.assertTrue(math.isnan(f.score[-1]))
        selection = select(279, {'X':s}, {'X':f}, {})
        self.assertEqual(selection['sector_rank'], []); self.assertEqual(selection['price_rank'], ['X'])

    def test_industry_median_precedes_trend_filter(self):
        s = trending(); features = {c:quality_features(s) for c in 'ABC'}
        for c,v in zip('ABC', [.1,.1,.3]):
            features[c].vol126[-1] = v
        features['A'].ma120[-1] = 1e9; features['B'].ma120[-1] = 1e9
        selection = select(279, {c:s for c in 'ABC'}, features, {c:{'industry':'I'} for c in 'ABC'})
        self.assertEqual(selection['industry_medians']['I'], .1)
        self.assertEqual(selection['sector_rank'], []); self.assertEqual(selection['price_rank'], ['C'])

    def test_quality_boundary_score_ranking_and_control(self):
        s = trending(); fs = {c:quality_features(s) for c in 'ABCD'}
        for c,v in zip('ABCD',[.1,.1,.12,.2]):
            fs[c].vol126[-1] = v; fs[c].score[-1] = {'A':2,'B':2,'C':3,'D':9}[c]
            fs[c].base.adv20[-1] = {'A':8e7,'B':9e7,'C':1e8,'D':2e8}[c]
        meta = {c:{'industry':'I'} for c in 'ABCD'}
        # median .11 => .132, C passes and D fails; same industry cap applies to both.
        x = select(279,{c:s for c in fs},fs,meta)
        self.assertEqual(x['sector_rank'],['C','A']); self.assertEqual(x['price_rank'],['D','C'])

    def test_unknown_industry_retired_status_retained(self):
        s = trending(); s.source_kind = 'tushare_retired'; f = quality_features(s)
        x = select(279, {'X':s}, {'X':f}, {'X':{'industry':None,'list_status':'D','name':'ST旧'}})
        self.assertEqual(x['sector_rank'], ['X']); self.assertEqual(x['eligible_retired'],1)

    def test_diversification_cluster_and_rank20(self):
        meta = {str(j):{'industry':['房产服务','全国地产','区域地产'][j//2]} for j in range(6)}
        self.assertEqual(diversify(list(meta),meta), ['0','1','2','3'])
        self.assertEqual(len(diversify([str(j) for j in range(30)],{str(j):{'industry':str(j)} for j in range(30)})),20)

    def test_control_checks_industry_slots_at_execution(self):
        b = QualityMomentumBook('price_control', {c:{'industry':'I'} for c in 'ABC'})
        for c in 'AB':
            b.positions[c] = Position(100,0,1000,10,10,0,0)
        self.assertFalse(b.slots_allow('C'))

    def setup_position(self, j=279, entry=250, peak=10):
        s = series(400); f = quality_features(s); f.ma120[j] = 9
        b = QualityMomentumBook('sector_base', {})
        b.positions['X'] = Position(100,entry,1000,peak,10,j,entry-1)
        return b,s,f

    def decide(self,b,s,f,j=279,review=False,rank=('X',)):
        b.decisions(j,'20260101',{'X':s},{'X':f},{'sector_rank':list(rank),'price_rank':list(rank)},review,399)

    def test_trailing_boundary_and_next_open(self):
        b,s,f = self.setup_position(peak=10/.82)
        self.decide(b,s,f)
        self.assertEqual(b.pending[0]['reason'], 'trailing18_close'); self.assertEqual(b.pending[0]['due_j'],280)
        s.raw_open[280] = s.pre_close[280] = s.adj_open[280] = 8
        b.execute(280,'20260102',{'X':s})
        self.assertAlmostEqual(b.trades[0]['raw_price_with_slippage'],7.992)

    def test_MA_strict_and_age_strict(self):
        b,s,f = self.setup_position(entry=27); f.ma120[279] = 10
        self.decide(b,s,f); self.assertEqual(b.pending,[])
        self.decide(b,s,f,j=280); self.assertEqual(b.pending[0]['reason'],'age_gt252')

    def test_daily_MA_exit_without_review(self):
        b,s,f = self.setup_position(); f.ma120[279] = 11
        self.decide(b,s,f); self.assertEqual(b.pending[0]['reason'],'below_MA120_close')

    def test_missing_close_does_not_fake_stop(self):
        b,s,f = self.setup_position(peak=100); s.valid[279] = 0
        self.decide(b,s,f); self.assertEqual(b.pending,[])

    def test_rank_buffer_only_review_and_no_same_review_rebuy(self):
        b,s,f = self.setup_position()
        self.decide(b,s,f,rank=()); self.assertEqual(b.pending,[])
        self.decide(b,s,f,review=True,rank=()); self.assertEqual(b.pending[0]['reason'],'review_rank_exit')
        b,s,f = self.setup_position(peak=20)
        self.decide(b,s,f,review=True); self.assertEqual([i['side'] for i in b.pending],['sell'])

    def test_circuit_cancels_buys_and_full63_sessions(self):
        b = QualityMomentumBook('sector_extra_day',{}); b.cash = 800000
        b.plan(0,'X','buy','test',raw_shares=100,budget_cny=1000,adv20=1e8)
        b.decisions(1,'20260101',{}, {}, {'sector_rank':[],'price_rank':[]},False,399)
        self.assertEqual(b.pending,[]); self.assertEqual(b.cooldown_until,65)
        b.decisions(64,'20260102',{}, {}, {'sector_rank':[],'price_rank':[]},False,399)
        self.assertEqual(b.cooldown_until,65)
        b.decisions(65,'20260103',{}, {}, {'sector_rank':[],'price_rank':[]},False,399)
        self.assertEqual(b.cooldown_until,-1); self.assertEqual(b.anchor_peak,800000)

    def test_circuit_waits_for_all_blocked_exits(self):
        b,s,f = self.setup_position(); b.cooldown_until = 100
        self.decide(b,s,f)
        self.assertEqual(b.cooldown_until,100); self.assertEqual(b.pending[0]['reason'],'portfolio_drawdown20')

    def test_signal_budget_delay_and_horizon(self):
        s = series(400); f = quality_features(s); b = QualityMomentumBook('sector_extra_day',{})
        self.decide(b,s,f,review=True)
        self.assertEqual(b.pending[0]['due_j'],281); self.assertEqual(b.pending[0]['budget_cny'],100000)
        self.assertEqual(b.pending[0]['raw_shares'],10000)
        b = QualityMomentumBook('sector_base',{})
        b.decisions(399,'20260101',{'X':s},{'X':f},{'sector_rank':['X'],'price_rank':['X']},True,399)
        self.assertEqual(b.pending,[])

    def test_gate_unknown_zero_and_no_control_improvement_requirement(self):
        result = {'CAGR_unknown_zero_recovery':.01,'CAGR_carry_proxy':.01,'max_drawdown_carry_proxy':-.4,'closed_trades':100}
        results = {n:copy.deepcopy(result) for n in RULES['curves']}; results['price_control']['CAGR_carry_proxy'] = .5
        self.assertTrue(evaluate_gate(results)['passed'])
        results['sector_extra_day']['CAGR_unknown_zero_recovery'] = None
        self.assertFalse(evaluate_gate(results)['passed'])

    def test_contract_flags_gate_and_required_bindings_fail_closed(self):
        contract = {'rules':RULES,'research_gate':GATE,'authorization':{'backtest':True,'orders':False,'services':False},
                    'research_only':True,'orders_authorized':False,'promotion_evidence':False}
        with self.assertRaisesRegex(ValueError,'required_frozen_sources_missing'):
            validate_contract(contract)
        for k in ('research_only','orders_authorized','promotion_evidence'):
            c = copy.deepcopy(contract); c[k] = not c[k]
            with self.assertRaisesRegex(ValueError,'quality_momentum_contract_invalid'):
                validate_contract(c)
        c = copy.deepcopy(contract); c['research_gate']['minimum_closed_trades'] = 1
        with self.assertRaisesRegex(ValueError,'quality_momentum_contract_invalid'):
            validate_contract(c)


if __name__ == '__main__':
    unittest.main()
