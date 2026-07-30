from __future__ import annotations

import json
import math
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from qount.alpha_agents.exchange_rules import SymbolRules
from qount.alpha_agents.historical_dvol import HISTORICAL_DVOL_VERSION
from qount.alpha_agents.options_dvol import OPTIONS_DVOL_EXPERIMENT_VERSION
from qount.alpha_agents.options_dvol import OptionsDvolExperimentConfig
from qount.alpha_agents.options_dvol import build_dvol_hourly_signals
from qount.alpha_agents.options_dvol import build_options_dvol_discovery_report
from qount.alpha_agents.options_dvol import build_options_dvol_experiment
from qount.alpha_agents.source_capacity import SOURCE_CAPACITY_VERSION
from qount.alpha_agents.source_capacity import FrozenOptionsDvolContract
from qount.alpha_agents.source_capacity import OptionsDvolProtocol
from qount.alpha_agents.source_capacity import build_options_dvol_preregistration
from qount.research_data.market_data import Bar


START_MS = 1_704_067_200_000
HOUR_MS = 3_600_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")


def _capacity() -> dict:
    return {
        "schema_version": SOURCE_CAPACITY_VERSION,
        "artifact_type": "source_capacity_matrix",
        "meta": {"data_hash": "capacity"},
        "diagnostics": {
            "verdict": "select_single_g0_candidate",
            "selected_candidate_id": "deribit_options_dvol_relative_stress",
            "strategy_results_evaluated": False,
        },
        "candidates": [
            {
                "candidate_id": "deribit_options_dvol_relative_stress",
                "status": "eligible_g0",
                "blockers": [],
            }
        ],
    }


def _dvol_rows(count: int) -> list[dict]:
    rows = []
    for index in range(count):
        spread = math.sin(index / 8.0) * 5.0
        rows.append(
            {
                "ts_ms": START_MS + index * HOUR_MS,
                "decision_ts_ms": START_MS + (index + 1) * HOUR_MS,
                "eth_minus_btc_dvol_close": spread,
                "complete": True,
            }
        )
    return rows


def _bars(symbol: str, count: int) -> list[Bar]:
    base = {"BTCUSDT": 40_000.0, "ETHUSDT": 2_000.0, "BNBUSDT": 300.0, "SOLUSDT": 100.0}[symbol]
    multiplier = {"BTCUSDT": 1.0, "ETHUSDT": 0.7, "BNBUSDT": 0.5, "SOLUSDT": 0.9}[symbol]
    result = []
    price = base
    for index in range(count):
        next_price = price * (1.0 + multiplier * math.sin(index / 9.0) * 0.001)
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


def _rules(symbol: str) -> SymbolRules:
    return SymbolRules(
        symbol=symbol,
        status="TRADING",
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        tick_size=Decimal("0.01"),
        min_price=Decimal("0.01"),
        max_price=Decimal("1000000"),
        step_size=Decimal("0.001"),
        market_step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal("1000000"),
        min_notional=Decimal("5"),
        source_market="um",
    )


class OptionsDvolTest(unittest.TestCase):
    def test_signal_uses_only_prior_window_and_reversion_polarity(self) -> None:
        contract = FrozenOptionsDvolContract(
            normalization_lookback_hours=2,
            normalization_min_periods=2,
        )
        rows = [
            {"ts_ms": START_MS + index * HOUR_MS, "decision_ts_ms": START_MS + (index + 1) * HOUR_MS, "eth_minus_btc_dvol_close": value, "complete": True}
            for index, value in enumerate((1.0, 3.0, 5.0))
        ]
        signals = build_dvol_hourly_signals(rows, contract=contract)
        self.assertIsNone(signals[0]["signal_zscore"])
        self.assertIsNone(signals[1]["signal_zscore"])
        self.assertAlmostEqual(signals[2]["signal_zscore"], -3.0)

    def test_builds_bound_experiment_with_price_and_filter_gates(self) -> None:
        contract = FrozenOptionsDvolContract(
            normalization_lookback_hours=2,
            normalization_min_periods=2,
            beta_lookback_hours=5,
            entry_zscore=0.5,
            holding_hours=2,
            cooldown_hours=1,
            minimum_entry_count_per_symbol=1,
        )
        protocol = OptionsDvolProtocol(
            discovery_window="2024-01-01T00:00:00Z..2024-01-31T23:00:00Z",
            historical_replication_window="2024-02-01T00:00:00Z..2024-02-29T23:00:00Z",
            reserved_forward_oos_window="2027-01-01T00:00:00Z..2027-01-31T23:00:00Z",
            contract_hash=contract.contract_hash,
            minimum_symbol_rank_ic=-1.0,
            minimum_symbol_net_residual_pct=-1_000.0,
            minimum_median_rank_ic=-1.0,
            minimum_mean_net_residual_pct=-1_000.0,
            minimum_feature_coverage=0.99,
            minimum_price_coverage=1.0,
            maximum_rolling_24h_turnover=24.0,
        )
        count = 31 * 24
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capacity_path = root / "capacity.json"
            capacity_path.write_text(json.dumps(_capacity()), encoding="utf-8")
            preregistration = build_options_dvol_preregistration(
                capacity_path, protocol=protocol, contract=contract
            )
            prereg_path = root / "prereg.json"
            prereg_path.write_text(json.dumps(preregistration), encoding="utf-8")
            dvol = {
                "schema_version": HISTORICAL_DVOL_VERSION,
                "artifact_type": "historical_dvol_dataset",
                "meta": {"data_hash": "dvol", "strategy_results_evaluated": False},
                "config": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
                "diagnostics": {"verdict": "pass_dataset"},
                "hourly_features": _dvol_rows(count),
            }
            dvol_path = root / "dvol.json"
            dvol_path.write_text(json.dumps(dvol), encoding="utf-8")
            artifact = build_options_dvol_experiment(
                OptionsDvolExperimentConfig(
                    dvol_path=str(dvol_path),
                    preregistration_path=str(prereg_path),
                    start_month="2024-01",
                    end_month="2024-01",
                    strategy_symbol="ETHUSDT",
                ),
                contract=contract,
                protocol=protocol,
                bars_by_symbol={symbol: _bars(symbol, count) for symbol in SYMBOLS},
                funding=[],
                rules_by_symbol={symbol: _rules(symbol) for symbol in SYMBOLS},
            )
        self.assertEqual(artifact["schema_version"], OPTIONS_DVOL_EXPERIMENT_VERSION)
        self.assertEqual(artifact["source_bindings"]["preregistration_path"], str(prereg_path.resolve()))
        self.assertEqual(artifact["diagnostics"]["price_coverage"]["aligned_coverage_ratio"], 1.0)
        self.assertEqual(artifact["diagnostics"]["filter_diagnostics"]["filter_coverage"], 1.0)
        self.assertGreater(artifact["diagnostics"]["execution"]["entry_count"], 0)
        self.assertFalse(artifact["diagnostics"]["promotion_allowed"])

    def test_report_enforces_three_symbol_denominator(self) -> None:
        protocol = OptionsDvolProtocol()
        prereg = {
            "schema_version": "alpha_agent_options_dvol_preregistration_v0.3",
            "artifact_type": "preregistration",
            "protocol": {"protocol_hash": protocol.protocol_hash},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prereg_path = root / "prereg.json"
            prereg_path.write_text(json.dumps(prereg), encoding="utf-8")
            paths = []
            for symbol in protocol.discovery_symbols:
                payload = {
                    "schema_version": OPTIONS_DVOL_EXPERIMENT_VERSION,
                    "artifact_type": "experiment",
                    "config": {"strategy_symbol": symbol},
                    "decision_contract": {"contract_hash": protocol.contract_hash},
                    "protocol": {"protocol_hash": protocol.protocol_hash},
                    "diagnostics": {
                        "holdout_role": protocol.discovery_holdout_role,
                        "verdict": "pass_discovery_symbol",
                        "blockers": [],
                        "ic": {"rank_ic": 0.03},
                        "score": {"net_residual_return_pct": 2.0},
                        "execution": {"entry_count": 20, "max_rolling_24h_turnover": 2.0},
                        "filter_diagnostics": {"filter_coverage": 1.0},
                        "feature_coverage": 1.0,
                        "price_coverage": {"aligned_coverage_ratio": 1.0},
                    },
                }
                path = root / f"{symbol}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths.append(path)
            report = build_options_dvol_discovery_report(
                preregistration_path=prereg_path,
                experiment_paths=paths,
                protocol=protocol,
            )
        self.assertEqual(report["diagnostics"]["verdict"], "advance_to_replication_authorization")
        self.assertFalse(report["diagnostics"]["historical_replication_consumed"])


if __name__ == "__main__":
    unittest.main()
