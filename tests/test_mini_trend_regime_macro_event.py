from __future__ import annotations

import json
import unittest

from qount.research_data.market_data import Bar
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.regime_macro_event import MACRO_EVENT_SPECS
from qount.mini_trend.regime_macro_event import MacroEventConfig
from qount.mini_trend.regime_macro_event import MacroEventTransform
from qount.mini_trend.regime_macro_event import build_macro_event_preregistration
from qount.mini_trend.regime_macro_event import validate_macro_event_preregistration
from qount.mini_trend.signals import target_weights


_T0 = 1_609_459_200_000
_DAY = 86_400_000


def _bars(closes: list[float]) -> dict[str, list[Bar]]:
    rows = [
        Bar(_T0 + index * _DAY, close, close * 1.01, close * 0.99, close, 1000.0)
        for index, close in enumerate(closes)
    ]
    return {symbol: list(rows) for symbol in TOP3}


def _feature(value: float, decision_date: str = "2021-01-01") -> dict:
    return {
        "decision_date": decision_date,
        "release_date": "2020-12-31",
        "observation_date": "2020-12-30",
        "fed_assets_4w_change_pct": value,
    }


def _dataset() -> dict:
    return {
        "meta": {"point_in_time": True},
        "diagnostics": {"verdict": "pass_point_in_time_macro_dataset"},
        "contract": {"contract_hash": "contract"},
        "data_hash": "data",
        "weekly_features": [_feature(0.01)],
    }


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {
                "symbol": symbol,
                "status": "TRADING",
                "min_qty": "0.001",
                "min_notional": "5",
            }
            for symbol in TOP3
        ],
    }


class MiniTrendRegimeMacroEventTest(unittest.TestCase):
    def test_contract_adds_exactly_three_trials(self) -> None:
        config = MacroEventConfig()
        self.assertEqual(config.trial_count, 3)
        self.assertEqual(config.cumulative_trial_count, 141)

    def test_contraction_blocks_new_entries_but_not_existing_positions(self) -> None:
        bars = _bars([100.0 + index for index in range(205)])
        desired = target_weights(bars, frozen_top3_config()).targets
        transform = MacroEventTransform([_feature(-0.01)], MACRO_EVENT_SPECS[0])
        blocked = transform(
            bars,
            frozen_top3_config(),
            desired,
            {symbol: 0.0 for symbol in TOP3},
        )
        self.assertTrue(any(value > 0 for value in desired.values()))
        self.assertTrue(all(value == 0 for value in blocked.values()))
        held = transform(bars, frozen_top3_config(), desired, desired)
        self.assertEqual(held, desired)

    def test_expansion_delays_only_master_gate_exit(self) -> None:
        bars = _bars([300.0 - index for index in range(205)])
        desired = target_weights(bars, frozen_top3_config())
        self.assertFalse(desired.gate.risk_on)
        previous = {symbol: 0.1 for symbol in TOP3}
        transform = MacroEventTransform([_feature(0.01)], MACRO_EVENT_SPECS[1])
        held = transform(bars, frozen_top3_config(), desired.targets, previous)
        self.assertEqual(held, previous)

    def test_preregistration_binds_h41_and_rules(self) -> None:
        preregistration = build_macro_event_preregistration(_dataset(), _rules())
        validate_macro_event_preregistration(
            preregistration, _dataset(), _rules(), MacroEventConfig()
        )
        changed = json.loads(json.dumps(_dataset()))
        changed["data_hash"] = "changed"
        with self.assertRaisesRegex(ValueError, "data hash mismatch"):
            validate_macro_event_preregistration(
                preregistration, changed, _rules(), MacroEventConfig()
            )


if __name__ == "__main__":
    unittest.main()
