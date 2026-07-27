from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from qount.contracts import canonical_hash
from qount.ledger import AuditJournalError
from qount.ledger import RuntimeLedger
from qount.ledger import RuntimeLedgerConflictError
from qount.ledger import RuntimeLedgerError
from qount.ledger import RuntimeLedgerSnapshotError
from qount.ledger import build_runtime_ledger_snapshot
from qount.ledger import reconcile_three_way
from qount.reporting import DashboardPublication
from qount.reporting import DashboardReadModelError
from qount.reporting import build_dashboard_v1
from qount.reporting import publish_dashboard_v1
from qount.reporting import read_dashboard_v1
from tests.test_immutable_contract_artifacts import _objects
from tests.test_runtime_ledger import _batch


CAPTURED_AT = "2026-07-20T00:07:20+00:00"


def _hash(name: str) -> str:
    return canonical_hash({"dashboard_ledger_fixture": name})


def _canonical_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _ledger_with_accounting(
    root: Path,
    *,
    unresolved: bool = False,
    include_nav: bool = True,
    include_reconciliation: bool = True,
) -> tuple[RuntimeLedger, object, object]:
    ledger = RuntimeLedger(root / "runtime.sqlite3")
    batch = _batch()
    registry = _objects()[6]
    ledger.record_verified_batch(
        batch,
        recorded_at="2026-07-20T00:06:00+00:00",
    )
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
    for event_key, event_type, amount, occurred_at in (
        ("funding-1", "funding", 2.0, "2026-07-20T00:06:30+00:00"),
        ("fee-1", "fee", 1.0, "2026-07-20T00:06:31+00:00"),
        ("transfer-1", "transfer", 10.0, "2026-07-20T00:06:32+00:00"),
    ):
        ledger.record_cash_event(
            event_key=event_key,
            event_type=event_type,
            amount=amount,
            asset="USDT",
            occurred_at=occurred_at,
            source_hash=_hash(event_key),
        )
    if not include_nav:
        return ledger, batch, registry
    ledger.record_account_observation(
        batch_id=batch.manifest.batch_id,
        observed_at="2026-07-20T00:07:00+00:00",
        quote_asset="USDT",
        wallet_balance=1_015.9,
        available_balance=900.0,
        actual_gross_notional=135.0,
        margin_used=67.5,
        source_id=_hash("account-source-id"),
        source_hash=_hash("account-source"),
    )
    nav = ledger.record_nav_mark(
        marked_at="2026-07-20T00:07:00+00:00",
        opening_equity=1_000.0,
        equity=1_015.9,
        trading_pnl=5.0,
        residual_tolerance=0.001,
        source_hash=_hash("nav-1"),
        signal_nav=1.018,
        standalone_executable_nav=1.0159,
    )
    ledger.transition_order(
        batch.plan.orders[0].client_order_id,
        "CANCELED",
        event_at="2026-07-20T00:07:01+00:00",
        source_hash=_hash("cancel-1"),
    )
    protective = batch.plan.orders[2]
    if unresolved:
        ledger.transition_order(
            protective.client_order_id,
            "SUBMITTING",
            event_at="2026-07-20T00:07:02+00:00",
            source_hash=_hash("protective-submitting"),
        )
        ledger.transition_order(
            protective.client_order_id,
            "UNKNOWN",
            event_at="2026-07-20T00:07:03+00:00",
            source_hash=_hash("protective-unknown"),
            reason="exchange_result_ambiguous",
        )
    else:
        ledger.transition_order(
            protective.client_order_id,
            "CANCELED",
            event_at="2026-07-20T00:07:02+00:00",
            source_hash=_hash("cancel-2"),
        )
    if not include_reconciliation:
        return ledger, batch, registry
    ledger_open_orders = ledger.open_order_ids()
    report = reconcile_three_way(
        batch_id=batch.manifest.batch_id,
        reconciled_at="2026-07-20T00:07:10+00:00",
        target_positions=dict(batch.plan.expected_positions),
        ledger_positions=ledger.position_quantities(),
        exchange_positions={"BTCUSDT": 0.001, "ETHUSDT": 0.01},
        position_tolerances=dict(batch.plan.reconciliation_tolerance),
        ledger_open_order_ids=ledger_open_orders,
        exchange_open_order_ids=ledger_open_orders,
        equity_residual=nav.residual,
        equity_residual_tolerance=nav.residual_tolerance,
    )
    ledger.record_reconciliation(report)
    return ledger, batch, registry


def _golden_summary(snapshot, models) -> dict[str, object]:
    publication = DashboardPublication.create(models)
    return {
        "schema_version": 1,
        "ledger_snapshot": {
            "snapshot_hash": snapshot.snapshot_hash,
            "canonical_hash": canonical_hash(snapshot.as_dict()),
            "source_updated_at": snapshot.source_updated_at,
            "audit_last_hash": snapshot.audit_last_hash,
            "audit_row_count": snapshot.audit_row_count,
            "positions": dict(snapshot.positions),
        },
        "dashboard": {
            model.read_model_type: {
                "read_model_id": model.read_model_id,
                "read_model_hash": model.read_model_hash,
                "payload_hash": canonical_hash(model.payload),
            }
            for model in models.models()
        },
        "publication_hash": publication.publication_hash,
    }


class LedgerDashboardBridgeTest(unittest.TestCase):
    def test_snapshot_is_deterministic_and_bound_to_audit_and_batch(self) -> None:
        snapshots = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temporary:
                ledger, batch, _ = _ledger_with_accounting(Path(temporary))
                snapshot = build_runtime_ledger_snapshot(
                    ledger,
                    batch,
                    captured_at=CAPTURED_AT,
                )
                snapshot.validate()
                snapshots.append(snapshot)
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(
            snapshots[0].positions,
            {"BTCUSDT": 0.001, "ETHUSDT": 0.01},
        )
        self.assertEqual(snapshots[0].audit_row_count, 16)
        self.assertEqual(
            snapshots[0].source_updated_at,
            "2026-07-20T00:07:10+00:00",
        )

    def test_snapshot_exposes_rich_runtime_facts_and_rejects_fill_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(Path(temporary))
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )

        self.assertEqual(snapshot.schema_version, 3)
        self.assertEqual(len(snapshot.orders), 3)
        self.assertEqual(len(snapshot.order_events), 4)
        self.assertEqual(len(snapshot.fills), 1)
        self.assertEqual(len(snapshot.cash_events), 3)
        self.assertEqual(len(snapshot.position_details), 2)
        self.assertEqual(snapshot.account["wallet_balance"], 1_015.9)
        self.assertAlmostEqual(
            snapshot.account["actual_gross_fraction"], 135.0 / 1_015.9
        )
        self.assertAlmostEqual(
            snapshot.account["margin_fraction"], 67.5 / 1_015.9
        )
        self.assertEqual(snapshot.account["peak_equity"], 1_015.9)
        self.assertEqual(snapshot.account["peak_drawdown_fraction"], 0.0)
        self.assertEqual(
            {row["phase"] for row in snapshot.orders},
            {"reduce", "increase", "protective"},
        )
        self.assertEqual(snapshot.fills[0]["fee"], 0.1)
        fill = dict(snapshot.fills[0])
        fill["fee"] = 9.9
        core = snapshot.as_dict()
        core.pop("snapshot_hash")
        core["fills"] = (fill,)
        tampered = type(snapshot)(
            **core,
            snapshot_hash=canonical_hash(core),
        )
        with self.assertRaisesRegex(
            RuntimeLedgerSnapshotError, "fill_hash_invalid"
        ):
            tampered.validate()

        account = dict(snapshot.account)
        account["wallet_balance"] = 9_999.0
        core = snapshot.as_dict()
        core.pop("snapshot_hash")
        core["account"] = account
        tampered_account = type(snapshot)(
            **core,
            snapshot_hash=canonical_hash(core),
        )
        with self.assertRaisesRegex(
            RuntimeLedgerSnapshotError, "account_hash_invalid"
        ):
            tampered_account.validate()

    def test_account_observation_is_idempotent_and_time_monotonic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(
                Path(temporary), include_nav=False
            )
            arguments = {
                "batch_id": batch.manifest.batch_id,
                "observed_at": "2026-07-20T00:06:50+00:00",
                "quote_asset": "USDT",
                "wallet_balance": 1_000.0,
                "available_balance": 900.0,
                "actual_gross_notional": 100.0,
                "margin_used": 50.0,
                "source_id": _hash("account-idempotent-id"),
                "source_hash": _hash("account-idempotent-source"),
            }
            first = ledger.record_account_observation(**arguments)
            self.assertEqual(ledger.record_account_observation(**arguments), first)
            with self.assertRaisesRegex(
                RuntimeLedgerConflictError, "account_observation_conflict"
            ):
                ledger.record_account_observation(
                    **(arguments | {"wallet_balance": 999.0})
                )
            ledger.record_account_observation(
                **(
                    arguments
                    | {
                        "observed_at": "2026-07-20T00:06:51+00:00",
                        "source_hash": _hash("account-later-source"),
                    }
                )
            )
            with self.assertRaisesRegex(
                RuntimeLedgerError, "account_observation_time_regression"
            ):
                ledger.record_account_observation(
                    **(
                        arguments
                        | {
                            "observed_at": "2026-07-20T00:06:49+00:00",
                            "source_hash": _hash("account-earlier-source"),
                        }
                    )
                )

    def test_peak_drawdown_is_derived_from_authoritative_nav_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(Path(temporary))
            ledger.record_account_observation(
                batch_id=batch.manifest.batch_id,
                observed_at="2026-07-20T00:08:00+00:00",
                quote_asset="USDT",
                wallet_balance=900.0,
                available_balance=800.0,
                actual_gross_notional=90.0,
                margin_used=45.0,
                source_id=_hash("drawdown-account-id"),
                source_hash=_hash("drawdown-account-source"),
            )
            nav = ledger.record_nav_mark(
                marked_at="2026-07-20T00:08:00+00:00",
                equity=900.0,
                trading_pnl=-115.9,
                residual_tolerance=0.001,
                source_hash=_hash("nav-drawdown"),
            )
            report = reconcile_three_way(
                batch_id=batch.manifest.batch_id,
                reconciled_at="2026-07-20T00:08:10+00:00",
                target_positions=dict(batch.plan.expected_positions),
                ledger_positions=ledger.position_quantities(),
                exchange_positions={"BTCUSDT": 0.001, "ETHUSDT": 0.01},
                position_tolerances=dict(batch.plan.reconciliation_tolerance),
                ledger_open_order_ids=ledger.open_order_ids(),
                exchange_open_order_ids=ledger.open_order_ids(),
                equity_residual=nav.residual,
                equity_residual_tolerance=nav.residual_tolerance,
            )
            ledger.record_reconciliation(report)
            snapshot = build_runtime_ledger_snapshot(
                ledger,
                batch,
                captured_at="2026-07-20T00:08:20+00:00",
            )

        expected = (1_015.9 - 900.0) / 1_015.9
        self.assertEqual(len(snapshot.nav_history), 2)
        self.assertAlmostEqual(snapshot.account["current_drawdown_fraction"], expected)
        self.assertAlmostEqual(snapshot.account["peak_drawdown_fraction"], expected)
        self.assertEqual(
            snapshot.account["peak_drawdown_at"],
            "2026-07-20T00:08:00+00:00",
        )

    def test_snapshot_requires_nav_and_same_batch_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(
                Path(temporary), include_nav=False
            )
            with self.assertRaisesRegex(
                RuntimeLedgerSnapshotError, "nav_mark_missing"
            ):
                build_runtime_ledger_snapshot(
                    ledger, batch, captured_at=CAPTURED_AT
                )
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(
                Path(temporary), include_reconciliation=False
            )
            with self.assertRaisesRegex(
                RuntimeLedgerSnapshotError, "reconciliation_missing"
            ):
                build_runtime_ledger_snapshot(
                    ledger, batch, captured_at=CAPTURED_AT
                )

    def test_audit_or_snapshot_tamper_fails_before_dashboard_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, registry = _ledger_with_accounting(Path(temporary))
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            tampered = replace(
                snapshot,
                positions={"BTCUSDT": 0.5, "ETHUSDT": 0.01},
            )
            with self.assertRaisesRegex(
                DashboardReadModelError, "runtime_ledger_snapshot_invalid"
            ):
                build_dashboard_v1(
                    batch,
                    registry,
                    generated_at=CAPTURED_AT,
                    ledger_snapshot=tampered,
                )

            lines = ledger.audit_path.read_text(encoding="ascii").splitlines()
            row = json.loads(lines[0])
            row["payload"]["manifest_hash"] = "f" * 64
            ledger.audit_path.write_text(
                json.dumps(
                    row,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
                + "\n".join(lines[1:])
                + "\n",
                encoding="ascii",
            )
            os.chmod(ledger.audit_path, 0o600)
            with self.assertRaises(AuditJournalError):
                build_runtime_ledger_snapshot(
                    ledger, batch, captured_at=CAPTURED_AT
                )

    def test_unresolved_order_remains_visible_and_blocks_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, registry = _ledger_with_accounting(
                Path(temporary), unresolved=True
            )
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            self.assertEqual(len(snapshot.unresolved_order_ids), 1)
            models = build_dashboard_v1(
                batch,
                registry,
                generated_at=CAPTURED_AT,
                ledger_snapshot=snapshot,
            )
            self.assertEqual(
                models.readiness.payload["status"], "blocked_runtime_state"
            )
            self.assertEqual(models.orders.payload["summary"]["open_order_count"], 1)
            self.assertEqual(
                [
                    row["status"]
                    for row in models.orders.payload["orders"]
                    if row["client_order_id"] in snapshot.unresolved_order_ids
                ],
                ["UNKNOWN"],
            )
            self.assertEqual(models.risk.payload["runtime"]["values"]["gate_status"], "block")
            self.assertEqual(models.system.payload["summary"]["status"], "halt_required")
            gates = {
                row["gate"]: row for row in models.readiness.payload["gates"]
            }
            self.assertEqual(gates["order_state_recovery"]["status"], "block")
            self.assertEqual(gates["runtime_ledger"]["status"], "pass")

    def test_state_change_after_reconciliation_requires_a_new_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, _ = _ledger_with_accounting(Path(temporary))
            ledger.record_cash_event(
                event_key="post-reconciliation-funding",
                event_type="funding",
                amount=0.5,
                asset="USDT",
                occurred_at="2026-07-20T00:07:11+00:00",
                source_hash=_hash("post-reconciliation-funding"),
            )
            with self.assertRaisesRegex(
                RuntimeLedgerSnapshotError, "reconciliation_not_latest"
            ):
                build_runtime_ledger_snapshot(
                    ledger, batch, captured_at=CAPTURED_AT
                )

    def test_available_models_use_only_snapshot_values_and_keep_live_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, registry = _ledger_with_accounting(Path(temporary))
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            models = build_dashboard_v1(
                batch,
                registry,
                generated_at=CAPTURED_AT,
                ledger_snapshot=snapshot,
                stale_after_seconds=300,
            )
            self.assertEqual(
                set(models.overview.source_hashes),
                {
                    "decision_batch_manifest",
                    "strategy_registry",
                    "runtime_ledger",
                },
            )
            self.assertEqual(
                models.overview.payload["portfolio"]["actual_positions"]["values"][
                    "positions"
                ],
                snapshot.positions,
            )
            self.assertEqual(
                models.positions.payload["summary"]["fact_scope"],
                "runtime_ledger",
            )
            self.assertEqual(
                models.positions.payload["summary"]["reconciliation_status"],
                "passed",
            )
            self.assertEqual(
                models.positions.payload["summary"]["unavailable_fields"], []
            )
            self.assertEqual(
                models.overview.payload["pnl"]["values"]["equity"], 1_015.9
            )
            self.assertEqual(
                models.strategies.payload["strategies"][0]["nav"]["values"][
                    "scope"
                ],
                "portfolio",
            )
            self.assertEqual(
                models.readiness.payload["status"], "read_model_ready"
            )
            self.assertEqual(models.orders.payload["summary"]["total_order_count"], 3)
            self.assertEqual(models.orders.payload["summary"]["fill_count"], 1)
            self.assertEqual(models.orders.payload["summary"]["fill_notional"], 100.0)
            self.assertEqual(
                models.orders.payload["summary"]["fill_fees_by_asset"],
                {"USDT": 0.1},
            )
            self.assertEqual(models.risk.payload["runtime"]["values"]["gate_status"], "pass")
            self.assertEqual(
                models.system.payload["summary"]["status"], "attention_required"
            )
            self.assertTrue(
                all(
                    row["live_orders_allowed"] is False
                    for row in models.readiness.payload["strategies"]
                )
            )
            strategy = models.strategies.payload["strategies"][0]
            self.assertEqual(strategy["registry_status"], "shadow")
            self.assertEqual(strategy["execution_status"], "disarmed")
            self.assertNotIn("promotion_status", strategy)
            publication_root = Path(temporary) / "dashboard"
            publication = publish_dashboard_v1(publication_root, models)
            loaded, loaded_publication = read_dashboard_v1(publication_root)
            self.assertEqual(loaded, models)
            self.assertEqual(loaded_publication, publication)

    def test_recapture_and_republication_cannot_refresh_unchanged_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, registry = _ledger_with_accounting(Path(temporary))
            first_snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            later_snapshot = build_runtime_ledger_snapshot(
                ledger,
                batch,
                captured_at="2026-07-20T00:10:00+00:00",
            )
            first = build_dashboard_v1(
                batch,
                registry,
                generated_at=CAPTURED_AT,
                evaluated_at="2026-07-20T00:12:09+00:00",
                stale_after_seconds=300,
                ledger_snapshot=first_snapshot,
            )
            stale = build_dashboard_v1(
                batch,
                registry,
                generated_at="2026-07-20T00:10:00+00:00",
                evaluated_at="2026-07-20T00:12:10+00:00",
                stale_after_seconds=300,
                ledger_snapshot=later_snapshot,
            )
            self.assertEqual(
                first.overview.freshness["source_updated_at"],
                stale.overview.freshness["source_updated_at"],
            )
            self.assertEqual(first.overview.freshness["status"], "fresh")
            self.assertEqual(stale.overview.freshness["status"], "stale")
            self.assertEqual(stale.readiness.payload["status"], "stale")

    def test_golden_replay_matches_exact_canonical_summary_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger, batch, registry = _ledger_with_accounting(Path(temporary))
            snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=CAPTURED_AT
            )
            models = build_dashboard_v1(
                batch,
                registry,
                generated_at=CAPTURED_AT,
                stale_after_seconds=300,
                ledger_snapshot=snapshot,
            )
            actual = _canonical_bytes(_golden_summary(snapshot, models))
        golden_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "dashboard_v1_ledger_golden.json"
        )
        expected = golden_path.read_bytes()
        self.assertEqual(actual, expected)
        self.assertEqual(
            hashlib.sha256(actual).hexdigest(),
            "9bdce873311a206ec216d6d427e008bb6c6876ec5442816f2810c373ebce9f71",
        )


if __name__ == "__main__":
    unittest.main()
