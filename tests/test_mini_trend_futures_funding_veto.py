from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_base_forward import build_futures_base_forward_preregistration
from qount.mini_trend.futures_funding_veto import FUTURES_FUNDING_VETO_PROTOCOL
from qount.mini_trend.futures_funding_veto import STRONG_BULL_FUNDING_MISSING
from qount.mini_trend.futures_funding_veto import STRONG_BULL_FUNDING_VETO
from qount.mini_trend.futures_funding_veto import FundingVetoRegimeSelector
from qount.mini_trend.futures_funding_veto import build_funding_veto_preregistration
from qount.mini_trend.futures_funding_veto_report import _event_audit
from qount.mini_trend.futures_funding_veto_report import _window_report
from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.futures_regime_stop_latch import FUTURES_REGIME_STOP_LATCH_PROTOCOL
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_BOOSTED
from qount.mini_trend.futures_regime_stop_latch import STRONG_BULL_LATCHED_BASE
from qount.mini_trend.live_lessons import LIVE_LESSONS_VERSION


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


def _funding(rate: float, *, include: tuple[str, ...] = TOP3, day_offset: int = 0) -> dict:
    bar_open = _series()[-1].ts_ms + day_offset * _DAY
    return {
        symbol: (
            [
                Funding(bar_open + 8 * 3_600_000, rate),
                Funding(bar_open + 16 * 3_600_000, rate),
                Funding(bar_open + _DAY, rate),
            ]
            if symbol in include
            else []
        )
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


def _prior_stop_latch(path: Path) -> None:
    metric = {
        "return_pct": 1.0,
        "sharpe": 0.5,
        "max_drawdown_pct": 10.0,
        "average_effective_gross": 0.2,
    }
    path.write_text(
        json.dumps(
            {
                "artifact_type": "mini_trend_um_regime_stop_latch_historical_diagnostic",
                "contract_hash": FUTURES_REGIME_STOP_LATCH_PROTOCOL.contract_hash,
                "diagnostics": {"verdict": "reject_historical_regime_stop_latch"},
                "full_window": {"candidate": metric},
                "segments": [
                    {"label": label, "candidate": metric}
                    for label in ("2021-2022", "2023-2024", "2025-2026")
                ],
            }
        ),
        encoding="utf-8",
    )


class MiniTrendFuturesFundingVetoTest(unittest.TestCase):
    def test_completed_day_high_funding_vetoes_only_risk_boost(self) -> None:
        selector = FundingVetoRegimeSelector(_funding(0.0005))
        config, stage = selector(_bars())
        self.assertEqual(stage, STRONG_BULL_FUNDING_VETO)
        self.assertEqual(config.vol_target, 0.015)
        self.assertEqual(selector.summary()["vetoed_bar_count"], 1)
        self.assertEqual(selector.summary()["funding_coverage"], 1.0)
        self.assertEqual(selector.summary()["events"][0]["decision_date"], _series()[-1].date)

    def test_below_threshold_funding_keeps_boost(self) -> None:
        selector = FundingVetoRegimeSelector(_funding(0.0004))
        config, stage = selector(_bars())
        self.assertEqual(stage, STRONG_BULL_BOOSTED)
        self.assertEqual(config.vol_target, 0.020)

    def test_missing_funding_fails_closed_to_base_risk(self) -> None:
        selector = FundingVetoRegimeSelector(
            _funding(0.0004, include=("BTCUSDT", "ETHUSDT"))
        )
        config, stage = selector(_bars())
        self.assertEqual(stage, STRONG_BULL_FUNDING_MISSING)
        self.assertEqual(config.vol_target, 0.015)
        self.assertEqual(selector.summary()["funding_coverage"], 0.0)

    def test_future_day_funding_is_not_used(self) -> None:
        current = _funding(0.0004)
        future = _funding(0.0010, day_offset=1)
        combined = {symbol: current[symbol] + future[symbol] for symbol in TOP3}
        selector = FundingVetoRegimeSelector(combined)
        self.assertEqual(selector(_bars())[1], STRONG_BULL_BOOSTED)

    def test_stop_on_veto_bar_still_latches_continuous_strong_bull(self) -> None:
        selector = FundingVetoRegimeSelector(_funding(0.0005))
        stage = selector(_bars())[1]
        selector.observe_stops(stage, {"BTCUSDT"})
        config, next_stage = selector(_bars())
        self.assertEqual(next_stage, STRONG_BULL_LATCHED_BASE)
        self.assertEqual(config.vol_target, 0.015)

    def test_preregistration_binds_external_threshold_without_search(self) -> None:
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
            _prior_stop_latch(prior_path)
            prereg = build_funding_veto_preregistration(
                _rules(), lessons, base_path, prior_path
            )
        delta = prereg["decision_contract"]["candidate_delta"]
        self.assertEqual(delta["annualized_funding_veto"], 0.50)
        self.assertFalse(delta["parameter_search_allowed"])
        self.assertTrue(delta["funding_is_cost_filter_not_carry_alpha"])
        self.assertFalse(prereg["meta"]["strategy_results_evaluated"])
        self.assertEqual(prereg["protocol"]["mechanism_family_trial_count"], 2)
        self.assertEqual(
            prereg["decision_contract"]["contract_hash"],
            FUTURES_FUNDING_VETO_PROTOCOL.contract_hash,
        )

    def test_zero_veto_event_audit_is_explicit(self) -> None:
        result = VariantResult(
            metrics={},
            equity=[
                {
                    "decision_date": "2025-01-01",
                    "outcome_date": "2025-01-02",
                    "equity": 400.0,
                }
            ],
        )
        audit = _event_audit(result, result, {"events": []})
        self.assertEqual(audit["event_count"], 0)
        self.assertEqual(audit["median_direct_delta_percentage_points"], 0.0)

    def test_historical_window_reports_btc_and_top3_beta_residuals(self) -> None:
        bars = _bars()
        series = _series()
        rules = {row["symbol"]: row for row in _rules()["rules"]}
        report = _window_report(
            {"bars": bars, "funding": _funding(0.0001)},
            {
                "label": "fixture",
                "start": series[200].date,
                "end": series[-1].date,
            },
            rules,
        )
        for key in ("control", "reference_stop_latch", "candidate"):
            residual = report[key]["beta_residual"]
            self.assertEqual(set(residual), {"btc_1x", "top3_equal_weight_1x"})
            self.assertEqual(
                set(residual["btc_1x"]),
                {"beta", "residual_sum_pct", "residual_compound_pct"},
            )


if __name__ == "__main__":
    unittest.main()
