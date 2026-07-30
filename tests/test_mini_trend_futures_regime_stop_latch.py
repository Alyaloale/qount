from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.research_data.market_data import Bar
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_base_forward import build_futures_base_forward_preregistration
from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.futures_regime_overlay import FUTURES_REGIME_OVERLAY_PROTOCOL
from qount.mini_trend.futures_regime_overlay import TRANSITION_RANGE
from qount.mini_trend.futures_regime_stop_latch import FUTURES_REGIME_STOP_LATCH_PROTOCOL
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_BOOSTED
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_LATCHED_BASE
from qount.mini_trend.futures_regime_stop_latch import StopLatchedRegimeSelector
from qount.mini_trend.futures_regime_stop_latch import build_regime_stop_latch_preregistration
from qount.mini_trend.futures_regime_stop_latch_report import max_drawdown_interval
from qount.mini_trend.futures_regime_stop_latch_report import summarize_latch_activity
from qount.mini_trend.live_lessons import LIVE_LESSONS_VERSION


_T0 = 1_609_459_200_000
_DAY = 86_400_000


def _series(closes: list[float]) -> list[Bar]:
    return [
        Bar(_T0 + index * _DAY, close, close * 1.01, close * 0.99, close, 1000.0)
        for index, close in enumerate(closes)
    ]


def _rising() -> list[Bar]:
    return _series([100.0 + index for index in range(240)])


def _falling() -> list[Bar]:
    return _series([400.0 - index for index in range(240)])


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "raw_exchange_info_hash": "raw",
        "rules": [
            {"symbol": symbol, "status": "TRADING", "min_qty": "0.001", "min_notional": "5"}
            for symbol in TOP3
        ],
    }


def _lessons(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": LIVE_LESSONS_VERSION,
                "verdict": "audit_complete_research_only",
                "candidate_constraints": {"carry_allowed": False, "market": "um_futures"},
                "equity": {
                    "inception_to_pre_withdrawal_return_pct": -2.1,
                    "july_rebound_giveback_usdt": -25.0,
                },
                "orders": {
                    "post_inception_placed_order_count": 37,
                    "exact_duplicate_order_count": 5,
                    "same_bar_direction_flip_group_count": 8,
                },
                "operations": {"fail_closed_unknown_capital_count": 66},
            }
        ),
        encoding="utf-8",
    )


def _prior_overlay(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_type": "mini_trend_um_regime_overlay_historical_diagnostic",
                "contract_hash": FUTURES_REGIME_OVERLAY_PROTOCOL.contract_hash,
                "diagnostics": {"verdict": "reject_historical_regime_overlay"},
                "full_window": {
                    "candidate": {"return_pct": 85.94, "max_drawdown_pct": 19.30}
                },
                "segments": [
                    {
                        "label": "2025-2026",
                        "candidate": {"return_pct": -5.13, "max_drawdown_pct": 12.45},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class MiniTrendFuturesRegimeStopLatchTest(unittest.TestCase):
    def test_stop_latch_reverts_boost_until_regime_exit(self) -> None:
        selector = StopLatchedRegimeSelector()
        strong = {symbol: _rising() for symbol in TOP3}
        transition = {
            "BTCUSDT": _rising(),
            "ETHUSDT": _falling(),
            "BNBUSDT": _falling(),
        }
        config, stage = selector(strong)
        self.assertEqual(stage, STRONG_BULL_BOOSTED)
        self.assertEqual(config.vol_target, 0.020)
        selector.observe_stops(stage, {"BTCUSDT"})
        config, stage = selector(strong)
        self.assertEqual(stage, STRONG_BULL_LATCHED_BASE)
        self.assertEqual(config.vol_target, 0.015)
        self.assertEqual(selector(transition)[1], TRANSITION_RANGE)
        config, stage = selector(strong)
        self.assertEqual(stage, STRONG_BULL_BOOSTED)
        self.assertEqual(config.vol_target, 0.020)

    def test_transition_stop_does_not_latch_future_strong_bull(self) -> None:
        selector = StopLatchedRegimeSelector()
        transition = {
            "BTCUSDT": _rising(),
            "ETHUSDT": _falling(),
            "BNBUSDT": _falling(),
        }
        stage = selector(transition)[1]
        selector.observe_stops(stage, {"BTCUSDT"})
        self.assertEqual(
            selector({symbol: _rising() for symbol in TOP3})[1],
            STRONG_BULL_BOOSTED,
        )

    def test_preregistration_adds_no_numeric_signal_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lessons = root / "lessons.json"
            base_path = root / "base.json"
            prior_path = root / "prior.json"
            _lessons(lessons)
            base_path.write_text(
                json.dumps(build_futures_base_forward_preregistration(_rules(), lessons)),
                encoding="utf-8",
            )
            _prior_overlay(prior_path)
            prereg = build_regime_stop_latch_preregistration(
                _rules(), lessons, base_path, prior_path
            )
        delta = prereg["decision_contract"]["candidate_delta"]
        self.assertEqual(delta["new_numeric_thresholds"], 0)
        self.assertTrue(delta["regime_classification_unchanged"])
        self.assertEqual(delta["strong_bull_initial_vol_target"], 0.020)
        self.assertFalse(prereg["meta"]["strategy_results_evaluated"])
        self.assertEqual(
            prereg["decision_contract"]["contract_hash"],
            FUTURES_REGIME_STOP_LATCH_PROTOCOL.contract_hash,
        )

    def test_latch_activity_is_auditable_from_rows(self) -> None:
        result = VariantResult(
            metrics={},
            equity=[
                {"risk_stage": STRONG_BULL_BOOSTED, "stopped": ["BTCUSDT"]},
                {"risk_stage": STRONG_BULL_LATCHED_BASE, "stopped": []},
                {"risk_stage": STRONG_BULL_LATCHED_BASE, "stopped": ["ETHUSDT"]},
                {"risk_stage": TRANSITION_RANGE, "stopped": []},
                {"risk_stage": STRONG_BULL_BOOSTED, "stopped": []},
            ],
        )
        summary = summarize_latch_activity(result)
        self.assertEqual(summary["stop_trigger_count"], 2)
        self.assertEqual(summary["latch_entry_count"], 1)
        self.assertEqual(summary["boosted_bar_count"], 2)
        self.assertEqual(summary["latched_bar_count"], 2)

    def test_drawdown_interval_reports_peak_and_trough(self) -> None:
        result = VariantResult(
            metrics={},
            equity=[
                {"decision_date": "2025-01-01", "outcome_date": "2025-01-02", "equity": 420.0},
                {"decision_date": "2025-01-02", "outcome_date": "2025-01-03", "equity": 378.0},
                {"decision_date": "2025-01-03", "outcome_date": "2025-01-04", "equity": 400.0},
            ],
        )
        interval = max_drawdown_interval(result, 400.0)
        self.assertEqual(interval["peak_date"], "2025-01-02")
        self.assertEqual(interval["trough_date"], "2025-01-03")
        self.assertEqual(interval["drawdown_pct"], 10.0)


if __name__ == "__main__":
    unittest.main()
