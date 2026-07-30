from __future__ import annotations

import json
import unittest

from qount.research_data.market_data import Bar
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_episode_attribution import BASE_EPISODE_REPORT_VERSION
from qount.mini_trend.futures_signal_exit_cooldown import SignalExitCooldownConfig
from qount.mini_trend.futures_signal_exit_cooldown import SignalExitCooldownTransform
from qount.mini_trend.futures_signal_exit_cooldown import build_signal_exit_cooldown_preregistration
from qount.mini_trend.futures_signal_exit_cooldown import rapid_reentry_audit
from qount.mini_trend.futures_signal_exit_cooldown import validate_signal_exit_cooldown_preregistration


_T0 = 1_609_459_200_000
_DAY = 86_400_000


def _series(rising: bool = True) -> list[Bar]:
    closes = [100.0 + index if rising else 400.0 - index for index in range(240)]
    return [
        Bar(_T0 + index * _DAY, close, close * 1.01, close * 0.99, close, 1000.0)
        for index, close in enumerate(closes)
    ]


def _bars(rising: bool = True) -> dict[str, list[Bar]]:
    return {symbol: _series(rising) for symbol in TOP3}


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {"symbol": symbol, "status": "TRADING", "min_qty": "0.001", "min_notional": "5"}
            for symbol in TOP3
        ],
    }


def _episode_artifact() -> dict:
    return {
        "schema_version": BASE_EPISODE_REPORT_VERSION,
        "contract": {"contract_hash": "episode-contract"},
        "diagnostics": {
            "verdict": "base_episode_attribution_complete",
            "qualified_exit_reasons": ["signal_or_allocation_exit"],
        },
        "episodes": [
            {
                "episode_id": "BTCUSDT-001",
                "symbol": "BTCUSDT",
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-03",
                "exit_reason": "signal_or_allocation_exit",
                "net_pnl_usdt": -1.0,
                "holding_bars": 2,
            },
            {
                "episode_id": "BTCUSDT-002",
                "symbol": "BTCUSDT",
                "entry_date": "2025-01-05",
                "exit_date": "2025-01-06",
                "exit_reason": "signal_or_allocation_exit",
                "net_pnl_usdt": -2.0,
                "holding_bars": 1,
            },
        ],
    }


class MiniTrendFuturesSignalExitCooldownTest(unittest.TestCase):
    def test_reuses_three_completed_bars_before_reentry(self) -> None:
        transform = SignalExitCooldownTransform(3)
        desired_exit = {symbol: (0.0 if symbol == "BTCUSDT" else 0.1) for symbol in TOP3}
        previous = {symbol: 0.1 for symbol in TOP3}
        transform(_bars(), frozen_top3_config(), desired_exit, previous)
        desired_entry = {symbol: 0.1 for symbol in TOP3}
        flat = {symbol: (0.0 if symbol == "BTCUSDT" else 0.1) for symbol in TOP3}
        for _ in range(3):
            result = transform(_bars(), frozen_top3_config(), desired_entry, flat)
            self.assertEqual(result["BTCUSDT"], 0.0)
        result = transform(_bars(), frozen_top3_config(), desired_entry, flat)
        self.assertEqual(result["BTCUSDT"], 0.1)
        self.assertEqual(transform.summary()["blocked_entry_symbol_bar_count"], 3)

    def test_master_gate_exit_does_not_start_symbol_cooldown(self) -> None:
        transform = SignalExitCooldownTransform(3)
        zero = {symbol: 0.0 for symbol in TOP3}
        previous = {symbol: 0.1 for symbol in TOP3}
        transform(_bars(False), frozen_top3_config(), zero, previous)
        self.assertEqual(transform.summary()["signal_exit_trigger_count"], 0)

    def test_rapid_reentry_audit_uses_existing_cooldown_horizon(self) -> None:
        audit = rapid_reentry_audit(_episode_artifact(), 3)
        self.assertEqual(audit["rapid_reentry_count"], 1)
        self.assertEqual(audit["rapid_reentry_positive_count"], 0)
        self.assertEqual(audit["rapid_reentry_net_pnl_usdt"], -2.0)

    def test_preregistration_binds_episode_evidence(self) -> None:
        preregistration = build_signal_exit_cooldown_preregistration(
            _episode_artifact(), _rules()
        )
        config = SignalExitCooldownConfig()
        validate_signal_exit_cooldown_preregistration(
            preregistration, _episode_artifact(), _rules(), config
        )
        self.assertEqual(preregistration["contract"]["trial_count"], 1)
        self.assertEqual(preregistration["contract"]["cumulative_trial_count"], 143)
        self.assertFalse(preregistration["meta"]["strategy_results_evaluated"])
        changed = json.loads(json.dumps(_episode_artifact()))
        changed["episodes"][1]["net_pnl_usdt"] = -1.5
        with self.assertRaisesRegex(ValueError, "episode artifact hash mismatch"):
            validate_signal_exit_cooldown_preregistration(
                preregistration, changed, _rules(), config
            )


if __name__ == "__main__":
    unittest.main()
