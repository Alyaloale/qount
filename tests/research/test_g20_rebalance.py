"""Close-time decisions, mandatory sector switches and next-open gap consequences."""
import copy
from functools import partial
from pathlib import Path
import sys
import unittest

from qount.research.g20_rebalance import rebalance_decision, MODES
from qount.research.g20_cash_execution import CashFriction
from qount.research.dual_engine_optimization import EquityPanel

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/research'))
from compare_g20_long_cash import simulate, SYMBOLS


class G20RebalanceTests(unittest.TestCase):
    def decide(self, *, held=20., cash=800., price=10., target=.2, mode='risk_units', previous='SOXL'):
        return rebalance_decision(target={'SOXL': target, 'BIL': 1-target},
            positions={'SOXL': held}, cash=cash, prices={'SOXL': price}, previous_symbol=previous, mode=mode)

    def test_unchanged_integer_risk_units_skip_bill_only_rebalance(self):
        r = self.decide(cash=805., target=.2)
        self.assertFalse(r['execute'])
        self.assertEqual(r['reason'], 'risk_units_unchanged')

    def test_initial_and_sector_change_always_pass(self):
        for mode in MODES:
            self.assertTrue(self.decide(mode=mode, previous=None)['execute'])
            self.assertEqual(self.decide(mode=mode, previous='CURE')['reason'], 'sector_change')
            r = rebalance_decision(target={'SOXL': .2, 'BIL': .8}, positions={'ERX': .1, 'SOXL': 20.},
                cash=799., prices={'ERX': 10., 'SOXL': 10.}, previous_symbol='SOXL', mode=mode)
            self.assertEqual(r['reason'], 'sector_change')

    def test_add_band_executes_feasible_small_risk_reduction(self):
        r = self.decide(target=.195, mode='add_band')
        self.assertTrue(r['execute'])
        self.assertEqual(r['reason'], 'risk_reduction')
        self.assertFalse(self.decide(target=.195, mode='symmetric_band')['execute'])

    def test_small_increase_deferred_and_large_increase_passed(self):
        self.assertFalse(self.decide(held=190., cash=810., price=1., target=.195, mode='add_band')['execute'])
        self.assertTrue(self.decide(held=150., cash=850., price=1., mode='add_band')['execute'])
        self.assertTrue(self.decide(held=190., cash=810., price=1., target=.195, mode='risk_units')['execute'])

    def test_rejects_invalid_prices_and_modes(self):
        for kwargs in ({'price': float('nan')}, {'price': 0.}, {'cash': -1.}, {'mode': 'unknown'}):
            with self.assertRaises(ValueError):
                self.decide(**kwargs)

    def test_band_is_absolute_capital_weight_and_explicit(self):
        kwargs = dict(target={'SOXL': .19, 'BIL': .81}, positions={'SOXL': 20.}, cash=800.,
                      prices={'SOXL': 10.}, previous_symbol='SOXL', mode='symmetric_band')
        self.assertTrue(rebalance_decision(**kwargs, band=.005)['execute'])
        self.assertFalse(rebalance_decision(**kwargs, band=.02)['execute'])

    def test_decision_does_not_mutate_inputs(self):
        kwargs = dict(target={'SOXL': .2, 'BIL': .8}, positions={'SOXL': 20.}, cash=800.,
                      prices={'SOXL': 10.}, previous_symbol='SOXL', mode='add_band')
        old = copy.deepcopy(kwargs)
        rebalance_decision(**kwargs)
        self.assertEqual(kwargs, old)

    def fixture(self):
        dates = ('2025-12-31', '2026-01-02', '2026-01-05', '2026-01-06')
        panel = EquityPanel(dates, {}, {}, {})
        prices = {s: {d: dict(open=10., close=10.) for d in dates} for s in SYMBOLS}
        targets = {0: {'SOXL': .2, 'BIL': .8}, 1: {'SOXL': .2, 'BIL': .8}}
        return panel, prices, targets

    def replay(self, p, prices, targets, *, filtered=True):
        return simulate(p, prices, {}, targets, capital=1000., friction=CashFriction(), delay=1,
            start='2026-01-02', decision_filter=partial(rebalance_decision, mode='risk_units') if filtered else None)

    def test_future_open_and_close_cannot_change_prior_close_decision(self):
        p, prices, targets = self.fixture()
        a = self.replay(p, prices, targets)
        changed = copy.deepcopy(prices)
        changed['SOXL']['2026-01-05'] = dict(open=9., close=9.)
        b = self.replay(p, changed, targets)
        self.assertEqual(a['decisions'][0], b['decisions'][0])
        self.assertEqual(a['records'][0], b['records'][0])

    def test_close_quantity_equality_does_not_guarantee_same_next_open_quantity(self):
        p, prices, targets = self.fixture()
        prices['SOXL']['2026-01-05'] = dict(open=9., close=9.)
        filtered = self.replay(p, prices, targets)
        full = self.replay(p, prices, targets, filtered=False)
        self.assertFalse(filtered['decisions'][0]['execute'])
        q = lambda r: next(v['quantity'] for v in r['records'][1]['positions'] if v['symbol'] == 'SOXL')
        self.assertGreater(q(full), q(filtered))
        self.assertFalse(any(t['date'] == '2026-01-05' for t in filtered['trades']))

    def test_skipped_plan_does_not_block_later_sector_switch(self):
        p, prices, targets = self.fixture()
        targets[2] = {'ERX': .2, 'BIL': .8}
        r = self.replay(p, prices, targets)
        self.assertEqual(r['decisions'][0]['reason'], 'risk_units_unchanged')
        self.assertEqual(r['decisions'][1]['reason'], 'sector_change')
        self.assertTrue(any(t['date'] == '2026-01-06' and t['symbol'] == 'ERX' for t in r['trades']))

    def test_default_replay_retains_all_cash_target_support(self):
        p, prices, targets = self.fixture()
        r = self.replay(p, prices, {0: {'BIL': 1.}}, filtered=False)
        self.assertFalse(any(v['symbol'] != 'BIL' for v in r['records'][-1]['positions']))


if __name__ == '__main__':
    unittest.main()
