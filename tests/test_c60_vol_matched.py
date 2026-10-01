import unittest

from qount.research import c60_cost_study as study
from qount.research import c60_vol_matched as vm
from tests.test_crypto_trend_premise import _series


class C60VolMatchedTests(unittest.TestCase):
    def setUp(self):
        self.panel, _ = study.build_panel(_series())

    def test_run_aligns_windows_and_guards(self):
        out = vm.run(self.panel)
        self.assertFalse(out["guards"]["trial"])
        self.assertEqual(set(out["variants"]), {"c60_v2", "btc_static_vol_matched",
                                                "btc_ex_ante_vol_matched", "btc_only_c60_gate"})
        c60 = out["variants"]["c60_v2"]
        static = out["variants"]["btc_static_vol_matched"]
        self.assertAlmostEqual(static["annual_vol"], c60["annual_vol"], delta=c60["annual_vol"] * 0.05)

    def test_ex_ante_weights_are_causal_and_bounded(self):
        c60_targets = study.target_path(self.panel, mode="research_monthly")
        base = vm.ex_ante_vol_matched(self.panel, c60_targets)
        # Changing prices after close t must not change the weight decided at close t.
        t = 400
        closes = {s: list(v) for s, v in self.panel.closes.items()}
        for s in closes:
            for i in range(t + 1, len(closes[s])):
                closes[s][i] *= 1.5
        shifted = study.Panel(self.panel.dates, {s: tuple(v) for s, v in closes.items()})
        moved = vm.ex_ante_vol_matched(shifted, study.target_path(shifted, mode="research_monthly"))
        self.assertEqual(base[t], moved[t])
        self.assertTrue(all(0.0 <= w.get("BTCUSDT", 0.0) <= 1.0 for w in base))

    def test_btc_only_gate_holds_only_btc(self):
        targets = vm.btc_only_gate(self.panel)
        self.assertTrue(all(set(t) <= {"BTCUSDT"} for t in targets))
        self.assertTrue(any(targets))


if __name__ == "__main__":
    unittest.main()
