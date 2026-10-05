import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from qount.research import dual_engine_zonal as r
from qount.research.dual_engine_zonal_recovery import recovery_scope, replay_zonal
from qount.research.dual_engine_containment import cap_decision, execute_cap, replay_containment
from qount.research.dual_engine_capital import capital_contributions

CONTRACT = Path(__file__).resolve().parents[1] / 'config/dual-engine-zonal-20261005.json'


def fixture():
    days = [(dt.date(2021, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(24)]
    prices = {k: {d: 100. for d in days} for k in ('X', 'Y', 'Z', 'GLD', 'BIL')}
    targets = {t: {'X': .5, **({'Y': .3} if t >= 5 else {})} for t in range(len(days))}
    return days, prices, targets


class ZonalTests(unittest.TestCase):
    def run_fixture(self, policy, lag=1, targets=None, closes=None):
        days, prices, aims = fixture()
        return replay_zonal(days, closes or prices, prices, targets or aims,
                            start=days[2], lag=lag, cost_bps=50, event_policy=policy, core_assets=('X', 'Z'))

    def test_scopes_are_declared_by_trigger_ownership(self):
        cores = {'X', 'Z'}; names = {'X', 'Y', 'Z', 'A'}
        self.assertEqual(recovery_scope('asset', {'Z'}, cores, names), {'Z'})
        self.assertEqual(recovery_scope('core', {'Z'}, cores, names), cores)
        self.assertIsNone(recovery_scope('core', {'Y'}, cores, names))
        self.assertEqual(recovery_scope('satellite', {'Y'}, cores, names), {'Y', 'A'})
        self.assertIsNone(recovery_scope('satellite', {'X'}, cores, names))
        self.assertIsNone(recovery_scope('family', {'X', 'Y'}, cores, names))
        with self.assertRaises(ValueError): recovery_scope('unregistered', {'X'}, cores, names)

    def test_satellite_recovery_stages_then_refills_its_zone(self):
        for policy in ('asset', 'satellite', 'family'):
            run = self.run_fixture(policy); decisions = {p['decision']: p for p in run['decisions']}
            p = decisions['2021-01-06']; q = decisions['2021-01-07']
            self.assertEqual(p['kind'], 'recover'); self.assertEqual(p['scope_assets'], ['Y'])
            self.assertEqual(p['target']['Y'], .15); self.assertEqual(q['target']['Y'], .3)
            self.assertEqual(q['continuing_assets'], ['Y'])
            rows = {r['date']: r for r in run['records']}
            self.assertEqual(rows['2021-01-07']['units']['X'], rows['2021-01-06']['units']['X'])
            self.assertGreater(rows['2021-01-08']['units']['Y'], rows['2021-01-07']['units']['Y'])

    def test_core_ablation_preserves_satellite_coupled_fill(self):
        p = next(p for p in self.run_fixture('core')['decisions'] if p['decision'] == '2021-01-06')
        self.assertEqual(p['kind'], 'full'); self.assertIsNone(p['scope_assets'])

    def test_core_transition_scopes_whole_core_and_not_satellites(self):
        days, _, aims = fixture()
        aims = {t: {'X': .3, 'Y': .2, **({'Z': .2} if t >= 5 else {})} for t in aims}
        for policy in ('core', 'family'):
            p = next(p for p in self.run_fixture(policy, targets=aims)['decisions'] if p['decision'] == days[5])
            self.assertEqual(p['kind'], 'recover'); self.assertEqual(p['scope_assets'], ['X', 'Z'])
            self.assertEqual(p['target']['Z'], .1)
            self.assertNotIn('X', p['sells']); self.assertNotIn('Z', p['sells'])

    def test_sunday_overrides_scope_and_staging(self):
        days, _, aims = fixture()
        aims = {t: {'X': .5, **({'Y': .3} if t >= 9 else {})} for t in aims}
        p = next(p for p in self.run_fixture('asset', targets=aims)['decisions'] if p['decision'] == days[9])
        self.assertTrue(p['weekly']); self.assertEqual(p['kind'], 'full'); self.assertEqual(p['target']['Y'], .3)

    def test_delayed_acquisitions_cancel_latest_closed_zero(self):
        days, _, aims = fixture(); aims[6] = {'X': .5}
        for policy in ('asset', 'core', 'satellite', 'family'):
            row = next(r for r in self.run_fixture(policy, 2, aims)['records'] if r['date'] == days[7])
            self.assertIn('Y', row['cancelled_stale']); self.assertNotIn('Y', row['units'])

    def test_complement_pending_zero_exit_and_scope_do_not_overlap(self):
        days, _, aims = fixture(); aims[5] = {'Y': .3}
        run = self.run_fixture('asset', 2, aims)
        p = next(p for p in run['decisions'] if p['decision'] == days[5])
        self.assertIn('X', p['zeros']); self.assertEqual(p['scope_assets'], ['Y'])
        row = next(r for r in run['records'] if r['date'] == days[7])
        self.assertNotIn('X', row['units']); self.assertGreater(row['units']['Y'], 0.)

    def test_future_targets_and_prices_preserve_prefix(self):
        days, prices, aims = fixture(); changed = copy.deepcopy(prices); future = copy.deepcopy(aims)
        for day in days[15:]: changed['X'][day] *= 100
        for t in range(15, len(days)): future[t] = {'Z': .8}
        for policy in ('asset', 'core', 'satellite', 'family'):
            a = self.run_fixture(policy, 2); b = self.run_fixture(policy, 2, future, changed)
            self.assertEqual(a['records'][:13], b['records'][:13])

    def test_cash_and_owned_vintages_conserve_without_complement_buys(self):
        days, prices, _ = fixture()
        for policy in ('asset', 'core', 'satellite', 'family'):
            cash = nav = 1.; units = {}
            for row in self.run_fixture(policy, 2)['records']:
                day = row['date']; names = set(units) | set(row['units'])
                flow = sum(abs(row['units'].get(k, 0.) - units.get(k, 0.)) * prices[k][day] for k in names)
                cash -= sum((row['units'].get(k, 0.) - units.get(k, 0.)) * prices[k][day] for k in names) + flow * .005
                self.assertAlmostEqual(cash, row['cash'], places=12)
                self.assertAlmostEqual(row['nav'], cash + sum(q * prices[k][day] for k, q in row['units'].items()), places=12)
                self.assertAlmostEqual(nav * (1 + row['return']), row['nav'], places=12)
                self.assertGreaterEqual(cash, -1e-12)
                for k, lots in row['vintages'].items(): self.assertAlmostEqual(sum(lots.values()), row['units'].get(k, 0.), places=12)
                if row['trade_clock'] == 'reduce': self.assertEqual(row['risk_buy_notional'], 0.)
                if row['trade_clock'] == 'recover':
                    for k in names - set(row['requested_scope']): self.assertLessEqual(row['units'].get(k, 0.), units.get(k, 0.) + 1e-12)
                units = row['units']; nav = row['nav']


class ContainmentTests(unittest.TestCase):
    def test_dated_ceiling_and_same_book_financing_with_both_fees(self):
        books = {'equity_crisis': {'cash': 0., 'units': {'X': 1., 'BIL': .5}}, 'gold': {'cash': 0., 'units': {'GLD': .1}}}
        plans = cap_decision('2021-01-01', books, {'X': 100., 'BIL': 100., 'GLD': 100.}, 200., {'equity_crisis': 3, 'gold': 2}, .4)
        p = plans['equity_crisis']; self.assertEqual(p['unit_ceilings'], {'X': .8}); self.assertEqual(p['epoch'], 3)
        new, detail = execute_cap(books['equity_crisis'], {'X': 100., 'BIL': 100.}, p, 40)
        self.assertAlmostEqual(new['units']['X'], .8)
        self.assertAlmostEqual(detail['fee'], .004 * sum(detail['traded_notional'].values()))
        self.assertAlmostEqual(sum(q * 100. for q in new['units'].values()) + new['cash'], 150. - detail['fee'])
        self.assertGreater(new['units']['BIL'], .5)
        again, repeated = execute_cap(new, {'X': 100., 'BIL': 100.}, p, 40)
        self.assertEqual(again, new); self.assertEqual(repeated['fee'], 0.); self.assertEqual(repeated['sales'], {})

    def containment_fixture(self, lag=2):
        days, prices, _ = fixture()
        prices['X'] = {d: 100. * 1.1 ** i for i, d in enumerate(days)}
        aims = {1: {'X': .2, 'GLD': .2, 'BIL': .6}, 5: {'X': .2, 'GLD': .2, 'BIL': .6}, 12: {'X': .2, 'GLD': .2, 'BIL': .6}}
        run = replay_containment(days, prices, prices, aims, start=days[3], lag=lag, cost_bps=40, full_refresh=set(aims), limit=.2)
        return days, prices, aims, run

    def test_cap_decisions_are_closed_and_delayed_and_epochs_cancel(self):
        days, _, _, run = self.containment_fixture()
        cancelled = fills = 0
        for row in run['records']:
            for name, action in row['cap_actions'].items():
                p = action['plan']; self.assertEqual(days.index(row['date']) - days.index(p['decision']), 2)
                self.assertEqual(p, run['containment_decisions'][days.index(p['decision'])][name])
                self.assertEqual(action['cancelled_epoch'], p['epoch'] != row['source_epochs'][name])
                cancelled += action['cancelled_epoch']; fills += bool(action['sales'])
                if action['cancelled_epoch']: self.assertEqual(action['sales'], {})
        self.assertGreater(cancelled, 0); self.assertGreater(fills, 0)

    def test_actual_exposure_can_overshoot_dated_limit(self):
        days, prices, _, run = self.containment_fixture()
        self.assertGreater(max(r['book_risk_weights']['equity_crisis'] for r in run['records']), .2)
        self.assertLess(capital_contributions(run, days, prices, prices)['max_error'], 1e-10)

    def test_book_cash_transfer_and_fee_equations(self):
        days, prices, _, run = self.containment_fixture(); old = {b: {'units': {}, 'cash': w, 'nav': w} for b, w in run['initial_capital_shares'].items()}
        for row in run['records']:
            total_fee = 0.; day = row['date']
            self.assertAlmostEqual(sum(b['capital_transfer'] for b in row['books'].values()), 0., places=12)
            for name, book in row['books'].items():
                before = old[name]; delta = {k: book['units'].get(k, 0.) - before['units'].get(k, 0.) for k in set(book['units']) | set(before['units'])}
                flow = sum(abs(q) * prices[k][day] for k, q in delta.items()); total_fee += book['fee']
                self.assertAlmostEqual(book['fee'], flow * .004, places=12)
                self.assertAlmostEqual(book['cash'], before['cash'] - sum(q * prices[k][day] for k, q in delta.items()) - book['fee'] + book['capital_transfer'], places=12)
                if row['cap_actions'].get(name, {}).get('sales'): self.assertEqual(book['capital_transfer'], 0.)
            self.assertAlmostEqual(row['nav'], sum(b['nav'] for b in row['books'].values()), places=12)
            old = row['books']

    def test_future_prices_do_not_change_prefix(self):
        days, prices, aims, run = self.containment_fixture(); changed = copy.deepcopy(prices)
        for day in days[15:]: changed['X'][day] *= 100
        later = replay_containment(days, changed, prices, aims, start=days[3], lag=2, cost_bps=40, full_refresh=set(aims), limit=.2)
        self.assertEqual(run['records'][:12], later['records'][:12])


class ProtocolTests(unittest.TestCase):
    def test_contract_inventory_and_changes_fail(self):
        c = r.read_contract(CONTRACT)
        self.assertEqual(c['new_candidate_trials'], 8); self.assertEqual(c['planned_curves'], 72)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'contract.json'
            for key in ('mechanisms', 'target_sources', 'selection_policy'):
                changed = copy.deepcopy(c); changed[key] = {}; p.write_text(json.dumps(changed))
                with self.assertRaises(ValueError): r.read_contract(p)

    def test_all_sources_and_controls_exact_and_fixtures_funded(self):
        from test_dual_engine_regimes import panel_fixture, assets_fixture
        c = r.read_contract(CONTRACT); panel = panel_fixture(); rates = {k: [0.] * len(panel.dates) for k in ('DFII10', 'T10YIE')}
        for rule in r.G20_CONTROLS:
            self.assertEqual(r.equity_targets(panel, c['g20'], rule, rates), r.tenth.equity_targets(panel, c['g20'], rule, rates))
        eq_close = {k: dict(zip(panel.dates, v)) for k, v in panel.total_closes.items()}; eq_open = {k: dict(zip(panel.dates, v)) for k, v in panel.total_opens.items()}
        settings = {**c['g20'], 'start': panel.dates[160]}
        for rule, source in r.G20_SOURCES.items():
            targets, members = r.equity_targets(panel, settings, rule, rates)
            self.assertEqual((targets, members), r.ninth.equity_targets(panel, settings, source, rates))
            run = r.candidate_replay('g20', rule, panel.dates, eq_close, eq_open, targets, settings=settings, delay=2, cost=40, panel=panel)
            self.assertLess(capital_contributions(run, panel.dates, eq_close, eq_open)['max_error'], 1e-10)
        axis, assets = assets_fixture(); settings = {**c['c60'], 'start': axis.dates[365]}
        for rule in r.C60_CONTROLS:
            self.assertEqual(r.crypto_targets(axis, assets, settings, rule), r.tenth.crypto_targets(axis, assets, settings, rule))
        closes, opens = r.base.crypto_prices(axis, assets, {a.symbol: dict(zip(axis.dates[a.start:a.start + len(a.closes)], a.closes)) for a in assets.values()})
        for rule in r.C60_CANDIDATES:
            targets, members = r.crypto_targets(axis, assets, settings, rule)
            self.assertEqual((targets, members), r.tenth.crypto_targets(axis, assets, settings, 'staged_risk4'))
            run = r.candidate_replay('c60', rule, axis.dates, closes, opens, targets, settings=settings, delay=1, cost=50, assets=assets)
            self.assertTrue(all(row['cash'] >= -1e-10 for row in run['records']))
