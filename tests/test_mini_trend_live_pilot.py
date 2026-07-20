from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.live_pilot import LivePilotEvidence
from qount.mini_trend.live_pilot import LivePilotRequest
from qount.mini_trend.live_pilot import build_live_pilot_readiness
from qount.mini_trend.live_pilot import append_live_pilot_journal
from qount.mini_trend.live_pilot import verify_live_pilot_journal


def _journal_row(decision_date: str = "2026-08-01") -> dict:
    return {
        "decision_date": decision_date,
        "recorded_at": f"{decision_date}T00:20:00+00:00",
        "mode": "paper",
        "strategy": LIVE_PILOT_CONTRACT.strategy,
        "capital_cap_usdt": 300.0,
        "wallet_balance_usdt": 300.0,
        "equity_usdt": 300.0,
        "desired_weights": {symbol: 0.0 for symbol in LIVE_PILOT_CONTRACT.universe},
        "actual_weights": {symbol: 0.0 for symbol in LIVE_PILOT_CONTRACT.universe},
        "order_intents": [],
        "order_results": [],
        "funding_pnl_usdt": 0.0,
        "fees_usdt": 0.0,
        "execution_state": {"halted": False},
        "risk_flags": [],
    }


class MiniTrendLivePilotTest(unittest.TestCase):
    def test_current_request_is_blocked_without_exact_capital_and_evidence(self) -> None:
        payload = build_live_pilot_readiness(
            LivePilotRequest(owner_requested_one_month_live=True),
            LivePilotEvidence(legacy_production_cron_disabled=True, public_api_ok=True),
        )
        self.assertEqual(
            payload["diagnostics"]["verdict"], "blocked_live_pilot_readiness"
        )
        self.assertIn(
            "exact_capital_within_pilot_cap", payload["diagnostics"]["blockers"]
        )
        self.assertIn("private_credentials", payload["diagnostics"]["blockers"])
        self.assertIn("minimum_dry_run_days", payload["diagnostics"]["blockers"])
        self.assertIn(
            "independent_runtime_verified", payload["diagnostics"]["blockers"]
        )
        self.assertFalse(payload["meta"]["live_orders_allowed"])

    def test_ready_state_still_requires_separate_manual_arm(self) -> None:
        evidence = LivePilotEvidence(
            forward_pairs=60,
            forward_active_bars=10,
            paper_days=30,
            dry_run_days=7,
            independent_runtime_verified=True,
            complete_funding_journal=True,
            configured_exchange_route_ok=True,
            public_api_ok=True,
            credentials_ok=True,
            api_key_reading_enabled=True,
            api_key_spot_margin_disabled=True,
            api_key_withdrawal_disabled=True,
            api_key_futures_enabled=True,
            api_key_ip_restricted=True,
            account_balance_audit_complete=True,
            available_balance_usdt=300.0,
            position_mode_oneway=True,
            position_audit_complete=True,
            unmanaged_position_count=0,
            account_flat=True,
            open_order_audit_complete=True,
            open_order_count=0,
            isolated_one_x_verified=True,
            legacy_production_cron_disabled=True,
            legacy_live_guard_disarmed=True,
            rollback_documented=True,
        )
        payload = build_live_pilot_readiness(
            LivePilotRequest(
                owner_requested_one_month_live=True,
                capital_usdt=300.0,
                start_date="2026-08-01",
            ),
            evidence,
        )
        self.assertEqual(
            payload["diagnostics"]["verdict"], "ready_for_manual_final_arm"
        )
        self.assertTrue(payload["diagnostics"]["readiness_passed"])
        self.assertFalse(payload["diagnostics"]["live_orders_allowed"])
        self.assertEqual(payload["request"]["end_date_exclusive"], "2026-08-31")

    def test_cap_above_one_thousand_is_not_the_current_live_pilot(self) -> None:
        payload = build_live_pilot_readiness(
            LivePilotRequest(
                owner_requested_one_month_live=True,
                capital_usdt=1000.01,
                start_date="2026-08-01",
            ),
            LivePilotEvidence(),
        )
        self.assertFalse(payload["gates"]["exact_capital_within_pilot_cap"])

    def test_contract_is_long_cash_one_x_without_carry(self) -> None:
        execution = LIVE_PILOT_CONTRACT.contract_basis["execution"]
        self.assertEqual(LIVE_PILOT_CONTRACT.exchange_leverage, 1)
        self.assertEqual(LIVE_PILOT_CONTRACT.maximum_effective_gross, 1.0)
        self.assertFalse(execution["shorting_allowed"])
        self.assertFalse(execution["carry_allowed"])
        self.assertTrue(execution["private_api_key_reading_permission_required"])
        self.assertTrue(execution["private_api_key_spot_margin_permission_allowed"])
        self.assertFalse(execution["funding_veto_controls_live_orders"])
        self.assertFalse(execution["risk_tier_controls_live_orders"])
        self.assertEqual(
            LIVE_PILOT_CONTRACT.shadow_candidate,
            "MiniTrend-UM-RiskTier-v0.2",
        )
        self.assertIsNone(LIVE_PILOT_CONTRACT.maximum_daily_loss_pct)
        self.assertEqual(LIVE_PILOT_CONTRACT.maximum_pilot_drawdown_pct, 10.0)

    def test_append_only_journal_chains_rows_and_rejects_duplicate_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pilot.jsonl"
            first = append_live_pilot_journal(path, _journal_row())
            second = append_live_pilot_journal(path, _journal_row("2026-08-02"))
            verified = verify_live_pilot_journal(path)
            with self.assertRaisesRegex(ValueError, "duplicate pilot journal decision date"):
                append_live_pilot_journal(path, _journal_row())
        self.assertEqual(verified["row_count"], 2)
        self.assertEqual(verified["final_chain_hash"], second["chain_hash"])
        self.assertNotEqual(first["chain_hash"], second["chain_hash"])

    def test_journal_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pilot.jsonl"
            append_live_pilot_journal(path, _journal_row())
            raw = path.read_text(encoding="utf-8").replace('"equity_usdt":300.0', '"equity_usdt":299.0')
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_live_pilot_journal(path)

    def test_journal_rejects_short_or_excess_gross(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            row = _journal_row()
            row["desired_weights"]["BTCUSDT"] = -0.1
            with self.assertRaisesRegex(ValueError, "short exposure"):
                append_live_pilot_journal(Path(tmp) / "pilot.jsonl", row)


if __name__ == "__main__":
    unittest.main()
