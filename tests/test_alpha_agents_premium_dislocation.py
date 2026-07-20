from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from qount.alpha_agents.historical_premium import HISTORICAL_PREMIUM_VERSION
from qount.alpha_agents.premium_dislocation import PREMIUM_DISLOCATION_VERSION
from qount.alpha_agents.premium_dislocation import FROZEN_PREMIUM_DISLOCATION_CONTRACT
from qount.alpha_agents.premium_dislocation import FrozenPremiumDislocationContract
from qount.alpha_agents.premium_dislocation import PremiumDislocationConfig
from qount.alpha_agents.premium_dislocation import aggregate_premium_to_hourly
from qount.alpha_agents.premium_dislocation import build_premium_dislocation_discovery_report
from qount.alpha_agents.premium_dislocation import build_premium_dislocation_experiment
from qount.alpha_agents.premium_dislocation import build_premium_dislocation_preregistration
from qount.grid.data import Bar


START_MS = 1_704_067_200_000
HOUR_MS = 3_600_000


def _rows(hour_values: list[float]) -> list[dict]:
    rows = []
    for hour_index, premium in enumerate(hour_values):
        for bucket_index in range(12):
            rows.append(
                {
                    "symbol": "ETHUSDT",
                    "ts_ms": START_MS + hour_index * HOUR_MS + bucket_index * 300_000,
                    "premium_index_close": premium,
                    "mark_index_basis": premium,
                    "premium_minus_mark_index_basis": 0.0,
                    "complete": True,
                    "segment_id": 0,
                }
            )
    return rows


def _bars(symbol: str, count: int) -> list[Bar]:
    price = {"BTCUSDT": 40_000.0, "ETHUSDT": 2_000.0, "BNBUSDT": 300.0, "SOLUSDT": 100.0}[symbol]
    multiplier = {"BTCUSDT": 1.0, "ETHUSDT": 0.7, "BNBUSDT": 0.4, "SOLUSDT": 0.9}[symbol]
    result = []
    for index in range(count):
        change = multiplier * (0.0004 + math.sin(index / 5.0) * 0.001)
        next_price = price * (1.0 + change)
        result.append(
            Bar(
                ts_ms=START_MS + index * HOUR_MS,
                open=price,
                high=max(price, next_price),
                low=min(price, next_price),
                close=next_price,
                volume=100.0,
            )
        )
        price = next_price
    return result


def _experiment(symbol: str, *, rank_ic: float, residual: float, passed: bool) -> dict:
    return {
        "schema_version": PREMIUM_DISLOCATION_VERSION,
        "artifact_type": "experiment",
        "config": {"strategy_symbol": symbol},
        "decision_contract": {"contract_hash": FROZEN_PREMIUM_DISLOCATION_CONTRACT.contract_hash},
        "diagnostics": {
            "holdout_role": "discovery",
            "verdict": "advance_to_independent_oos" if passed else "block_discovery",
            "blockers": [] if passed else ["rank_ic_below_frozen_gate"],
            "ic": {"rank_ic": rank_ic},
            "score": {"net_residual_return_pct": residual},
            "execution": {"entry_count": 12, "max_rolling_24h_turnover": 2.0},
            "filter_diagnostics": {"filter_coverage": 1.0},
        },
    }


class PremiumDislocationTest(unittest.TestCase):
    def test_hourly_signal_uses_prior_values_and_reversion_polarity(self) -> None:
        contract = FrozenPremiumDislocationContract(normalization_lookback_hours=2)
        hourly = aggregate_premium_to_hourly(
            _rows([-0.001, 0.001, 0.003]),
            symbol="ETHUSDT",
            contract=contract,
        )
        self.assertIsNone(hourly[0]["signal_zscore"])
        self.assertIsNone(hourly[1]["signal_zscore"])
        self.assertAlmostEqual(hourly[2]["signal_zscore"], -3.0)

    def test_builds_low_turnover_experiment_from_premium_artifact(self) -> None:
        count = 75
        premiums = [0.0005 * math.sin(index / 4.0) for index in range(count)]
        for index in range(8, count, 12):
            premiums[index] = 0.01 if index % 24 else -0.01
        payload = {
            "schema_version": HISTORICAL_PREMIUM_VERSION,
            "meta": {"replayable": True},
            "diagnostics": {"verdict": "pass_data_smoke"},
            "five_minute_features": _rows(premiums),
        }
        contract = FrozenPremiumDislocationContract(
            normalization_lookback_hours=4,
            entry_zscore=1.0,
            holding_hours=6,
            cooldown_hours=18,
            beta_lookback_hours=5,
            minimum_rank_ic=-1.0,
            minimum_entry_count=1,
        )
        symbols = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "premium.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            artifact = build_premium_dislocation_experiment(
                PremiumDislocationConfig(
                    premium_path=str(source),
                    symbols=symbols,
                    strategy_symbol="ETHUSDT",
                    min_feature_coverage=0.9,
                ),
                contract=contract,
                bars_by_symbol={symbol: _bars(symbol, count + 1) for symbol in symbols},
                funding=[],
            )
        self.assertEqual(artifact["schema_version"], PREMIUM_DISLOCATION_VERSION)
        self.assertGreater(artifact["diagnostics"]["execution"]["entry_count"], 0)
        self.assertLessEqual(artifact["diagnostics"]["execution"]["max_rolling_24h_turnover"], 2.0)
        self.assertIn("exchange_filter_coverage_incomplete", artifact["diagnostics"]["blockers"])
        active = next(row for row in artifact["periods"] if row["strategy_position_applied"] != 0)
        self.assertIsNotNone(active["strategy_raw_feature_value"])

    def test_report_enforces_frozen_three_symbol_protocol(self) -> None:
        preregistration = build_premium_dislocation_preregistration()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prereg = root / "prereg.json"
            prereg.write_text(json.dumps(preregistration), encoding="utf-8")
            paths = []
            for symbol, rank_ic, residual, passed in (
                ("ETHUSDT", 0.04, 3.0, True),
                ("BNBUSDT", 0.03, 2.0, True),
                ("SOLUSDT", -0.01, -1.0, False),
            ):
                path = root / f"{symbol}.json"
                path.write_text(
                    json.dumps(_experiment(symbol, rank_ic=rank_ic, residual=residual, passed=passed)),
                    encoding="utf-8",
                )
                paths.append(path)
            report = build_premium_dislocation_discovery_report(
                preregistration_path=prereg,
                experiment_paths=paths,
            )
        self.assertEqual(report["diagnostics"]["verdict"], "advance_to_reserved_oos_preregistration")
        self.assertFalse(report["diagnostics"]["reserved_oos_consumed"])


if __name__ == "__main__":
    unittest.main()
