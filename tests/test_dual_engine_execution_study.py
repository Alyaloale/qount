"""Contract and paired-statistic checks for the finite mechanism study."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from qount.research import dual_engine_execution_study as study
from qount.research.dual_engine_optimization import OptimizationStudyError


def run(values):
    return {"records": [{"date": f"2021-01-{i + 1:02d}", "return": v, "cash_return": 0.0001,
                          "turnover": 0, "cost_fraction": 0} for i, v in enumerate(values)]}


class ExecutionStudyTests(unittest.TestCase):
    def test_frozen_contract(self):
        p = Path(__file__).resolve().parents[1] / "config/dual-engine-execution-20261004.json"
        c = study.read_contract(p)
        self.assertEqual(c["planned_curve_exposures"], 64)
        with tempfile.TemporaryDirectory() as td:
            c["c60"]["delays"] = [0, 2]
            changed = Path(td) / "contract.json"
            changed.write_text(json.dumps(c))
            with self.assertRaises(OptimizationStudyError):
                study.read_contract(changed)

    def test_paired_same_returns_have_zero_intervals(self):
        r = run([0.01, -0.02, 0.03, 0.002] * 4)
        intervals = study.paired_diagnostics(r, copy.deepcopy(r), annual=252,
                                            settings={"block_lengths": [2, 4], "draws": 20, "seed": 4})
        for result in intervals.values():
            self.assertEqual(result["log_growth_ci95"], [0.0, 0.0])
            self.assertEqual(result["sharpe_ci95"], [0.0, 0.0])

    def test_pairing_rejects_different_dates(self):
        a, b = run([0.01, -0.01]), run([0.01, -0.01])
        b["records"][0]["date"] = "2021-02-01"
        with self.assertRaises(OptimizationStudyError):
            study.paired_diagnostics(a, b, annual=252, settings={"block_lengths": [2], "draws": 20, "seed": 4})

    def test_scenario_contrasts_do_not_conflate_cost_and_delay(self):
        group = {"baseline": {f"c{cost}-d{delay}": {m: cost + 100 * delay for m in
                 ("cagr", "sharpe", "cash_excess_sharpe", "max_drawdown")}
                 for cost in (20, 40) for delay in (1, 2)}}
        result = study.orthogonal_contrasts(group, low=20, high=40, early=1, late=2)["baseline"]
        self.assertEqual(result["cost_only_early"]["cagr"], 20)
        self.assertEqual(result["delay_only_low_cost"]["cagr"], 100)
