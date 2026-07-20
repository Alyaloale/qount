from __future__ import annotations

import json
import unittest

from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_funding_veto import STRONG_BULL_FUNDING_VETO
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_BOOSTED
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_LATCHED_BASE
from qount.mini_trend.macro_h41_model import MACRO_H41_MODEL_VERSION
from qount.mini_trend.regime_macro_boost_veto import STRONG_BULL_MACRO_VETO
from qount.mini_trend.regime_macro_boost_veto import MacroBoostVetoConfig
from qount.mini_trend.regime_macro_boost_veto import MacroBoostVetoSelector
from qount.mini_trend.regime_macro_boost_veto import build_macro_boost_veto_preregistration
from qount.mini_trend.regime_macro_boost_veto import validate_macro_boost_veto_preregistration


_T0 = 1_609_459_200_000
_DAY = 86_400_000


def _series() -> list[Bar]:
    return [
        Bar(
            _T0 + index * _DAY,
            100.0 + index,
            (100.0 + index) * 1.01,
            (100.0 + index) * 0.99,
            100.0 + index,
            1000.0,
        )
        for index in range(240)
    ]


def _bars() -> dict[str, list[Bar]]:
    return {symbol: _series() for symbol in TOP3}


def _funding(rate: float) -> dict[str, list[Funding]]:
    bar_open = _series()[-1].ts_ms
    return {
        symbol: [
            Funding(bar_open + 8 * 3_600_000, rate),
            Funding(bar_open + 16 * 3_600_000, rate),
            Funding(bar_open + _DAY, rate),
        ]
        for symbol in TOP3
    }


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {"symbol": symbol, "status": "TRADING", "min_qty": "0.001", "min_notional": "5"}
            for symbol in TOP3
        ],
    }


def _audit() -> dict:
    return {
        "schema_version": MACRO_H41_MODEL_VERSION,
        "diagnostics": {"verdict": "retain_h41_macro_features_for_strategy_ablation"},
        "retained_trial_ids": ["h41_fed_assets_4w_change_pct"],
        "contract": {"contract_hash": "macro-contract"},
        "data_lineage": {"h41_data_hash": "h41-data"},
        "trials": [
            {
                "trial_id": "h41_fed_assets_4w_change_pct",
                "folds": [{"purge_check_passed": True}],
                "prediction_rows": [
                    {"decision_date": "2023-01-01", "predicted": -0.5, "actual": 0.2},
                    {"decision_date": "2023-01-02", "predicted": 0.5, "actual": -0.2},
                ],
            }
        ],
    }


class MiniTrendRegimeMacroBoostVetoTest(unittest.TestCase):
    def test_nonpositive_macro_score_vetoes_only_the_boost(self) -> None:
        date = _series()[-1].date
        selector = MacroBoostVetoSelector(_funding(0.0001), {date: -0.1})
        config, stage = selector(_bars())
        self.assertEqual(stage, STRONG_BULL_MACRO_VETO)
        self.assertEqual(config.vol_target, 0.015)
        self.assertEqual(selector.summary()["macro_vetoed_bar_count"], 1)

    def test_positive_macro_score_keeps_the_boost(self) -> None:
        date = _series()[-1].date
        selector = MacroBoostVetoSelector(_funding(0.0001), {date: 0.1})
        config, stage = selector(_bars())
        self.assertEqual(stage, STRONG_BULL_BOOSTED)
        self.assertEqual(config.vol_target, 0.020)

    def test_funding_veto_takes_precedence(self) -> None:
        date = _series()[-1].date
        selector = MacroBoostVetoSelector(_funding(0.0005), {date: -0.1})
        config, stage = selector(_bars())
        self.assertEqual(stage, STRONG_BULL_FUNDING_VETO)
        self.assertEqual(config.vol_target, 0.015)
        self.assertEqual(selector.summary()["macro_boost_eligible_bar_count"], 0)

    def test_stop_on_macro_veto_bar_still_latches(self) -> None:
        date = _series()[-1].date
        selector = MacroBoostVetoSelector(_funding(0.0001), {date: -0.1})
        stage = selector(_bars())[1]
        selector.observe_stops(stage, {"BTCUSDT"})
        self.assertEqual(selector(_bars())[1], STRONG_BULL_LATCHED_BASE)

    def test_preregistration_binds_scores_and_rules(self) -> None:
        preregistration = build_macro_boost_veto_preregistration(_audit(), _rules())
        config = MacroBoostVetoConfig()
        validate_macro_boost_veto_preregistration(
            preregistration, _audit(), _rules(), config
        )
        self.assertFalse(preregistration["meta"]["strategy_results_evaluated"])
        self.assertEqual(preregistration["contract"]["trial_count"], 1)
        self.assertEqual(preregistration["contract"]["cumulative_trial_count"], 142)
        changed = json.loads(json.dumps(_audit()))
        changed["trials"][0]["prediction_rows"][0]["predicted"] = -0.4
        with self.assertRaisesRegex(ValueError, "audit hash mismatch"):
            validate_macro_boost_veto_preregistration(
                preregistration, changed, _rules(), config
            )


if __name__ == "__main__":
    unittest.main()
