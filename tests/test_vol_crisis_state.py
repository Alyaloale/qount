from __future__ import annotations

import copy
import datetime as dt
import math
import unittest

from qount.research_data.market_data import Bar
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.vol_crisis_state import (
    CRISIS_STATE_PROTOCOL,
    CrisisStateSelector,
    FixedVolTargetSelector,
    build_crisis_state_preregistration,
    build_crisis_state_report,
    compute_risk_multiplier_series,
    research_rules,
    validate_crisis_state_preregistration,
)


def _bars(count: int = 500) -> dict[str, list[Bar]]:
    start = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    growth = {"BTCUSDT": 0.0010, "ETHUSDT": 0.0012, "BNBUSDT": 0.0009}
    result: dict[str, list[Bar]] = {}
    for symbol_index, symbol in enumerate(TOP3):
        price = 100.0 + symbol_index * 20.0
        rows: list[Bar] = []
        for index in range(count):
            daily = growth[symbol] + math.sin(index / (7.0 + symbol_index)) * 0.002
            opened = price
            price *= 1.0 + daily
            rows.append(
                Bar(
                    ts_ms=int((start + dt.timedelta(days=index)).timestamp() * 1000),
                    open=opened,
                    high=max(opened, price) * 1.005,
                    low=min(opened, price) * 0.995,
                    close=price,
                    volume=1_000_000.0,
                )
            )
        result[symbol] = rows
    return result


class VolCrisisStateTests(unittest.TestCase):
    def test_preregistration_is_result_free_and_hash_bound(self) -> None:
        payload = build_crisis_state_preregistration("2026-07-25T00:00:00+00:00")
        validate_crisis_state_preregistration(payload)
        self.assertFalse(payload["meta"]["strategy_results_evaluated"])
        self.assertEqual(
            payload["protocol"]["protocol_hash"],
            CRISIS_STATE_PROTOCOL.protocol_hash,
        )
        self.assertEqual(CRISIS_STATE_PROTOCOL.global_trial_number, 148)
        self.assertEqual(CRISIS_STATE_PROTOCOL.trial_number_within_family, 1)

        tampered = copy.deepcopy(payload)
        tampered["decision_contract"]["signal"]["crisis_threshold"] = 3.0
        with self.assertRaisesRegex(ValueError, "contract hash mismatch"):
            validate_crisis_state_preregistration(tampered)

    def test_risk_multiplier_is_in_zero_one(self) -> None:
        bars = _bars(500)
        from qount.mini_trend.backtest import align_bars
        aligned = align_bars(bars, TOP3)
        rm = compute_risk_multiplier_series(aligned, {s: [] for s in TOP3})
        self.assertGreater(len(rm), 0)
        for value in rm.values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_fixed_vol_target_weights_are_long_only_and_gross_bounded(self) -> None:
        weights, mode, feasible = FixedVolTargetSelector()(
            _bars(240), research_rules(), 400.0, frozen_top3_config()
        )
        self.assertTrue(feasible)
        self.assertEqual(mode, "fixed_vol_target")
        self.assertTrue(all(weight >= 0.0 for weight in weights.values()))
        self.assertLessEqual(sum(weights.values()), 1.0)

    def test_crisis_selector_scales_weights_down_or_same(self) -> None:
        bars = _bars(500)
        from qount.mini_trend.backtest import align_bars
        aligned = align_bars(bars, TOP3)
        rm = compute_risk_multiplier_series(aligned, {s: [] for s in TOP3})
        base_weights, _, _ = FixedVolTargetSelector()(bars, research_rules(), 400.0, frozen_top3_config())
        crisis_weights, mode, _ = CrisisStateSelector(FixedVolTargetSelector(), rm)(
            bars, research_rules(), 400.0, frozen_top3_config()
        )
        self.assertTrue(mode.endswith("_crisis_scaled"))
        for symbol in TOP3:
            self.assertLessEqual(crisis_weights[symbol], base_weights[symbol] + 1e-12)

    def test_report_reconciles_nav_and_produces_crisis_comparison(self) -> None:
        preregistration = build_crisis_state_preregistration("2026-07-25T00:00:00+00:00")
        report, trajectories = build_crisis_state_report(
            _bars(500),
            {symbol: [] for symbol in TOP3},
            preregistration,
            funding_complete=False,
            observed_at="2026-07-25T01:00:00+00:00",
        )
        self.assertFalse(report["meta"]["orders_authorized"])
        self.assertFalse(report["diagnostics"]["candidate_pnl_ready"])
        self.assertEqual(len(report["crisis_comparison"]), 3)
        self.assertEqual(len(report["summaries"]), 6)
        self.assertEqual(set(trajectories), {
            "base", "base_crisis", "multi", "multi_crisis", "voltarget", "voltarget_crisis",
        })
        for summary in report["summaries"].values():
            self.assertLessEqual(summary["independent_nav_reconciliation_difference"], 1e-7)
        self.assertTrue(
            report["diagnostics"]["verdict"].startswith("reject_crisis_state")
            or report["diagnostics"]["verdict"].startswith("retain_crisis_state")
        )


if __name__ == "__main__":
    unittest.main()
