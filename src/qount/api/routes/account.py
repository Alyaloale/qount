"""Account snapshot route for qount API."""

from __future__ import annotations

import hashlib
import json
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

router = APIRouter(prefix="/account", tags=["account"])

DEFAULT_ACCOUNT_SOURCE = "state/research_runs/personal_assistant_reconciled_20261012/summary.json"
DEFAULT_TRADES_SOURCE = "state/research_runs/personal_assistant_reconciled_20261012/trades.json"


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

        produced_at = summary.get("generated_at", "2026-10-12T09:00:00Z")
        sha256_val = _compute_sha256(source_path)

        # Load real audited paper portfolio from personal assistant (MA120 model on core ETF)
        assets = summary.get("assets", {})
        target_asset = assets.get("513100.SH", {})
        baselines = target_asset.get("baselines", [])
        ma120_baseline = next((b for b in baselines if b.get("model_name") == "MA120_Band1.5pct"), None)

        nav = 1000000.0
        cash = 0.0
        positions = []

        if ma120_baseline:
            nav = round(float(ma120_baseline.get("terminal_equity", 1000000.0)), 2)

            # Check last trade date if trades file exists
            entry_date = "2026-04-24"
            if os.path.exists(trades_path):
                try:
                    with open(trades_path, "r", encoding="utf-8") as tf:
                        trades_data = json.load(tf)
                    t_list = trades_data.get("513100.SH", {}).get("MA120_Band1.5pct", [])
                    if t_list:
                        last_t = t_list[-1]
                        raw_d = str(last_t.get("date", "20260424"))
                        if len(raw_d) == 8:
                            entry_date = f"{raw_d[:4]}-{raw_d[4:6]}-{raw_d[6:]}"
                        else:
                            entry_date = raw_d
                except Exception:
                    pass

            positions = [
                PositionItem(
                    symbol="513100.SH",
                    weight=1.0,
                    entry_date=entry_date,
                )
            ]
            cash = 0.0

        return AccountSnapshot(
            as_of="2026-10-12T09:00:00Z",
            mode="PAPER",
            nav=nav,
            cash=cash,
            positions=positions,
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
    wallet_balance = float(observation.get("wallet_balance") or 0.0)
    available_balance = float(observation.get("available_balance") or 0.0)
    observed_at = str(observation.get("observed_at") or _now_iso())

    balances = [
        BalanceItem(
            asset=quote_asset,
            free=available_balance,
            locked=max(0.0, wallet_balance - available_balance),
        )
    ]

    positions: list[PositionItem] = []
    for row in observation.get("positions") or []:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        if not symbol:
            continue
        try:
            weight = float(row.get("actual_weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        positions.append(PositionItem(symbol=str(symbol), weight=weight))

    return AccountSnapshot(
        as_of=observed_at,
        mode="LIVE_READONLY",
        source_kind="binance_api",
        nav=wallet_balance,
        cash=available_balance,
        positions=positions,
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
