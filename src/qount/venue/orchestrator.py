"""Venue capability snapshot orchestration layer.

Coordinates fetch, build, and archive of venue capability snapshots.
Accepts an injected VenueDataFetcher; does NOT import ccxt or
qount.exchange_utils.

Import boundary: this module must NOT import qount.execution,
qount.executor, qount.mini_trend.pilot_dispatcher, or ccxt.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Sequence

from qount.venue.contracts import VenueCapabilitySnapshot
from qount.venue.fetch import VenueData
from qount.venue.fetch import VenueDataFetcher
from qount.venue.fetch import extract_symbol_rules
from qount.venue.fetch import fetch_venue_data
from qount.venue.snapshot import build_venue_capability_snapshot


def run_venue_snapshot(
    *,
    fetcher: VenueDataFetcher,
    venue: str = "binance_usdm",
    symbols: Sequence[str] | None = None,
    position_mode: str = "one_way",
    margin_mode: str = "isolated",
    leverage: int = 1,
    previous_snapshot: VenueCapabilitySnapshot | None = None,
    archive_dir: str | os.PathLike[str] | None = None,
) -> VenueCapabilitySnapshot:
    """Run one venue capability snapshot cycle.

    Steps:
    1. Fetch exchange_info, server time, and changelog body.
    2. Extract symbol rules for the specified symbols.
    3. Build VenueCapabilitySnapshot (with previous snapshot comparison).
    4. Archive snapshot (if archive_dir provided).

    Returns the new VenueCapabilitySnapshot.
    """
    venue_data = fetch_venue_data(fetcher)

    symbol_list = list(symbols) if symbols else None
    symbol_rules = extract_symbol_rules(
        venue_data.exchange_info, symbol_list
    )

    observed_at = dt.datetime.now(dt.timezone.utc).isoformat()

    snapshot = build_venue_capability_snapshot(
        venue=venue,
        observed_at=observed_at,
        exchange_info=venue_data.exchange_info,
        symbol_rules=symbol_rules,
        position_mode=position_mode,
        margin_mode=margin_mode,
        leverage=leverage,
        server_time_offset_ms=venue_data.server_time_offset_ms,
        changelog_last_reviewed_at=venue_data.changelog_observed_at,
        changelog_source_hash=venue_data.changelog_source_hash,
        previous_snapshot=previous_snapshot,
    )

    if archive_dir is not None:
        _archive_venue_snapshot(snapshot, archive_dir=archive_dir)

    return snapshot


def _archive_venue_snapshot(
    snapshot: VenueCapabilitySnapshot,
    *,
    archive_dir: str | os.PathLike[str],
) -> str:
    """Archive a VenueCapabilitySnapshot as a timestamped JSON file."""
    dir_path = Path(archive_dir)
    dir_path.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.fromisoformat(snapshot.observed_at)
    filename = timestamp.strftime("%Y%m%dT%H%M%SZ")
    file_path = dir_path / f"{filename}.json"

    payload = {
        "schema_version": snapshot.schema_version,
        "snapshot_id": snapshot.snapshot_id,
        "venue": snapshot.venue,
        "observed_at": snapshot.observed_at,
        "server_time_offset_ms": snapshot.server_time_offset_ms,
        "exchange_info_schema_hash": snapshot.exchange_info_schema_hash,
        "symbol_rules_hash": snapshot.symbol_rules_hash,
        "position_mode": snapshot.position_mode,
        "margin_mode": snapshot.margin_mode,
        "leverage": snapshot.leverage,
        "order_endpoint_contract_hashes": dict(
            snapshot.order_endpoint_contract_hashes
        ),
        "algo_endpoint_contract_hashes": dict(
            snapshot.algo_endpoint_contract_hashes
        ),
        "order_capabilities": dict(snapshot.order_capabilities),
        "conditional_algo_capabilities": dict(
            snapshot.conditional_algo_capabilities
        ),
        "query_retention_assumptions": dict(
            snapshot.query_retention_assumptions
        ),
        "websocket_assumptions": dict(snapshot.websocket_assumptions),
        "rest_recovery_assumptions": dict(snapshot.rest_recovery_assumptions),
        "changelog_last_reviewed_at": snapshot.changelog_last_reviewed_at,
        "changelog_source_hash": snapshot.changelog_source_hash,
        "compatibility": snapshot.compatibility,
        "blockers": list(snapshot.blockers),
        "snapshot_hash": snapshot.snapshot_hash,
    }

    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    with open(file_path, "w", encoding="ascii") as f:
        f.write(canonical)

    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
