import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from qount.research.dual_engine_recovery import replay_recovery
from qount.research.dual_engine_redistribution import replay_redistribution, allocate_capital
from qount.research.dual_engine_capital import capital_contributions
from qount.research.dual_engine_renewal import read_contract


class RecoveryTests(unittest.TestCase):
    def fixture(self):
        days = [(dt.date(2021, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(24)]
        prices = {k: {d: 100. for d in days} for k in ('X', 'Y')}
        targets = {t: {'X': .5, **({'Y': .3} if t >= 5 else {})} for t in range(len(days))}
        return days, prices, targets

    def run_fixture(self, policy, lag=1, targets=None, prices=None):
        days, original, aims = self.fixture()
        return replay_recovery(days, prices or original, original, targets or aims,
                               start=days[2], lag=lag, cost_bps=50,
                               event_policy=policy, core_assets=('X',))

    def test_off_week_recovery_fills_after_declared_delay(self):
        days, _, _ = self.fixture()
        for lag in (1, 2):
            run = self.run_fixture('all', lag)
            decision = next(p for p in run['decisions'] if p['decision'] == days[5])
            self.assertEqual(decision['recovered_assets'], ['Y'])
            self.assertEqual(decision['kind'], 'full')
            row = next(r for r in run['records'] if r['date'] == days[5 + lag])
            self.assertGreater(row['units']['Y'], 0.)
            self.assertEqual(row['signal_date'], days[5])

    def test_core_transition_policy_does_not_trigger_for_satellite(self):
        run = self.run_fixture('core')
        p = next(p for p in run['decisions'] if p['decision'] == '2021-01-06')
        self.assertEqual(p['kind'], 'reduce')
        self.assertEqual(p['recovered_assets'], [])

    def test_staged_entry_halves_only_recovered_asset_then_refills(self):
        run = self.run_fixture('staged')
        plans = {p['decision']: p for p in run['decisions']}
        self.assertEqual(plans['2021-01-06']['target'], {'X': .5, 'Y': .15})
        self.assertEqual(plans['2021-01-07']['target'], {'X': .5, 'Y': .3})
        self.assertEqual(plans['2021-01-07']['continuing_assets'], ['Y'])

    def test_scoped_recovery_freezes_other_units_and_is_cash_funded(self):
        run = self.run_fixture('scoped')
        row = next(r for r in run['records'] if r['date'] == '2021-01-07')
        prior = next(r for r in run['records'] if r['date'] == '2021-01-06')
        self.assertEqual(row['trade_clock'], 'recover')
        self.assertEqual(row['units']['X'], prior['units']['X'])
        self.assertGreater(row['units']['Y'], 0)
        self.assertGreaterEqual(row['cash'], 0)

    def test_delayed_recovery_cancelled_when_latest_closed_gate_zero(self):
        days, _, targets = self.fixture()
        targets[6] = {'X': .5}
        for policy in ('all', 'staged', 'scoped'):
            row = next(r for r in self.run_fixture(policy, 2, targets)['records'] if r['date'] == days[7])
            self.assertIn('Y', row['cancelled_stale'])
            self.assertNotIn('Y', row['units'])

    def test_future_inputs_cannot_change_account_prefix(self):
        days, prices, targets = self.fixture()
        changed = copy.deepcopy(prices); future = copy.deepcopy(targets)
        for d in days[15:]: changed['X'][d] *= 20
        for t in range(15, len(days)): future[t] = {'Y': .8}
        for policy in ('all', 'core', 'staged', 'scoped'):
            a = self.run_fixture(policy, 2)
            b = self.run_fixture(policy, 2, future, changed)
            self.assertEqual(a['records'][:13], b['records'][:13])

    def test_cash_units_and_actual_fee_conserve_wealth(self):
        days, prices, _ = self.fixture()
        for policy in ('all', 'core', 'staged', 'scoped'):
            cash = nav = 1.; units = {}
            for row in self.run_fixture(policy, 2)['records']:
                day = row['date']
                flow = sum(abs(row['units'].get(k, 0) - units.get(k, 0)) * prices[k][day]
                           for k in set(units) | set(row['units']))
                cash -= sum((row['units'].get(k, 0) - units.get(k, 0)) * prices[k][day]
                            for k in set(units) | set(row['units'])) + flow * .005
                self.assertAlmostEqual(row['cash'], cash, places=12)
                self.assertAlmostEqual(row['nav'], cash + sum(q * prices[k][day] for k, q in row['units'].items()), places=12)
                self.assertAlmostEqual(nav * (1 + row['return']), row['nav'], places=12)
                units = row['units']; nav = row['nav']


class RedistributionTests(unittest.TestCase):
    def test_delayed_monthly_signal_in_warmup_has_all_cash_snapshot(self):
        days, prices, aims = self.fixture()
        aims[1] = dict(aims[0])
        for policy in ('sweep20', 'cap40', 'active20'):
            run = replay_redistribution(days, prices, prices, aims, start=days[2], lag=2,
                                       cost_bps=40, full_refresh=set(aims), policy=policy)
            row = next(r for r in run['records'] if r['date'] == days[3])
            allocation = row['capital_allocation']
            self.assertTrue(allocation['warmup'])
            self.assertEqual(allocation['decision_date'], days[1])
            self.assertEqual(allocation['closed_book_nav'], {'equity_crisis': .2, 'gold': .2, 'reserve': .6})
            self.assertEqual(allocation['closed_nav'], 1.)
            self.assertLess(capital_contributions(run, days, prices, prices)['max_error'], 1e-10)

    def fixture(self):
        days = [(dt.date(2021, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(24)]
        prices = {k: {d: 100. * (1 + r) ** i for i, d in enumerate(days)}
                  for k, r in [('X', .1), ('GLD', -.01), ('BIL', .0001)]}
        aims = {0: {'X': .2, 'GLD': .2, 'BIL': .6},
                12: {'X': .2, 'GLD': .2, 'BIL': .6}, 18: {'GLD': .2, 'BIL': .8}}
        return days, prices, aims

    def test_allocations_use_original_closed_signal_not_fill_day(self):
        days, prices, aims = self.fixture()
        for policy in ('sweep20', 'cap40', 'active20'):
            run = replay_redistribution(days, prices, prices, aims, start=days[2], lag=2,
                                       cost_bps=40, full_refresh=set(aims), policy=policy)
            rows = {r['date']: r for r in run['records']}
            allocation = rows[days[14]]['capital_allocation']
            self.assertEqual(allocation['decision_date'], days[12])
            self.assertEqual(allocation['closed_nav'], rows[days[12]]['nav'])
            self.assertAlmostEqual(sum(allocation['shares'].values()), 1.)
            for r in run['records']:
                self.assertAlmostEqual(sum(b['capital_transfer'] for b in r['books'].values()), 0., places=12)
            self.assertLess(capital_contributions(run, days, prices, prices)['max_error'], 1e-10)

    def test_profit_sweep_does_not_replenish_losing_book(self):
        days, prices, aims = self.fixture()
        run = replay_redistribution(days, prices, prices, aims, start=days[2], lag=2,
                                   cost_bps=40, full_refresh=set(aims), policy='sweep20')
        shares = run['allocation_decisions'][12]['shares']
        self.assertEqual(shares['equity_crisis'], .2)
        self.assertLess(shares['gold'], .2)

    def test_activation_releases_dormant_budget_into_reserve(self):
        days, prices, aims = self.fixture()
        run = replay_redistribution(days, prices, prices, aims, start=days[2], lag=2,
                                   cost_bps=40, full_refresh=set(aims), policy='active20')
        self.assertEqual(run['allocation_decisions'][18]['shares'],
                         {'equity_crisis': 0., 'gold': .2, 'reserve': .8})

    def test_future_marks_leave_prior_capital_decisions_identical(self):
        days, prices, aims = self.fixture(); future = copy.deepcopy(prices)
        for d in days[15:]: future['X'][d] *= 50
        for policy in ('sweep20', 'cap40', 'active20'):
            args = dict(start=days[2], lag=2, cost_bps=40, full_refresh=set(aims), policy=policy)
            a = replay_redistribution(days, prices, prices, aims, **args)
            b = replay_redistribution(days, future, prices, aims, **args)
            self.assertEqual(a['records'][:13], b['records'][:13])

    def test_unfunded_allocation_rejected(self):
        with self.assertRaisesRegex(ValueError, 'capital_allocation_unfunded'):
            allocate_capital({}, {}, {}, 40, {'equity_crisis': .5, 'gold': .5, 'reserve': .5})


class RenewalContractTests(unittest.TestCase):
    def test_every_candidate_integrates_original_sources_and_accounting(self):
        from qount.research import dual_engine_renewal as r
        from test_dual_engine_regimes import panel_fixture, assets_fixture
        c = read_contract(Path('config/dual-engine-renewal-20261005.json'))
        panel = panel_fixture(); rates = {k: [0.] * len(panel.dates) for k in ('DFII10', 'T10YIE')}
        closes = {k: dict(zip(panel.dates, v)) for k, v in panel.total_closes.items()}
        opens = {k: dict(zip(panel.dates, v)) for k, v in panel.total_opens.items()}
        settings = {**c['g20'], 'start': panel.dates[160]}
        for rule, source in r.G20_SOURCES.items():
            targets, members = r.equity_targets(panel, settings, rule, rates)
            self.assertEqual((targets, members), r.ninth.equity_targets(panel, settings, source, rates))
            run = r.candidate_replay('g20', rule, panel.dates, closes, opens, targets,
                                    settings=settings, delay=2, cost=40, panel=panel)
            self.assertLess(capital_contributions(run, panel.dates, closes, opens)['max_error'], 1e-10)
        axis, assets = assets_fixture()
        raw_opens = {a.symbol: dict(zip(axis.dates[a.start:a.start + len(a.closes)], a.closes)) for a in assets.values()}
        closes, opens = r.base.crypto_prices(axis, assets, raw_opens)
        settings = {**c['c60'], 'start': axis.dates[365]}
        for rule, source in r.C60_SOURCES.items():
            targets, members = r.crypto_targets(axis, assets, settings, rule)
            self.assertEqual((targets, members), r.ninth.crypto_targets(axis, assets, settings, source))
            run = r.candidate_replay('c60', rule, axis.dates, closes, opens, targets,
                                    settings=settings, delay=1, cost=50, assets=assets)
            self.assertTrue(all(row['cash'] >= -1e-10 for row in run['records']))

    def test_contract_and_mechanism_changes_fail_closed(self):
        c = read_contract(Path('config/dual-engine-renewal-20261005.json'))
        c['mechanisms']['g20']['cap40'] = 'unlimited'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'contract.json'; path.write_text(json.dumps(c))
            with self.assertRaisesRegex(ValueError, 'renewal_mechanisms_changed'): read_contract(path)
