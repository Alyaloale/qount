from __future__ import annotations

import datetime as dt
import json
import math
import tempfile
import unittest
from pathlib import Path

from qount.alpha_agents.tradeflow_experiment import FROZEN_LOW_TURNOVER_CONTRACT
from qount.alpha_agents.tradeflow_experiment import TRADEFLOW_EXPERIMENT_VERSION
from qount.alpha_agents.tradeflow_replication import FROZEN_REPLICATION_PROTOCOL
from qount.alpha_agents.tradeflow_replication import assert_replication_matches_anchor
from qount.alpha_agents.tradeflow_replication import build_tradeflow_replication_preregistration
from qount.alpha_agents.tradeflow_replication import build_tradeflow_replication_report
from qount.alpha_agents.tradeflow_replication import replication_meta


START = dt.datetime(2024, 4, 1, tzinfo=dt.UTC)


def _experiment(symbol: str, role: str, returns: list[float]) -> dict:
    verdict = "advance_to_independent_oos" if role == "discovery" else "pass_independent_oos"
    return {
        "schema_version": TRADEFLOW_EXPERIMENT_VERSION,
        "config": {"strategy_symbol": symbol},
        "decision_contract": {"contract_hash": FROZEN_LOW_TURNOVER_CONTRACT.contract_hash},
        "diagnostics": {
            "holdout_role": role,
            "verdict": verdict,
            "blockers": [],
            "ic": {"rank_ic": 0.03},
            "score": {"net_residual_return_pct": sum(returns)},
            "execution": {"entry_count": 12, "max_rolling_24h_turnover": 2.0},
            "filter_diagnostics": {"filter_coverage": 1.0},
        },
        "periods": [
            {
                "ts": str(int((START + dt.timedelta(days=index)).timestamp() * 1000)),
                "strategy_return_pct": value,
                "btc_return_pct": 0.05 if index % 2 else -0.05,
            }
            for index, value in enumerate(returns)
        ],
    }


def _returns(symbol_index: int) -> list[float]:
    return [
        0.20
        + 0.08 * math.sin((index + 1) * (symbol_index + 1) * 0.73)
        + 0.03 * math.cos((index + 2) * (symbol_index + 2) * 0.41)
        for index in range(30)
    ]


class TradeFlowReplicationTest(unittest.TestCase):
    def test_preregistration_is_frozen_before_replication_data(self) -> None:
        payload = build_tradeflow_replication_preregistration()
        self.assertEqual(payload["diagnostics"]["verdict"], "preregistered")
        self.assertFalse(payload["diagnostics"]["replication_data_consumed"])
        self.assertFalse(payload["diagnostics"]["parameter_tuning_allowed"])
        self.assertEqual(payload["protocol"]["protocol_hash"], FROZEN_REPLICATION_PROTOCOL.protocol_hash)

    def test_positive_replication_panel_passes_correlation_stress(self) -> None:
        symbols = ("ETHUSDT", "BTCUSDT", "BNBUSDT", "SOLUSDT")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preregistration = root / "preregistration.json"
            preregistration.write_text(
                json.dumps(build_tradeflow_replication_preregistration()), encoding="utf-8"
            )
            discovery_paths: dict[str, str] = {}
            oos_paths: dict[str, str] = {}
            for index, symbol in enumerate(symbols):
                discovery = root / f"{symbol}-discovery.json"
                oos = root / f"{symbol}-oos.json"
                values = _returns(index)
                discovery.write_text(json.dumps(_experiment(symbol, "discovery", values)), encoding="utf-8")
                oos.write_text(json.dumps(_experiment(symbol, "historical_oos", values)), encoding="utf-8")
                discovery_paths[symbol] = str(discovery)
                oos_paths[symbol] = str(oos)
            report = build_tradeflow_replication_report(
                preregistration_path=preregistration,
                anchor_discovery_path=discovery_paths["ETHUSDT"],
                anchor_oos_path=oos_paths["ETHUSDT"],
                replica_discovery_paths={symbol: discovery_paths[symbol] for symbol in symbols[1:]},
                replica_oos_paths={symbol: oos_paths[symbol] for symbol in symbols[1:]},
            )
            assert_replication_matches_anchor(report, oos_paths["ETHUSDT"])
        self.assertEqual(report["diagnostics"]["verdict"], "pass_correlation_stress")
        self.assertGreaterEqual(
            report["diagnostics"]["correlation_stress"]["effective_breadth"], 2.0
        )
        self.assertTrue(replication_meta(report)["correlation_stress_pass"])
        self.assertEqual(report["diagnostics"]["g4_pbo_unchanged"], 1.0)

    def test_missing_replica_discovery_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preregistration = root / "preregistration.json"
            preregistration.write_text(
                json.dumps(build_tradeflow_replication_preregistration()), encoding="utf-8"
            )
            anchor_discovery = root / "anchor-discovery.json"
            anchor_oos = root / "anchor-oos.json"
            values = _returns(0)
            anchor_discovery.write_text(
                json.dumps(_experiment("ETHUSDT", "discovery", values)), encoding="utf-8"
            )
            anchor_oos.write_text(
                json.dumps(_experiment("ETHUSDT", "historical_oos", values)), encoding="utf-8"
            )
            report = build_tradeflow_replication_report(
                preregistration_path=preregistration,
                anchor_discovery_path=anchor_discovery,
                anchor_oos_path=anchor_oos,
                replica_discovery_paths={},
                replica_oos_paths={},
            )
        self.assertEqual(report["diagnostics"]["verdict"], "block_correlation_stress")
        self.assertIn("replica_discovery_missing", report["diagnostics"]["blockers"])


if __name__ == "__main__":
    unittest.main()
