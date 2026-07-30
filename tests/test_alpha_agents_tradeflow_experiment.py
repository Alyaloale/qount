from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from qount.alpha_agents.historical_tradeflow import HISTORICAL_TRADEFLOW_VERSION
from qount.alpha_agents.tradeflow_experiment import FrozenTradeFlowContract
from qount.alpha_agents.tradeflow_experiment import TradeFlowExperimentConfig
from qount.alpha_agents.tradeflow_experiment import _funding_by_hour
from qount.alpha_agents.tradeflow_experiment import aggregate_five_minute_to_hourly
from qount.alpha_agents.tradeflow_experiment import build_tradeflow_experiment
from qount.alpha_agents.tradeflow_experiment import write_tradeflow_experiment_artifact
from qount.research_data.market_data import Bar
from qount.research_data.market_data import Funding
from qount.settings import Settings


START_MS = 1_704_067_200_000


def _five_minute_rows(imbalances: list[float], *, gap_index: int | None = None) -> list[dict]:
    rows: list[dict] = []
    for hour_index, imbalance in enumerate(imbalances):
        buy = 50.0 * (1.0 + imbalance)
        sell = 50.0 * (1.0 - imbalance)
        for bucket_index in range(12):
            absolute_index = hour_index * 12 + bucket_index
            if absolute_index == gap_index:
                continue
            rows.append(
                {
                    "symbol": "ETHUSDT",
                    "ts_ms": START_MS + absolute_index * 300_000,
                    "segment_id": 0 if gap_index is None or absolute_index < gap_index else 1,
                    "complete": True,
                    "agg_trade_count": 10,
                    "agg_trade_quote_volume": buy + sell,
                    "aggressive_buy_quote_volume": buy,
                    "aggressive_sell_quote_volume": sell,
                }
            )
    return rows


def _bars(symbol: str, count: int) -> list[Bar]:
    multiplier = {"BTCUSDT": 1.0, "ETHUSDT": 0.6, "BNBUSDT": 0.3, "SOLUSDT": 0.8}[symbol]
    price = {"BTCUSDT": 40_000.0, "ETHUSDT": 2_000.0, "BNBUSDT": 300.0, "SOLUSDT": 100.0}[symbol]
    result: list[Bar] = []
    for index in range(count):
        change = multiplier * (0.0005 + math.sin(index / 7.0) * 0.001)
        next_price = price * (1.0 + change)
        result.append(
            Bar(
                ts_ms=START_MS + index * 3_600_000,
                open=price,
                high=max(price, next_price),
                low=min(price, next_price),
                close=next_price,
                volume=100.0,
            )
        )
        price = next_price
    return result


class TradeFlowExperimentTest(unittest.TestCase):
    def test_funding_uses_the_applied_position_hour(self) -> None:
        funding_return, count = _funding_by_hour(
            [Funding(ts_ms=START_MS, rate=0.01), Funding(ts_ms=START_MS + 3_600_000, rate=0.02)],
            period_start_ts=START_MS,
            period_end_ts=START_MS + 3_600_000,
            position=1.0,
        )
        self.assertEqual(count, 1)
        self.assertAlmostEqual(funding_return, -2.0)

    def test_hourly_aggregation_uses_only_prior_hours_for_zscore(self) -> None:
        contract = FrozenTradeFlowContract(normalization_lookback_hours=2)
        hourly = aggregate_five_minute_to_hourly(
            _five_minute_rows([0.0, 0.5, 1.0]),
            symbol="ETHUSDT",
            contract=contract,
        )
        self.assertEqual(len(hourly), 3)
        self.assertIsNone(hourly[0]["signal_zscore"])
        self.assertIsNone(hourly[1]["signal_zscore"])
        self.assertAlmostEqual(hourly[2]["signal_zscore"], 3.0)
        self.assertEqual(hourly[2]["decision_ts_ms"], START_MS + 3 * 3_600_000)

    def test_incomplete_hour_is_excluded(self) -> None:
        hourly = aggregate_five_minute_to_hourly(
            _five_minute_rows([0.1, 0.2], gap_index=13),
            symbol="ETHUSDT",
        )
        self.assertEqual(len(hourly), 1)
        self.assertEqual(hourly[0]["hour_ts_ms"], START_MS)

    def test_builds_single_candidate_with_low_turnover_state_machine(self) -> None:
        count = 120
        imbalances = [0.02 * math.sin(index / 3.0) for index in range(count)]
        for index in range(8, count, 24):
            imbalances[index] = 0.9 if (index // 24) % 2 == 0 else -0.9
        rows = _five_minute_rows(imbalances)
        payload = {
            "schema_version": HISTORICAL_TRADEFLOW_VERSION,
            "meta": {"replayable": True},
            "diagnostics": {"verdict": "pass_data_smoke"},
            "five_minute_features": rows,
        }
        contract = FrozenTradeFlowContract(
            normalization_lookback_hours=4,
            entry_zscore=1.0,
            holding_hours=6,
            cooldown_hours=18,
            beta_lookback_hours=5,
            minimum_rank_ic=-1.0,
            minimum_entry_count=1,
        )
        symbols = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
        bars_by_symbol = {symbol: _bars(symbol, count + 1) for symbol in symbols}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "tradeflow.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            artifact = build_tradeflow_experiment(
                TradeFlowExperimentConfig(
                    tradeflow_path=str(source),
                    symbols=symbols,
                    strategy_symbol="ETHUSDT",
                    min_feature_coverage=0.9,
                ),
                contract=contract,
                bars_by_symbol=bars_by_symbol,
                funding=[],
            )
            output = Path(tmp) / "experiment.json"
            written = write_tradeflow_experiment_artifact(
                Settings.from_env(), artifact, explicit_path=str(output)
            )
            output_exists = output.exists()
        self.assertEqual(artifact["decision_contract"]["selection_trials"], 1)
        self.assertFalse(artifact["decision_contract"]["frozen_before_independent_oos"])
        self.assertGreater(artifact["diagnostics"]["execution"]["entry_count"], 0)
        self.assertLessEqual(artifact["diagnostics"]["execution"]["max_rolling_24h_turnover"], 2.0)
        self.assertIn("exchange_filter_coverage_incomplete", artifact["diagnostics"]["blockers"])
        self.assertTrue(output_exists)
        self.assertEqual(written["artifact_path"], str(output))

    def test_historical_oos_scores_only_explicit_evaluation_month(self) -> None:
        count = 31 * 24 + 48
        rows = _five_minute_rows([0.1 * math.sin(index / 5.0) for index in range(count)])
        payload = {
            "schema_version": HISTORICAL_TRADEFLOW_VERSION,
            "meta": {"replayable": True},
            "diagnostics": {"verdict": "pass_data_smoke"},
            "five_minute_features": rows,
        }
        contract = FrozenTradeFlowContract(
            normalization_lookback_hours=4,
            entry_zscore=1.0,
            holding_hours=2,
            cooldown_hours=22,
            beta_lookback_hours=5,
            minimum_rank_ic=-1.0,
            minimum_entry_count=1,
        )
        symbols = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
        bars_by_symbol = {symbol: _bars(symbol, count + 1) for symbol in symbols}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "tradeflow.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            artifact = build_tradeflow_experiment(
                TradeFlowExperimentConfig(
                    tradeflow_path=str(source),
                    symbols=symbols,
                    strategy_symbol="ETHUSDT",
                    start_month="2024-01",
                    end_month="2024-02",
                    evaluation_start_month="2024-02",
                    evaluation_end_month="2024-02",
                    holdout_role="historical_oos",
                    min_feature_coverage=0.9,
                ),
                contract=contract,
                bars_by_symbol=bars_by_symbol,
                funding=[],
            )
        self.assertTrue(all(int(row["ts"]) >= 1_706_745_600_000 for row in artifact["periods"]))
        self.assertEqual(artifact["diagnostics"]["holdout_role"], "historical_oos")
        self.assertTrue(artifact["diagnostics"]["independent_oos_status"].startswith("consumed_once_"))
        self.assertFalse(artifact["diagnostics"]["advance_to_independent_oos"])


if __name__ == "__main__":
    unittest.main()
