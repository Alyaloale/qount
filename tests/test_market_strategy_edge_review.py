import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/research'))
from review_market_strategy_edge import (
    cluster_interval, execution_rules, independent_opportunities,
    portfolio_comparison, selection_diagnostics,
)
from qount.research.market_model_profit import replay_asset


class MarketStrategyEdgeReviewTests(unittest.TestCase):
    def test_quarters_share_asset_shocks_and_keep_zero_quarters(self):
        clocks = np.array(['2024-01-01', '2024-04-01', '2024-07-01', '2024-10-01'], dtype='datetime64[ms]').astype('int64')
        values = np.array([.02, -.01, 0., .01])
        base = cluster_interval(values, clocks, weights=np.ones(4))
        duplicated = cluster_interval(np.repeat(values, 7), np.repeat(clocks, 7), weights=np.ones(28))
        self.assertEqual(base['quarter_clusters'], 4)
        self.assertAlmostEqual(base['mean'], .005)
        np.testing.assert_allclose(base['interval95'], duplicated['interval95'])

    def test_sliced_independent_trade_matches_full_cash_and_funding(self):
        bars = np.array([[0,100,101,99,100,10,999], [1000,100,102,99,101,10,1999],
                         [2000,104,106,103,105,10,2999], [3000,110,111,109,110,10,3999]], float)
        row = dict(group='crypto', asset='X', coverage=True, known_at=500, entry_at=1000,
                   side=1, stop=90, target=None, max_bars=2, fraction=1., capacity=100000)
        filters = {'X':dict(tick=.01, step=.01, min_qty=.01, min_notional=5.)}
        events = [dict(fundingTime=1500, fundingRate='.001', markPrice='100'),
                  dict(fundingTime=3000, fundingRate='.001', markPrice='110')]
        reference = replay_asset(bars, [row], events, initial=10000, rules=execution_rules(filters, 'crypto', 'X', 1))['trades'][0]
        independent_opportunities([row], {'crypto':{'X':bars}}, {'X_funding':events}, filters)
        self.assertAlmostEqual(row['standalone']['net_pnl'], reference['net_pnl'])
        self.assertAlmostEqual(row['standalone']['funding'], reference['funding'])
        self.assertNotEqual(reference['funding'], 0.)

    def test_exposure_comparison_is_explicit_log_return_diagnostic(self):
        times = np.array(['2024-01-01', '2024-04-01', '2024-07-01', '2024-10-01'], dtype='datetime64[ms]').astype('int64')
        logs = np.cumsum([.02, -.01, .03, -.02])
        def run(policy, exposure):
            return dict(group='crypto', policy=policy, summary=dict(average_exposure=exposure, yearly_returns={'2024':0.}))
        a = run('model70', .1), times, 10000*np.exp(logs*.5)
        b = run('rules_common', .2), times, 10000*np.exp(logs)
        result = portfolio_comparison(a, b, exposure_match=True)
        self.assertAlmostEqual(result['reference_scale'], .5)
        self.assertAlmostEqual(result['total_log_excess'], 0.)

    def test_matched_random_selects_exact_count_within_strata(self):
        rows = [dict(group='crypto', asset='X', strategy='range_rejection', known_at=1704067200000,
                     masks={'model70':True}, forecast_state='range', endpoint_actual='range',
                     standalone=dict(filled=True, net_R=v, net_notional=v*.01)) for v in [-1., .5]]
        result = selection_diagnostics(rows, 'crypto')
        self.assertEqual(result['selected_proposals'], 2)
        self.assertAlmostEqual(result['matched_random']['mean_net_R'], -.25)
        self.assertAlmostEqual(result['matched_random']['observed_minus_random_mean'], 0.)


if __name__ == '__main__': unittest.main()
