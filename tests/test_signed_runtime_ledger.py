from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from qount.contracts import MarketSnapshot
from qount.contracts import OrderPlan
from qount.contracts import PlannedOrder
from qount.contracts import PortfolioTarget
from qount.contracts import RiskDecision
from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash
from qount.contracts import trace_id
from qount.ledger import RuntimeLedger
from qount.ledger import RuntimeLedgerError
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import build_decision_batch_manifest


DECISION_TIME = "2026-07-26T12:00:00+00:00"


def _hash(value: str) -> str:
    return canonical_hash({"fixture": value})


def _batch(
    *,
    side: str,
    quantity: float,
    phase: str,
    reduce_only: bool,
    expected_position: float,
) -> VerifiedDecisionBatch:
    snapshot = MarketSnapshot.create(
        decision_time=DECISION_TIME,
        data_cutoff="2026-07-26T11:59:00+00:00",
        prices={"BTCUSDT": 100.0},
        funding={"BTCUSDT": 0.0001},
        features={},
        exchange_rules_hash="a" * 64,
        account_snapshot_hash=None,
        data_quality={"complete": True, "blockers": ()},
        source_hashes={"market": "b" * 64},
    )
    target_weight = expected_position * 100.0 / 1_000.0
    intent = StrategyIntent.create(
        strategy_id="signed_ledger_test",
        strategy_version="2.0.0",
        snapshot_id=snapshot.snapshot_id,
        decision_time=DECISION_TIME,
        data_cutoff="2026-07-26T11:59:00+00:00",
        target_weights={"BTCUSDT": target_weight},
        expected_holding_bars=1,
        target_stress_loss_fraction=0.1,
        reason_codes=("SIGNED_LEDGER_TEST",),
        evidence_hash="c" * 64,
        state_hash="d" * 64,
    )
    target = PortfolioTarget.create(
        snapshot_id=snapshot.snapshot_id,
        decision_ids=(intent.decision_id,),
        decision_time=DECISION_TIME,
        proposed_target_weights=intent.target_weights,
        target_weights=intent.target_weights,
        sleeve_contributions={intent.strategy_id: intent.target_weights},
        blockers=(),
        allocatable=True,
        allocation_hash=_hash("allocation"),
    )
    batch_id = trace_id(
        "decision_batch",
        {
            "snapshot_id": snapshot.snapshot_id,
            "portfolio_target_id": target.portfolio_target_id,
            "side": side,
            "quantity": quantity,
        },
    )
    risk = RiskDecision.create(
        batch_id=batch_id,
        portfolio_target_id=target.portfolio_target_id,
        decision_time=DECISION_TIME,
        approved=True,
        input_target=target.target_weights,
        approved_target=target.target_weights,
        adjustments=(),
        violations=(),
        risk_state_hash=_hash("risk"),
        increase_risk_allowed=True,
        reduce_risk_allowed=True,
    )
    order = PlannedOrder.create(
        batch_id=batch_id,
        decision_ids=target.decision_ids,
        symbol="BTCUSDT",
        side=side,
        quantity=quantity,
        reduce_only=reduce_only,
        phase=phase,
        sequence=1,
    )
    plan = OrderPlan.create(
        batch_id=batch_id,
        risk_decision_id=risk.risk_decision_id,
        portfolio_target_id=target.portfolio_target_id,
        snapshot_id=snapshot.snapshot_id,
        decision_ids=target.decision_ids,
        created_at=DECISION_TIME,
        current_position_hash=_hash("position"),
        approved_target=risk.approved_target,
        orders=(order,),
        expected_positions={"BTCUSDT": expected_position},
        reconciliation_tolerance={"BTCUSDT": 1e-9},
        blockers=(),
        executable=True,
    )
    manifest = build_decision_batch_manifest(
        snapshot=snapshot,
        intents=(intent,),
        target=target,
        risk=risk,
        plan=plan,
        created_at=DECISION_TIME,
    )
    return VerifiedDecisionBatch(
        manifest=manifest,
        snapshot=snapshot,
        intents=(intent,),
        target=target,
        risk=risk,
        plan=plan,
    )


def _execute_fill(
    ledger: RuntimeLedger,
    batch: VerifiedDecisionBatch,
    *,
    initial_quantity: float,
    initial_cost: float,
    fill_price: float,
) -> None:
    ledger.record_verified_batch(batch, recorded_at=DECISION_TIME)
    ledger.record_position_snapshot(
        symbol="BTCUSDT",
        quantity=initial_quantity,
        average_cost=initial_cost,
        realized_trading_pnl=0.0,
        occurred_at="2026-07-26T12:00:01+00:00",
        source_hash=_hash("opening"),
    )
    order = batch.plan.orders[0]
    ledger.transition_order(
        order.client_order_id,
        "SUBMITTING",
        event_at="2026-07-26T12:00:02+00:00",
        source_hash=_hash("submitting"),
    )
    ledger.transition_order(
        order.client_order_id,
        "ACKNOWLEDGED",
        event_at="2026-07-26T12:00:03+00:00",
        source_hash=_hash("acknowledged"),
        exchange_order_id="exchange-1",
    )
    ledger.transition_order(
        order.client_order_id,
        "FILLED",
        event_at="2026-07-26T12:00:04+00:00",
        source_hash=_hash("filled"),
        exchange_order_id="exchange-1",
        executed_quantity=float(order.quantity or 0.0),
        average_price=fill_price,
    )
    ledger.record_fill(
        client_order_id=order.client_order_id,
        exchange_trade_id="trade-1",
        quantity=float(order.quantity or 0.0),
        price=fill_price,
        fee=0.0,
        fee_asset="USDT",
        occurred_at="2026-07-26T12:00:04+00:00",
        source_hash=_hash("fill"),
    )


def _position(path: Path) -> tuple[float, float, float]:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT quantity,average_cost,realized_trading_pnl "
            "FROM positions WHERE symbol='BTCUSDT'"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return float(row[0]), float(row[1]), float(row[2])


class SignedRuntimeLedgerTest(unittest.TestCase):
    def test_open_short_and_profitable_cover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "open-short.sqlite3"
            ledger = RuntimeLedger(path)
            _execute_fill(
                ledger,
                _batch(
                    side="sell",
                    quantity=10.0,
                    phase="increase",
                    reduce_only=False,
                    expected_position=-10.0,
                ),
                initial_quantity=0.0,
                initial_cost=0.0,
                fill_price=100.0,
            )
            self.assertEqual(_position(path), (-10.0, 100.0, 0.0))

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cover-short.sqlite3"
            ledger = RuntimeLedger(path)
            _execute_fill(
                ledger,
                _batch(
                    side="buy",
                    quantity=10.0,
                    phase="reduce",
                    reduce_only=True,
                    expected_position=0.0,
                ),
                initial_quantity=-10.0,
                initial_cost=100.0,
                fill_price=80.0,
            )
            self.assertEqual(_position(path), (0.0, 0.0, 200.0))

    def test_non_reduce_fill_can_flip_short_to_long_at_fill_price(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "flip.sqlite3"
            ledger = RuntimeLedger(path)
            _execute_fill(
                ledger,
                _batch(
                    side="buy",
                    quantity=15.0,
                    phase="increase",
                    reduce_only=False,
                    expected_position=5.0,
                ),
                initial_quantity=-10.0,
                initial_cost=100.0,
                fill_price=80.0,
            )
            self.assertEqual(_position(path), (5.0, 80.0, 200.0))

    def test_reduce_only_fill_cannot_cross_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reduce-only.sqlite3"
            ledger = RuntimeLedger(path)
            batch = _batch(
                side="buy",
                quantity=15.0,
                phase="reduce",
                reduce_only=True,
                expected_position=0.0,
            )
            with self.assertRaisesRegex(
                RuntimeLedgerError,
                "fill_reduce_only_would_increase_position",
            ):
                _execute_fill(
                    ledger,
                    batch,
                    initial_quantity=-10.0,
                    initial_cost=100.0,
                    fill_price=80.0,
                )
            self.assertEqual(_position(path), (-10.0, 100.0, 0.0))

    def test_v2_database_migrates_positions_table_atomically_to_v3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "migration.sqlite3"
            source_hash = _hash("legacy-source")
            core = {
                "symbol": "BTCUSDT",
                "quantity": 1.0,
                "average_cost": 100.0,
                "realized_trading_pnl": 0.0,
                "updated_at": "2026-07-26T11:00:00+00:00",
                "source_hash": source_hash,
            }
            connection = sqlite3.connect(path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE schema_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    INSERT INTO schema_metadata VALUES ('schema_version','2');
                    CREATE TABLE positions (
                        symbol TEXT PRIMARY KEY,
                        quantity REAL NOT NULL CHECK(quantity >= 0),
                        average_cost REAL NOT NULL CHECK(average_cost >= 0),
                        realized_trading_pnl REAL NOT NULL,
                        updated_at TEXT NOT NULL,
                        source_hash TEXT NOT NULL,
                        position_hash TEXT NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
                    (
                        core["symbol"],
                        core["quantity"],
                        core["average_cost"],
                        core["realized_trading_pnl"],
                        core["updated_at"],
                        core["source_hash"],
                        canonical_hash(core),
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            os.chmod(path, 0o600)

            ledger = RuntimeLedger(path)
            ledger.record_position_snapshot(
                symbol="BTCUSDT",
                quantity=-2.0,
                average_cost=90.0,
                realized_trading_pnl=5.0,
                occurred_at="2026-07-26T12:00:00+00:00",
                source_hash=_hash("signed-snapshot"),
            )
            connection = sqlite3.connect(path)
            try:
                version = connection.execute(
                    "SELECT value FROM schema_metadata WHERE key='schema_version'"
                ).fetchone()[0]
                sql = connection.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='positions'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(version, "3")
            self.assertNotIn("quantity >= 0", sql)
            self.assertEqual(_position(path), (-2.0, 90.0, 5.0))


if __name__ == "__main__":
    unittest.main()
