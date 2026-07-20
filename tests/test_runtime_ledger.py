from __future__ import annotations

import json
import os
import sqlite3
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from qount.contracts import canonical_hash
from qount.execution import ExchangeOrderObservation
from qount.execution import recover_unknown_orders
from qount.ledger import AuditJournalError
from qount.ledger import RuntimeLedger
from qount.ledger import RuntimeLedgerConflictError
from qount.ledger import RuntimeLedgerError
from qount.ledger import RuntimeLedgerSecurityError
from qount.ledger import reconcile_three_way
from qount.ledger import verify_audit_journal
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import build_decision_batch_manifest
from tests.test_immutable_contract_artifacts import _objects


BATCH_TIME = "2026-07-20T00:06:00+00:00"


def _hash(name: str) -> str:
    return canonical_hash({"fixture": name})


def _batch() -> VerifiedDecisionBatch:
    snapshot, intent, target, risk, plan, *_ = _objects()
    manifest = build_decision_batch_manifest(
        snapshot=snapshot,
        intents=(intent,),
        target=target,
        risk=risk,
        plan=plan,
        created_at=BATCH_TIME,
    )
    return VerifiedDecisionBatch(
        manifest=manifest,
        snapshot=snapshot,
        intents=(intent,),
        target=target,
        risk=risk,
        plan=plan,
    )


class RuntimeLedgerTest(unittest.TestCase):
    def _ledger(
        self,
        root: Path,
        *,
        auto_flush: bool = True,
    ) -> RuntimeLedger:
        return RuntimeLedger(root / "runtime.sqlite3", auto_flush=auto_flush)

    def test_wal_schema_permissions_integrity_and_batch_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = self._ledger(root)
            batch = _batch()

            self.assertTrue(ledger.record_verified_batch(batch, recorded_at=BATCH_TIME))
            self.assertFalse(ledger.record_verified_batch(batch, recorded_at=BATCH_TIME))
            report = ledger.integrity_check()

            self.assertEqual(report["journal_mode"], "wal")
            self.assertTrue(report["foreign_keys"])
            self.assertEqual(report["synchronous"], "full")
            self.assertEqual(report["audit_rows"], 1 + len(batch.plan.orders))
            self.assertEqual(
                stat.S_IMODE(os.stat(root / "runtime.sqlite3").st_mode),
                0o600,
            )
            connection = sqlite3.connect(root / "runtime.sqlite3")
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                order_count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            finally:
                connection.close()
            self.assertTrue(
                {
                    "batches",
                    "orders",
                    "order_events",
                    "fills",
                    "cash_events",
                    "positions",
                    "nav_marks",
                    "reconciliations",
                    "audit_outbox",
                }.issubset(tables)
            )
            self.assertEqual(order_count, len(batch.plan.orders))

            os.chmod(root / "runtime.sqlite3", 0o644)
            with self.assertRaisesRegex(
                RuntimeLedgerSecurityError,
                "database_mode_invalid",
            ):
                self._ledger(root)

    def test_tampered_batch_and_conflicting_immutable_event_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = self._ledger(Path(temporary))
            batch = _batch()
            tampered = replace(
                batch,
                snapshot=replace(batch.snapshot, prices={"BTCUSDT": 99_000.0}),
            )
            with self.assertRaisesRegex(RuntimeLedgerError, "verified_decision_batch_invalid"):
                ledger.record_verified_batch(tampered, recorded_at=BATCH_TIME)

            ledger.record_verified_batch(batch, recorded_at=BATCH_TIME)
            ledger.record_cash_event(
                event_key="funding-1",
                event_type="funding",
                amount=1.0,
                asset="USDT",
                occurred_at="2026-07-20T00:06:30+00:00",
                source_hash=_hash("funding-1"),
            )
            with self.assertRaisesRegex(RuntimeLedgerConflictError, "cash_event_conflict"):
                ledger.record_cash_event(
                    event_key="funding-1",
                    event_type="funding",
                    amount=2.0,
                    asset="USDT",
                    occurred_at="2026-07-20T00:06:30+00:00",
                    source_hash=_hash("funding-1"),
                )

    def test_order_state_machine_rejects_skips_regressions_and_identity_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = self._ledger(Path(temporary))
            batch = _batch()
            ledger.record_verified_batch(batch, recorded_at=BATCH_TIME)
            order = batch.plan.orders[1]

            with self.assertRaisesRegex(ValueError, "PLANNED->FILLED"):
                ledger.transition_order(
                    order.client_order_id,
                    "FILLED",
                    event_at="2026-07-20T00:06:10+00:00",
                    source_hash=_hash("illegal"),
                    executed_quantity=order.quantity,
                    average_price=100_000.0,
                )
            ledger.transition_order(
                order.client_order_id,
                "SUBMITTING",
                event_at="2026-07-20T00:06:10+00:00",
                source_hash=_hash("submitting"),
            )
            ledger.transition_order(
                order.client_order_id,
                "PARTIALLY_FILLED",
                event_at="2026-07-20T00:06:20+00:00",
                source_hash=_hash("partial"),
                exchange_order_id="exchange-1",
                executed_quantity=0.0004,
                average_price=100_000.0,
            )
            with self.assertRaisesRegex(RuntimeLedgerError, "quantity_regression"):
                ledger.transition_order(
                    order.client_order_id,
                    "PARTIALLY_FILLED",
                    event_at="2026-07-20T00:06:21+00:00",
                    source_hash=_hash("regression"),
                    exchange_order_id="exchange-1",
                    executed_quantity=0.0003,
                    average_price=100_000.0,
                )
            with self.assertRaisesRegex(RuntimeLedgerConflictError, "exchange_id_conflict"):
                ledger.transition_order(
                    order.client_order_id,
                    "UNKNOWN",
                    event_at="2026-07-20T00:06:22+00:00",
                    source_hash=_hash("wrong-exchange-id"),
                    exchange_order_id="exchange-2",
                    executed_quantity=0.0004,
                    average_price=100_000.0,
                )

    def test_unknown_recovery_resolves_by_client_id_or_requires_halt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = self._ledger(root)
            batch = _batch()
            ledger.record_verified_batch(batch, recorded_at=BATCH_TIME)
            order = batch.plan.orders[1]
            ledger.transition_order(
                order.client_order_id,
                "SUBMITTING",
                event_at="2026-07-20T00:06:10+00:00",
                source_hash=_hash("submitting"),
            )

            unresolved = recover_unknown_orders(
                ledger,
                lambda query: None,
                started_at="2026-07-20T00:06:11+00:00",
                completed_at="2026-07-20T00:06:12+00:00",
            )
            self.assertTrue(unresolved.halt_required)
            self.assertFalse(unresolved.risk_increase_allowed)
            self.assertEqual(ledger.get_order(order.client_order_id)["status"], "UNKNOWN")

            restarted = self._ledger(root)

            def resolve(query):
                self.assertEqual(query.client_order_id, order.client_order_id)
                return ExchangeOrderObservation.create(
                    client_order_id=query.client_order_id,
                    status="FILLED",
                    observed_at="2026-07-20T00:06:20+00:00",
                    exchange_order_id="exchange-1",
                    executed_quantity=float(order.quantity),
                    average_price=100_000.0,
                    source_hash=_hash("filled-observation"),
                )

            resolved = recover_unknown_orders(
                restarted,
                resolve,
                started_at="2026-07-20T00:06:19+00:00",
                completed_at="2026-07-20T00:06:21+00:00",
            )
            self.assertFalse(resolved.halt_required)
            self.assertEqual(resolved.resolved_client_order_ids, (order.client_order_id,))
            self.assertEqual(restarted.get_order(order.client_order_id)["status"], "FILLED")

    def test_recovery_query_error_stays_unknown_without_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = self._ledger(Path(temporary))
            batch = _batch()
            ledger.record_verified_batch(batch, recorded_at=BATCH_TIME)
            order = batch.plan.orders[1]
            ledger.transition_order(
                order.client_order_id,
                "SUBMITTING",
                event_at="2026-07-20T00:06:10+00:00",
                source_hash=_hash("submitting"),
            )

            def failing_resolver(_query):
                raise TimeoutError("private exchange detail must not leak")

            report = recover_unknown_orders(
                ledger,
                failing_resolver,
                started_at="2026-07-20T00:06:11+00:00",
                completed_at="2026-07-20T00:06:12+00:00",
            )
            self.assertEqual(
                report.errors[order.client_order_id],
                "resolver_error:TimeoutError",
            )
            self.assertNotIn("private exchange detail", json.dumps(dict(report.errors)))
            self.assertEqual(ledger.get_order(order.client_order_id)["status"], "UNKNOWN")
            self.assertEqual(len(batch.plan.orders), 3)

    def test_partial_fill_survives_restart_and_does_not_duplicate_fills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = self._ledger(root)
            batch = _batch()
            ledger.record_verified_batch(batch, recorded_at=BATCH_TIME)
            order = batch.plan.orders[1]
            ledger.transition_order(
                order.client_order_id,
                "SUBMITTING",
                event_at="2026-07-20T00:06:10+00:00",
                source_hash=_hash("submitting"),
            )
            ledger.transition_order(
                order.client_order_id,
                "PARTIALLY_FILLED",
                event_at="2026-07-20T00:06:20+00:00",
                source_hash=_hash("partial-1"),
                exchange_order_id="exchange-1",
                executed_quantity=0.0004,
                average_price=100_000.0,
            )
            ledger.record_fill(
                client_order_id=order.client_order_id,
                exchange_trade_id="trade-1",
                quantity=0.0004,
                price=100_000.0,
                fee=0.04,
                fee_asset="USDT",
                occurred_at="2026-07-20T00:06:20+00:00",
                source_hash=_hash("fill-1"),
            )

            restarted = self._ledger(root)
            restarted.transition_order(
                order.client_order_id,
                "FILLED",
                event_at="2026-07-20T00:06:30+00:00",
                source_hash=_hash("filled"),
                exchange_order_id="exchange-1",
                executed_quantity=0.001,
                average_price=100_100.0,
            )
            restarted.record_fill(
                client_order_id=order.client_order_id,
                exchange_trade_id="trade-2",
                quantity=0.0006,
                price=100_200.0,
                fee=0.06,
                fee_asset="USDT",
                occurred_at="2026-07-20T00:06:30+00:00",
                source_hash=_hash("fill-2"),
            )
            self.assertFalse(
                restarted.record_fill(
                    client_order_id=order.client_order_id,
                    exchange_trade_id="trade-2",
                    quantity=0.0006,
                    price=100_200.0,
                    fee=0.06,
                    fee_asset="USDT",
                    occurred_at="2026-07-20T00:06:30+00:00",
                    source_hash=_hash("fill-2"),
                )
            )
            self.assertAlmostEqual(restarted.position_quantities()["BTCUSDT"], 0.001)
            self.assertEqual(len(restarted.list_order_events(order.client_order_id)), 3)
            restarted.integrity_check()

    def test_outbox_recovers_both_crash_windows_without_duplicate_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = self._ledger(root, auto_flush=False)
            ledger.record_verified_batch(_batch(), recorded_at=BATCH_TIME)
            self.assertFalse(ledger.audit_path.exists())

            restarted = self._ledger(root)
            expected_rows = 1 + len(_batch().plan.orders)
            self.assertEqual(
                verify_audit_journal(restarted.audit_path).row_count,
                expected_rows,
            )
            self.assertFalse(restarted.record_verified_batch(_batch(), recorded_at=BATCH_TIME))
            self.assertEqual(
                verify_audit_journal(restarted.audit_path).row_count,
                expected_rows,
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = self._ledger(root)
            with patch.object(
                ledger,
                "_mark_outbox_published",
                side_effect=OSError("injected marker failure"),
            ), self.assertRaisesRegex(OSError, "marker failure"):
                ledger.record_verified_batch(_batch(), recorded_at=BATCH_TIME)
            expected_rows = 1 + len(_batch().plan.orders)
            self.assertEqual(
                verify_audit_journal(ledger.audit_path).row_count,
                1,
            )

            restarted = self._ledger(root)
            self.assertEqual(
                verify_audit_journal(restarted.audit_path).row_count,
                expected_rows,
            )
            restarted.integrity_check()

    def test_jsonl_tamper_is_detected_before_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = self._ledger(root)
            ledger.record_verified_batch(_batch(), recorded_at=BATCH_TIME)
            lines = ledger.audit_path.read_text(encoding="ascii").splitlines()
            row = json.loads(lines[0])
            row["payload"]["manifest_hash"] = "f" * 64
            ledger.audit_path.write_text(
                json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                + "\n"
                + "\n".join(lines[1:])
                + "\n",
                encoding="ascii",
            )
            os.chmod(ledger.audit_path, 0o600)
            with self.assertRaises(AuditJournalError):
                verify_audit_journal(ledger.audit_path)
            with self.assertRaises(AuditJournalError):
                self._ledger(root)

    def test_accounting_identity_residual_and_three_way_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = self._ledger(Path(temporary))
            batch = _batch()
            ledger.record_verified_batch(batch, recorded_at=BATCH_TIME)
            ledger.record_position_snapshot(
                symbol="ETHUSDT",
                quantity=0.01,
                average_cost=3_500.0,
                realized_trading_pnl=0.0,
                occurred_at="2026-07-20T00:06:05+00:00",
                source_hash=_hash("eth-opening-position"),
            )
            buy = batch.plan.orders[1]
            ledger.transition_order(
                buy.client_order_id,
                "SUBMITTING",
                event_at="2026-07-20T00:06:10+00:00",
                source_hash=_hash("submitting"),
            )
            ledger.transition_order(
                buy.client_order_id,
                "FILLED",
                event_at="2026-07-20T00:06:20+00:00",
                source_hash=_hash("filled"),
                exchange_order_id="exchange-1",
                executed_quantity=0.001,
                average_price=100_000.0,
            )
            ledger.record_fill(
                client_order_id=buy.client_order_id,
                exchange_trade_id="trade-1",
                quantity=0.001,
                price=100_000.0,
                fee=0.1,
                fee_asset="USDT",
                occurred_at="2026-07-20T00:06:20+00:00",
                source_hash=_hash("fill"),
            )
            ledger.record_cash_event(
                event_key="funding-1",
                event_type="funding",
                amount=2.0,
                asset="USDT",
                occurred_at="2026-07-20T00:06:30+00:00",
                source_hash=_hash("funding"),
            )
            ledger.record_cash_event(
                event_key="fee-1",
                event_type="fee",
                amount=1.0,
                asset="USDT",
                occurred_at="2026-07-20T00:06:31+00:00",
                source_hash=_hash("fee"),
            )
            ledger.record_cash_event(
                event_key="transfer-1",
                event_type="transfer",
                amount=10.0,
                asset="USDT",
                occurred_at="2026-07-20T00:06:32+00:00",
                source_hash=_hash("transfer"),
            )
            nav = ledger.record_nav_mark(
                marked_at="2026-07-20T00:07:00+00:00",
                opening_equity=1_000.0,
                equity=1_015.9,
                trading_pnl=5.0,
                residual_tolerance=0.001,
                source_hash=_hash("nav-1"),
            )
            self.assertAlmostEqual(nav.equity_change, 15.9)
            self.assertAlmostEqual(nav.funding, 2.0)
            self.assertAlmostEqual(nav.fees, 1.1)
            self.assertAlmostEqual(nav.transfers, 10.0)
            self.assertAlmostEqual(nav.residual, 0.0)
            self.assertTrue(nav.passed)
            with self.assertRaisesRegex(
                RuntimeLedgerError,
                "closed_nav_period",
            ):
                ledger.record_cash_event(
                    event_key="late-funding",
                    event_type="funding",
                    amount=1.0,
                    asset="USDT",
                    occurred_at="2026-07-20T00:06:59+00:00",
                    source_hash=_hash("late-funding"),
                )

            for index, order in enumerate((batch.plan.orders[0], batch.plan.orders[2]), 1):
                ledger.transition_order(
                    order.client_order_id,
                    "CANCELED",
                    event_at=f"2026-07-20T00:07:0{index}+00:00",
                    source_hash=_hash(f"cancel-{index}"),
                )
            passed = reconcile_three_way(
                batch_id=batch.manifest.batch_id,
                reconciled_at="2026-07-20T00:07:10+00:00",
                target_positions=dict(batch.plan.expected_positions),
                ledger_positions=ledger.position_quantities(),
                exchange_positions={"BTCUSDT": 0.001, "ETHUSDT": 0.01},
                position_tolerances=dict(batch.plan.reconciliation_tolerance),
                ledger_open_order_ids=ledger.open_order_ids(),
                exchange_open_order_ids=(),
                equity_residual=nav.residual,
                equity_residual_tolerance=nav.residual_tolerance,
            )
            self.assertTrue(passed.passed)
            ledger.record_reconciliation(passed)
            self.assertTrue(ledger.risk_increase_allowed())

            fabricated = reconcile_three_way(
                batch_id=batch.manifest.batch_id,
                reconciled_at="2026-07-20T00:07:11+00:00",
                target_positions={"BTCUSDT": 0.001},
                ledger_positions=ledger.position_quantities(),
                exchange_positions={"BTCUSDT": 0.001, "ETHUSDT": 0.01},
                position_tolerances=dict(batch.plan.reconciliation_tolerance),
                ledger_open_order_ids=ledger.open_order_ids(),
                exchange_open_order_ids=(),
                equity_residual=nav.residual,
                equity_residual_tolerance=nav.residual_tolerance,
            )
            with self.assertRaisesRegex(
                RuntimeLedgerError,
                "target_not_batch_authoritative",
            ):
                ledger.record_reconciliation(fabricated)

            failed_nav = ledger.record_nav_mark(
                marked_at="2026-07-20T00:08:00+00:00",
                equity=1_017.9,
                trading_pnl=1.0,
                residual_tolerance=0.01,
                source_hash=_hash("nav-2"),
            )
            self.assertAlmostEqual(failed_nav.residual, 1.0)
            self.assertFalse(failed_nav.passed)
            self.assertFalse(ledger.risk_increase_allowed())

            unmanaged = reconcile_three_way(
                batch_id=batch.manifest.batch_id,
                reconciled_at="2026-07-20T00:08:10+00:00",
                target_positions={"BTCUSDT": 0.001},
                ledger_positions={"BTCUSDT": 0.001},
                exchange_positions={"BTCUSDT": 0.001, "ETHUSDT": 0.01},
                position_tolerances={"BTCUSDT": 1e-9, "ETHUSDT": 1e-9},
                ledger_open_order_ids=("known-order",),
                exchange_open_order_ids=("unmanaged-order",),
                equity_residual=failed_nav.residual,
                equity_residual_tolerance=failed_nav.residual_tolerance,
            )
            self.assertFalse(unmanaged.passed)
            self.assertTrue(unmanaged.halt_required)
            self.assertIn("unmanaged_exchange_order:unmanaged-order", unmanaged.blockers)
            self.assertIn("ledger_order_missing_on_exchange:known-order", unmanaged.blockers)
            self.assertIn("ledger_exchange_position_mismatch:ETHUSDT", unmanaged.blockers)
            self.assertIn("equity_residual_exceeds_tolerance", unmanaged.blockers)


if __name__ == "__main__":
    unittest.main()
