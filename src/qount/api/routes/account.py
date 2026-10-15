"""Account snapshot route for qount API."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter

from qount.api.schemas import (
    AccountSnapshot,
    BalanceItem,
    LineSafety,
    LineSource,
    PositionItem,
)
from qount.api.ledger import parse_personal_assistant_position_ledger

router = APIRouter(prefix="/account", tags=["account"])

DEFAULT_ACCOUNT_SOURCE = "deploy/research/artifacts/personal_assistant_reconciled_20261012/summary.json"
DEFAULT_TRADES_SOURCE = "deploy/research/artifacts/personal_assistant_reconciled_20261012/trades.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_sha256(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _file_mtime_iso(path: str) -> Optional[str]:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
    except OSError:
        return None


def load_account_snapshot() -> AccountSnapshot:
    source_path = os.environ.get("QOUNT_ACCOUNT_SOURCE_PATH", DEFAULT_ACCOUNT_SOURCE)
    trades_path = os.environ.get("QOUNT_ACCOUNT_TRADES_PATH", DEFAULT_TRADES_SOURCE)

    if not os.path.exists(source_path):
        # No source means no figures. Returning a synthetic "1,000,000 initial capital" here
        # would render as a real-looking balance in the UI, indistinguishable from an actual one.
        return AccountSnapshot(
            as_of=_now_iso(),
            mode="PAPER",
            source_kind="local_snapshot",
            nav=0.0,
            cash=0.0,
            positions=[],
            positions_status="MISSING",
            currency="CNY",
            source=LineSource(path=source_path, sha256=None, produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error=(
                "SOURCE_NOT_FOUND: the reconciled paper package is absent, so no paper NAV is "
                "reported. This is a simulation figure and is unrelated to the real account."
            ),
        )

    try:
        with open(source_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        produced_at = summary.get("generated_at") or _file_mtime_iso(source_path)
        sha256_val = _compute_sha256(source_path)

        # Load real audited paper portfolio from personal assistant (MA120 model on core ETF)
        assets = summary.get("assets", {})
        target_asset = assets.get("513100.SH", {})
        baselines = target_asset.get("baselines", [])
        ma120_baseline = next((b for b in baselines if b.get("model_name") == "MA120_Band1.5pct"), None)

        if ma120_baseline is None:
            return AccountSnapshot(
                as_of=produced_at or _now_iso(),
                mode="PAPER",
                source_kind="local_snapshot",
                nav=0.0,
                cash=0.0,
                positions=[],
                positions_status="MISSING",
                currency="CNY",
                source=LineSource(
                    path=source_path,
                    sha256=sha256_val,
                    produced_at=produced_at,
                ),
                safety=LineSafety(research_only=True, orders_authorized=False),
                error="BASELINE_ABSENT: MA120_Band1.5pct is missing; no paper NAV is reported.",
            )

        nav = round(float(ma120_baseline["terminal_equity"]), 2)
        cash = None
        open_shares = 0.0
        entry_date = None
        position_error = None
        positions_status = "UNKNOWN"
        if os.path.isfile(trades_path):
            with open(trades_path, "r", encoding="utf-8") as tf:
                trades_data = json.load(tf)
            ledger = trades_data.get("513100.SH", {}).get("MA120_Band1.5pct")
            try:
                open_shares, entry_date = parse_personal_assistant_position_ledger(
                    ledger, as_of=str(ma120_baseline["end_date"])
                )
                positions_status = "KNOWN"
            except (TypeError, ValueError) as exc:
                position_error = f"POSITION_LEDGER_INVALID: {type(exc).__name__}"

        positions = (
            [PositionItem(symbol="513100.SH", weight=None, quantity=round(open_shares, 6), entry_date=entry_date)]
            if open_shares > 1e-9 else []
        )
        raw_as_of = str(ma120_baseline.get("end_date") or "")
        as_of = (
            f"{raw_as_of[:4]}-{raw_as_of[4:6]}-{raw_as_of[6:]}"
            if len(raw_as_of) == 8 and raw_as_of.isdigit()
            else raw_as_of
        )
        if not as_of:
            raise ValueError("baseline end_date is absent")

        return AccountSnapshot(
            as_of=as_of,
            mode="PAPER",
            nav=nav,
            initial_equity=ma120_baseline.get("initial_equity"),
            cash=cash,
            positions=positions,
            positions_status=positions_status,
            position_error=position_error,
            currency="CNY",
            source=LineSource(
                path=source_path,
                sha256=sha256_val,
                produced_at=produced_at,
            ),
            safety=LineSafety(research_only=True, orders_authorized=False),
        )
    except Exception as exc:
        return AccountSnapshot(
            as_of=_now_iso(),
            mode="PAPER",
            source_kind="local_snapshot",
            nav=0.0,
            cash=0.0,
            positions=[],
            positions_status="MISSING",
            currency="CNY",
            source=LineSource(path=source_path, sha256=_compute_sha256(source_path)),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error=f"PACKAGE_UNREADABLE: {type(exc).__name__}",
        )


@router.get("", response_model=AccountSnapshot)
def get_account() -> AccountSnapshot:
    """Return the current paper account snapshot."""
    return load_account_snapshot()


# ---------------------------------------------------------------------------
# Live read-only exchange account
# ---------------------------------------------------------------------------

#: Written every ~5 minutes on the VPS by qount-dashboard-account-observer, which reads the
#: exchange through a read-only key. This process never touches the key itself.
DEFAULT_OBSERVATION_SOURCE = "/var/lib/qount/blocked_runtime_observation.json"


def load_live_account_snapshot() -> AccountSnapshot:
    """Map the host's read-only account observation onto an AccountSnapshot.

    The observation already exists on the host; nothing here talks to an exchange. When the
    file is absent or unreadable the snapshot reports the failure and carries no balance —
    it must never fall back to the PAPER figures, which would present a simulation number as
    if it were the real account.
    """
    path = os.environ.get("QOUNT_ACCOUNT_OBSERVATION_PATH", DEFAULT_OBSERVATION_SOURCE)

    if not os.path.exists(path):
        return AccountSnapshot(
            as_of=_now_iso(),
            mode="LIVE_READONLY",
            source_kind="binance_api",
            nav=0.0,
            cash=0.0,
            positions=[],
            positions_status="MISSING",
            currency="USDT",
            balances=[],
            read_only=True,
            source=LineSource(path=path, sha256=None, produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error=(
                "OBSERVATION_NOT_FOUND: the read-only account observation is produced on the host "
                "that holds the exchange key and is not present here."
            ),
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        observation = payload.get("account_observation") or {}
    except Exception as exc:
        return AccountSnapshot(
            as_of=_now_iso(),
            mode="LIVE_READONLY",
            source_kind="binance_api",
            nav=0.0,
            cash=0.0,
            positions=[],
            currency="USDT",
            balances=[],
            read_only=True,
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error=f"OBSERVATION_UNREADABLE: {type(exc).__name__}",
        )

    quote_asset = str(observation.get("quote_asset") or "USDT")
    try:
        wallet_balance = float(observation["wallet_balance"])
        available_balance = float(observation["available_balance"])
        if not math.isfinite(wallet_balance) or not math.isfinite(available_balance) or wallet_balance < 0 or available_balance < 0 or available_balance > wallet_balance:
            raise ValueError("invalid balances")
    except (KeyError, TypeError, ValueError):
        return AccountSnapshot(
            as_of=_now_iso(), mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
            cash=0.0, positions=[], currency="USDT", balances=[], read_only=True,
            positions_status="MISSING",
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error="OBSERVATION_INCOMPLETE: required wallet and available balances are absent or invalid.",
        )
    observed_at = observation.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at.strip():
        return AccountSnapshot(
            as_of="unknown", mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
            cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
            positions_status="MISSING",
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error="OBSERVATION_INCOMPLETE: observed_at is absent; freshness cannot be established.",
        )
    try:
        parsed_time = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            raise ValueError("observation timestamp needs a timezone")
    except ValueError:
        return AccountSnapshot(
            as_of="unknown", mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
            cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
            positions_status="MISSING",
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=None),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error="OBSERVATION_INCOMPLETE: observed_at is invalid.",
        )
    observed_at = observed_at.strip()
    raw_positions = observation.get("positions")
    if not isinstance(raw_positions, list):
        return AccountSnapshot(
            as_of=observed_at, mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
            cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
            positions_status="MISSING",
            source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=observed_at),
            safety=LineSafety(research_only=True, orders_authorized=False),
            error="OBSERVATION_INCOMPLETE: positions must be an explicit list.",
        )

    balances = [
        BalanceItem(
            asset=quote_asset,
            free=available_balance,
            locked=max(0.0, wallet_balance - available_balance),
        )
    ]

    positions: list[PositionItem] = []
    for row in raw_positions:
        if not isinstance(row, dict):
            return AccountSnapshot(
                as_of=observed_at, mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
                cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
                positions_status="MISSING",
                source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=observed_at),
                safety=LineSafety(research_only=True, orders_authorized=False),
                error="OBSERVATION_INCOMPLETE: positions contains an invalid row.",
            )
        symbol = row.get("symbol")
        if not symbol:
            return AccountSnapshot(
                as_of=observed_at, mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
                cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
                positions_status="MISSING",
                source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=observed_at),
                safety=LineSafety(research_only=True, orders_authorized=False),
                error="OBSERVATION_INCOMPLETE: a position has no symbol.",
            )
        try:
            quantity = float(row["quantity"])
            notional = float(row["notional"])
            if not math.isfinite(quantity) or not math.isfinite(notional) or notional < 0:
                raise ValueError("invalid position values")
        except (KeyError, TypeError, ValueError):
            return AccountSnapshot(
                as_of=observed_at, mode="LIVE_READONLY", source_kind="binance_api", nav=0.0,
                cash=0.0, positions=[], currency=quote_asset, balances=[], read_only=True,
                positions_status="MISSING",
                source=LineSource(path=path, sha256=_compute_sha256(path), produced_at=observed_at),
                safety=LineSafety(research_only=True, orders_authorized=False),
                error="OBSERVATION_INCOMPLETE: a position is missing quantity or notional.",
            )
        positions.append(PositionItem(
            symbol=str(symbol), weight=None, quantity=quantity,
            market_value=notional, side=str(row.get("side") or "unknown").lower(),
        ))

    return AccountSnapshot(
        as_of=observed_at,
        mode="LIVE_READONLY",
        source_kind="binance_api",
        nav=wallet_balance,
        observation_interval_seconds=300,
        cash=available_balance,
        positions=positions,
        positions_status="KNOWN",
        currency=quote_asset,
        balances=balances,
        read_only=True,
        source=LineSource(
            path=path,
            sha256=_compute_sha256(path),
            produced_at=observed_at,
        ),
        safety=LineSafety(research_only=True, orders_authorized=False),
        error=None,
    )


@router.get("/live", response_model=AccountSnapshot)
def get_live_account() -> AccountSnapshot:
    """Return the real read-only exchange account, or an explicit failure."""
    return load_live_account_snapshot()
