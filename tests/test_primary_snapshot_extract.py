from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from qount.primary_snapshot import extract_primary_snapshot
from qount.primary_snapshot import extract_runtime_state


def _create_test_ledger(path: Path) -> sqlite3.Connection:
    """Create a minimal RuntimeLedger SQLite for testing."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL NOT NULL,
            average_cost REAL NOT NULL,
            realized_trading_pnl REAL NOT NULL,
            updated_at TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            position_hash TEXT NOT NULL
        );
        CREATE TABLE nav_marks (
            nav_mark_id TEXT PRIMARY KEY,
            marked_at TEXT NOT NULL UNIQUE,
            previous_equity REAL NOT NULL,
            equity REAL NOT NULL,
            equity_change REAL NOT NULL,
            trading_pnl REAL NOT NULL,
            funding REAL NOT NULL,
            fees REAL NOT NULL,
            transfers REAL NOT NULL,
            residual REAL NOT NULL,
            residual_tolerance REAL NOT NULL,
            passed INTEGER NOT NULL,
            trading_pnl_cumulative REAL NOT NULL,
            funding_cumulative REAL NOT NULL,
            fees_cumulative REAL NOT NULL,
            transfers_cumulative REAL NOT NULL,
            source_hash TEXT NOT NULL,
            mark_hash TEXT NOT NULL UNIQUE
        );
        CREATE TABLE cash_events (
            cash_event_id TEXT PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            amount REAL NOT NULL,
            asset TEXT NOT NULL,
            symbol TEXT,
            occurred_at TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE
        );
        CREATE TABLE orders (
            client_order_id TEXT PRIMARY KEY,
            status TEXT NOT NULL
        );
        CREATE TABLE reconciliations (
            reconciliation_id TEXT PRIMARY KEY,
            reconciled_at TEXT NOT NULL,
            passed INTEGER NOT NULL,
            halt_required INTEGER NOT NULL
        );
        """
    )
    conn.commit()
    return conn


class ExtractPrimarySnapshotTest(unittest.TestCase):
    def test_extract_with_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.sqlite3"
            conn = _create_test_ledger(db_path)
            conn.execute(
                "INSERT INTO positions (symbol, quantity, average_cost, "
                "realized_trading_pnl, updated_at, source_hash, position_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("BTCUSDT", 0.001, 100000.0, 0.0, "2026-07-23T00:00:00+00:00",
                 "abc", "def"),
            )
            conn.execute(
                "INSERT INTO nav_marks (nav_mark_id, marked_at, previous_equity, "
                "equity, equity_change, trading_pnl, funding, fees, transfers, "
                "residual, residual_tolerance, passed, trading_pnl_cumulative, "
                "funding_cumulative, fees_cumulative, transfers_cumulative, "
                "source_hash, mark_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("nav1", "2026-07-23T00:00:00+00:00", 486.0,
                 486.16, 0.16, 0.0, 0.01, 0.04, 0.0,
                 0.0, 1e-8, 1, 0.0, 0.01, 0.04, 0.0,
                 "src1", "mark1"),
            )
            conn.execute(
                "INSERT INTO cash_events (cash_event_id, event_key, event_type, "
                "amount, asset, symbol, occurred_at, source_hash, event_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ce1", "key1", "funding", 0.01, "USDT", "BTCUSDT",
                 "2026-07-23T00:00:00+00:00", "src2", "eh1"),
            )
            conn.execute(
                "INSERT INTO orders (client_order_id, status) VALUES (?, ?)",
                ("ord1", "FILLED"),
            )
            conn.execute(
                "INSERT INTO reconciliations (reconciliation_id, reconciled_at, "
                "passed, halt_required) VALUES (?, ?, ?, ?)",
                ("recon1", "2026-07-23T00:00:00+00:00", 1, 0),
            )
            conn.commit()
            conn.close()

            snapshot = extract_primary_snapshot(db_path)
            self.assertEqual(snapshot["snapshot_version"], 1)
            self.assertIn("BTCUSDT", snapshot["positions"])
            self.assertAlmostEqual(
                snapshot["positions"]["BTCUSDT"]["quantity"], 0.001
            )
            self.assertAlmostEqual(
                snapshot["nav"]["equity"], 486.16
            )
            self.assertAlmostEqual(
                snapshot["nav"]["commission"], 0.04
            )
            self.assertIsNone(snapshot["nav"]["unrealized_pnl"])
            self.assertEqual(len(snapshot["cash_events"]), 1)
            self.assertEqual(
                snapshot["cash_events"][0]["event_type"], "funding"
            )
            self.assertEqual(snapshot["unknown_order_count"], 0)
            self.assertTrue(snapshot["reconciliation_passed"])
            self.assertFalse(snapshot["reconciliation_halt_required"])

    def test_extract_empty_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.sqlite3"
            conn = _create_test_ledger(db_path)
            conn.close()
            snapshot = extract_primary_snapshot(db_path)
            self.assertEqual(snapshot["positions"], {})
            self.assertIsNone(snapshot["nav"]["equity"])
            self.assertEqual(snapshot["cash_events"], [])
            self.assertEqual(snapshot["unknown_order_count"], 0)
            self.assertIsNone(snapshot["reconciliation_passed"])

    def test_unknown_order_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.sqlite3"
            conn = _create_test_ledger(db_path)
            conn.execute(
                "INSERT INTO orders (client_order_id, status) VALUES (?, ?)",
                ("ord1", "UNKNOWN"),
            )
            conn.execute(
                "INSERT INTO orders (client_order_id, status) VALUES (?, ?)",
                ("ord2", "FILLED"),
            )
            conn.execute(
                "INSERT INTO orders (client_order_id, status) VALUES (?, ?)",
                ("ord3", "UNKNOWN"),
            )
            conn.commit()
            conn.close()
            snapshot = extract_primary_snapshot(db_path)
            self.assertEqual(snapshot["unknown_order_count"], 2)

    def test_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            extract_primary_snapshot("/nonexistent/path.sqlite3")


class ExtractRuntimeStateTest(unittest.TestCase):
    def test_extract_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.sqlite3"
            conn = _create_test_ledger(db_path)
            conn.execute(
                "INSERT INTO orders (client_order_id, status) VALUES (?, ?)",
                ("ord1", "UNKNOWN"),
            )
            conn.execute(
                "INSERT INTO reconciliations (reconciliation_id, reconciled_at, "
                "passed, halt_required) VALUES (?, ?, ?, ?)",
                ("recon1", "2026-07-23T00:00:00+00:00", 0, 1),
            )
            conn.commit()
            conn.close()
            state = extract_runtime_state(db_path)
            self.assertEqual(state["unknown_order_count"], 1)
            self.assertFalse(state["reconciliation_passed"])
            self.assertTrue(state["reconciliation_halt_required"])
            self.assertEqual(state["data_quality_blockers"], 0)

    def test_extract_runtime_state_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.sqlite3"
            conn = _create_test_ledger(db_path)
            conn.close()
            state = extract_runtime_state(db_path)
            self.assertEqual(state["unknown_order_count"], 0)
            self.assertIsNone(state["reconciliation_passed"])

    def test_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            extract_runtime_state("/nonexistent/path.sqlite3")


if __name__ == "__main__":
    unittest.main()
