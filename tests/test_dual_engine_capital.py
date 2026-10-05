import copy
import datetime as dt
import unittest

from qount.research.dual_engine_capital import SHARES, capital_contributions, replay_capital, reset_capital, split_target
from qount.research.dual_engine_structural import replay_units


class CapitalTests(unittest.TestCase):
    def fixture(self):
        dates = [(dt.date(2021, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(24)]
        closes = {k: {d: 100. * (1 + r) ** i for i, d in enumerate(dates)} for k, r in [('X', .03), ('Y', -.01), ('GLD', .005), ('BIL', .0001)]}
        opens = {k: dict(v) for k, v in closes.items()}
        targets = {0: {'X': .2, 'GLD': .2, 'BIL': .6}, 4: {'X': .05, 'Y': .15, 'GLD': .2, 'BIL': .6},
                   7: {'X': .05, 'GLD': .2, 'BIL': .75}, 12: {'X': .2, 'GLD': .2, 'BIL': .6}, 18: {'X': .2, 'GLD': .2, 'BIL': .6}}
        return dates, closes, opens, targets

    def test_split_keeps_base_gold_and_funded_crisis_gold_separate(self):
        books = split_target({'X': .05, 'GLD': .35, 'BIL': .6})
        self.assertEqual(books['gold']['GLD'], 1.)
        self.assertAlmostEqual(books['equity_crisis']['GLD'], .75)
        self.assertAlmostEqual(books['equity_crisis']['X'], .25)
        self.assertTrue(all(abs(sum(v.values()) - 1) < 1e-12 for v in books.values()))
        with self.assertRaises(ValueError): split_target({'X': .3, 'GLD': .2, 'BIL': .5})

    def test_initial_warmup_cash_does_not_force_gold_purchase(self):
        books = split_target({'BIL': 1.})
        self.assertEqual(books['gold'], {'GLD': 0., 'BIL': 1.})
        self.assertEqual(books['equity_crisis'], {'BIL': 1.})

    def test_locked_books_never_transfer_capital_after_initialization(self):
        days, closes, opens, targets = self.fixture()
        run = replay_capital(days, closes, opens, targets, start=days[1], lag=1, cost_bps=40, full_refresh={0, 12, 18}, reset_monthly=False)
        self.assertTrue(all(abs(b['capital_transfer']) < 1e-12 for r in run['records'][1:] for b in r['books'].values()))
        self.assertNotAlmostEqual(run['records'][-1]['books']['equity_crisis']['nav'] / run['records'][-1]['nav'], .2, places=3)

    def test_protection_changes_do_not_touch_gold_or_reserve_units(self):
        days, closes, opens, targets = self.fixture()
        run = replay_capital(days, closes, opens, targets, start=days[1], lag=1, cost_bps=40, full_refresh={0, 12, 18}, reset_monthly=True)
        rows = {r['date']: r for r in run['records']}
        for name in ('gold', 'reserve'):
            self.assertEqual(rows[days[4]]['books'][name]['units'], rows[days[5]]['books'][name]['units'])
        self.assertEqual(rows[days[5]]['untouched_books_units_max_error'], 0)
        self.assertEqual(rows[days[7]]['books']['equity_crisis']['units']['X'], rows[days[8]]['books']['equity_crisis']['units']['X'])

    def test_monthly_reset_is_funded_and_matches_declared_open_shares(self):
        days, closes, opens, targets = self.fixture()
        run = replay_capital(days, closes, opens, targets, start=days[1], lag=1, cost_bps=40, full_refresh={0, 12, 18}, reset_monthly=True)
        for row in run['records']:
            self.assertAlmostEqual(sum(b['capital_transfer'] for b in row['books'].values()), 0., places=12)
            if row['capital_reset']:
                own = {b: v['cash'] + sum(q * opens[k][row['date']] for k, q in v['units'].items()) for b, v in row['books'].items()}
                for b, value in own.items(): self.assertAlmostEqual(value / sum(own.values()), SHARES[b], places=12)

    def test_opposite_book_trades_pay_gross_fees(self):
        books = {'equity_crisis': {'cash': 0., 'units': {'GLD': .2}}, 'gold': {'cash': 0., 'units': {'BIL': .2}}, 'reserve': {'cash': 0., 'units': {'BIL': .6}}}
        aims = {'equity_crisis': {'BIL': 1.}, 'gold': {'GLD': 1.}, 'reserve': {'BIL': 1.}}
        new, details = reset_capital(books, {'GLD': 1., 'BIL': 1.}, aims, 40)
        gross = sum(sum(d['traded_notional'].values()) for d in details.values())
        net = abs(new['gold']['units']['GLD'] - .2) + abs(sum(b['units'].get('BIL', 0.) for b in new.values()) - .8)
        self.assertGreater(gross, net + .5)
        self.assertAlmostEqual(sum(d['fee'] for d in details.values()), gross * .004, places=12)

    def test_every_event_reset_reproduces_aggregate_target_account(self):
        days, closes, opens, targets = self.fixture()
        # Distinct assets with no opposite source trades: full monthly source
        # budgets produce the same original aggregate cash/units and fees.
        targets = {0: {'X': .2, 'GLD': .2, 'BIL': .6}, 12: {'Y': .2, 'GLD': .2, 'BIL': .6}}
        a = replay_capital(days, closes, opens, targets, start=days[1], lag=1, cost_bps=0, full_refresh=set(targets), reset_monthly=True)
        b = replay_units(days, closes, opens, targets, start=days[1], lag=1, cost_bps=0, cash_asset='BIL')
        for x, y in zip(a['records'], b['records']): self.assertAlmostEqual(x['nav'], y['nav'], places=12)

    def test_asset_and_book_profits_exclude_internal_transfers(self):
        days, closes, opens, targets = self.fixture()
        for reset in (False, True):
            run = replay_capital(days, closes, opens, targets, start=days[1], lag=1, cost_bps=40, full_refresh={0, 12, 18}, reset_monthly=reset)
            a = capital_contributions(run, days, closes, opens)
            self.assertLess(a['max_error'], 1e-12)
            self.assertAlmostEqual(sum(v['net_pnl'] for v in a['assets'].values()), run['records'][-1]['nav'] - 1, places=12)
            self.assertAlmostEqual(sum(v['net_pnl'] for v in a['books'].values()), run['records'][-1]['nav'] - 1, places=12)
            self.assertAlmostEqual(sum(v['capital_transfers'] for v in a['books'].values()), 0., places=12)

    def test_future_prices_leave_book_history_prefix_unchanged(self):
        days, closes, opens, targets = self.fixture(); changed = copy.deepcopy(closes)
        for k in changed:
            for d in days[15:]: changed[k][d] *= 20
        kwargs = dict(start=days[1], lag=1, cost_bps=40, full_refresh={0, 12, 18}, reset_monthly=True)
        a = replay_capital(days, closes, opens, targets, **kwargs); b = replay_capital(days, changed, opens, targets, **kwargs)
        self.assertEqual(a['records'][:14], b['records'][:14])

    def test_missing_open_fails_before_book_trading(self):
        days, closes, opens, targets = self.fixture(); del opens['GLD'][days[1]]
        with self.assertRaisesRegex(ValueError, 'required_capital_open_missing'):
            replay_capital(days, closes, opens, targets, start=days[1], lag=1, cost_bps=40, full_refresh={0, 12, 18}, reset_monthly=True)
