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
from qount.mini_trend.pilot_dispatcher import build_manual_arm


def _journal_row(decision_date: str = "2026-08-01") -> dict:
    return {
        "decision_date": decision_date,
        "recorded_at": f"{decision_date}T00:20:00+00:00",
        "mode": "paper",
        "strategy": LIVE_PILOT_CONTRACT.strategy,
        "capital_cap_usdt": 100.0,
        "wallet_balance_usdt": 100.0,
        "equity_usdt": 100.0,
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
        self.assertIn("dry_run_days", payload["diagnostics"]["observation_shortfalls"])
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
            standard_authority_verified=True,
            authority_batch_id="a" * 64,
            runtime_ledger_snapshot_hash="b" * 64,
            pre_dispatch_reconciliation_hash="c" * 64,
            pre_dispatch_reconciliation_passed=True,
            notification_snapshot_hash="d" * 64,
            daily_brief_hash="e" * 64,
            system_health_snapshot_hash="f" * 64,
            system_health_ready=True,
            release_provenance_verified=True,
            release_git_commit="1" * 40,
            release_version="0.2.1",
            release_source_tree_hash="2" * 64,
            release_provenance_hash="3" * 64,
        )
        payload = build_live_pilot_readiness(
            LivePilotRequest(
                owner_requested_one_month_live=True,
                capital_usdt=100.0,
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

    def test_cap_above_one_hundred_is_not_the_current_live_pilot(self) -> None:
        payload = build_live_pilot_readiness(
            LivePilotRequest(
                owner_requested_one_month_live=True,
                capital_usdt=100.01,
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
        self.assertEqual(LIVE_PILOT_CONTRACT.maximum_daily_loss_pct, 5.0)
        self.assertEqual(LIVE_PILOT_CONTRACT.maximum_pilot_drawdown_pct, 10.0)
        self.assertEqual(LIVE_PILOT_CONTRACT.maximum_live_source_age_seconds, 900)
        self.assertEqual(LIVE_PILOT_CONTRACT.maximum_adverse_slippage_bps, 25.0)
        self.assertEqual(LIVE_PILOT_CONTRACT.canary_capital_usdt, 100.0)
        self.assertEqual(LIVE_PILOT_CONTRACT.maximum_capital_usdt, 1000.0)

    def test_elapsed_time_targets_are_observations_not_live_blockers(self) -> None:
        evidence = LivePilotEvidence(
            independent_runtime_verified=True,
            complete_funding_journal=True,
            configured_exchange_route_ok=True,
            public_api_ok=True,
            credentials_ok=True,
            api_key_reading_enabled=True,
            api_key_withdrawal_disabled=True,
            api_key_futures_enabled=True,
            api_key_ip_restricted=True,
            account_balance_audit_complete=True,
            available_balance_usdt=300.0,
            position_mode_oneway=True,
            position_audit_complete=True,
            unmanaged_position_count=0,
            open_order_audit_complete=True,
            isolated_one_x_verified=True,
            legacy_production_cron_disabled=True,
            legacy_live_guard_disarmed=True,
            rollback_documented=True,
            standard_authority_verified=True,
            runtime_ledger_snapshot_hash="a" * 64,
            pre_dispatch_reconciliation_hash="b" * 64,
            pre_dispatch_reconciliation_passed=True,
            notification_snapshot_hash="c" * 64,
            daily_brief_hash="d" * 64,
            system_health_snapshot_hash="e" * 64,
            system_health_ready=True,
            release_provenance_verified=True,
            release_git_commit="1" * 40,
            release_version="0.2.1",
            release_source_tree_hash="2" * 64,
            release_provenance_hash="3" * 64,
        )
        payload = build_live_pilot_readiness(
            LivePilotRequest(
                owner_requested_one_month_live=True,
                capital_usdt=100.0,
                start_date="2026-08-01",
            ),
            evidence,
        )
        self.assertEqual(payload["diagnostics"]["verdict"], "ready_for_manual_final_arm")
        self.assertEqual(
            set(payload["diagnostics"]["observation_shortfalls"]),
            {"forward_pairs", "forward_active_bars", "paper_days", "dry_run_days"},
        )
        tampered = dict(payload)
        tampered["observations"] = {
            **payload["observations"],
            "forward_pairs": {
                **payload["observations"]["forward_pairs"],
                "actual": 60,
            },
        }
        with self.assertRaisesRegex(ValueError, "readiness hash is invalid"):
            build_manual_arm(
                tampered,
                readiness_artifact_sha256="a" * 64,
                confirmed_readiness_hash=payload["readiness_hash"],
                arm_token="a-long-manual-arm-token",
            )

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
            raw = path.read_text(encoding="utf-8").replace('"equity_usdt":100.0', '"equity_usdt":99.0')
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_live_pilot_journal(path)

    def test_journal_rejects_short_or_excess_gross(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            row = _journal_row()
            row["desired_weights"]["BTCUSDT"] = -0.1
            with self.assertRaisesRegex(ValueError, "short exposure"):
                append_live_pilot_journal(Path(tmp) / "pilot.jsonl", row)

    def test_live_journal_rejects_capital_above_canary(self) -> None:
        row = _journal_row()
        row["mode"] = "live"
        row["capital_cap_usdt"] = 100.01
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            ValueError,
            "authorized canary",
        ):
            append_live_pilot_journal(Path(tmp) / "pilot.jsonl", row)


if __name__ == "__main__":
    unittest.main()
