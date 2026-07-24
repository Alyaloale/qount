from __future__ import annotations

import copy
import datetime as dt
import math
import unittest

from qount.grid.data import Bar
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.multi_speed_state_machine import (
    STATE_MACHINE_PROTOCOL,
    StateMachineSelector,
    build_state_machine_preregistration,
    build_state_machine_report,
    research_rules,
    validate_state_machine_preregistration,
)


def _bars(count: int = 460) -> dict[str, list[Bar]]:
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


class StateMachineTests(unittest.TestCase):
    def test_preregistration_is_result_free_and_hash_bound(self) -> None:
        payload = build_state_machine_preregistration("2026-07-25T00:00:00+00:00")
        validate_state_machine_preregistration(payload)
        self.assertFalse(payload["meta"]["strategy_results_evaluated"])
        self.assertEqual(
            payload["protocol"]["protocol_hash"],
            STATE_MACHINE_PROTOCOL.protocol_hash,
        )
        self.assertEqual(STATE_MACHINE_PROTOCOL.global_trial_number, 147)
        self.assertEqual(STATE_MACHINE_PROTOCOL.trial_number_within_family, 3)

        tampered = copy.deepcopy(payload)
        tampered["decision_contract"]["signal"]["fast_derisk"]["factor"] = 0.75
        with self.assertRaisesRegex(ValueError, "contract hash mismatch"):
            validate_state_machine_preregistration(tampered)

    def test_one_bar_delay_does_not_read_the_latest_signal_bar(self) -> None:
        bars = _bars(240)
        selector = StateMachineSelector(signal_delay_bars=1)
        baseline, _, feasible = selector(bars, research_rules(), 400.0, frozen_top3_config())
        self.assertTrue(feasible)

        changed = {symbol: list(rows) for symbol, rows in bars.items()}
        for symbol in TOP3:
            last = changed[symbol][-1]
            changed[symbol][-1] = Bar(
                ts_ms=last.ts_ms,
                open=last.open,
                high=last.high * 2.0,
                low=last.low * 0.1,
                close=last.close * 0.2,
                volume=last.volume,
            )
        delayed, _, delayed_feasible = selector(
            changed, research_rules(), 400.0, frozen_top3_config()
        )
        self.assertTrue(delayed_feasible)
        self.assertEqual(baseline, delayed)

    def test_state_machine_weights_are_long_only_and_gross_bounded(self) -> None:
        weights, mode, feasible = StateMachineSelector()(
            _bars(240), research_rules(), 400.0, frozen_top3_config()
        )
        self.assertTrue(feasible)
        self.assertEqual(mode, "multi_speed_layered_state_machine")
        self.assertEqual(set(weights), set(TOP3))
        self.assertTrue(all(weight >= 0.0 for weight in weights.values()))
        self.assertLessEqual(sum(weights.values()), 1.0)

    def test_report_reconciles_nav_and_triggers_family_review(self) -> None:
        preregistration = build_state_machine_preregistration("2026-07-25T00:00:00+00:00")
        report, trajectories = build_state_machine_report(
            _bars(),
            {symbol: [] for symbol in TOP3},
            preregistration,
            funding_complete=False,
            observed_at="2026-07-25T01:00:00+00:00",
        )
        self.assertFalse(report["meta"]["orders_authorized"])
        self.assertTrue(report["meta"]["family_review_triggered"])
        self.assertFalse(report["diagnostics"]["candidate_pnl_ready"])
        self.assertLessEqual(report["diagnostics"]["maximum_observed_gross"], 1.0)
        self.assertLessEqual(
            report["summaries"]["candidate"]["independent_nav_reconciliation_difference"],
            1e-7,
        )
        self.assertEqual(
            set(trajectories),
            {
                "base",
                "candidate",
                "base_doubled_cost",
                "candidate_doubled_cost",
                "candidate_one_bar_delay",
            },
        )
        self.assertTrue(
            report["diagnostics"]["verdict"].startswith("reject_state_machine")
            or report["diagnostics"]["verdict"].startswith("retain_state_machine")
        )


if __name__ == "__main__":
    unittest.main()
