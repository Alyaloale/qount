import copy
import json
from pathlib import Path
import tempfile
import unittest
from qount.research import dual_engine_clocks as r
from test_dual_engine_regimes import panel_fixture,assets_fixture

CONTRACT=Path(__file__).resolve().parents[1]/'config/dual-engine-clocks-20261005.json'


class ClocksTests(unittest.TestCase):
    def test_fixed_inventory_and_changed_protocol_rejected(self):
        c=r.read_contract(CONTRACT)
        self.assertEqual(c['new_candidate_trials'],8)
        self.assertEqual(c['planned_curves'],4*len(r.G20_CONTROLS+r.G20_CANDIDATES+r.C60_CONTROLS+r.C60_CANDIDATES))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'contract.json'
            for line,key,value in [('g20','delays',[0,1]),('c60','end','2026-09-30'),('c60','annual_volatility_cap',.8)]:
                changed=copy.deepcopy(c);changed[line][key]=value;p.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):r.read_contract(p)

    def test_equity_changes_accounting_not_signal_selection(self):
        c=r.read_contract(CONTRACT);p=panel_fixture();rates={s:[0.]*len(p.dates) for s in ('DFII10','T10YIE')}
        for rule,source in r.G20_SOURCES.items():
            self.assertEqual(r.equity_targets(p,c['g20'],rule,rates),r.previous_round.equity_targets(p,c['g20'],source,rates))

    def test_crypto_changes_clock_not_target_and_universe(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture()
        for rule,source in r.C60_SOURCES.items():
            self.assertEqual(r.crypto_targets(axis,assets,c['c60'],rule),r.previous_round.crypto_targets(axis,assets,c['c60'],source))

    def test_future_crypto_data_leave_target_prefix_unchanged(self):
        c=r.read_contract(CONTRACT);axis,assets=assets_fixture();changed=copy.deepcopy(assets)
        for a in changed.values():
            object.__setattr__(a,'closes',tuple(v if i+a.start<400 else v*10 for i,v in enumerate(a.closes)))
        for rule in r.C60_CANDIDATES:
            a,_=r.crypto_targets(axis,assets,c['c60'],rule);b,_=r.crypto_targets(axis,changed,c['c60'],rule)
            self.assertEqual({t:w for t,w in a.items() if t<400},{t:w for t,w in b.items() if t<400})
