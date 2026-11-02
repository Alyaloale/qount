#!/usr/bin/env python3
"""Refresh the Dashboard's private account observation without order authority."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.exchange_utils import build_exchange  # noqa: E402
from qount.mini_trend.pilot_preflight import build_pilot_account_preflight  # noqa: E402
from qount.operations.account_assets import append_asset_history, collect_asset_overview  # noqa: E402
from qount.operations.account_trades import collect_trade_records, persist_trade_records  # noqa: E402
from qount.operations.macro_notifications import collect_macro_runtime  # noqa: E402
from qount.operations.authority_writer import _readonly_account_observation  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--assets-path", type=Path, help="Defaults to account-assets.json beside the legacy observation")
    parser.add_argument("--history-path", type=Path, help="Defaults to account-assets-history.sqlite3 beside the observation")
    parser.add_argument("--trades-path", type=Path, help="Read-only fills/income database beside the observation")
    return parser


def _write(path: Path, payload: dict[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise ValueError("dashboard_account_observation_output_symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii") + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    runtime = collect_macro_runtime(
        Path(os.environ.get("QOUNT_1ATR_RESULT_PATH", "/var/lib/qount/1atr/live-result.json")),
        Path(os.environ.get("QOUNT_1ATR_HALT_PATH", "/var/lib/qount/1atr/HALT")),
        notification_store=os.environ.get("QOUNT_NOTIFICATION_STORE"))
    settings = Settings.from_env()
    preflight = build_pilot_account_preflight(settings)
    observed_at = str(preflight["created_at"])
    observation = _readonly_account_observation(preflight, observed_at)
    client = build_exchange(settings, private=True)
    try:
        overview = collect_asset_overview(client)
        records = collect_trade_records(client)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    preflight_hash = canonical_hash(preflight)
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_type": "qount_blocked_runtime_observation",
        "created_at": observed_at,
        "observed_at": observed_at,
        "status": "blocked",
        "live_orders_allowed": False,
        "runtime_ledger_created": False,
        "strategy_id": "dashboard_readonly_account_observer",
        "blockers": ["private_account_observation_only"],
        "run_id": f"dashboard-account-observer-{preflight_hash[:16]}",
        "source_hashes": {"account_preflight": preflight_hash},
        "account_observation": observation,
    }
    payload = core | {"observation_hash": canonical_hash(core)}
    history_path = args.history_path or args.output_path.with_name("account-assets-history.sqlite3")
    assets_path = args.assets_path or args.output_path.with_name("account-assets.json")
    trades_path = args.trades_path or args.output_path.with_name("account-trades.sqlite3")
    overview["strategy_runtime"] = runtime
    if len({p.resolve() for p in (history_path, assets_path, trades_path, args.output_path)}) != 4:
        raise ValueError("asset_output_paths_must_differ")
    append_asset_history(history_path, overview)
    _write(assets_path, overview)
    # Account fill/income persistence is independent of the strict legacy
    # observation. A ledger failure must not suppress fresh balance snapshots.
    try:
        persist_trade_records(trades_path, records)
        print(f"account_history_status={records['status']}")
    except Exception as exc:
        print(f"account_history_status=ERROR:{type(exc).__name__}")
        try:
            persist_trade_records(trades_path, {**records,"fills":[],"income":[],"status":"ERROR",
                "errors":{**records["errors"],"persistence":type(exc).__name__}})
        except Exception:
            pass  # Balance/legacy snapshots remain available independently.
    # The existing observation has strict readers; its schema and last good value stay intact.
    if observation is not None:
        _write(args.output_path, payload)
        print(f"observation_hash={payload['observation_hash']}")
    print(f"asset_status={overview['status']}")
    print("private_api_order_attempted=false")
    print("live_orders_allowed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
