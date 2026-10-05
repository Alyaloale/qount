import copy
import json
from pathlib import Path
import tempfile
import unittest

from qount.research import dual_engine_reform as r
from test_dual_engine_regimes import panel_fixture, assets_fixture

CONTRACT = Path(__file__).resolve().parents[1] / 'config/dual-engine-reform-20261005.json'


class ReformTests(unittest.TestCase):
    def test_fixed_candidate_inventory_and_protocol(self):
        c = r.read_contract(CONTRACT)
        self.assertEqual(c['new_candidate_trials'], 14)
        self.assertEqual(c['planned_curves'], 4 * len(r.G20_CONTROLS + r.G20_CANDIDATES + r.C60_CONTROLS + r.C60_CANDIDATES))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'contract.json'
            for line, key, value in [('g20', 'delays', [0, 1]), ('c60', 'annual_volatility_cap', .8), ('c60', 'end', '2026-09-30')]:
                changed = copy.deepcopy(c); changed[line][key] = value; p.write_text(json.dumps(changed))
                with self.assertRaises(ValueError): r.read_contract(p)

    def test_every_equity_candidate_keeps_original_target_and_selection(self):
        c = r.read_contract(CONTRACT); panel = panel_fixture(); rates = {k: [0.] * len(panel.dates) for k in ('DFII10', 'T10YIE')}
        for rule, source in r.G20_SOURCES.items():
            self.assertEqual(r.equity_targets(panel, c['g20'], rule, rates), r.previous_round.equity_targets(panel, c['g20'], source, rates))

    def test_every_crypto_candidate_keeps_original_target_and_universe(self):
        c = r.read_contract(CONTRACT); axis, assets = assets_fixture()
        for rule, source in r.C60_SOURCES.items():
            self.assertEqual(r.crypto_targets(axis, assets, c['c60'], rule), r.previous_round.crypto_targets(axis, assets, c['c60'], source))

    def test_source_target_prefix_is_independent_of_future_crypto_prices(self):
        c = r.read_contract(CONTRACT); axis, assets = assets_fixture(); future = copy.deepcopy(assets)
        for a in future.values():
            object.__setattr__(a, 'closes', tuple(v if i + a.start < 400 else v * 10 for i, v in enumerate(a.closes)))
        for rule in r.C60_CANDIDATES:
            a, _ = r.crypto_targets(axis, assets, c['c60'], rule); b, _ = r.crypto_targets(axis, future, c['c60'], rule)
            self.assertEqual({t: w for t, w in a.items() if t < 400}, {t: w for t, w in b.items() if t < 400})

    def test_capital_methods_change_execution_and_keep_original_controls(self):
        c = r.read_contract(CONTRACT); panel = panel_fixture(); rates = {k: [0.] * len(panel.dates) for k in ('DFII10', 'T10YIE')}
        for control in r.G20_CONTROLS:
            self.assertEqual(r.equity_targets(panel, c['g20'], control, rates), r.previous_round.equity_targets(panel, c['g20'], control, rates))

    def test_every_crypto_candidate_integrates_risk_accounting_on_fixture(self):
        c = r.read_contract(CONTRACT); axis, assets = assets_fixture()
        opns = {a.symbol: dict(zip(axis.dates[a.start:a.start + len(a.closes)], a.closes)) for a in assets.values()}
        closes, opens = r.base.crypto_prices(axis, assets, opns)
        settings = {**c['c60'], 'start': axis.dates[365]}
        for rule in r.C60_CANDIDATES:
            targets, _ = r.crypto_targets(axis, assets, settings, rule)
            run = r.candidate_replay('c60', rule, axis.dates, closes, opens, targets,
                                    settings=settings, delay=1, cost=50, assets=assets)
            self.assertTrue(run['records'])
            self.assertTrue(all(row['cash'] >= -1e-10 and row['vintage_units_relative_error'] < 1e-12 for row in run['records']))
            self.assertTrue(all(row['risk_buy_notional'] < 1e-12 for row in run['records'] if row['trade_clock'] == 'reduce'))

    def test_every_capital_candidate_integrates_funded_books_on_fixture(self):
        c = r.read_contract(CONTRACT); panel = panel_fixture(); rates = {k: [0.] * len(panel.dates) for k in ('DFII10', 'T10YIE')}
        closes = {k: dict(zip(panel.dates, v)) for k, v in panel.total_closes.items()}
        opens = {k: dict(zip(panel.dates, v)) for k, v in panel.total_opens.items()}
        settings = {**c['g20'], 'start': panel.dates[160]}
        for rule in r.G20_CANDIDATES:
            targets, _ = r.equity_targets(panel, settings, rule, rates)
            run = r.candidate_replay('g20', rule, panel.dates, closes, opens, targets,
                                    settings=settings, delay=2, cost=40, panel=panel)
            self.assertTrue(all(row['cash'] >= -1e-10 and row['untouched_books_units_max_error'] == 0 for row in run['records']))
            a = r.capital_contributions(run, panel.dates, closes, opens)
            self.assertLess(a['max_error'], 1e-10)
