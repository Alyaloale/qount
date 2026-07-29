#!/usr/bin/env python3
"""Prepare, arm, switch, or run the bounded FOMC live execution path."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.settings import Settings  # noqa: E402
from qount.small_account.fomc_live import FomcLiveStore  # noqa: E402
from qount.small_account.fomc_live import build_fomc_live_auto_authorization  # noqa: E402
from qount.small_account.fomc_live import build_fomc_live_account_preflight  # noqa: E402
from qount.small_account.fomc_live import build_fomc_live_arm  # noqa: E402
from qount.small_account.fomc_live import prepare_fomc_live_readiness  # noqa: E402
from qount.small_account.fomc_live import run_fomc_auto_execution_cycle  # noqa: E402
from qount.small_account.fomc_live import run_fomc_live_cycle  # noqa: E402
from qount.small_account.fomc_live import set_fomc_live_environment_switch  # noqa: E402
from qount.small_account.fomc_live import write_fomc_live_environment  # noqa: E402
from qount.small_account.fomc_watcher import FomcStateStore  # noqa: E402
from qount.small_account.fomc_watcher import load_fomc_event_definition  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-config", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare", help="Run private preflight and freeze readiness."
    )
    prepare.add_argument("--observed-at")

    arm = subparsers.add_parser("arm", help="Create one short-lived arm with switch off.")
    arm.add_argument("--environment-file", type=Path, required=True)
    arm.add_argument("--confirm-readiness-hash", required=True)

    switch = subparsers.add_parser("switch", help="Change only the matching arm switch.")
    switch.add_argument("--environment-file", type=Path, required=True)
    switch.add_argument("--arm-id", required=True)
    switch_group = switch.add_mutually_exclusive_group(required=True)
    switch_group.add_argument("--enable", action="store_true")
    switch_group.add_argument("--disable", action="store_true")

    authorize_auto = subparsers.add_parser(
        "authorize-auto",
        help="Bind one owner-authorized automatic entry to the current account.",
    )
    authorize_auto.add_argument("--observed-at")

    subparsers.add_parser("cycle", help="Run one fail-closed scheduled cycle.")
    subparsers.add_parser(
        "auto-cycle",
        help="Run the bounded owner-authorized automatic event cycle.",
    )
    return parser


def _summary(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    event = load_fomc_event_definition(args.event_config)
    state_store = FomcStateStore(args.state_root, event.event_id)
    live_store = FomcLiveStore(args.state_root, event.event_id)

    if args.command == "prepare":
        readiness = prepare_fomc_live_readiness(
            Settings.from_env(),
            event,
            state_store,
            live_store,
            observed_at=args.observed_at,
        )
        _summary(
            {
                "event_id": event.event_id,
                "readiness_hash": readiness["readiness_hash"],
                "expires_at": readiness["expires_at"],
                "verdict": readiness["verdict"],
                "blockers": readiness["blockers"],
                "exchange_mutation_attempted": False,
            }
        )
        return 0 if readiness["verdict"] == "ready_for_fomc_live_arm" else 2

    if args.command == "arm":
        readiness = live_store.read_readiness()
        if readiness is None:
            parser.error("no live readiness artifact exists")
        if args.confirm_readiness_hash != readiness.get("readiness_hash"):
            parser.error("confirmed readiness hash does not match the stored artifact")
        token = secrets.token_urlsafe(48)
        arm = build_fomc_live_arm(
            readiness,
            arm_token=token,
            armed_at=dt.datetime.now(dt.timezone.utc),
            confirmed_readiness_hash=args.confirm_readiness_hash,
        )
        live_store.write_arm(arm)
        write_fomc_live_environment(
            args.environment_file,
            arm=arm,
            arm_token=token,
            enabled=False,
        )
        _summary(
            {
                "event_id": event.event_id,
                "arm_id": arm["arm_id"],
                "readiness_hash": arm["readiness_hash"],
                "plan_hash": arm["plan_hash"],
                "account_scope_hash": arm["account_scope_hash"],
                "scope": arm["scope"],
                "expires_at": arm["expires_at"],
                "environment_file": str(args.environment_file),
                "live_switch_enabled": False,
            }
        )
        return 0

    if args.command == "switch":
        set_fomc_live_environment_switch(
            args.environment_file,
            arm_id=args.arm_id,
            enabled=args.enable,
        )
        _summary(
            {
                "event_id": event.event_id,
                "arm_id": args.arm_id,
                "environment_file": str(args.environment_file),
                "live_switch_enabled": bool(args.enable),
            }
        )
        return 0

    if args.command == "authorize-auto":
        observed_at = args.observed_at or dt.datetime.now(dt.timezone.utc)
        preflight = build_fomc_live_account_preflight(
            Settings.from_env(),
            event,
            observed_at=observed_at,
            halt_present=live_store.halt_path.exists(),
        )
        authorization = build_fomc_live_auto_authorization(
            event,
            preflight,
            authorized_at=observed_at,
        )
        live_store.write_auto_authorization(authorization)
        _summary(
            {
                "event_id": event.event_id,
                "authorization_id": authorization["authorization_id"],
                "account_scope_hash": authorization["account_scope_hash"],
                "policy": authorization["policy"],
                "expires_at": authorization["expires_at"],
                "exchange_mutation_attempted": False,
            }
        )
        return 0

    if args.command == "auto-cycle":
        result = run_fomc_auto_execution_cycle(
            Settings.from_env(),
            event,
            state_store,
            live_store,
            observed_at=None,
        )
        _summary(dict(result))
        status = str(result.get("status", ""))
        successful = {
            "auto_disarmed",
            "auto_waiting_for_observation",
            "auto_waiting_for_signal",
            "protected",
            "force_exit_flattened",
            "protection_failure_flattened",
            "native_stop_flattened",
            "management_early_exit_flattened",
        }
        return 0 if status in successful else 2

    result = run_fomc_live_cycle(
        Settings.from_env(),
        event,
        state_store,
        live_store,
        observed_at=None,
        arm_token=os.getenv("QOUNT_FOMC_ARM_TOKEN"),
        live_switch_enabled=(
            os.getenv("QOUNT_FOMC_LIVE_ENABLE", "").strip().lower()
            in {"1", "true", "yes", "on", "live"}
        ),
        live_confirmation=os.getenv("QOUNT_FOMC_LIVE_CONFIRMATION"),
    )
    _summary(dict(result))
    status = str(result.get("status", ""))
    successful = {
        "disarmed",
        "protected",
        "force_exit_flattened",
        "protection_failure_flattened",
        "native_stop_flattened",
        "management_early_exit_flattened",
    }
    return 0 if status in successful else 2


if __name__ == "__main__":
    raise SystemExit(main())
