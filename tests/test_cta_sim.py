from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

# cta_sim itself is pure stdlib, but importing the qount package chain can touch
# modules that expect ccxt/openai to exist. Stub them like the other test module.
if "ccxt" not in sys.modules:
    class _StubExchange:
        def __init__(self, options=None) -> None:
            self.options = options or {}

    sys.modules["ccxt"] = types.SimpleNamespace(binance=_StubExchange, binanceus=_StubExchange)

from qount.cta_sim import DEFAULT_UNIVERSE
from qount.cta_sim import MODE_PRESETS
from qount.cta_sim import SimConfig
from qount.cta_sim import _cap_unit_weights
from qount.cta_sim import _target_weights
from qount.cta_sim import generate_synthetic_panel
from qount.cta_sim import load_prices_csv
from qount.cta_sim import render_summary
from qount.cta_sim import run_paper_sim


REPO_ROOT = Path(__file__).resolve().parents[1]


def _rets_from_prices(prices: dict[str, list[float]]) -> dict[str, list[float | None]]:
    rets: dict[str, list[float | None]] = {}
    for name, series in prices.items():
        out: list[float | None] = [None]
        for t in range(1, len(series)):
            prev = series[t - 1]
            out.append(series[t] / prev - 1.0 if prev > 0 else None)
        rets[name] = out
    return rets


class GenerateSyntheticPanelTest(unittest.TestCase):
    def test_shape_and_positive_prices(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=500, seed=3)
        self.assertEqual(len(prices), len(DEFAULT_UNIVERSE))
        for series in prices.values():
            self.assertEqual(len(series), 500)
            self.assertTrue(all(p > 0 for p in series))

    def test_deterministic_with_seed(self) -> None:
        a = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=300, seed=11)
        b = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=300, seed=11)
        self.assertEqual(a, b)

    def test_cross_asset_breadth_escapes_ceiling(self) -> None:
        # The whole thesis: a cross-asset panel must beat the crypto-majors ~1.6 ceiling.
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=1500, seed=5)
        result = run_paper_sim(prices, SimConfig())
        breadth = result["effective_breadth"]["effective_breadth"]
        self.assertGreater(breadth, 3.0)

    def test_rejects_too_short(self) -> None:
        with self.assertRaises(ValueError):
            generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=1, seed=1)


class RunPaperSimTest(unittest.TestCase):
    def test_result_keys_and_equity_curve(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=1200, seed=7)
        result = run_paper_sim(prices, SimConfig())
        for key in (
            "sharpe",
            "annualized_return",
            "annualized_vol",
            "max_drawdown",
            "final_equity",
            "rebalances",
            "effective_breadth",
        ):
            self.assertIn(key, result)
        self.assertGreater(result["rebalances"], 0)
        self.assertGreater(result["final_equity"], 0.0)
        self.assertLessEqual(result["max_drawdown"], 0.0)
        self.assertTrue(result["equity_curve_sampled"])

    def test_deterministic(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=800, seed=2)
        r1 = run_paper_sim(prices, SimConfig())
        r2 = run_paper_sim(prices, SimConfig())
        self.assertEqual(r1["final_equity"], r2["final_equity"])
        self.assertEqual(r1["sharpe"], r2["sharpe"])

    def test_cost_reduces_return(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=1200, seed=9)
        free = run_paper_sim(prices, SimConfig(cost_per_side_pct=0.0))
        costly = run_paper_sim(prices, SimConfig(cost_per_side_pct=0.002))
        self.assertGreater(free["final_equity"], costly["final_equity"])

    def test_rejects_insufficient_history(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=255, seed=1)
        with self.assertRaises(ValueError):
            run_paper_sim(prices, SimConfig(lookback_days=(252,)))

    def test_render_summary_runs(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=800, seed=4)
        text = render_summary(run_paper_sim(prices, SimConfig()))
        self.assertIn("CTA-R paper-sim", text)
        self.assertIn("Sharpe", text)


class NoLookaheadTest(unittest.TestCase):
    def test_target_weights_ignore_future_prices(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=600, seed=6)
        config = SimConfig()
        t = 400
        rets = _rets_from_prices(prices)
        before = _target_weights(prices, rets, t, config, equity=1.0, peak_equity=1.0)

        # Corrupt prices strictly after the decision index; weights at t must not change.
        future = {name: list(series) for name, series in prices.items()}
        for name in future:
            for k in range(t + 1, len(future[name])):
                future[name][k] *= 5.0
        future_rets = _rets_from_prices(future)
        after = _target_weights(future, future_rets, t, config, equity=1.0, peak_equity=1.0)
        self.assertEqual(before, after)


class LongOnlyTest(unittest.TestCase):
    def test_long_only_drops_short_legs(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=600, seed=6)
        rets = _rets_from_prices(prices)
        t = 400
        ls = _target_weights(
            prices, rets, t, SimConfig(long_only=False), equity=1.0, peak_equity=1.0
        )
        lo = _target_weights(
            prices, rets, t, SimConfig(long_only=True), equity=1.0, peak_equity=1.0
        )
        # The long/short book must have at least one short here (else the test is vacuous);
        # the long-only book must have no negative weights at all.
        self.assertTrue(any(w < 0 for w in ls.values()))
        self.assertTrue(all(w >= 0 for w in lo.values()))
        self.assertTrue(any(w > 0 for w in lo.values()))

    def test_long_only_flows_through_run_paper_sim(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=800, seed=4)
        res = run_paper_sim(prices, SimConfig(long_only=True, max_leverage=1.0))
        # Cash, no-short, no-leverage: gross exposure can never exceed the 1.0 cap.
        self.assertLessEqual(res["avg_gross_exposure"], 1.0 + 1e-9)


class CapUnitWeightsTest(unittest.TestCase):
    def test_caps_and_water_fills_preserving_gross(self) -> None:
        # Bond-like concentration: one name at 0.70, rest small.
        w = {"BOND": 0.70, "A": 0.10, "B": 0.10, "C": 0.10}
        capped = _cap_unit_weights(w, 0.30)
        self.assertAlmostEqual(capped["BOND"], 0.30, places=6)
        self.assertLessEqual(max(abs(v) for v in capped.values()), 0.30 + 1e-6)
        self.assertAlmostEqual(sum(abs(v) for v in capped.values()), 1.0, places=6)
        # The freed weight went to the others (they grew from 0.10).
        self.assertGreater(capped["A"], 0.10)

    def test_preserves_sign_for_short_legs(self) -> None:
        w = {"X": -0.80, "Y": 0.20}
        capped = _cap_unit_weights(w, 0.50)
        self.assertLess(capped["X"], 0.0)  # still short
        self.assertAlmostEqual(abs(capped["X"]), 0.50, places=6)

    def test_no_cap_when_cap_ge_one(self) -> None:
        w = {"A": 0.6, "B": 0.4}
        self.assertEqual(_cap_unit_weights(w, 1.0), w)

    def test_max_weight_reduces_concentration_in_target_weights(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=600, seed=6)
        rets = _rets_from_prices(prices)
        t = 400
        uncapped = _target_weights(
            prices, rets, t, SimConfig(long_only=True), equity=1.0, peak_equity=1.0
        )
        capped = _target_weights(
            prices, rets, t, SimConfig(long_only=True, max_weight=0.25),
            equity=1.0, peak_equity=1.0,
        )
        gross_capped = sum(abs(v) for v in capped.values())
        # Largest share of gross must respect the cap (allow a little vol-target slack).
        top_share = max(abs(v) for v in capped.values()) / gross_capped
        self.assertLessEqual(top_share, 0.25 + 1e-6)
        top_uncapped = max(abs(v) for v in uncapped.values()) / sum(
            abs(v) for v in uncapped.values()
        )
        self.assertGreater(top_uncapped, top_share)


class ModePresetTest(unittest.TestCase):
    def test_presets_are_cash_account_shaped(self) -> None:
        for name in ("conservative", "balanced", "aggressive"):
            preset = MODE_PRESETS[name]
            self.assertTrue(preset["long_only"])
            self.assertEqual(preset["max_leverage"], 1.0)  # cash: no leverage
        # Aggressive drops bonds; conservative keeps everything.
        self.assertEqual(MODE_PRESETS["conservative"]["exclude_classes"], ())
        self.assertIn("bond", MODE_PRESETS["aggressive"]["exclude_classes"])
        # Risk rises conservative -> aggressive.
        self.assertLess(
            MODE_PRESETS["conservative"]["target_vol"],
            MODE_PRESETS["aggressive"]["target_vol"],
        )


class LoadPricesCsvTest(unittest.TestCase):
    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.csv"
            path.write_text(
                "date,AAA,BBB\n2020-01-01,100,200\n2020-01-02,101,199\n2020-01-03,102,201\n",
                encoding="utf-8",
            )
            prices = load_prices_csv(path)
            self.assertEqual(prices["AAA"], [100.0, 101.0, 102.0])
            self.assertEqual(prices["BBB"], [200.0, 199.0, 201.0])

    def test_forward_fills_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.csv"
            path.write_text("date,X\n2020-01-01,10\n2020-01-02,\n2020-01-03,12\n", encoding="utf-8")
            prices = load_prices_csv(path)
            self.assertEqual(prices["X"], [10.0, 10.0, 12.0])


class CliSmokeTest(unittest.TestCase):
    def test_cli_runs_and_emits_json(self) -> None:
        # Use the standalone, dependency-free entry so it runs without ccxt installed.
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT / "src")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sim.json"
            proc = subprocess.run(
                [
                    sys.executable, "-m", "qount.cta_sim",
                    "--days", "500", "--seed", "1", "--output-path", str(out),
                ],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["version"], "cta_sim_v1")
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
