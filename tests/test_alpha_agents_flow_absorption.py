from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.alpha_agents.flow_absorption import FLOW_ABSORPTION_VERSION
from qount.alpha_agents.flow_absorption import FROZEN_FLOW_ABSORPTION_CONTRACT
from qount.alpha_agents.flow_absorption import FROZEN_FLOW_ABSORPTION_PROTOCOL
from qount.alpha_agents.flow_absorption import _apply_flow_absorption_signal
from qount.alpha_agents.flow_absorption import build_flow_absorption_discovery_report
from qount.alpha_agents.flow_absorption import build_flow_absorption_preregistration
from qount.alpha_agents.tradeflow_experiment import TRADEFLOW_EXPERIMENT_VERSION
from qount.alpha_agents.tradeflow_experiment import TradeFlowExperimentConfig
from qount.grid.data import Bar


START_MS = 1_704_067_200_000
HOUR_MS = 3_600_000


def _bar(ts_ms: int, open_price: float, close_price: float) -> Bar:
    return Bar(
        ts_ms=ts_ms,
        open=open_price,
        high=max(open_price, close_price),
        low=min(open_price, close_price),
        close=close_price,
        volume=100.0,
    )


def _experiment(symbol: str, *, rank_ic: float, residual: float, passed: bool) -> dict:
    return {
        "schema_version": TRADEFLOW_EXPERIMENT_VERSION,
        "config": {"strategy_symbol": symbol},
        "decision_contract": {"contract_hash": FROZEN_FLOW_ABSORPTION_CONTRACT.contract_hash},
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


class FlowAbsorptionTest(unittest.TestCase):
    def test_absorbed_buy_flow_becomes_short_reversal_signal(self) -> None:
        symbols = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
        aligned = []
        eth_close = 2_000.0
        btc_close = 40_000.0
        for index in range(30):
            ts_ms = START_MS + index * HOUR_MS
            eth_open = eth_close
            btc_open = btc_close
            eth_close *= 1.001
            btc_close *= 1.001
            if index == 24:
                eth_close = eth_open * 0.99
                btc_close = btc_open * 1.001
            aligned.append(
                (
                    ts_ms,
                    {
                        "BTCUSDT": _bar(ts_ms, btc_open, btc_close),
                        "ETHUSDT": _bar(ts_ms, eth_open, eth_close),
                        "BNBUSDT": _bar(ts_ms, 300.0, 300.0),
                        "SOLUSDT": _bar(ts_ms, 100.0, 100.0),
                    },
                )
            )
        hourly = [
            {
                "hour_ts_ms": START_MS + 24 * HOUR_MS,
                "decision_ts_ms": START_MS + 25 * HOUR_MS,
                "signal_zscore": 2.5,
            }
        ]
        transformed = _apply_flow_absorption_signal(
            hourly,
            aligned,
            TradeFlowExperimentConfig(
                tradeflow_path="unused.json",
                symbols=symbols,
                strategy_symbol="ETHUSDT",
            ),
            FROZEN_FLOW_ABSORPTION_CONTRACT,
        )
        self.assertTrue(transformed[0]["flow_absorbed"])
        self.assertLess(transformed[0]["completed_hour_beta_residual_return_pct"], 0.0)
        self.assertEqual(transformed[0]["signal_zscore"], -2.5)

    def test_discovery_report_enforces_registered_symbol_denominator(self) -> None:
        preregistration = build_flow_absorption_preregistration()
        self.assertEqual(preregistration["schema_version"], FLOW_ABSORPTION_VERSION)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prereg_path = root / "prereg.json"
            prereg_path.write_text(json.dumps(preregistration), encoding="utf-8")
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
            report = build_flow_absorption_discovery_report(
                preregistration_path=prereg_path,
                experiment_paths=paths,
            )
            missing_report = build_flow_absorption_discovery_report(
                preregistration_path=prereg_path,
                experiment_paths=paths[:2],
            )
        self.assertEqual(
            report["protocol"]["protocol_hash"], FROZEN_FLOW_ABSORPTION_PROTOCOL.protocol_hash
        )
        self.assertEqual(report["diagnostics"]["verdict"], "advance_to_reserved_oos_preregistration")
        self.assertEqual(missing_report["diagnostics"]["verdict"], "block_discovery")
        self.assertIn("registered_symbol_missing", missing_report["diagnostics"]["blockers"])


if __name__ == "__main__":
    unittest.main()
