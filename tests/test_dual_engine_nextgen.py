import copy
import datetime as dt
import math
from pathlib import Path
import unittest
from qount.research import dual_engine_nextgen as n
from qount.research import dual_engine_expansion as ex
from qount.research.dual_engine_nextgen_data import supply_features
from qount.research.dual_engine_optimization import EquityPanel
from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from test_dual_engine_expansion import crypto_fixture, macro_fixture

CONTRACT = Path(__file__).resolve().parents[1] / "config/dual-engine-nextgen-20261004.json"


def supply_fixture():
    end = dt.date(2021, 3, 31)
    return {(end - dt.timedelta(days=i)).isoformat():
        {"SplyCur": 1000 * math.exp(.001 * (90 - i)), "FeeTotNtv": 1 + .01 * (90 - i)} for i in range(90)}


class NextgenTests(unittest.TestCase):
    def test_registered_inventory(self):
        c = n.read_contract(CONTRACT)
        self.assertEqual(c["planned_curves"], 4 * len(n.G20_CONTROLS + n.G20_CANDIDATES + n.C60_CONTROLS + n.C60_CANDIDATES))
        self.assertEqual(c["new_candidate_trials"], 16)

    def test_supply_exact_lag_and_no_future_leakage(self):
        rows = supply_fixture()
        a = supply_features(rows, "2021-03-31")
        self.assertAlmostEqual(a["issued_growth30"], .03)
        self.assertEqual(a["feature_end"], "2021-03-24")
        for day in rows:
            if day > a["feature_end"]:
                rows[day] = {"SplyCur": 1e20, "FeeTotNtv": 1e30}
        self.assertEqual(a, supply_features(rows, "2021-03-31"))

    def test_supply_gap_and_fee_unavailability_differ(self):
        rows = supply_fixture()
        rows["2021-03-20"]["FeeTotNtv"] = 0
        self.assertIsNone(supply_features(rows, "2021-03-31")["fee_density_growth"])
        del rows["2021-03-20"]
        self.assertIsNone(supply_features(rows, "2021-03-31"))

    def test_supply_and_fee_units_cannot_change_ranking_features(self):
        rows = supply_fixture()
        scaled = {d: {"SplyCur": r["SplyCur"] * 30, "FeeTotNtv": r["FeeTotNtv"] * 71} for d, r in rows.items()}
        a, b = (supply_features(r, "2021-03-31") for r in (rows, scaled))
        for m in ("issued_growth30", "fee_density_growth"):
            self.assertAlmostEqual(a[m], b[m])

    def test_all_original_controls_preserved(self):
        c = n.read_contract(CONTRACT)
        panel = macro_fixture()
        rates = {s: [0.] * len(panel.dates) for s in ("DFII10", "T10YIE")}
        for rule in n.G20_CONTROLS:
            self.assertEqual(n.equity_targets(panel, c["g20"], rule, rates), ex.equity_targets(panel, c["g20"], rule, rates))
        axis, assets = crypto_fixture()
        for rule in ("residual2", "btc_continuous", "core_only"):
            self.assertEqual(n.crypto_targets(axis, assets, c["c60"], rule, {}), ex.crypto_targets(axis, assets, c["c60"], rule, {}))

    def test_normal_crisis_variant_reproduces_residual2_targets(self):
        c = n.read_contract(CONTRACT)
        axis, assets = crypto_fixture()
        baseline, _ = n.crypto_targets(axis, assets, c["c60"], "residual2", {})
        variant, _ = n.crypto_targets(axis, assets, c["c60"], "crisis_core_cash", {})
        self.assertEqual(baseline, variant)

    def test_missing_supply_leaves_satellite_budget_cash(self):
        c = n.read_contract(CONTRACT)
        axis, assets = crypto_fixture()
        core, _ = n.crypto_targets(axis, assets, c["c60"], "core_only", {})
        for rule in ("supply_covered2", "supply_gate2", "supply_rank2", "fee_covered2", "fee_density2"):
            targets, _ = n.crypto_targets(axis, assets, c["c60"], rule, {})
            self.assertEqual(core, targets)

    def test_held_asset_crisis_ignores_unrelated_spy_selloff(self):
        c = n.read_contract(CONTRACT)
        panel = macro_fixture()
        # Every selection proxy trends steadily; unrelated broad equity falls.
        maps = [dict(panel.closes), dict(panel.total_closes), dict(panel.total_opens)]
        for mapping in maps:
            for proxy in G20_EXECUTION_TO_PROXY.values():
                mapping[proxy] = tuple(100 * math.exp(.001 * i) for i in range(len(panel.dates)))
            mapping["SPY"] = tuple(100. if i < 180 else 70. for i in range(len(panel.dates)))
        panel = EquityPanel(panel.dates, *maps)
        rates = {s: [0.] * len(panel.dates) for s in ("DFII10", "T10YIE")}
        _, events = n.equity_targets(panel, c["g20"], "aware_gold_cash", rates)
        self.assertTrue(events)
        self.assertTrue(all(e["state"] == "normal" for e in events))

    def test_static_insurance_uses_monthly_clock_and_full_cash_budget(self):
        c = n.read_contract(CONTRACT)
        panel = macro_fixture()
        rates = {s: [0.] * len(panel.dates) for s in ("DFII10", "T10YIE")}
        baseline, _ = n.equity_targets(panel, c["g20"], "gold20", rates)
        tail, _ = n.equity_targets(panel, c["g20"], "gold_tail_static5", rates)
        self.assertEqual(set(baseline), set(tail))
        for t, w in tail.items():
            self.assertAlmostEqual(sum(w.values()), 1)
            self.assertEqual(w["VIXY"], .05)
            self.assertAlmostEqual(w["BIL"], baseline[t]["BIL"] - .05)

    def test_crypto_future_prices_do_not_change_prefix_targets(self):
        c = n.read_contract(CONTRACT)
        axis, assets = crypto_fixture()
        changed = copy.deepcopy(assets)
        for k, a in changed.items():
            object.__setattr__(a, "closes", tuple(v if i + a.start < 400 else v * 10 for i, v in enumerate(a.closes)))
        for rule in ("recovery_source", "supply_recovery"):
            x, _ = n.crypto_targets(axis, assets, c["c60"], rule, {})
            y, _ = n.crypto_targets(axis, changed, c["c60"], rule, {})
            self.assertEqual({t: w for t, w in x.items() if t < 400}, {t: w for t, w in y.items() if t < 400})

    def test_recovery_probe_precedes_slow_trend_with_satellites_paused(self):
        c = n.read_contract(CONTRACT)
        axis, assets = crypto_fixture()
        btc = next(a for a in assets.values() if a.symbol == "BTCUSDT")
        prices = list(btc.closes)
        for i in range(390, len(prices)):
            prices[i] = prices[389] * (.70 if i < 405 else .70 * math.exp(.025 * (i - 405)))
        object.__setattr__(btc, "closes", tuple(prices))
        targets, events = n.crypto_targets(axis, assets, c["c60"], "recovery_source", {})
        baseline, _ = n.crypto_targets(axis, assets, c["c60"], "residual2", {})
        self.assertEqual({e["state"] for e in events.values()}, {"normal", "defensive", "recovery"})
        probe = axis.index("2021-02-13")
        self.assertGreater(targets[probe][btc.asset_id], baseline[probe].get(btc.asset_id, 0))
        self.assertEqual(set(targets[probe]), {btc.asset_id})
