from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import build_futures_base_forward_preregistration
from qount.mini_trend.futures_recovery import selected_um_rules
from qount.mini_trend.futures_recovery_backtest import run_variant
from qount.mini_trend.futures_regime_overlay import BEAR_CASH
from qount.mini_trend.futures_regime_overlay import FUTURES_REGIME_OVERLAY_PROTOCOL
from qount.mini_trend.futures_regime_overlay import STRONG_BULL, TRANSITION_RANGE
from qount.mini_trend.futures_regime_overlay import build_regime_overlay_preregistration
from qount.mini_trend.futures_regime_overlay import classify_regime, regime_config_selector
from qount.mini_trend.futures_regime_overlay import control_regime_config_selector
from qount.mini_trend.futures_regime_overlay import regime_overlay_config
from qount.mini_trend.futures_regime_overlay_report import summarize_risk_stages
from qount.mini_trend.futures_risk_tier import FUTURES_RISK_TIER_PROTOCOL
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


def _prior_risk_tier(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_type": "mini_trend_um_risk_tier_historical_diagnostic",
                "contract_hash": FUTURES_RISK_TIER_PROTOCOL.contract_hash,
                "diagnostics": {"verdict": "reject_historical_risk_tier"},
                "full_window": {
                    "control": {"return_pct": 66.5},
                    "candidate": {"return_pct": 103.3, "max_drawdown_pct": 21.2},
                },
            }
        ),
        encoding="utf-8",
    )


class MiniTrendFuturesRegimeOverlayTest(unittest.TestCase):
    def test_completed_bar_classifier_covers_three_stages(self) -> None:
        strong = classify_regime({symbol: _rising() for symbol in TOP3})
        transition = classify_regime(
            {"BTCUSDT": _rising(), "ETHUSDT": _falling(), "BNBUSDT": _falling()}
        )
        bear = classify_regime({symbol: _falling() for symbol in TOP3})
        self.assertEqual(strong.stage, STRONG_BULL)
        self.assertEqual(strong.config.vol_target, 0.020)
        self.assertEqual(transition.stage, TRANSITION_RANGE)
        self.assertEqual(transition.config.vol_target, 0.015)
        self.assertEqual(bear.stage, BEAR_CASH)
        self.assertEqual(bear.config.vol_target, 0.015)

    def test_overlay_changes_only_strategy_id_and_stage_vol_target(self) -> None:
        base = frozen_top3_config()
        candidate = regime_overlay_config(0.020)
        expected = vars(base) | {"strategy": candidate.strategy, "vol_target": 0.020}
        self.assertEqual(vars(candidate), expected)

    def test_preregistration_binds_rejected_global_risk_tier(self) -> None:
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
            _prior_risk_tier(prior_path)
            prereg = build_regime_overlay_preregistration(
                _rules(), lessons, base_path, prior_path
            )
        self.assertFalse(prereg["meta"]["strategy_results_evaluated"])
        self.assertEqual(prereg["prior_risk_tier"]["verdict"], "reject_historical_risk_tier")
        self.assertFalse(prereg["decision_contract"]["capital"]["carry_allowed"])
        self.assertFalse(prereg["decision_contract"]["execution"]["shorting_allowed"])
        self.assertEqual(
            prereg["decision_contract"]["contract_hash"],
            FUTURES_REGIME_OVERLAY_PROTOCOL.contract_hash,
        )
        self.assertEqual(
            prereg["protocol"]["historical_pass_gates"]["maximum_full_window_drawdown_pct"],
            20.0,
        )

    def test_variant_records_stage_and_increases_risk_only_in_strong_bull(self) -> None:
        bars = {symbol: _rising() for symbol in TOP3}
        funding = {symbol: [Funding(_T0, 0.0)] for symbol in TOP3}
        rules, _ = selected_um_rules(_rules())
        common = {
            "recovery_enabled": False,
            "gross_cap_policy": "renormalize_active_targets_with_filter_floors",
        }
        control = run_variant(
            bars,
            funding,
            rules,
            base_config=frozen_top3_config(),
            **common,
        )
        labeled_control = run_variant(
            bars,
            funding,
            rules,
            base_config=frozen_top3_config(),
            base_config_selector=control_regime_config_selector,
            **common,
        )
        candidate = run_variant(
            bars,
            funding,
            rules,
            base_config=regime_overlay_config(0.015),
            base_config_selector=regime_config_selector,
            **common,
        )
        self.assertTrue(all(row["risk_stage"] == STRONG_BULL for row in candidate.equity))
        self.assertEqual(control.metrics, labeled_control.metrics)
        self.assertEqual(
            [row["equity"] for row in control.equity],
            [row["equity"] for row in labeled_control.equity],
        )
        self.assertGreater(
            max(float(row["gross"]) for row in candidate.equity),
            max(float(row["gross"]) for row in control.equity),
        )
        summary = summarize_risk_stages(candidate, 400.0)
        self.assertEqual(summary[STRONG_BULL]["bar_count"], len(candidate.equity))
        self.assertEqual(len(summary[STRONG_BULL]["worst_daily_observations"]), 3)
        self.assertEqual(summary[TRANSITION_RANGE]["bar_count"], 0)
        self.assertEqual(summary[BEAR_CASH]["bar_count"], 0)


if __name__ == "__main__":
    unittest.main()
