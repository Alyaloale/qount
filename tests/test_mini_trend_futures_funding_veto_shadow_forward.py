from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_base_forward import build_futures_base_forward_preregistration
from qount.mini_trend.futures_funding_veto_shadow_forward import (
    FUNDING_VETO_SHADOW_FORWARD_PROTOCOL,
)
from qount.mini_trend.futures_funding_veto_shadow_forward import (
    build_funding_veto_shadow_forward_preregistration,
)
from qount.mini_trend.futures_funding_veto_shadow_forward import (
    build_funding_veto_shadow_forward_report,
)
from qount.mini_trend.futures_funding_veto_state_decay import (
    FUNDING_VETO_STATE_DECAY_REPORT_VERSION,
)
from qount.mini_trend.futures_funding_veto_state_decay import (
    FUNDING_VETO_STATE_DECAY_PROTOCOL,
)
from qount.mini_trend.futures_recovery import selected_um_rules


_DAY = 86_400_000
_T0 = int(dt.datetime(2025, 12, 1, tzinfo=dt.UTC).timestamp() * 1000)


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
                "schema_version": "mini_trend_live_lessons_v0.1",
                "verdict": "audit_complete_research_only",
                "candidate_constraints": {"carry_allowed": False, "market": "um_futures"},
                "equity": {
                    "inception_to_pre_withdrawal_return_pct": -2.0,
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


def _state_decay(path: Path, rules_hash: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": FUNDING_VETO_STATE_DECAY_REPORT_VERSION,
                "artifact_type": "mini_trend_um_funding_veto_state_decay_historical_diagnostic",
                "contract_hash": FUNDING_VETO_STATE_DECAY_PROTOCOL.contract_hash,
                "protocol_hash": FUNDING_VETO_STATE_DECAY_PROTOCOL.protocol_hash,
                "exchange_rules_hash": rules_hash,
                "source_historical_sha256": "historical",
                "diagnostics": {"verdict": "historical_execution_state_decay_resolved"},
                "state_decay": {
                    "state_divergent_bar_count": 696,
                    "first_sync_duration_summary": {"median": 46},
                },
            }
        ),
        encoding="utf-8",
    )


def _bars(count: int, *, trending: bool) -> list[Bar]:
    rows = []
    for index in range(count):
        close = 100.0 + index * 0.2 if trending else 100.0
        rows.append(
            Bar(
                _T0 + index * _DAY,
                close,
                close * 1.01,
                close * 0.99,
                close,
                1000.0,
            )
        )
    return rows


def _funding(count: int, rate: float) -> list[Funding]:
    rows = []
    for index in range(count):
        bar_open = _T0 + index * _DAY
        rows.extend(
            [
                Funding(bar_open + 8 * 3_600_000, rate),
                Funding(bar_open + 16 * 3_600_000, rate),
                Funding(bar_open + _DAY, rate),
            ]
        )
    return rows


class MiniTrendFuturesFundingVetoShadowForwardTest(unittest.TestCase):
    def _registration(self, root: Path) -> tuple[dict, Path, Path]:
        lessons = root / "lessons.json"
        base = root / "base.json"
        state_decay = root / "state-decay.json"
        _lessons(lessons)
        base.write_text(
            json.dumps(build_futures_base_forward_preregistration(_rules(), lessons)),
            encoding="utf-8",
        )
        _, rules_hash = selected_um_rules(_rules())
        _state_decay(state_decay, rules_hash)
        registration = build_funding_veto_shadow_forward_preregistration(
            _rules(), base, state_decay
        )
        return registration, base, state_decay

    def test_preregistration_starts_same_cash_state_and_is_future_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registration, _, _ = self._registration(Path(tmp))
        initialization = registration["decision_contract"]["initialization"]
        self.assertFalse(registration["meta"]["strategy_results_evaluated"])
        self.assertFalse(initialization["historical_trading_state_carried_into_forward"])
        self.assertEqual(initialization["same_initial_capital_usdt"], 400.0)
        self.assertEqual(
            registration["decision_contract"]["data"]["forward_start_date"], "2026-07-19"
        )
        self.assertFalse(registration["protocol"]["paper_or_live_allowed"])

    def test_no_future_pair_is_explicit_wait_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registration, base, state_decay = self._registration(root)
            bars = {symbol: _bars(200, trending=False) for symbol in TOP3}
            funding = {symbol: _funding(200, 0.0) for symbol in TOP3}
            report = build_funding_veto_shadow_forward_report(
                bars, funding, _rules(), registration, base, state_decay
            )
        self.assertEqual(report["diagnostics"]["verdict"], "await_shadow_forward_data")
        self.assertFalse(report["meta"]["strategy_results_evaluated"])
        self.assertEqual(report["data"]["evaluation_bar_count"], 0)
        self.assertFalse(report["diagnostics"]["paper_or_live_allowed"])

    def test_forward_rows_have_dual_state_hashes_and_no_historical_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registration, base, state_decay = self._registration(root)
            bars = {symbol: _bars(270, trending=True) for symbol in TOP3}
            funding = {symbol: _funding(270, 0.0005) for symbol in TOP3}
            report = build_funding_veto_shadow_forward_report(
                bars, funding, _rules(), registration, base, state_decay
            )
        self.assertTrue(report["meta"]["strategy_results_evaluated"])
        self.assertEqual(report["evaluation"]["reference"]["start_equity_usdt"], 400.0)
        self.assertEqual(report["evaluation"]["candidate"]["start_equity_usdt"], 400.0)
        self.assertGreater(len(report["journal"]["rows"]), 0)
        first = report["journal"]["rows"][0]
        self.assertGreaterEqual(first["decision_date"], "2026-07-19")
        self.assertEqual(len(first["reference"]["state_hash"]), 64)
        self.assertEqual(len(first["candidate"]["state_hash"]), 64)
        self.assertEqual(len(first["chain_hash"]), 64)
        self.assertGreater(
            report["evaluation"]["funding_veto_activity"]["vetoed_bar_count"], 0
        )
        self.assertFalse(report["diagnostics"]["paper_or_live_allowed"])

    def test_incomplete_forward_funding_is_not_evaluated_as_zero_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registration, base, state_decay = self._registration(root)
            bars = {symbol: _bars(270, trending=True) for symbol in TOP3}
            funding = {symbol: _funding(200, 0.0005) for symbol in TOP3}
            report = build_funding_veto_shadow_forward_report(
                bars, funding, _rules(), registration, base, state_decay
            )
        self.assertGreater(report["data"]["forward_price_pair_count"], 0)
        self.assertEqual(report["data"]["funding_complete_prefix_pair_count"], 0)
        self.assertEqual(report["data"]["evaluation_bar_count"], 0)
        self.assertFalse(report["meta"]["strategy_results_evaluated"])
        self.assertEqual(report["diagnostics"]["verdict"], "await_complete_shadow_inputs")
        self.assertNotIn("evaluation", report)
        self.assertNotIn("journal", report)


if __name__ == "__main__":
    unittest.main()
