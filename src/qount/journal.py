from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import ExecutionResult, MarketSnapshotBundle, RiskVerdict, ValidatedDecision, to_jsonable, utc_now


class Journal:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def now_iso(self) -> str:
        return utc_now().isoformat()

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    mode TEXT NOT NULL,
                    status TEXT,
                    summary_json TEXT
                );

                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_decisions_raw (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    response_text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_decisions_validated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    valid INTEGER NOT NULL,
                    errors_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS risk_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    verdict_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    side TEXT,
                    quantity REAL,
                    notional_quote REAL,
                    pnl_quote REAL,
                    external_order_id TEXT,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def start_run(self, mode: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO runs (started_at, mode, status) VALUES (?, ?, ?)",
                (utc_now().isoformat(), mode, "started"),
            )
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, summary: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET finished_at = ?, status = ?, summary_json = ? WHERE id = ?",
                (utc_now().isoformat(), status, json.dumps(summary), run_id),
            )

    def record_snapshot(self, run_id: int, bundle: MarketSnapshotBundle) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO snapshots (run_id, created_at, snapshot_json) VALUES (?, ?, ?)",
                (run_id, utc_now().isoformat(), json.dumps(to_jsonable(bundle))),
            )

    def record_ai_raw(
        self,
        run_id: int,
        model: str,
        prompt_version: str,
        request_payload: dict[str, Any],
        response_text: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_decisions_raw (run_id, created_at, model, prompt_version, request_json, response_text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_now().isoformat(),
                    model,
                    prompt_version,
                    json.dumps(request_payload),
                    response_text,
                ),
            )

    def record_validated_decision(self, run_id: int, validated: ValidatedDecision) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_decisions_validated (run_id, created_at, valid, errors_json, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_now().isoformat(),
                    1 if validated.valid else 0,
                    json.dumps(validated.errors),
                    json.dumps(
                        {
                            "decision": to_jsonable(validated.decision),
                            "raw_payload": validated.raw_payload,
                        }
                    ),
                ),
            )

    def record_risk(self, run_id: int, verdict: RiskVerdict) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO risk_actions (run_id, created_at, verdict_json) VALUES (?, ?, ?)",
                (run_id, utc_now().isoformat(), json.dumps(to_jsonable(verdict))),
            )

    def record_order(self, run_id: int, result: ExecutionResult) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO orders (
                    run_id, created_at, mode, status, symbol, action, side, quantity,
                    notional_quote, pnl_quote, external_order_id, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_now().isoformat(),
                    result.mode,
                    result.status,
                    result.symbol,
                    result.action,
                    result.side,
                    result.quantity,
                    result.notional_quote,
                    result.pnl_quote,
                    result.external_order_id,
                    json.dumps(result.raw),
                ),
            )

    def get_runtime_state(self, key: str, default: Any) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row["value_json"])

    def set_runtime_state(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_state (key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), utc_now().isoformat()),
            )

    def get_consecutive_losses(self, symbol: str, limit: int = 2) -> int:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT pnl_quote
                FROM orders
                WHERE symbol = ? AND pnl_quote IS NOT NULL
                ORDER BY id DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        streak = 0
        for row in rows:
            if float(row["pnl_quote"]) < 0:
                streak += 1
            else:
                break
        return streak

    def get_recent_orders(self, limit: int = 10, mode: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT created_at, mode, status, symbol, action, side, quantity, notional_quote, pnl_quote, external_order_id
            FROM orders
        """
        params: list[Any] = []
        if mode is not None:
            sql += " WHERE mode = ?"
            params.append(mode)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_recent_runs(self, limit: int = 10, mode: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT started_at, finished_at, mode, status, summary_json
            FROM runs
        """
        params: list[Any] = []
        if mode is not None:
            sql += " WHERE mode = ?"
            params.append(mode)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item.get("summary_json"):
                item["summary"] = json.loads(item["summary_json"])
                item.pop("summary_json", None)
            result.append(item)
        return result

    def get_signal_review_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    runs.id AS run_id,
                    runs.started_at,
                    runs.finished_at,
                    runs.mode,
                    runs.status,
                    snapshots.snapshot_json,
                    ai_decisions_validated.payload_json,
                    ai_decisions_validated.valid,
                    ai_decisions_validated.errors_json,
                    risk_actions.verdict_json
                FROM runs
                JOIN snapshots ON snapshots.run_id = runs.id
                JOIN ai_decisions_validated ON ai_decisions_validated.run_id = runs.id
                JOIN risk_actions ON risk_actions.run_id = runs.id
                ORDER BY runs.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["snapshot_json"] = json.loads(item["snapshot_json"])
            item["payload_json"] = json.loads(item["payload_json"])
            item["errors_json"] = json.loads(item["errors_json"])
            item["verdict_json"] = json.loads(item["verdict_json"])
            raw_payload = item["payload_json"].get("raw_payload") or {}
            if raw_payload.get("scope") == "portfolio":
                continue
            result.append(item)
        return result

    def get_order_history(self, mode: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT run_id, created_at, mode, status, symbol, action, side, quantity, notional_quote, pnl_quote, external_order_id, raw_json
            FROM orders
        """
        params: list[Any] = []
        if mode is not None:
            sql += " WHERE mode = ?"
            params.append(mode)
        sql += " ORDER BY id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["raw_json"] = json.loads(item["raw_json"])
            result.append(item)
        return result

    def get_latest_snapshot_prices(self) -> dict[str, float]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT snapshot_json FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return {}
        snapshot_json = json.loads(row["snapshot_json"])
        prices: dict[str, float] = {}
        for symbol_entry in snapshot_json.get("symbols", []):
            prices[str(symbol_entry["symbol"])] = float(symbol_entry["last_price"])
        return prices

    def get_latest_snapshot(self, mode: str | None = None) -> dict[str, Any] | None:
        sql = """
            SELECT snapshots.snapshot_json
            FROM snapshots
            JOIN runs ON runs.id = snapshots.run_id
        """
        params: list[Any] = []
        if mode is not None:
            sql += " WHERE runs.mode = ?"
            params.append(mode)
        sql += " ORDER BY snapshots.id DESC LIMIT 1"
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return json.loads(row["snapshot_json"])

    def get_equity_series(self, mode: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql = """
            SELECT runs.mode, snapshots.snapshot_json
            FROM snapshots
            JOIN runs ON runs.id = snapshots.run_id
        """
        params: list[Any] = []
        if mode is not None:
            sql += " WHERE runs.mode = ?"
            params.append(mode)
        sql += " ORDER BY snapshots.id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        series: list[dict[str, Any]] = []
        for row in reversed(rows):
            snapshot = json.loads(row["snapshot_json"])
            account = snapshot.get("account") or {}
            series.append(
                {
                    "timestamp": snapshot.get("generated_at"),
                    "equity_quote": float(account.get("equity_quote") or 0.0),
                    "free_quote": float(account.get("free_quote") or 0.0),
                    "mode": row["mode"],
                }
            )
        return series

    def get_recent_signal_actions(self, limit: int = 50, symbol: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT
                runs.id AS run_id,
                runs.mode,
                runs.started_at,
                snapshots.snapshot_json,
                ai_decisions_validated.payload_json,
                risk_actions.verdict_json
            FROM runs
            JOIN snapshots ON snapshots.run_id = runs.id
            JOIN ai_decisions_validated ON ai_decisions_validated.run_id = runs.id
            JOIN risk_actions ON risk_actions.run_id = runs.id
            ORDER BY runs.id DESC
            LIMIT ?
        """
        with self.connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            snapshot = json.loads(row["snapshot_json"])
            payload = json.loads(row["payload_json"])
            verdict = json.loads(row["verdict_json"])
            decision = payload.get("decision") or {}
            raw_payload = payload.get("raw_payload") or {}
            if raw_payload.get("scope") == "portfolio":
                continue
            entry_symbol = str(verdict.get("symbol") or decision.get("symbol") or "")
            if symbol is not None and entry_symbol != symbol:
                continue

            symbol_entry = next((item for item in snapshot.get("symbols", []) if item.get("symbol") == entry_symbol), None)
            recent_candles = (symbol_entry or {}).get("recent_candles") or []
            bar_timestamp_ms = int(recent_candles[-1]["timestamp_ms"]) if recent_candles else None
            position_entry = next(
                (item for item in ((snapshot.get("account") or {}).get("open_positions") or []) if item.get("symbol") == entry_symbol),
                None,
            )
            result.append(
                {
                    "run_id": int(row["run_id"]),
                    "mode": row["mode"],
                    "started_at": row["started_at"],
                    "symbol": entry_symbol,
                    "decision_action": str(decision.get("action") or "hold"),
                    "final_action": str(verdict.get("final_action") or "hold"),
                    "approved": bool(verdict.get("approved")),
                    "confidence": float(verdict.get("confidence") or decision.get("confidence") or 0.0),
                    "take_profit_pct": float(verdict.get("take_profit_pct") or decision.get("take_profit_pct") or 0.0),
                    "stop_loss_pct": float(verdict.get("stop_loss_pct") or decision.get("stop_loss_pct") or 0.0),
                    "ttl_minutes": int(verdict.get("ttl_minutes") or decision.get("ttl_minutes") or 0),
                    "bar_timestamp_ms": bar_timestamp_ms,
                    "position_side_before_action": None if position_entry is None else position_entry.get("side"),
                    "risk_reasons": [str(reason) for reason in (verdict.get("reasons") or [])],
                }
            )
        return result
