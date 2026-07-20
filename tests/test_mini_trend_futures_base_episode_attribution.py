from __future__ import annotations

import json
import unittest

from qount.grid.data import Bar
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_base_episode_attribution import BaseEpisodeAttributionConfig
from qount.mini_trend.futures_base_episode_attribution import build_base_episode_preregistration
from qount.mini_trend.futures_base_episode_attribution import extract_base_episodes
from qount.mini_trend.futures_base_episode_attribution import validate_base_episode_preregistration
from qount.mini_trend.futures_recovery_backtest import VariantResult


_T0 = 1_609_459_200_000
_DAY = 86_400_000


def _bars() -> dict[str, list[Bar]]:
    closes = [100.0, 110.0, 100.0]
    rows = [
        Bar(
            _T0 + index * _DAY,
            close,
            115.0 if index == 1 else close * 1.01,
            95.0 if index == 1 else close * 0.99,
            close,
            1000.0,
        )
        for index, close in enumerate(closes)
    ]
    return {symbol: list(rows) for symbol in TOP3}


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {"symbol": symbol, "status": "TRADING", "min_qty": "0.001", "min_notional": "5"}
            for symbol in TOP3
        ],
    }


def _result(*, stopped: bool, mode: str) -> VariantResult:
    bars = _bars()["BTCUSDT"]
    first_net = 0.5 * (110.0 / 100.0 - 1.0) - 0.5 * 0.0012
    first_equity = 400.0 * (1.0 + first_net)
    second_net = -0.5 * 0.0012
    second_equity = first_equity * (1.0 + second_net)
    zero = {symbol: 0.0 for symbol in TOP3}
    active = dict(zero, BTCUSDT=0.5)
    return VariantResult(
        metrics={},
        equity=[
            {
                "decision_date": bars[0].date,
                "outcome_date": bars[1].date,
                "equity": round(first_equity, 8),
                "mode": "base_trend",
                "stopped": [],
                "gross_price_return": 0.05,
                "funding_return": 0.0,
                "trading_cost_return": -0.0006,
                "net_return": first_net,
                "execution_state": {"target_weights": active},
            },
            {
                "decision_date": bars[1].date,
                "outcome_date": bars[2].date,
                "equity": round(second_equity, 8),
                "mode": mode,
                "stopped": ["BTCUSDT"] if stopped else [],
                "gross_price_return": 0.0,
                "funding_return": 0.0,
                "trading_cost_return": -0.0006,
                "net_return": second_net,
                "execution_state": {"target_weights": zero},
            },
        ],
    )


class MiniTrendFuturesBaseEpisodeAttributionTest(unittest.TestCase):
    def test_episode_reconciles_price_and_two_sided_cost(self) -> None:
        episodes, reconciliation = extract_base_episodes(
            _result(stopped=True, mode="base_trend"),
            _bars(),
            {symbol: [] for symbol in TOP3},
        )
        self.assertEqual(len(episodes), 1)
        episode = episodes[0]
        self.assertEqual(episode["exit_reason"], "chandelier_stop")
        self.assertEqual(episode["holding_bars"], 1)
        self.assertAlmostEqual(episode["mfe_pct"], 15.0)
        self.assertAlmostEqual(episode["mae_pct"], -5.0)
        self.assertAlmostEqual(reconciliation["net_pnl_difference_usdt"], 0.0, places=7)
        self.assertAlmostEqual(
            episode["net_pnl_usdt"],
            episode["price_pnl_usdt"]
            + episode["funding_pnl_usdt"]
            - episode["trading_cost_usdt"],
            places=7,
        )

    def test_cash_mode_classifies_master_gate_exit(self) -> None:
        episodes, _ = extract_base_episodes(
            _result(stopped=False, mode="cash"),
            _bars(),
            {symbol: [] for symbol in TOP3},
        )
        self.assertEqual(episodes[0]["exit_reason"], "master_gate_cash")

    def test_preregistration_is_diagnostic_not_strategy_trial(self) -> None:
        preregistration = build_base_episode_preregistration(_rules())
        config = BaseEpisodeAttributionConfig()
        validate_base_episode_preregistration(preregistration, _rules(), config)
        self.assertEqual(preregistration["contract"]["trial_count"], 0)
        self.assertEqual(preregistration["contract"]["cumulative_trial_count"], 142)
        self.assertFalse(preregistration["meta"]["strategy_results_evaluated"])
        changed = json.loads(json.dumps(_rules()))
        changed["rules"][0]["min_notional"] = "50"
        with self.assertRaisesRegex(ValueError, "exchange-rules hash mismatch"):
            validate_base_episode_preregistration(preregistration, changed, config)


if __name__ == "__main__":
    unittest.main()
