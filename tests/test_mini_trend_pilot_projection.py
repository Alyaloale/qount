from __future__ import annotations

import datetime as dt
import unittest

from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.pilot_paper import build_pilot_paper_replay
from qount.mini_trend.portfolio_intent import base_intent_from_projection
from qount.mini_trend.portfolio_intent import base_snapshot_from_projection
from qount.mini_trend.pilot_projection import build_latest_pilot_projection


_DAY_MS = 86_400_000
_START = dt.datetime(2026, 7, 19, tzinfo=dt.UTC)
_T0 = int((_START - dt.timedelta(days=200)).timestamp() * 1000)


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {
                "symbol": symbol,
                "status": "TRADING",
                "min_qty": "0.000001",
                "min_notional": "5",
            }
            for symbol in TOP3
        ],
    }


def _bars(count: int, *, final_multiplier: float = 1.0) -> dict[str, list[Bar]]:
    rows = []
    for index in range(count):
        close = 100.0 * (1.002**index)
        if index == count - 1:
            close *= final_multiplier
        rows.append(
            Bar(
                _T0 + index * _DAY_MS,
                close,
                close * 1.01,
                close * 0.99,
                close,
                1_000.0,
            )
        )
    return {symbol: list(rows) for symbol in TOP3}


def _funding(count: int) -> dict[str, list[Funding]]:
    rows = []
    for index in range(count):
        day = _T0 + index * _DAY_MS
        rows.extend(
            [
                Funding(day + 8 * 3_600_000 + 3, 0.0),
                Funding(day + 16 * 3_600_000 + 4, 0.0),
                Funding(day + _DAY_MS + 5, 0.0),
            ]
        )
    return {symbol: list(rows) for symbol in TOP3}


class MiniTrendPilotProjectionTest(unittest.TestCase):
    def test_waits_until_the_first_pilot_bar_exists(self) -> None:
        report = build_latest_pilot_projection(
            _bars(200), _funding(200), _rules()
        )
        self.assertEqual(
            report["diagnostics"]["verdict"], "await_latest_completed_pilot_bar"
        )
        self.assertIsNone(report["decision"])

    def test_production_projection_rejects_an_older_latest_bar(self) -> None:
        report = build_latest_pilot_projection(
            _bars(201),
            _funding(201),
            _rules(),
            expected_latest_date="2026-07-20",
        )
        self.assertEqual(
            report["diagnostics"]["verdict"],
            "await_latest_completed_pilot_bar",
        )
        self.assertIn(
            "latest_completed_bar_not_available",
            report["diagnostics"]["blockers"],
        )
        self.assertIsNone(report["decision"])

    def test_production_projection_accepts_the_expected_latest_bar(self) -> None:
        report = build_latest_pilot_projection(
            _bars(201),
            _funding(201),
            _rules(),
            expected_latest_date="2026-07-19",
        )
        self.assertEqual(
            report["diagnostics"]["verdict"],
            "latest_causal_decision_projected",
        )
        self.assertEqual(report["decision"]["decision_date"], "2026-07-19")

    def test_projects_first_latest_decision_without_an_outcome(self) -> None:
        report = build_latest_pilot_projection(
            _bars(201), _funding(201), _rules()
        )
        self.assertEqual(
            report["diagnostics"]["verdict"], "latest_causal_decision_projected"
        )
        self.assertEqual(report["decision"]["decision_date"], "2026-07-19")
        self.assertEqual(set(report["decision"]["desired_weights"]), set(TOP3))
        self.assertEqual(
            set(report["decision"]["protective_stop_prices"]), set(TOP3)
        )
        self.assertTrue(
            all(
                report["decision"]["protective_stop_prices"][symbol]
                < report["decision"]["prices"][symbol]
                for symbol in TOP3
            )
        )
        self.assertFalse(report["meta"]["live_orders_allowed"])

    def test_projection_matches_later_paper_state_for_same_decision(self) -> None:
        bars_at_decision = _bars(201)
        projection = build_latest_pilot_projection(
            bars_at_decision, _funding(202), _rules()
        )
        bars_with_outcome = {
            symbol: [
                *bars_at_decision[symbol],
                _bars(202, final_multiplier=0.7)[symbol][-1],
            ]
            for symbol in TOP3
        }
        replay = build_pilot_paper_replay(
            bars_with_outcome,
            _funding(202),
            _rules(),
        )
        paper_state = replay.journal_rows[0]["execution_state"]
        self.assertEqual(
            projection["decision"]["desired_weights"],
            paper_state["target_weights"],
        )
        self.assertEqual(
            projection["decision"]["execution_state_hash"],
            canonical_hash(paper_state),
        )

    def test_ready_projection_converts_to_standard_order_free_strategy_intent(self) -> None:
        projection = build_latest_pilot_projection(
            _bars(201), _funding(201), _rules()
        )
        intent = base_intent_from_projection(
            projection,
            projection_evidence_hash="a" * 64,
            target_stress_loss_fraction=0.10,
        )
        self.assertEqual(intent.strategy_id, projection["decision"]["strategy"])
        self.assertEqual(intent.target_weights, projection["decision"]["desired_weights"])
        self.assertEqual(
            intent.state_hash, projection["decision"]["execution_state_hash"]
        )
        self.assertEqual(intent.validate(), ())
        snapshot = base_snapshot_from_projection(
            projection,
            projection_evidence_hash="a" * 64,
        )
        self.assertEqual(snapshot.validate(), ())
        self.assertEqual(intent.schema_version, 2)
        self.assertEqual(intent.strategy_version, "0.2.0")
        self.assertEqual(intent.decision_id, projection["decision"]["decision_id"])
        self.assertEqual(intent.snapshot_id, snapshot.snapshot_id)
        self.assertTrue(intent.reason_codes)
        self.assertFalse(snapshot.data_quality["account_snapshot_linked"])

    def test_unready_projection_cannot_create_strategy_intent(self) -> None:
        projection = build_latest_pilot_projection(
            _bars(200), _funding(200), _rules()
        )
        with self.assertRaisesRegex(ValueError, "projection is not ready"):
            base_intent_from_projection(
                projection,
                projection_evidence_hash="a" * 64,
                target_stress_loss_fraction=0.10,
            )


if __name__ == "__main__":
    unittest.main()
