"""Causality, input parity and accounting regressions for historical evaluation."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from qount.research.etf_trader.historical_data import file_hash, load_panel
from qount.research.etf_trader.universe import US_ACCOUNT

try:
    import torch
except ImportError:
    torch = None


class HistoricalDataTests(unittest.TestCase):
    def test_panel_requires_adjusted_and_unadjusted_prices_and_all_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {"source": "unit fixture", "files": {}}
            for symbol in (*US_ACCOUNT.symbols, US_ACCOUNT.cash_symbol):
                path = root / f"{symbol}_daily.csv"
                with path.open("w", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["Date", "Open", "Close", "Adj Close", "Volume"])
                    writer.writerow(["2020-01-02", 100, 100, 90, 1e6])
                    writer.writerow(["2020-01-03", 101, 101, 91, 1e6])
                manifest["files"][symbol] = {"sha256": file_hash(path), "split_events": 0}
            (root / "manifest.json").write_text(json.dumps(manifest))
            data, dates, _ = load_panel(root, US_ACCOUNT, "2020-01-03")
            self.assertEqual(data.n, 9)
            self.assertEqual(len(dates), 2)
            self.assertNotEqual(data.close[0, 0], data.close_adj[0, 0])
            self.assertAlmostEqual(data.cash_return[1], 91 / 90 - 1)
            (root / "QQQ_daily.csv").unlink()
            with self.assertRaises(FileNotFoundError):
                load_panel(root, US_ACCOUNT, "2020-01-03")


@unittest.skipIf(torch is None, "torch research dependency unavailable")
class HistoricalPolicyTests(unittest.TestCase):
    def test_inputs_and_decisions_match_training_and_exact_environment(self):
        from qount.research.etf_trader.env import MarketData, Observation, simulate
        from qount.research.etf_trader.costs import cost_params_for
        from qount.research.etf_trader.features import WorldFeatures
        from qount.research.etf_trader.historical_backtest import HistoricalPolicy, load_checkpoint, metrics
        from qount.research.etf_trader.policy import PolicyConfig, Trader, construct
        from qount.research.etf_trader.torch_env import Batch, TorchEnv
        from qount.research.etf_trader.train import EpisodeTensors, policy_inputs

        torch.set_num_threads(1)
        torch.manual_seed(7)
        rng = np.random.default_rng(3)
        T, n = 8, 9
        close = 100 * np.cumprod(1 + rng.normal(0, 0.01, (T, n)), axis=0)
        adv = np.full_like(close, 1e8)
        sigma = np.full_like(close, 0.01)
        spread = np.full_like(close, 1e-4)
        data = MarketData(close, close, close, adv, sigma, np.full(T, 1e-4), spread=spread)
        features = WorldFeatures(rng.normal(size=(T, n, 8)), np.ones((T, n), bool),
                                 rng.normal(size=(T, 6)), sigma, np.ones((T, n)), np.zeros((T, n), bool), False)
        tensor = lambda x, dtype=torch.float32: torch.as_tensor(x, dtype=dtype).unsqueeze(0)
        batch = Batch(tensor(close), tensor(close), tensor(close), tensor(adv), tensor(sigma),
                      tensor(data.cash_return), tensor(spread), tensor(features.reduce_only, torch.bool),
                      tensor(np.zeros_like(close), torch.bool), tensor(np.zeros_like(close), torch.bool))
        ep = EpisodeTensors(batch, tensor(features.asset), tensor(features.eligible, torch.bool),
                            tensor(features.market), tensor(sigma), tensor(features.tradable),
                            torch.ones(1), torch.ones(1))
        env = TorchEnv(batch, US_ACCOUNT, cost_params_for(US_ACCOUNT), exact=True)
        model = Trader(PolicyConfig(16, 16, 1)).eval()
        policy = HistoricalPolicy(model, features, data, US_ACCOUNT)
        h = model.initial_state(1)
        def checked(obs: Observation):
            nonlocal h
            training_obs = env.observe()
            with torch.no_grad():
                action, h = model(*policy_inputs(env, ep, training_obs, US_ACCOUNT), h)
                weights = construct(ep.static[:, obs.t, :, :4], ep.sigma_c[:, obs.t], ep.eligible[:, obs.t], action, US_ACCOUNT)
            decision = policy(obs)
            np.testing.assert_allclose(decision.target, weights[0].numpy(), atol=1e-6)
            self.assertAlmostEqual(decision.band, action.band.item(), places=6)
            self.assertAlmostEqual(decision.kappa, action.kappa.item(), places=6)
            env.step(weights, action.band, action.kappa)
            return decision
        result = simulate(data, US_ACCOUNT, checked, cost_params_for(US_ACCOUNT))
        self.assertGreater(result.costs[1], 0)
        self.assertEqual(result.costs[0], 0)
        self.assertEqual(len(policy.actions), T - 1)
        dates = [f"2020-01-{i + 1:02d}" for i in range(T)]
        self.assertEqual(metrics(result, data, dates)["trading_days"], T - 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.pt"
            cfg = {"account": "us", "policy": {"d_phi": 16, "hidden": 16, "layers": 1}}
            torch.save({"model": model.state_dict(), "config": cfg}, path)
            restored, loaded = load_checkpoint(path)
            self.assertEqual(loaded, cfg)
            for key, value in model.state_dict().items():
                torch.testing.assert_close(value, restored.state_dict()[key])


if __name__ == "__main__":
    unittest.main()
