from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PREREG_VERSION
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL
from qount.mini_trend.futures_recovery import build_futures_recovery_preregistration
from qount.mini_trend.futures_recovery import load_live_lessons_evidence
from qount.mini_trend.futures_recovery import validate_futures_recovery_registration
from qount.mini_trend.live_lessons import LIVE_LESSONS_VERSION
from qount.mini_trend.futures_recovery_backtest import allocate_with_filters
from qount.mini_trend.futures_recovery_backtest import recovery_confirmed
from qount.mini_trend.futures_recovery_backtest import run_variant


_T0 = 1_609_459_200_000
_DAY = 86_400_000


def _bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(_T0 + index * _DAY, close, close * 1.01, close * 0.99, close, 1000.0)
        for index, close in enumerate(closes)
    ]


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "raw_exchange_info_hash": "raw",
        "rules": [
            {
                "symbol": symbol,
                "status": "TRADING",
                "market_step_size": "0.001",
                "min_qty": "0.001",
                "min_notional": "5",
            }
            for symbol in TOP3
        ],
    }


class MiniTrendFuturesRecoveryTest(unittest.TestCase):
    def _evidence(self, root: Path) -> dict:
        path = root / "lessons.json"
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
        return load_live_lessons_evidence(path)

    def test_preregistration_freezes_no_carry_low_frequency_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = self._evidence(Path(tmp))
            prereg = build_futures_recovery_preregistration(_rules(), evidence)
        self.assertEqual(prereg["schema_version"], FUTURES_RECOVERY_PREREG_VERSION)
        self.assertFalse(prereg["meta"]["strategy_results_evaluated"])
        self.assertFalse(prereg["decision_contract"]["capital"]["carry_allowed"])
        self.assertEqual(prereg["decision_contract"]["data"]["interval"], "1d")
        self.assertFalse(prereg["protocol"]["high_frequency_data_allowed"])
        self.assertFalse(prereg["protocol"]["paper_or_live_allowed"])
        self.assertEqual(
            prereg["decision_contract"]["contract_hash"], FUTURES_RECOVERY_PROTOCOL.contract_hash
        )

    def test_registration_binds_rules_and_live_lessons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = self._evidence(Path(tmp))
            prereg = build_futures_recovery_preregistration(_rules(), evidence)
            validate_futures_recovery_registration(prereg, _rules(), evidence)
            changed = json.loads(json.dumps(_rules()))
            changed["rules"][0]["min_notional"] = "50"
            with self.assertRaisesRegex(ValueError, "exchange-rules hash mismatch"):
                validate_futures_recovery_registration(prereg, changed, evidence)
            changed_evidence = dict(evidence, artifact_sha256="changed")
            with self.assertRaisesRegex(ValueError, "live-lessons hash mismatch"):
                validate_futures_recovery_registration(prereg, _rules(), changed_evidence)

    def test_spot_rules_fail_closed(self) -> None:
        rules = _rules()
        rules["market"] = "spot"
        with tempfile.TemporaryDirectory() as tmp:
            evidence = self._evidence(Path(tmp))
            with self.assertRaisesRegex(ValueError, "requires UM"):
                build_futures_recovery_preregistration(rules, evidence)

    def test_recovery_confirmation_and_filter_budget(self) -> None:
        closes = [100.0] * 25 + [101.0, 102.0, 103.0]
        bars = {symbol: _bars(closes) for symbol in TOP3}
        self.assertTrue(recovery_confirmed(bars))
        rules, equity = {row["symbol"]: row for row in _rules()["rules"]}, 400.0
        rules["BTCUSDT"]["min_notional"] = "50"
        weights, feasible = allocate_with_filters(
            {symbol: 1.0 for symbol in TOP3},
            0.25,
            equity,
            {symbol: 100.0 for symbol in TOP3},
            rules,
        )
        self.assertTrue(feasible)
        self.assertAlmostEqual(sum(weights.values()), 0.25)
        self.assertGreaterEqual(weights["BTCUSDT"] * equity, 52.5)

    def test_variant_is_daily_and_has_no_same_bar_stop_reentry(self) -> None:
        closes = [100.0] * 205 + [100.0 + index for index in range(30)]
        bars = {symbol: _bars(closes) for symbol in TOP3}
        rules = {row["symbol"]: row for row in _rules()["rules"]}
        funding = {symbol: [Funding(_T0, 0.0)] for symbol in TOP3}
        result = run_variant(bars, funding, rules, recovery_enabled=True)
        self.assertEqual(result.metrics["duplicate_decision_count"], 0)
        self.assertEqual(result.metrics["same_bar_stop_reentry_count"], 0)
        self.assertLessEqual(
            result.metrics["decision_batch_count"], len(result.equity)
        )
        for row in result.equity:
            self.assertAlmostEqual(
                row["net_return"],
                row["gross_price_return"]
                + row["funding_return"]
                + row["trading_cost_return"],
                places=15,
            )
            self.assertEqual(
                sorted(row["execution_state"]["target_weights"]), sorted(TOP3)
            )
            self.assertEqual(
                sorted(row["execution_state"]["cooldown_remaining"]), sorted(TOP3)
            )

    def test_variant_records_desired_weight_transform_state(self) -> None:
        class PassthroughTransform:
            def __call__(self, bars, config, desired, previous):
                return desired

            def state_snapshot(self):
                return {"transform": "passthrough"}

        closes = [100.0] * 205 + [100.0 + index for index in range(30)]
        bars = {symbol: _bars(closes) for symbol in TOP3}
        rules = {row["symbol"]: row for row in _rules()["rules"]}
        funding = {symbol: [Funding(_T0, 0.0)] for symbol in TOP3}
        result = run_variant(
            bars,
            funding,
            rules,
            recovery_enabled=False,
            desired_weights_transform=PassthroughTransform(),
        )
        self.assertTrue(result.equity)
        self.assertTrue(
            all(
                row["execution_state"]["desired_transform_state"]
                == {"transform": "passthrough"}
                for row in result.equity
            )
        )

    def test_variant_rejects_invalid_desired_weight_transform(self) -> None:
        closes = [100.0] * 205 + [100.0 + index for index in range(30)]
        bars = {symbol: _bars(closes) for symbol in TOP3}
        rules = {row["symbol"]: row for row in _rules()["rules"]}
        funding = {symbol: [Funding(_T0, 0.0)] for symbol in TOP3}
        transforms = (
            (
                lambda window, config, desired, previous: {"BTCUSDT": 0.0},
                "exactly TOP3",
            ),
            (
                lambda window, config, desired, previous: {
                    symbol: (-0.1 if symbol == "BTCUSDT" else 0.0) for symbol in TOP3
                },
                "invalid target",
            ),
        )
        for transform, message in transforms:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    run_variant(
                        bars,
                        funding,
                        rules,
                        recovery_enabled=False,
                        desired_weights_transform=transform,
                    )


if __name__ == "__main__":
    unittest.main()
