import copy
import datetime as dt
import unittest

from qount.research.dual_engine_books import replay_books
from qount.research.dual_engine_intents import execute_reductions, reduction_intent, replay_intents, sync_vintages


class IntentTests(unittest.TestCase):
    def fixture(self):
        days = [(dt.date(2020, 12, 30) + dt.timedelta(days=i)).isoformat() for i in range(24)]
        closes = {k: {d: 100. * (1 + rate) ** i for i, d in enumerate(days)} for k, rate in [('X', .01), ('Y', -.005)]}
        opens = {k: dict(v) for k, v in closes.items()}
        targets = {i: {} if i < 2 else {'X': .6} for i in range(len(days))}
        return days, closes, opens, targets

    def test_stale_zero_account_plan_does_not_clear_later_purchase(self):
        days, closes, opens, targets = self.fixture()
        old = replay_books(days, closes, opens, targets, start=days[2], lag=2, cost_bps=50, weekly=True)
        new = replay_intents(days, closes, opens, targets, start=days[2], lag=2, cost_bps=50)
        a = {r['date']: r for r in old['records']}; b = {r['date']: r for r in new['records']}
        self.assertGreater(a['2021-01-05']['units']['X'], 0)
        self.assertNotIn('X', a['2021-01-06']['units'])
        self.assertEqual(b['2021-01-05']['units']['X'], b['2021-01-06']['units']['X'])
        self.assertTrue(b['2021-01-06']['version_mismatch'])

    def test_captured_sale_never_consumes_later_vintage(self):
        vintages = {'X': {1: 1., 2: 2.}}
        units, cash, fee, flow, requested, actual = execute_reductions(
            {'X': 3.}, vintages, {'X': {1: 2.}}, [], {'X': 10.}, 0., 50)
        self.assertEqual(units, {'X': 2.}); self.assertEqual(vintages, {'X': {2: 2.}})
        self.assertEqual(actual, {'X': 1.}); self.assertAlmostEqual(cash, 9.95)
        self.assertAlmostEqual(fee, .05)

    def test_overlapping_pending_sales_cannot_sell_new_purchase(self):
        vintages = {'X': {1: 1., 2: 2.}}; units = {'X': 3.}; cash = 0.
        for _ in range(2):
            units, cash, _, _, _, _ = execute_reductions(units, vintages, {'X': {1: 1.}}, [], {'X': 10.}, cash, 0)
        self.assertEqual(units, {'X': 2.}); self.assertEqual(cash, 10.)

    def test_nominal_zero_is_distinct_account_wide_risk_exit(self):
        sells, zeros = reduction_intent({}, {}, {}, {}, 1., pending_assets=('X',))
        self.assertEqual(sells, {}); self.assertEqual(zeros, ['X'])
        units, cash, _, _, _, _ = execute_reductions({'X': 2.}, {'X': {9: 2.}}, sells, zeros, {'X': 10.}, 0., 0)
        self.assertEqual(units, {}); self.assertEqual(cash, 20.)

    def test_full_fill_sync_preserves_position_vintages(self):
        vintages = {'X': {1: 1., 2: 2.}}
        sync_vintages(vintages, {'X': 3.}, {'X': 4.}, 3)
        self.assertEqual(vintages['X'], {1: 1., 2: 2., 3: 1.})
        sync_vintages(vintages, {'X': 4.}, {'X': 1.5}, 4)
        self.assertEqual(vintages['X'], {2: .5, 3: 1.})

    def test_cash_fee_and_unit_nav_reconcile(self):
        days, closes, opens, targets = self.fixture()
        run = replay_intents(days, closes, opens, targets, start=days[2], lag=2, cost_bps=50)
        old = {}; cash = nav = 1.
        for row in run['records']:
            day = row['date']; open_nav = cash + sum(q * opens[k][day] for k, q in old.items())
            flow = sum(abs(row['units'].get(k, 0.) - old.get(k, 0.)) * opens[k][day] for k in set(old) | set(row['units']))
            fee = flow * .005
            cash -= sum((row['units'].get(k, 0.) - old.get(k, 0.)) * opens[k][day] for k in set(old) | set(row['units'])) + fee
            self.assertAlmostEqual(cash, row['cash'], places=12)
            self.assertAlmostEqual(flow / open_nav, row['turnover'], places=12)
            self.assertAlmostEqual(cash + sum(q * closes[k][day] for k, q in row['units'].items()), row['nav'], places=12)
            self.assertAlmostEqual(nav * (1 + row['return']), row['nav'], places=12)
            old = row['units']; nav = row['nav']

    def test_latest_closed_target_controls_current_reductions(self):
        days, closes, opens, targets = self.fixture()
        targets[7] = {}  # The close before January 7, despite an older positive plan.
        run = replay_intents(days, closes, opens, targets, start=days[2], lag=2, cost_bps=50, mode='current')
        row = next(r for r in run['records'] if r['date'] == days[8])
        self.assertEqual(row['execution_risk']['date'], days[7]); self.assertEqual(row['units'], {})

    def test_stale_buy_cancellation_uses_only_closed_nominal_target(self):
        days, closes, opens, targets = self.fixture(); targets[5] = {}
        run = replay_intents(days, closes, opens, targets, start=days[2], lag=2, cost_bps=50, cancel_stale=True)
        row = next(r for r in run['records'] if r['date'] == '2021-01-05')
        self.assertEqual(row['cancelled_stale'], ['X']); self.assertEqual(row['units'], {})

    def test_core_weekly_keeps_new_core_and_allows_daily_satellite_buys(self):
        days, closes, opens, targets = self.fixture()
        targets = {i: {} if i < 2 else {'X': .5, 'Y': .2 if i < 6 else .3} for i in range(len(days))}
        run = replay_intents(days, closes, opens, targets, start=days[2], lag=2, cost_bps=50,
                             mode='core_weekly', core_assets=('X',))
        mixed = [r for r in run['records'] if r['trade_clock'] == 'mixed']
        self.assertTrue(any(r['risk_buy_notional'] > 0 for r in mixed))
        self.assertTrue(all(r['core_buy_notional'] < 1e-12 for r in mixed))
        rows = {r['date']: r for r in run['records']}
        self.assertGreater(rows['2021-01-06']['units']['X'], 0)

    def test_future_prices_and_targets_leave_prefix_unchanged(self):
        days, closes, opens, targets = self.fixture(); changed = copy.deepcopy(closes); future = copy.deepcopy(targets)
        for k in changed:
            for d in days[15:]: changed[k][d] *= 50
        for t in range(15, len(days)): future[t] = {'Y': .9}
        for mode in ('vintage', 'current', 'core_weekly'):
            a = replay_intents(days, closes, opens, targets, start=days[2], lag=2, cost_bps=50, mode=mode, core_assets=('X',))
            b = replay_intents(days, changed, opens, future, start=days[2], lag=2, cost_bps=50, mode=mode, core_assets=('X',))
            self.assertEqual(a['records'][:13], b['records'][:13])

    def test_covariance_scale_is_applied_to_original_decision(self):
        days, closes, opens, targets = self.fixture()
        run = replay_intents(days, closes, opens, targets, start=days[2], lag=2, cost_bps=50, risk_scale=lambda t, w: .5)
        sunday = next(p for p in run['decisions'] if p['decision'] == '2021-01-03')
        self.assertEqual(sunday['target'], {'X': .3}); self.assertEqual(sunday['risk_scale'], .5)

    def test_missing_required_open_fails_without_price_substitution(self):
        days, closes, opens, targets = self.fixture(); del opens['X']['2021-01-05']
        with self.assertRaisesRegex(ValueError, 'required_intent_open_missing'):
            replay_intents(days, closes, opens, targets, start=days[2], lag=2, cost_bps=50)

    def test_low_price_asset_large_units_keep_relative_ownership_reconciliation(self):
        vintages = {'X': {1: 10000000000.1, 2: 10000000000.2}}
        old = {'X': 20000000000.3}; new = {'X': 30000000000.4}
        sync_vintages(vintages, old, new, 3)
        units, cash, fee, flow, _, actual = execute_reductions(new, vintages, {'X': {1: 10000000000.1}}, [], {'X': .0000001}, 0., 50)
        self.assertAlmostEqual(actual['X'] / 10000000000.1, 1., places=12)
        self.assertAlmostEqual(units['X'] / 20000000000.3, 1., places=12)
        self.assertAlmostEqual(cash + fee, flow, places=12)
