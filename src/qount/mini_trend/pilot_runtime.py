"""Independent systemd runtime evidence for the MiniTrend forward cycle."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.models import utc_now
from qount.settings import Settings


PILOT_RUNTIME_PROOF_VERSION = "mini_trend_um_runtime_proof_v0.1"
_LIVE_SWITCHES = (
    "QOUNT_LIVE_ENABLE",
    "QOUNT_X4_LIVE_ENABLE",
    "QOUNT_RV_LIVE_ENABLE",
    "QOUNT_CXD_CARRY_ENABLE",
    "QOUNT_MINI_TREND_LIVE_ENABLE",
)


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "live"}


def _file_source(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    raw = target.read_bytes()
    return {
        "path": str(target),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "executable": os.access(target, os.X_OK),
    }


def build_pilot_runtime_proof(
    *,
    cycle_path: str | os.PathLike[str],
    service_unit_path: str | os.PathLike[str],
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environment is None else environment)
    switches = {name: _enabled(env.get(name)) for name in _LIVE_SWITCHES}
    invocation = str(env.get("INVOCATION_ID") or "")
    errors: dict[str, str] = {}
    sources: dict[str, Any] = {}
    for name, path in (("cycle", cycle_path), ("service_unit", service_unit_path)):
        try:
            sources[name] = _file_source(path)
        except OSError as exc:
            errors[name] = f"{type(exc).__name__}: {str(exc)[:300]}"
    gates = {
        "systemd_invocation_present": bool(invocation),
        "cycle_source_bound": "cycle" in sources,
        "cycle_executable": bool((sources.get("cycle") or {}).get("executable")),
        "service_unit_source_bound": "service_unit" in sources,
        "all_live_switches_disabled": not any(switches.values()),
        "legacy_confirmation_absent": not bool(env.get("QOUNT_LIVE_CONFIRMATION")),
        "mini_trend_confirmation_absent": not bool(
            env.get("QOUNT_MINI_TREND_LIVE_CONFIRMATION")
        ),
        "arm_token_absent": not bool(env.get("QOUNT_MINI_TREND_ARM_TOKEN")),
    }
    passed = all(gates.values()) and not errors
    return {
        "schema_version": PILOT_RUNTIME_PROOF_VERSION,
        "artifact_type": "mini_trend_um_independent_runtime_proof",
        "created_at": utc_now().isoformat(),
        "meta": {
            "order_free_runtime": True,
            "private_api_order_attempted": False,
            "mutating_account_method_attempted": False,
            "orders_allowed": False,
            "live_orders_allowed": False,
        },
        "contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
        "runtime": {
            "manager": "systemd",
            "invocation_id_sha256": (
                hashlib.sha256(invocation.encode("utf-8")).hexdigest()
                if invocation
                else None
            ),
            "live_switches": switches,
        },
        "sources": sources,
        "diagnostics": {
            "errors": errors,
            "gates": gates,
            "blockers": [name for name, value in gates.items() if not value],
            "verdict": (
                "independent_runtime_verified"
                if passed
                else "blocked_independent_runtime"
            ),
        },
    }


def validate_pilot_runtime_proof(payload: Mapping[str, Any]) -> bool:
    meta = payload.get("meta") or {}
    gates = (payload.get("diagnostics") or {}).get("gates") or {}
    runtime = payload.get("runtime") or {}
    sources = payload.get("sources") or {}
    source_hashes_valid = all(
        isinstance((sources.get(name) or {}).get("sha256"), str)
        and len((sources.get(name) or {}).get("sha256")) == 64
        for name in ("cycle", "service_unit")
    )
    return (
        payload.get("schema_version") == PILOT_RUNTIME_PROOF_VERSION
        and payload.get("artifact_type")
        == "mini_trend_um_independent_runtime_proof"
        and payload.get("contract_hash") == LIVE_PILOT_CONTRACT.contract_hash
        and bool(meta.get("order_free_runtime"))
        and not any(
            bool(meta.get(name))
            for name in (
                "private_api_order_attempted",
                "mutating_account_method_attempted",
                "orders_allowed",
                "live_orders_allowed",
            )
        )
        and bool(gates)
        and all(bool(value) for value in gates.values())
        and isinstance(runtime.get("invocation_id_sha256"), str)
        and len(runtime.get("invocation_id_sha256")) == 64
        and source_hashes_valid
        and (payload.get("diagnostics") or {}).get("verdict")
        == "independent_runtime_verified"
    )


def write_pilot_runtime_proof_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-runtime-proof",
        path_key="artifact_path",
        default_filename="mini_trend_um_runtime_proof.json",
        explicit_path=explicit_path,
    )
