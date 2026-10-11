import copy
import math
import unittest
from array import array

from tests.test_ashare_strategy import series
from qount.research.ashare_strategy import Position, make_features
from qount.research.ashare_leader import (
    LeaderBook, RULES, exit_state, make_leader_features, select, trend_breakout,
)


def rising(n=300, rate=.002):
    s = series(n)
    for j in range(n):
        value = 10*math.exp(j*rate)
        for key in ('adj_close', 'raw_close', 'raw_open', 'pre_close', 'adj_open'):
            getattr(s, key)[j] = value
    return s


def selection_fixture(groups, n=300):
    s = rising(n)
    base = make_features(s)
    extra = make_leader_features(s, base)
    panel, features, extras, meta = {}, {}, {}, {}
    for industry, count in groups:
        for i in range(count):
            code = f'{industry or "U"}{i:02}'
            panel[code] = copy.deepcopy(s)
            features[code] = copy.deepcopy(base)
            extras[code] = copy.deepcopy(extra)
            meta[code] = {'industry': industry}
    return panel, features, extras, meta


def position(basis=10, peak=10, j=0):
    return Position(100, j, basis*100, peak, 10, j, j)


def blank_selection():
    return {'market_on': False, 'sector_rank': [], 'price_rank': []}


class LeaderFeatureTests(unittest.TestCase):
    def test_exact_windows_and_excluding_current_breakout(self):
        s = rising()
        f = make_features(s)
        extra = make_leader_features(s, f)
        j = 299
        self.assertAlmostEqual(extra.ma20[j], sum(s.adj_close[280:300])/20)
        self.assertAlmostEqual(extra.ma60_lag20[j], sum(s.adj_close[220:280])/60)
        self.assertAlmostEqual(extra.return63[j], s.adj_close[j]/s.adj_close[j-63]-1)
        self.assertEqual(extra.prior20_high[j], max(s.adj_close[279:299]))
        self.assertLess(extra.prior20_high[j], s.adj_close[j])
        self.assertTrue(trend_breakout(j, 'X', {'X': s}, {'X': f}, {'X': extra}))

    def test_breakout_equals_previous_high_is_not_new_breakout(self):
        s = rising()
        s.adj_close[-1] = s.adj_close[-2]
        f = make_features(s)
        x = make_leader_features(s, f)
        self.assertFalse(trend_breakout(299, 'X', {'X': s}, {'X': f}, {'X': x}))

    def test_prior_high_expires_on_exact_exchange_clock(self):
        s = rising()
        s.adj_close[278] = 999
        x = make_leader_features(s)
        self.assertEqual(x.prior20_high[298], 999)
        self.assertEqual(x.prior20_high[299], s.adj_close[298])

    def test_missing_close_no_compression(self):
        s = rising()
        s.valid[290] = 0
        x = make_leader_features(s)
        self.assertTrue(math.isnan(x.ma20[-1]))
        self.assertTrue(math.isnan(x.prior20_high[-1]))
        self.assertTrue(math.isnan(x.return63[-1]))
        self.assertFalse(make_features(s).eligible[-1])

    def test_missing_old_close_only_affects_its_exact_windows(self):
        s = rising()
        s.valid[250] = 0
        x = make_leader_features(s)
        self.assertTrue(math.isfinite(x.ma20[-1]))
        self.assertTrue(math.isfinite(x.prior20_high[-1]))
        self.assertTrue(math.isnan(x.return63[-1]))

    def test_future_price_cannot_change_past_features(self):
        s = rising()
        a = make_leader_features(s)
        s.adj_close[-1] = 1e9
        b = make_leader_features(s)
        for field in ('ma20', 'ma60_lag20', 'return63', 'prior20_high'):
            self.assertEqual(getattr(a, field)[290], getattr(b, field)[290])

    def test_new_features_do_not_bypass_source_maturity(self):
        s = rising()
        s.history[-1] = 251
        f = make_features(s)
        x = make_leader_features(s, f)
        self.assertTrue(math.isfinite(x.return63[-1]))
        selected = select(299, {'X': s}, {'X': f}, {'X': x}, {'X': {'industry': 'A'}})
        self.assertEqual(selected['eligible_count'], 0)


class LeaderSelectionTests(unittest.TestCase):
    def test_floor_return_quintile_and_ceil_liquidity_half_intersect(self):
        panel, fs, xs, meta = selection_fixture([('A', 11)])
        for i, c in enumerate(panel):
            xs[c].return63[-1] = 1-i*.01
            fs[c].adv20[-1] = 1e8 if i else 1e7
        result = select(299, panel, fs, xs, meta)
        # Only A00,A01 are return-quintile leaders; A00 is outside liquid half.
        self.assertEqual(result['sector_rank'], ['A01'])
        self.assertEqual(len(result['price_rank']), 11)

    def test_top_return_fraction_uses_all_eligible_before_trend(self):
        panel, fs, xs, meta = selection_fixture([('A', 10)])
        xs['A00'].return63[-1] = .9
        xs['A01'].return63[-1] = .8
        xs['A02'].return63[-1] = .7
        xs['A00'].prior20_high[-1] = 1e6
        xs['A01'].prior20_high[-1] = 1e6
        result = select(299, panel, fs, xs, meta)
        self.assertEqual(result['sector_rank'], [])
        self.assertIn('A02', result['price_rank'])

    def test_member_minimum_and_breadth_gate(self):
        panel, fs, xs, meta = selection_fixture([('A', 9), ('B', 10)])
        for i in range(5):
            fs[f'B{i:02}'].ma60[-1] = 1e6
        result = select(299, panel, fs, xs, meta)
        self.assertEqual(result['selected_sectors'], [])
        fs['B04'].ma60[-1] = 1
        result = select(299, panel, fs, xs, meta)
        self.assertEqual(result['selected_sectors'], ['B'])

    def test_sector_lexical_ties_and_top5(self):
        panel, fs, xs, meta = selection_fixture([(c, 10) for c in reversed('ABCDEFG')])
        result = select(299, panel, fs, xs, meta)
        self.assertEqual(result['selected_sectors'], list('ABCDE'))
        self.assertEqual(result['sector_rank'][:2], ['A00', 'A01'])
        self.assertEqual(len(result['sector_rank']), 10)

    def test_unknown_shared_group_retired_not_removed_and_cap1(self):
        panel, fs, xs, meta = selection_fixture([(None, 10)])
        for c in panel:
            panel[c].source_kind = 'tushare_retired'
            meta[c].update(list_status='D', name='*STunknown')
        meta['U00'].pop('industry')
        result = select(299, panel, fs, xs, meta)
        self.assertEqual(result['sector_rank'], ['U00'])
        self.assertEqual(result['selected_sectors'], ['__unclassified__'])
        self.assertEqual(result['eligible_retired'], 10)
        self.assertEqual(len(result['price_rank']), 10)

    def test_sector_median_positive_not_one_outlier(self):
        panel, fs, xs, meta = selection_fixture([('A', 10)])
        for i in range(6):
            xs[f'A{i:02}'].return63[-1] = -.1
        self.assertEqual(select(299, panel, fs, xs, meta)['selected_sectors'], [])

    def test_sector_ranking_then_global_return_ADV_symbol(self):
        panel, fs, xs, meta = selection_fixture([('A', 10), ('B', 10)])
        xs['B00'].return63[-1] = .8
        xs['A00'].return63[-1] = .8
        fs['B00'].adv20[-1] = 2e8
        result = select(299, panel, fs, xs, meta)
        self.assertEqual(result['sector_rank'][:2], ['B00', 'A00'])

    def test_real_estate_cluster_cap2_in_selection(self):
        panel, fs, xs, meta = selection_fixture([('房产服务', 10), ('全国地产', 10)])
        result = select(299, panel, fs, xs, meta)
        self.assertEqual(len(result['sector_rank']), 2)


class LeaderExitTests(unittest.TestCase):
    def test_cost_basis_is_all_in_and_initial_close_stop_inclusive(self):
        p = position(basis=10.05)
        x = exit_state(p, 10.05*.93, 1, 1)
        self.assertAlmostEqual(x['entry_adjusted_basis'], 10.05)
        self.assertAlmostEqual(x['initial_stop7_level'], 9.3465)
        self.assertEqual(x['reason'], 'initial_stop7')
        self.assertIsNone(exit_state(p, 9.347, 1, 1)['reason'])

    def test_trail8_activates_from_persisted_peak_not_current_profit(self):
        p = position(10, 11.5)
        x = exit_state(p, 11.5*.92, 1, 1)
        self.assertEqual(x['reason'], 'profit_trail8')
        self.assertEqual(x['trailing_stage_pct'], 8)
        self.assertIsNone(exit_state(position(10, 11.49), 10.5, 1, 1)['reason'])

    def test_tight_trail5_takes_precedence_after_peak30pct(self):
        p = position(10, 13)
        x = exit_state(p, 12.34, 13, 200)
        self.assertEqual(x['reason'], 'profit_trail5')
        self.assertEqual(x['profit_trail_level'], 12.35)
        self.assertEqual(exit_state(p, 9, 13, 200)['reason'], 'initial_stop7')

    def test_MA20_strict_threshold_then_age126(self):
        p = position()
        self.assertEqual(exit_state(p, 10, 10.1, 126)['reason'], 'below_MA20')
        self.assertEqual(exit_state(p, 10, 10, 126)['reason'], 'age126')
        self.assertIsNone(exit_state(p, 10, 10, 125)['reason'])
        self.assertEqual(exit_state(p, math.nan, math.nan, 126)['reason'], 'age126')

    def test_peak_is_post_entry_valid_close_and_never_high(self):
        s = rising()
        b = LeaderBook('sector_base', {})
        b.positions['X'] = position(10, 10)
        s.adj_close[1] = 11.5
        s.raw_high[1] = 1e6
        b.mark(1, '20260101', {'X': s})
        self.assertEqual(b.positions['X'].peak, 11.5)
        s.adj_close[2] = 1e6
        s.valid[2] = 0
        b.mark(2, '20260102', {'X': s})
        self.assertEqual(b.positions['X'].peak, 11.5)

    def test_stop_next_open_fills_gap_price_not_threshold(self):
        s = series()
        f, extra = make_features(s), make_leader_features(s)
        s.adj_close[1] = 9.2
        f.adv20[1] = 1e8
        b = LeaderBook('sector_base', {})
        b.positions['X'] = position()
        b.decisions(1, '20260101', {'X': s}, {'X': f}, {'X': extra}, blank_selection(), 279)
        self.assertEqual(b.pending[0]['reason'], 'initial_stop7')
        self.assertEqual(b.pending[0]['due_j'], 2)
        self.assertEqual(b.trades, [])
        s.raw_open[2] = s.pre_close[2] = s.adj_open[2] = 8
        b.execute(2, '20260102', {'X': s})
        self.assertAlmostEqual(b.trades[0]['raw_price_with_slippage'], 7.992)
        self.assertLess(b.closed[0]['net_trade_return'], -.20)

    def test_hold_despite_ranking_loss_and_no_same_review_rebuy(self):
        s = series()
        f, extra = make_features(s), make_leader_features(s)
        b = LeaderBook('sector_base', {'X': {'industry': 'A'}})
        b.positions['X'] = position()
        b.decisions(1, '20260101', {'X': s}, {'X': f}, {'X': extra}, blank_selection(), 279)
        self.assertEqual(b.pending, [])
        s.adj_close[2] = 9
        b.decisions(2, '20260102', {'X': s}, {'X': f}, {'X': extra},
                    {'market_on': True, 'sector_rank': ['X']}, 279)
        self.assertEqual([i['side'] for i in b.pending], ['sell'])


class LeaderPortfolioTests(unittest.TestCase):
    def test_12pct_trigger_cancels_delayed_buys(self):
        b = LeaderBook('sector_extra_day', {})
        b.plan(1, 'X', 'buy', 'test', raw_shares=100, budget_cny=1000, adv20=1e8)
        b.cash = 880000
        b.decisions(2, '20260101', {}, {}, {}, {'market_on': True, 'sector_rank': ['X']}, 300)
        self.assertEqual(b.pending, [])
        self.assertEqual(b.pending_buys, set())
        self.assertEqual(b.cooldown_until, 22)
        self.assertEqual(b.blocks['risk_cancelled_pending_buy'], 1)
        self.assertEqual(b.risk_events[0]['anchor_peak'], 1_000_000)

    def test_circuit_overrides_stock_reason_and_waits_complete_exit(self):
        s = series()
        f, extra = make_features(s), make_leader_features(s)
        b = LeaderBook('sector_base', {})
        b.cash = 870000
        b.positions['X'] = position(10, 13)
        s.adj_close[1] = 8
        b.decisions(1, '20260101', {'X': s}, {'X': f}, {'X': extra}, blank_selection(), 279)
        self.assertEqual(b.pending[0]['reason'], 'portfolio_drawdown12')
        s.raw_open[2] = 9
        b.execute(2, '20260102', {'X': s})
        self.assertIn('X', b.pending_sells)
        b.decisions(22, '20260202', {'X': s}, {'X': f}, {'X': extra}, blank_selection(), 279)
        self.assertEqual(b.cooldown_until, 21)
        self.assertEqual(len(b.pending), 1)

    def test_full20sessions_before_reset_anchor(self):
        b = LeaderBook('sector_base', {})
        b.cash = 880000
        b.decisions(1, '20260101', {}, {}, {}, blank_selection(), 300)
        b.decisions(20, '20260130', {}, {}, {}, blank_selection(), 300)
        self.assertEqual(b.cooldown_until, 21)
        b.decisions(21, '20260201', {}, {}, {}, blank_selection(), 300)
        self.assertEqual(b.cooldown_until, -1)
        self.assertEqual(b.anchor_peak, 880000)
        self.assertEqual(len(b.risk_events), 1)

    def test_execution_hard_caps_unknown_and_real_estate(self):
        b = LeaderBook('sector_base', {'U': {}, '房': {'industry': '房产服务'}, '国': {'industry': '全国地产'},
                                      '区': {'industry': '区域地产'}})
        b.positions['X'] = position()
        self.assertFalse(b.slots_allow('U'))
        b.positions = {'房': position(), '国': position()}
        self.assertFalse(b.slots_allow('区'))
        control = LeaderBook('price_control', b.metadata)
        control.positions = dict(b.positions)
        self.assertTrue(control.slots_allow('区'))
        control.positions = {str(i): position() for i in range(8)}
        self.assertFalse(control.slots_allow('区'))

    def test_fill_execution_rechecks_unknown_and_cluster_caps(self):
        s = series()
        for meta, held, target in [
            ({}, ['U'], 'X'),
            ({'R': {'industry': '房产服务'}, 'D': {'industry': '全国地产'},
              'X': {'industry': '区域地产'}}, ['R', 'D'], 'X'),
        ]:
            b = LeaderBook('sector_base', meta)
            b.positions = {c: position() for c in held}
            b.plan(0, target, 'buy', 'test', raw_shares=100, budget_cny=10000, adv20=1e8)
            b.execute(1, '20260101', {target: s})
            self.assertNotIn(target, b.positions)
            self.assertEqual(b.blocks['slot_or_exposure_cap'], 1)

    def test_eight_slot_reservation_and_signal_budget(self):
        panel, fs, extra, meta = selection_fixture([(c, 1) for c in 'ABCDEFGHIJ'])
        b = LeaderBook('sector_base', meta)
        rank = list(panel)
        b.decisions(299, '20260101', panel, fs, extra, {'market_on': True, 'sector_rank': rank}, 400)
        self.assertEqual(len(b.pending_buys), 8)
        for intent in b.pending:
            self.assertAlmostEqual(intent['budget_cny'], 1_000_000*.0075/.07)
            self.assertEqual(intent['raw_shares'] % 100, 0)
            self.assertLessEqual(intent['raw_shares']*panel[intent['symbol']].raw_close[299], intent['budget_cny'])
        self.assertAlmostEqual(RULES['new_entry_fraction'], .10714285714285714)

    def test_delayed_pending_buys_reserve_remaining_slots_and_industries(self):
        panel, fs, extra, meta = selection_fixture([(c, 1) for c in 'ABCDEFGHIJ'])
        b = LeaderBook('sector_extra_day', meta)
        for code in list(panel)[:7]:
            b.plan(297, code, 'buy', 'test', raw_shares=100, budget_cny=1000, adv20=1e8)
        b.decisions(298, '20260101', panel, fs, extra, {'market_on': True, 'sector_rank': list(panel)}, 400)
        self.assertEqual(len(b.pending_buys), 8)
        b.decisions(299, '20260102', panel, fs, extra, {'market_on': True, 'sector_rank': list(panel)}, 400)
        self.assertEqual(len(b.pending_buys), 8)
        # Actual fill still rejects the ninth buy even if its intent was externally malformed.
        b.positions = {str(i): position() for i in range(8)}
        b.pending = []
        b.pending_buys.clear()
        b.plan(298, 'J00', 'buy', 'test', raw_shares=100, budget_cny=10000, adv20=1e8)
        b.execute(300, '20260103', panel)
        self.assertEqual(len(b.positions), 8)
        self.assertEqual(b.blocks['slot_or_exposure_cap'], 1)

    def test_unknown_and_cluster_caps_apply_to_pending_reservations(self):
        panel, fs, extra, meta = selection_fixture([(None, 3), ('房产服务', 3), ('全国地产', 3)])
        b = LeaderBook('sector_extra_day', meta)
        b.plan(297, 'U00', 'buy', 'test', raw_shares=100, budget_cny=1000, adv20=1e8)
        b.plan(297, '房产服务00', 'buy', 'test', raw_shares=100, budget_cny=1000, adv20=1e8)
        b.decisions(298, '20260101', panel, fs, extra, {'market_on': True, 'sector_rank': list(panel)}, 400)
        self.assertEqual(sum(c.startswith('U') for c in b.pending_buys), 1)
        self.assertEqual(sum(not c.startswith('U') for c in b.pending_buys), 2)


if __name__ == '__main__':
    unittest.main()
