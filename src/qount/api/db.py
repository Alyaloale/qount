"""SQLite database storage for the simplified API."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, time, timezone
from math import isfinite
from typing import List, Optional

from qount.api.schemas import (
    NavPoint,
    PaperLine,
    PaperLineSummary,
    LineMetrics,
    PositionItem,
    PaperPositionRecord,
    PaperTradeRecord,
    LineSource,
    LineSafety,
)
from qount.api.paper_filter import is_forward_binance_line, normalize_paper_line

DEFAULT_DB_PATH = "state/qount.db"


def get_db_path() -> str:
    return os.environ.get("QOUNT_DB_PATH", DEFAULT_DB_PATH)


def _nav_timestamp(value: str) -> Optional[datetime]:
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text[:10])
        except ValueError:
            return None
        parsed = datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
            CREATE TABLE IF NOT EXISTS schema_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', '3');"
        )
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
              signal_nav REAL,
              PRIMARY KEY (line_id, date)
            );
            """
        )
        nav_columns = {row[1] for row in cursor.execute("PRAGMA table_info(paper_nav);").fetchall()}
        if "signal_nav" not in nav_columns:
            cursor.execute("ALTER TABLE paper_nav ADD COLUMN signal_nav REAL;")
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
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS ingest_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ran_at TEXT NOT NULL,
              status TEXT NOT NULL,
              failed_lines TEXT NOT NULL DEFAULT '[]'
            );"""
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_positions (
              line_id TEXT NOT NULL,
              date TEXT NOT NULL,
              symbol TEXT NOT NULL,
              quantity REAL,
              weight REAL,
              price REAL,
              market_value REAL,
              action TEXT NOT NULL,
              record_kind TEXT NOT NULL DEFAULT 'simulated_not_realized',
              PRIMARY KEY (line_id, date, symbol)
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
              line_id TEXT NOT NULL,
              date TEXT NOT NULL,
              symbol TEXT NOT NULL,
              side TEXT NOT NULL,
              quantity REAL NOT NULL,
              price REAL,
              cost REAL,
              note TEXT NOT NULL DEFAULT '',
              record_kind TEXT NOT NULL DEFAULT 'simulated_not_realized',
              PRIMARY KEY (line_id, date, symbol, side)
            );
            """
        )
        conn.commit()


def _canonical_timestamp(value: str) -> Optional[str]:
    parsed = _nav_timestamp(value)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") if parsed else None


def _position_observation_time(line: PaperLine) -> str:
    for candidate in (
        line.nav_series[-1].date if line.nav_series else None,
        line.source.produced_at,
        line.as_of,
    ):
        if candidate:
            canonical = _canonical_timestamp(str(candidate))
            if canonical:
                return canonical
    raise ValueError(f"position_observation_time_missing:{line.line_id}")


def _previous_position_snapshot(
    cursor: sqlite3.Cursor, line_id: str, before: str
) -> tuple[Optional[str], dict[str, dict[str, Optional[float]]]]:
    cursor.execute(
        "SELECT date FROM paper_positions WHERE line_id = ? AND date < ? ORDER BY date DESC LIMIT 1;",
        (line_id, before),
    )
    row = cursor.fetchone()
    if not row:
        return None, {}
    previous_date = str(row[0])
    cursor.execute(
        "SELECT symbol, quantity, weight, price, market_value FROM paper_positions WHERE line_id = ? AND date = ?;",
        (line_id, previous_date),
    )
    positions = {
        str(symbol): {
            "quantity": quantity,
            "weight": weight,
            "price": price,
            "market_value": market_value,
        }
        for symbol, quantity, weight, price, market_value in cursor.fetchall()
    }
    return previous_date, positions


def _number_or_none(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _config_trade_cost_bps(line_id: str) -> Optional[float]:
    config_path = os.environ.get("QOUNT_API_CONFIG", "config/api.json")
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        raw = payload.get("paper_trade_cost_bps", {}).get(line_id)
        parsed = _number_or_none(raw)
        return parsed if parsed is not None and parsed >= 0.0 else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _insert_trade(
    cursor: sqlite3.Cursor,
    *,
    line_id: str,
    date_value: str,
    symbol: str,
    side: str,
    quantity: float,
    price: Optional[float],
    cost: Optional[float],
    note: str,
    record_kind: str = "simulated_not_realized",
) -> None:
    if quantity < 0.0 or (quantity == 0.0 and side != "SPLIT"):
        return
    cursor.execute(
        """
        INSERT OR IGNORE INTO paper_trades
          (line_id, date, symbol, side, quantity, price, cost, note, record_kind)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (line_id, date_value, symbol, side, quantity, price, cost, note, record_kind),
    )


def _save_snapshot_trades(
    cursor: sqlite3.Cursor,
    line: PaperLine,
    observed_at: str,
    previous: dict[str, dict[str, Optional[float]]],
    current: dict[str, dict[str, Optional[float]]],
) -> None:
    fee_bps = _config_trade_cost_bps(line.line_id)
    for symbol in sorted(set(previous) | set(current)):
        old = previous.get(symbol, {})
        new = current.get(symbol, {})
        old_quantity = _number_or_none(old.get("quantity"))
        new_quantity = _number_or_none(new.get("quantity"))
        # An omitted symbol in a complete KNOWN snapshot is a confirmed zero; a present
        # symbol whose quantity is null remains unknown and cannot produce a trade delta.
        if symbol not in previous:
            old_quantity = 0.0
        if symbol not in current:
            new_quantity = 0.0
        if old_quantity is None or new_quantity is None:
            continue
        quantity_delta = new_quantity - old_quantity
        if abs(quantity_delta) <= 1e-12:
            continue
        price = _number_or_none(new.get("price")) or _number_or_none(old.get("price"))
        notional = abs(quantity_delta) * price if price is not None else None
        cost = notional * fee_bps / 10_000.0 if notional is not None and fee_bps is not None else None
        side = "BUY" if quantity_delta > 0.0 else "SELL"
        note = "simulated_not_realized; derived from consecutive position snapshots"
        if cost is None:
            note += "; contract fee or price unavailable"
        _insert_trade(
            cursor,
            line_id=line.line_id,
            date_value=observed_at,
            symbol=symbol,
            side=side,
            quantity=abs(quantity_delta),
            price=price,
            cost=cost,
            note=note,
        )


def _save_source_trade_events(
    cursor: sqlite3.Cursor,
    line: PaperLine,
    trade_events: list[dict[str, object]],
) -> None:
    """Persist explicit paper execution events embedded in an authoritative snapshot."""
    grouped: dict[tuple[str, str, str], dict[str, float]] = {}
    notes: dict[tuple[str, str, str], list[str]] = {}
    missing_costs: set[tuple[str, str, str]] = set()
    for event in trade_events:
        observed_at = _canonical_timestamp(str(event.get("date") or ""))
        symbol = str(event.get("symbol") or "").strip()
        side = str(event.get("side") or "").strip().upper()
        quantity = _number_or_none(event.get("quantity"))
        price = _number_or_none(event.get("price"))
        cost = _number_or_none(event.get("cost"))
        if not observed_at or not symbol:
            continue
        if side == "CORPORATE_ACTION_SPLIT":
            _insert_trade(
                cursor, line_id=line.line_id, date_value=observed_at, symbol=symbol,
                side="SPLIT", quantity=0.0, price=None, cost=None,
                note=str(event.get("note") or f"split_ratio={event.get('split_ratio', 'unknown')}"),
                record_kind="corporate_action",
            )
            continue
        if side not in {"BUY", "SELL"} or quantity is None or quantity <= 0.0:
            continue
        key = (observed_at, symbol, side)
        row = grouped.setdefault(key, {"quantity": 0.0, "notional": 0.0, "cost": 0.0})
        row["quantity"] += quantity
        if price is not None:
            row["notional"] += quantity * price
        if cost is not None:
            row["cost"] += cost
        else:
            missing_costs.add(key)
        note = str(event.get("note") or "").strip()
        if note and note not in notes.setdefault(key, []):
            notes[key].append(note)
    for (observed_at, symbol, side), values in grouped.items():
        quantity = values["quantity"]
        price = values["notional"] / quantity if values["notional"] > 0.0 else None
        cost = values["cost"] if (observed_at, symbol, side) not in missing_costs else None
        _insert_trade(
            cursor,
            line_id=line.line_id,
            date_value=observed_at,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            cost=cost,
            note="; ".join(notes.get((observed_at, symbol, side), [])) or "simulated_not_realized; source paper rebalance event",
            record_kind="historical_backtest" if line.run_id else "simulated_not_realized",
        )


def save_paper_line(
    line: PaperLine,
    db_path: Optional[str] = None,
    ingested_at: Optional[str] = None,
    trade_events: Optional[list[dict[str, object]]] = None,
) -> None:
    # Historical/non-forward rows remain available to the ingestion archive;
    # the API boundary filters them out. Forward rows must pass the shared
    # Binance identity map before they can be persisted as current research.
    # Filename conventions are not provenance.  Normalize positions and source
    # trade events whenever the structured input identifies a Binance line;
    # generic or legacy rows remain archived and are filtered at read time.
    if line.source.venue == "binance_usdm" or line.source.instrument_type == "USD-M":
        line = normalize_paper_line(line)
    if trade_events and (line.source.venue == "binance_usdm" or line.source.instrument_type == "USD-M"):
        from qount.binance_assets import asset_by_execution_symbol, asset_by_signal_symbol, load_binance_assets
        candidates = load_binance_assets()
        normalized_events: list[dict[str, object]] = []
        for raw_event in trade_events:
            event = dict(raw_event)
            symbol = str(event.get("symbol") or "").strip()
            if symbol:
                asset = asset_by_execution_symbol(symbol, assets=candidates) or asset_by_signal_symbol(symbol, assets=candidates)
                if asset is None or asset.status != "active":
                    raise ValueError(f"unknown_binance_asset:{symbol}")
                event["symbol"] = asset.execution_symbol
            normalized_events.append(event)
        trade_events = normalized_events
    path = db_path or get_db_path()
    now_str = ingested_at or datetime.now(timezone.utc).isoformat()
    init_db(path)

    # Store payload JSON (can omit nav_series to keep row lightweight)
    line_dict = line.model_dump()
    nav_series = line_dict.pop("nav_series", [])
    payload_json = json.dumps(line_dict, ensure_ascii=False)
    has_position_observation = line.position_status == "KNOWN" and not line.error
    # Archived/stopped lines and unavailable sources often have no position timestamp.
    # They carry no current position snapshot, so requiring one must not turn a valid
    # archived curve (or a missing-source result) into an adapter ERROR.
    observed_at = _position_observation_time(line) if has_position_observation else None
    current_positions = {
        position.symbol: {
            "quantity": _number_or_none(position.quantity),
            "weight": _number_or_none(position.weight),
            "price": _number_or_none(position.price),
            "market_value": _number_or_none(position.market_value),
        }
        for position in line.positions
    } if has_position_observation else {}

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        old_row = cursor.execute("SELECT payload FROM paper_lines WHERE line_id = ?", (line.line_id,)).fetchone()
        if line.run_id and line.data_status == "AVAILABLE" and trade_events is not None:
            # This SQLite view holds the explicitly selected experiment only.
            # Full histories remain in immutable <line>/<run_id> directories.
            cursor.execute("DELETE FROM paper_trades WHERE line_id=?", (line.line_id,))
            cursor.execute("DELETE FROM paper_positions WHERE line_id=?", (line.line_id,))
        if line.data_status in {"MISSING", "ERROR"} and not nav_series and old_row:
            attempt_source = line_dict.get("source")
            old_payload = json.loads(old_row[0])
            # Retain the last valid curve and the provenance that belongs to it.
            for key in ("run_id", "as_of", "freshness", "curve_granularity", "source", "nav_series", "metrics"):
                if key in old_payload:
                    line_dict[key] = old_payload[key]
            line_dict["last_attempt_at"] = now_str
            line_dict["last_attempt_status"] = line.data_status
            line_dict["last_attempt_error"] = line.error
            line_dict["last_attempt_source"] = attempt_source
            line_dict["position_status"] = "UNKNOWN"
            payload_json = json.dumps(line_dict, ensure_ascii=False)
        elif line.data_status == "AVAILABLE":
            line_dict["last_attempt_at"] = now_str
            line_dict["last_attempt_status"] = "AVAILABLE"
            line_dict["last_attempt_error"] = None
            line_dict["last_attempt_source"] = line_dict.get("source")
            payload_json = json.dumps(line_dict, ensure_ascii=False)
        if has_position_observation:
            assert observed_at is not None
            previous_date, previous_positions = _previous_position_snapshot(cursor, line.line_id, observed_at)
        else:
            previous_date = None
            previous_positions = {}
        position_actions: dict[str, str] = {}
        for symbol in sorted(set(previous_positions) | set(current_positions)):
            old = previous_positions.get(symbol)
            new = current_positions.get(symbol)
            if old is None:
                position_actions[symbol] = "OPEN"
            elif new is None:
                position_actions[symbol] = "CLOSE"
            elif new.get("quantity") is None or old.get("quantity") is None:
                # Unknown quantity stays unknown; weight-only observations cannot establish a close.
                position_actions[symbol] = "HOLD" if new.get("weight") == old.get("weight") else "ADJUST"
            elif new.get("quantity") <= 1e-12:
                position_actions[symbol] = "CLOSE"
            elif abs(new["quantity"] - old["quantity"]) > 1e-12:
                position_actions[symbol] = "ADJUST"
            else:
                position_actions[symbol] = "HOLD"

        # Position history is a timestamped snapshot. Rows for holdings that disappeared are
        # retained as zero-quantity CLOSE records, so the latest snapshot remains interpretable.
        position_rows = []
        for symbol in sorted(set(previous_positions) | set(current_positions)):
            row = current_positions.get(symbol)
            if row is None:
                row = {"quantity": 0.0, "weight": 0.0, "price": previous_positions[symbol].get("price"), "market_value": 0.0}
            position_rows.append(
                (
                    line.line_id,
                    observed_at,
                    symbol,
                    row.get("quantity"),
                    row.get("weight"),
                    row.get("price"),
                    row.get("market_value"),
                    position_actions[symbol],
                    "simulated_not_realized",
                )
            )

        cursor.execute(
            """
            INSERT OR REPLACE INTO paper_lines (line_id, name, category, status, as_of, freshness, payload, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (line.line_id, line.name, line.category, line.status, line.as_of, line.freshness, payload_json, now_str),
        )

        nav_rows = [
            (
                line.line_id,
                pt["date"],
                float(pt["nav"]),
                float(pt["benchmark_nav"]) if pt.get("benchmark_nav") is not None else None,
                float(pt["signal_nav"]) if pt.get("signal_nav") is not None else None,
            )
            for pt in nav_series
        ]
        if nav_rows:
            cursor.execute("DELETE FROM paper_nav WHERE line_id = ?;", (line.line_id,))
            cursor.executemany(
                """
                INSERT OR REPLACE INTO paper_nav (line_id, date, nav, benchmark_nav, signal_nav)
                VALUES (?, ?, ?, ?, ?);
                """,
                nav_rows,
            )
        if position_rows:
            cursor.executemany(
                """
                INSERT OR REPLACE INTO paper_positions
                  (line_id, date, symbol, quantity, weight, price, market_value, action, record_kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                position_rows,
            )
        if has_position_observation:
            assert observed_at is not None
            if trade_events is None:
                # The first observed holding is a baseline snapshot, not evidence of a trade.
                if previous_date is not None:
                    _save_snapshot_trades(cursor, line, observed_at, previous_positions, current_positions)
            else:
                _save_source_trade_events(cursor, line, trade_events)
        elif trade_events is not None:
            _save_source_trade_events(cursor, line, trade_events)
        conn.commit()


def get_paper_lines_summary(db_path: Optional[str] = None, *, forward_only: bool = True) -> List[PaperLineSummary]:
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
                from qount.api.adapters.utils import compute_freshness
                data["freshness"] = (
                    "MISSING" if data.get("data_status") == "MISSING"
                    else compute_freshness(data.get("as_of"))
                )
                line = PaperLine(**data)
                if forward_only:
                    line = normalize_paper_line(line)
                if forward_only and not is_forward_binance_line(line):
                    continue
                summaries.append(PaperLineSummary(**line.model_dump(exclude={"nav_series"})))
            except Exception:
                continue
    return summaries


def get_paper_line(line_id: str, db_path: Optional[str] = None, *, forward_only: bool = True) -> Optional[PaperLine]:
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return None
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT payload FROM paper_lines WHERE line_id = ?;", (line_id,))
        row = cursor.fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0])
            from qount.api.adapters.utils import compute_freshness
            data["freshness"] = (
                "MISSING" if data.get("data_status") == "MISSING"
                else compute_freshness(data.get("as_of"))
            )

            cursor.execute(
                "SELECT date, nav, benchmark_nav, signal_nav FROM paper_nav WHERE line_id = ?;",
                (line_id,),
            )
            nav_rows = cursor.fetchall()
            nav_rows.sort(
                key=lambda row: (
                    _nav_timestamp(row[0]) is None,
                    _nav_timestamp(row[0]) or datetime.max.replace(tzinfo=timezone.utc),
                    row[0],
                )
            )
            data["nav_series"] = [
                {"date": r[0], "nav": r[1], "benchmark_nav": r[2], "signal_nav": r[3]}
                for r in nav_rows
            ]
            line = PaperLine(**data)
            if forward_only:
                line = normalize_paper_line(line)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            # Unknown/stale positions are hidden at the read boundary rather
            # than leaking adapter errors through detail or history endpoints.
            return None
        if forward_only and not is_forward_binance_line(line):
            return None
        return line


def _range_boundary(value: Optional[str], *, end: bool = False) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) == 10:
            parsed_date = date.fromisoformat(text)
            parsed = datetime.combine(
                parsed_date,
                time.max if end else time.min,
                tzinfo=timezone.utc,
            )
        else:
            parsed = _nav_timestamp(text)
            if parsed is None:
                return None
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def get_paper_positions(
    line_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    db_path: Optional[str] = None,
    *, forward_only: bool = True,
) -> List[PaperPositionRecord]:
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return []
    if get_paper_line(line_id, path, forward_only=forward_only) is None:
        return []
    start_time = _range_boundary(start)
    end_time = _range_boundary(end, end=True)
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            """
            SELECT line_id, date, symbol, quantity, weight, price, market_value, action, record_kind
            FROM paper_positions WHERE line_id = ?;
            """,
            (line_id,),
        ).fetchall()
    records = []
    for row in rows:
        parsed_time = _nav_timestamp(row[1])
        if parsed_time is None or (start_time and parsed_time < start_time) or (end_time and parsed_time > end_time):
            continue
        records.append(PaperPositionRecord(
            line_id=row[0], date=row[1], symbol=row[2], quantity=row[3], weight=row[4],
            price=row[5], market_value=row[6], action=row[7], record_kind=row[8],
        ))
    records.sort(key=lambda record: (_nav_timestamp(record.date) or datetime.max.replace(tzinfo=timezone.utc), record.symbol))
    return records


def get_current_paper_positions(line_id: str, db_path: Optional[str] = None, *, forward_only: bool = True) -> List[PaperPositionRecord]:
    """Return only the latest recorded position snapshot for a line."""
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return []
    if get_paper_line(line_id, path, forward_only=forward_only) is None:
        return []
    with sqlite3.connect(path) as conn:
        latest = conn.execute(
            "SELECT MAX(date) FROM paper_positions WHERE line_id = ?;", (line_id,)
        ).fetchone()[0]
        if latest is None:
            return []
        rows = conn.execute(
            """SELECT line_id, date, symbol, quantity, weight, price, market_value, action, record_kind
               FROM paper_positions WHERE line_id = ? AND date = ? ORDER BY symbol;""",
            (line_id, latest),
        ).fetchall()
    return [PaperPositionRecord(
        line_id=row[0], date=row[1], symbol=row[2], quantity=row[3], weight=row[4],
        price=row[5], market_value=row[6], action=row[7], record_kind=row[8],
    ) for row in rows]


def get_current_paper_position_snapshot(line_id: str, db_path: Optional[str] = None, *, forward_only: bool = True) -> dict[str, object]:
    """Return current validity and the last stored position rows as a single read."""
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return {"line_id": line_id, "status": "MISSING", "positions": [], "error": "database_missing"}
    # Do not expose retained rows after a line becomes stale, archived, failed,
    # or otherwise loses Binance forward eligibility.
    visible_line = get_paper_line(line_id, path, forward_only=forward_only)
    if visible_line is None:
        return {"line_id": line_id, "status": "MISSING", "positions": [], "error": "line_missing_or_hidden"}
    positions = get_current_paper_positions(line_id, path, forward_only=forward_only)
    status = visible_line.position_status
    data_status = visible_line.data_status
    if data_status in {"ERROR", "MISSING"} and status == "KNOWN":
        status = "UNKNOWN"
    latest = positions[0].date if positions else visible_line.as_of
    return {
        "line_id": line_id,
        "status": status,
        "as_of": latest if status == "KNOWN" else None,
        "last_valid_as_of": latest,
        "positions": positions,
        "error": visible_line.error,
    }


def get_paper_trades(
    line_id: str,
    limit: int = 100,
    db_path: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    *, forward_only: bool = True,
) -> List[PaperTradeRecord]:
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return []
    if get_paper_line(line_id, path, forward_only=forward_only) is None:
        return []
    safe_limit = max(1, min(int(limit), 1000))
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            """
            SELECT line_id, date, symbol, side, quantity, price, cost, note, record_kind
            FROM paper_trades WHERE line_id = ?;
            """,
            (line_id,),
        ).fetchall()
    lower = _range_boundary(start)
    upper = _range_boundary(end, end=True)
    rows = [row for row in rows if (
        (lower is None or (_nav_timestamp(row[1]) is not None and _nav_timestamp(row[1]) >= lower))
        and (upper is None or (_nav_timestamp(row[1]) is not None and _nav_timestamp(row[1]) <= upper))
    )]
    rows.sort(key=lambda row: (_nav_timestamp(row[1]) or datetime.min.replace(tzinfo=timezone.utc), row[2], row[3]), reverse=True)
    return [
        PaperTradeRecord(
            line_id=row[0], date=row[1], symbol=row[2], side=row[3], quantity=row[4],
            price=row[5], cost=row[6], note=row[7], record_kind=row[8],
        )
        for row in rows[:safe_limit]
    ]


def prune_unregistered_paper_lines(
    registered_line_ids: set[str], db_path: Optional[str] = None
) -> list[str]:
    """Remove stale paper rows whose line ids no longer exist in the registry."""
    path = db_path or get_db_path()
    init_db(path)
    removed: list[str] = []
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT line_id FROM paper_lines;")
        candidates = [str(row[0]) for row in cursor.fetchall() if str(row[0]) not in registered_line_ids]
        for line_id in candidates:
            cursor.execute("DELETE FROM paper_nav WHERE line_id = ?;", (line_id,))
            cursor.execute("DELETE FROM paper_positions WHERE line_id = ?;", (line_id,))
            cursor.execute("DELETE FROM paper_trades WHERE line_id = ?;", (line_id,))
            cursor.execute("DELETE FROM paper_lines WHERE line_id = ?;", (line_id,))
            removed.append(line_id)
        conn.commit()
    return removed


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


def get_ingest_health(db_path: Optional[str] = None) -> tuple[str, int, int]:
    """Return latest ingest health and current stale/missing source counts."""
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return "never", 0, 0
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT status FROM ingest_runs ORDER BY id DESC LIMIT 1;").fetchone()
        if row is not None:
            ingest_status = str(row[0])
        else:
            row = conn.execute("SELECT ok FROM ingest_log ORDER BY id DESC LIMIT 1;").fetchone()
            ingest_status = "never" if row is None else ("ok" if row[0] else "failed")
    summaries = get_paper_lines_summary(path, forward_only=False)
    stale = sum(1 for line in summaries if line.paper_enabled and line.freshness == "STALE")
    missing = sum(1 for line in summaries if line.data_status in {"MISSING", "ERROR"} or line.freshness == "MISSING")
    if ingest_status == "ok" and missing:
        ingest_status = "partial"
    return ingest_status, stale, missing


def log_ingest_run(status: str, failed_lines: list[str], db_path: Optional[str] = None, ran_at: Optional[str] = None) -> None:
    path = db_path or get_db_path()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO ingest_runs (ran_at, status, failed_lines) VALUES (?, ?, ?)",
            (ran_at or datetime.now(timezone.utc).isoformat(), status, json.dumps(sorted(failed_lines))),
        )
        conn.commit()


def mark_line_data_error(line_id: str, message: str, db_path: Optional[str] = None) -> None:
    """Mark the latest line payload as errored while keeping its last valid NAV history."""
    path = db_path or get_db_path()
    if not os.path.exists(path) and path != ":memory:":
        return
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT payload FROM paper_lines WHERE line_id = ?;", (line_id,)).fetchone()
        if not row:
            return
        payload = json.loads(row[0])
        payload["data_status"] = "ERROR"
        payload["error"] = message
        payload["position_status"] = "UNKNOWN"
        payload["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
        payload["last_attempt_status"] = "ERROR"
        payload["last_attempt_error"] = message
        conn.execute("UPDATE paper_lines SET payload = ? WHERE line_id = ?;", (json.dumps(payload, ensure_ascii=False), line_id))
        conn.commit()


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
