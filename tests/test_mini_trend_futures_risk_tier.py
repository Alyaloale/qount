from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_base_forward import build_futures_base_forward_preregistration
from qount.mini_trend.futures_recovery import selected_um_rules
from qount.mini_trend.futures_recovery_backtest import run_variant
from qount.mini_trend.futures_recovery_backtest import enforce_gross_cap
from qount.mini_trend.futures_risk_tier import FUTURES_RISK_TIER_PROTOCOL
from qount.mini_trend.futures_risk_tier import build_risk_tier_preregistration
from qount.mini_trend.futures_risk_tier import risk_tier_config
from qount.mini_trend.live_lessons import LIVE_LESSONS_VERSION


_T0 = 1_609_459_200_000
_DAY = 86_400_000


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


def _bars() -> list[Bar]:
    closes = [100.0] * 200 + [100.0 + index for index in range(40)]
    return [
        Bar(_T0 + index * _DAY, close, close * 1.01, close * 0.99, close, 1000.0)
        for index, close in enumerate(closes)
    ]


class MiniTrendFuturesRiskTierTest(unittest.TestCase):
    def test_candidate_changes_only_strategy_id_and_vol_target(self) -> None:
        control = frozen_top3_config()
        candidate = risk_tier_config()
        control_values = vars(control) | {"strategy": candidate.strategy, "vol_target": candidate.vol_target}
        self.assertEqual(vars(candidate), control_values)
        self.assertEqual(candidate.vol_target, 0.020)

    def test_preregistration_binds_base_contract_and_single_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lessons = root / "lessons.json"
            base_path = root / "base.json"
            _lessons(lessons)
            base_path.write_text(
                json.dumps(build_futures_base_forward_preregistration(_rules(), lessons)),
                encoding="utf-8",
            )
            prereg = build_risk_tier_preregistration(_rules(), lessons, base_path)
        self.assertFalse(prereg["meta"]["strategy_results_evaluated"])
        self.assertFalse(prereg["decision_contract"]["capital"]["carry_allowed"])
        self.assertFalse(prereg["decision_contract"]["execution"]["shorting_allowed"])
        self.assertEqual(
            prereg["decision_contract"]["candidate"]["single_variable_change"],
            {"field": "vol_target", "control": 0.015, "candidate": 0.020},
        )
        self.assertEqual(
            prereg["decision_contract"]["contract_hash"],
            FUTURES_RISK_TIER_PROTOCOL.contract_hash,
        )
        self.assertEqual(
            prereg["decision_contract"]["execution"]["gross_cap_policy"],
            "renormalize_active_targets_with_filter_floors",
        )

    def test_gross_cap_policy_preserves_filters_and_caps_portfolio(self) -> None:
        rules, _ = selected_um_rules(_rules())
        target, normalized = enforce_gross_cap(
            {"BTCUSDT": 0.5, "ETHUSDT": 0.4, "BNBUSDT": 0.3},
            1.0,
            400.0,
            {symbol: 100.0 for symbol in TOP3},
            rules,
            policy="renormalize_active_targets_with_filter_floors",
        )
        self.assertTrue(normalized)
        self.assertAlmostEqual(sum(target.values()), 1.0)
        self.assertTrue(all(weight * 400.0 >= 5.25 for weight in target.values()))

    def test_candidate_config_increases_effective_risk_without_leverage_boost(self) -> None:
        bars = {symbol: _bars() for symbol in TOP3}
        funding = {symbol: [Funding(_T0, 0.0)] for symbol in TOP3}
        rules, _ = selected_um_rules(_rules())
        control = run_variant(
            bars,
            funding,
            rules,
            recovery_enabled=False,
            base_config=frozen_top3_config(),
        )
        candidate = run_variant(
            bars,
            funding,
            rules,
            recovery_enabled=False,
            base_config=risk_tier_config(),
        )
        control_gross = max(float(row["gross"]) for row in control.equity)
        candidate_gross = max(float(row["gross"]) for row in candidate.equity)
        self.assertGreater(candidate_gross, control_gross)
        self.assertLessEqual(candidate_gross, 1.0)


if __name__ == "__main__":
    unittest.main()
