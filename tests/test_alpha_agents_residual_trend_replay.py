from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from qount.alpha_agents.residual_trend_model import FEATURE_NAMES
from qount.alpha_agents.residual_trend_replay import FROZEN_RESIDUAL_TREND_REPLAY_PROTOCOL
from qount.alpha_agents.residual_trend_replay import RESIDUAL_TREND_REPLAY_VERSION
from qount.alpha_agents.residual_trend_replay import build_residual_trend_replay_preregistration
from qount.alpha_agents.residual_trend_replay import build_residual_trend_replay_report
from qount.alpha_agents.residual_trend_replay import predict_from_frozen_model
from qount.alpha_agents.residual_trend_replay import _audit_price_bars
from qount.research_data.market_data import Bar


def _model_card() -> dict:
    return {
        "feature_names": list(FEATURE_NAMES),
        "scaler_mean": [0.0] * len(FEATURE_NAMES),
        "scaler_scale": [1.0] * len(FEATURE_NAMES),
        "coefficients": {
            name: (1.0 if index == 0 else 0.0)
            for index, name in enumerate(FEATURE_NAMES)
        },
        "intercept": 0.0,
    }


def _replay(symbol: str, anchor_hash: str) -> dict:
    return {
        "schema_version": RESIDUAL_TREND_REPLAY_VERSION,
        "artifact_type": "temporal_model_replay",
        "config": {"strategy_symbol": symbol},
        "meta": {
            "protocol_hash": "replaced-in-test",
            "anchor_model_sha256": anchor_hash,
        },
        "diagnostics": {
            "verdict": "temporal_stress_failed_no_promotion",
            "diagnostic_blockers": ["auc_below_frozen_gate"],
            "prediction": {"auc": 0.5, "rank_ic": 0.0, "brier_improvement": -0.01},
            "score": {"net_residual_return_pct": -1.0},
            "execution": {"entry_count": 10, "max_rolling_24h_turnover": 2.0},
            "filter_diagnostics": {"filter_coverage": 1.0},
            "anti_overfit": {"deflated_sharpe_ratio": 0.1, "pbo": 1.0},
        },
    }


class ResidualTrendReplayTest(unittest.TestCase):
    def test_price_audit_is_cross_symbol_and_window_bounded(self) -> None:
        start_ms = 1_735_689_600_000
        bars = {
            symbol: [
                Bar(ts_ms=start_ms + index * 3_600_000, open=1, high=1, low=1, close=1, volume=1)
                for index in range(24 - (1 if symbol == "ETHUSDT" else 0))
            ]
            for symbol in ("BTCUSDT", "ETHUSDT")
        }
        audit = _audit_price_bars(
            bars,
            ("BTCUSDT", "ETHUSDT"),
            start_ms=start_ms,
            end_ms=start_ms + 24 * 3_600_000,
        )
        self.assertEqual(audit["by_symbol"]["BTCUSDT"]["coverage"], 1.0)
        self.assertAlmostEqual(audit["minimum_coverage"], 23 / 24)

    def test_manual_frozen_probability_uses_saved_scaler_and_coefficients(self) -> None:
        rows = [
            {"feature_values": [0.0] * len(FEATURE_NAMES)},
            {"feature_values": [2.0] + [0.0] * (len(FEATURE_NAMES) - 1)},
            {"feature_values": [-2.0] + [0.0] * (len(FEATURE_NAMES) - 1)},
        ]
        probabilities = predict_from_frozen_model(_model_card(), rows)
        self.assertAlmostEqual(probabilities[0], 0.5)
        self.assertAlmostEqual(probabilities[1], 1.0 / (1.0 + math.exp(-2.0)))
        self.assertAlmostEqual(probabilities[2], 1.0 / (1.0 + math.exp(2.0)))

    def test_preregistration_forbids_refit_and_keeps_promotion_closed(self) -> None:
        preregistration = build_residual_trend_replay_preregistration()
        diagnostics = preregistration["diagnostics"]
        self.assertFalse(diagnostics["refit_allowed"])
        self.assertFalse(diagnostics["recalibration_allowed"])
        self.assertFalse(diagnostics["promotion_allowed"])
        self.assertFalse(diagnostics["a10_sequence_enabled"])
        self.assertEqual(diagnostics["pbo"], 1.0)
        self.assertEqual(len(preregistration["protocol"]["anchor_model_sha256"]), 3)

    def test_report_is_non_promotional_even_when_all_replays_are_present(self) -> None:
        hashes = tuple(
            (symbol, hashlib.sha256(symbol.encode()).hexdigest())
            for symbol in ("ETHUSDT", "BNBUSDT", "SOLUSDT")
        )
        protocol = replace(
            FROZEN_RESIDUAL_TREND_REPLAY_PROTOCOL,
            anchor_model_sha256=hashes,
        )
        preregistration = build_residual_trend_replay_preregistration(protocol)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prereg_path = root / "prereg.json"
            prereg_path.write_text(json.dumps(preregistration), encoding="utf-8")
            replay_paths = []
            for symbol, anchor_hash in hashes:
                payload = _replay(symbol, anchor_hash)
                payload["meta"]["protocol_hash"] = protocol.protocol_hash
                path = root / f"{symbol}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                replay_paths.append(path)
            report = build_residual_trend_replay_report(
                preregistration_path=prereg_path,
                replay_paths=replay_paths,
                protocol=protocol,
            )
        diagnostics = report["diagnostics"]
        self.assertEqual(diagnostics["verdict"], "temporal_replay_complete_no_promotion")
        self.assertFalse(diagnostics["promotion_allowed"])
        self.assertFalse(diagnostics["anchor_failure_reversible"])
        self.assertFalse(diagnostics["a10_sequence_enabled"])
        self.assertEqual(diagnostics["pbo"], 1.0)


if __name__ == "__main__":
    unittest.main()
