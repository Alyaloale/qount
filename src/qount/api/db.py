"""SQLite database storage for the simplified API."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from qount.api.schemas import (
    NavPoint,
    PaperLine,
    PaperLineSummary,
    LineMetrics,
    PositionItem,
    LineSource,
    LineSafety,
)

DEFAULT_DB_PATH = "state/qount.db"


def get_db_path() -> str:
    return os.environ.get("QOUNT_DB_PATH", DEFAULT_DB_PATH)


def init_db(db_path: Optional[str] = None) -> None:
    path = db_path or get_db_path()
    if path != ":memory:":
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_lines (
              line_id TEXT PRIMARY KEY,
              name TEXT,
              category TEXT,
              status TEXT,
              as_of TEXT,
              freshness TEXT,
              payload TEXT,
              ingested_at TEXT
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_nav (
              line_id TEXT,
              date TEXT,
              nav REAL,
              benchmark_nav REAL,
              PRIMARY KEY (line_id, date)
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ran_at TEXT,
              line_id TEXT,
              ok INTEGER,
              message TEXT
            );
            """
        )
        conn.commit()


def save_paper_line(line: PaperLine, db_path: Optional[str] = None, ingested_at: Optional[str] = None) -> None:
    path = db_path or get_db_path()
    now_str = ingested_at or datetime.now(timezone.utc).isoformat()
    init_db(path)

    # Store payload JSON (can omit nav_series to keep row lightweight)
    line_dict = line.model_dump()
    nav_series = line_dict.pop("nav_series", [])
    payload_json = json.dumps(line_dict, ensure_ascii=False)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO paper_lines (line_id, name, category, status, as_of, freshness, payload, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (line.line_id, line.name, line.category, line.status, line.as_of, line.freshness, payload_json, now_str),
        )

        cursor.execute("DELETE FROM paper_nav WHERE line_id = ?;", (line.line_id,))
        nav_rows = [
            (line.line_id, pt["date"], float(pt["nav"]), float(pt.get("benchmark_nav", 1.0)))
            for pt in nav_series
        ]
        if nav_rows:
            cursor.executemany(
                """
                INSERT OR REPLACE INTO paper_nav (line_id, date, nav, benchmark_nav)
                VALUES (?, ?, ?, ?);
                """,
                nav_rows,
            )
        conn.commit()


def get_paper_lines_summary(db_path: Optional[str] = None) -> List[PaperLineSummary]:
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return []

    summaries: List[PaperLineSummary] = []
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT payload FROM paper_lines ORDER BY line_id;")
        rows = cursor.fetchall()
        for (payload_str,) in rows:
            try:
                data = json.loads(payload_str)
                summaries.append(PaperLineSummary(**data))
            except Exception:
                continue
    return summaries


def get_paper_line(line_id: str, db_path: Optional[str] = None) -> Optional[PaperLine]:
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return None

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT payload FROM paper_lines WHERE line_id = ?;", (line_id,))
        row = cursor.fetchone()
        if not row:
            return None
        data = json.loads(row[0])

        cursor.execute(
            "SELECT date, nav, benchmark_nav FROM paper_nav WHERE line_id = ? ORDER BY date ASC;",
            (line_id,),
        )
        nav_rows = cursor.fetchall()
        data["nav_series"] = [
            {"date": r[0], "nav": r[1], "benchmark_nav": r[2]}
            for r in nav_rows
        ]
        return PaperLine(**data)


def log_ingest(line_id: str, ok: bool, message: str, db_path: Optional[str] = None, ran_at: Optional[str] = None) -> None:
    path = db_path or get_db_path()
    now_str = ran_at or datetime.now(timezone.utc).isoformat()
    init_db(path)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ingest_log (ran_at, line_id, ok, message)
            VALUES (?, ?, ?, ?);
            """,
            (now_str, line_id, 1 if ok else 0, message),
        )
        conn.commit()


def get_last_ingest_time(db_path: Optional[str] = None) -> Optional[str]:
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return None

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT ran_at FROM ingest_log ORDER BY id DESC LIMIT 1;")
            row = cursor.fetchone()
            if row:
                return row[0]
        except sqlite3.OperationalError:
            return None
    return None


def get_paper_lines_count(db_path: Optional[str] = None) -> int:
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return 0

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT count(*) FROM paper_lines;")
            row = cursor.fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0
