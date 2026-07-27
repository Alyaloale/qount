"""Build one order-free authority bundle from a verified MiniTrend run.

This is the narrow bridge from the existing order-free runtime artifacts to the
standard reporting contracts.  It may read local JSON and the private runtime
ledger, but it never creates an exchange client, calls a private API, sends a
notification, or grants order authority.  Incomplete input is a normal,
fail-closed result and leaves the previous authority bundle untouched.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.governance import StrategyRegistry
from qount.governance import StrategyRegistration
from qount.ledger import RuntimeLedger
from qount.ledger import build_runtime_ledger_snapshot
from qount.ledger import build_verified_legacy_dispatch_batch
from qount.ledger import reconcile_three_way
from qount.notifications import NotificationStore
from qount.notifications import SystemHealthObservation
from qount.notifications import alerts_from_runtime_ledger_snapshot
from qount.notifications import alerts_from_system_health
from qount.notifications import alerts_from_verified_decision_batch
from qount.notifications import build_notification_snapshot
from qount.notifications import synchronize_producer_incidents
from qount.operations.health_probes import DEFAULT_ALLOWED_SERVICE_NAMES
from qount.operations.health_probes import HealthProbeConfig
from qount.operations.health_probes import HealthProbeDependencies
from qount.operations.health_probes import collect_os_system_health
from qount.persistence import publish_decision_batch
from qount.persistence import write_immutable_artifact
from qount.reporting import build_daily_brief
from qount.reporting import read_vps_authority_bundle
from qount.mini_trend.forward import TOP3
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.live_pilot import manual_arm_owner_authorization_hash
from qount.strategies import BASE_STRATEGY_VERSION
from qount.strategies import base_strategy_registration


AUTHORITY_WRITER_SCHEMA_VERSION = 1
BLOCKED_RUNTIME_OBSERVATION_SCHEMA_VERSION = 1
_RUN_NAME = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
_SOURCE_FILES = (
    "account_preflight.json",
    "dispatch_readiness.json",
    "dry_dispatch.json",
    "exchange_rules.json",
    "latest_projection.json",
)


class AuthorityWriterError(ValueError):
    """Raised when authority source validation or publication fails."""


class AuthorityWriterBlocked(AuthorityWriterError):
    """Raised internally for a safe, expected source gate block."""

    def __init__(self, blockers: tuple[str, ...], *, run_dir: Path):
        self.blockers = blockers
        self.run_dir = run_dir
        super().__init__("authority_source_blocked:" + ",".join(blockers))


@dataclass(frozen=True)
class AuthorityWriterConfig:
    repo_root: Path
    source_root: Path
    authority_root: Path
    runtime_root: Path
    backup_root: Path
    dashboard_root: Path
    lock_path: Path
    notification_store_path: Path | None = None
    target_stress_loss_fraction: float = 0.01
    service_name: str = "qount-dashboard-publisher.timer"

    def validate(self) -> None:
        paths = (
            self.repo_root,
            self.source_root,
            self.authority_root,
            self.runtime_root,
            self.backup_root,
            self.dashboard_root,
            self.lock_path,
            *(
                (self.notification_store_path,)
                if self.notification_store_path is not None
                else ()
            ),
        )
        if any(not isinstance(path, Path) or not path.is_absolute() for path in paths):
            raise AuthorityWriterError("authority_writer_absolute_paths_required")
        if self.service_name not in DEFAULT_ALLOWED_SERVICE_NAMES:
            raise AuthorityWriterError("authority_writer_service_not_allowlisted")
        try:
            fraction = float(self.target_stress_loss_fraction)
        except (TypeError, ValueError) as exc:
            raise AuthorityWriterError("authority_writer_stress_fraction_invalid") from exc
        if isinstance(self.target_stress_loss_fraction, bool) or not 0.0 < fraction <= 1.0:
            raise AuthorityWriterError("authority_writer_stress_fraction_invalid")


@dataclass(frozen=True)
class AuthorityWriterResult:
    schema_version: int
    status: str
    generated_at: str
    run_dir: str
    blockers: tuple[str, ...]
    batch_id: str | None
    authority_hash: str | None
    source_hashes: Mapping[str, str]
    result_hash: str

    @classmethod
    def create(
        cls,
        *,
        status: str,
        generated_at: str,
        run_dir: Path,
        blockers: tuple[str, ...] = (),
        batch_id: str | None = None,
        authority_hash: str | None = None,
        source_hashes: Mapping[str, str] | None = None,
    ) -> "AuthorityWriterResult":
        core = {
            "schema_version": AUTHORITY_WRITER_SCHEMA_VERSION,
            "status": status,
            "generated_at": generated_at,
            "run_dir": str(run_dir),
            "blockers": tuple(blockers),
            "batch_id": batch_id,
            "authority_hash": authority_hash,
            "source_hashes": dict(sorted((source_hashes or {}).items())),
        }
        return cls(**core, result_hash=canonical_hash(core))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "generated_at": self.generated_at,
            "run_dir": self.run_dir,
            "blockers": list(self.blockers),
            "batch_id": self.batch_id,
            "authority_hash": self.authority_hash,
            "source_hashes": dict(self.source_hashes),
            "result_hash": self.result_hash,
        }


def _blocked_observation_path(config: AuthorityWriterConfig) -> Path:
    return config.authority_root.parent / "blocked_runtime_observation.json"


def _blocked_observation(
    config: AuthorityWriterConfig,
    blocked: AuthorityWriterBlocked,
    *,
    captured_at: str,
) -> dict[str, Any] | None:
    allowed_dispatch = {
        "dispatch:critical_account_preflight_blocked",
        "dispatch:current_account_snapshot_blocked",
        "dispatch:unmanaged_or_short_position",
        "dispatch:unmanaged_or_duplicate_conditional_order",
        "dispatch:unresolved_regular_open_orders",
    }
    allowed_exact = {
        "account_snapshot_unmanaged_or_short_position",
        "account_snapshot_regular_orders_present",
        "account_snapshot_unmanaged_conditional_order",
    }
    if not blocked.blockers or any(
        value not in allowed_dispatch
        and value not in allowed_exact
        and not value.startswith("preflight:")
        and not value.startswith("account_snapshot:")
        for value in blocked.blockers
    ):
        return None
    values = {}
    hashes = {}
    for name in _SOURCE_FILES:
        values[name], hashes[name] = _read_source(blocked.run_dir / name, name=name)
    projection = values["latest_projection.json"]
    preflight = values["account_preflight.json"]
    dispatch = values["dry_dispatch.json"]
    if (
        projection.get("diagnostics", {}).get("projection_ready") is not True
        or projection.get("decision") is None
        or not all(
            _order_free(values[name])
            for name in (
                "account_preflight.json",
                "dispatch_readiness.json",
                "dry_dispatch.json",
                "latest_projection.json",
            )
        )
        or preflight.get("meta", {}).get("read_only") is not True
        or dispatch.get("diagnostics", {}).get("verdict") != "blocked_dispatch"
    ):
        return None
    observed_at = max(
        aware_datetime(str(value["created_at"]))
        for value in (projection, preflight, dispatch)
    ).isoformat()
    account_observation = _readonly_account_observation(preflight, observed_at)
    core = {
        "schema_version": BLOCKED_RUNTIME_OBSERVATION_SCHEMA_VERSION,
        "artifact_type": "qount_blocked_runtime_observation",
        "created_at": captured_at,
        "observed_at": observed_at,
        "status": "blocked",
        "live_orders_allowed": False,
        "runtime_ledger_created": False,
        "strategy_id": str(
            (projection.get("contract") or {}).get("strategy")
            or (projection.get("decision") or {}).get("strategy")
        ),
        "blockers": list(blocked.blockers),
        "run_id": blocked.run_dir.name,
        "source_hashes": dict(sorted(hashes.items())),
    }
    if account_observation is not None:
        core["account_observation"] = account_observation
    return core | {"observation_hash": canonical_hash(core)}


def _readonly_account_observation(
    preflight: Mapping[str, Any], observed_at: str,
) -> dict[str, Any] | None:
    account = preflight.get("account")
    balance = account.get("balance") if isinstance(account, Mapping) else None
    positions = account.get("nonzero_positions") if isinstance(account, Mapping) else None
    if not isinstance(balance, Mapping) or not isinstance(positions, list):
        return None
    try:
        wallet_balance = float(balance["wallet_balance"])
        available_balance = float(balance["quote_free"])
        margin_balance = float(balance["margin_balance"])
        margin_used = float(balance["quote_used"])
        open_order_count = int(account["open_order_count"])
    except (KeyError, TypeError, ValueError):
        return None
    if min(wallet_balance, available_balance, margin_balance, margin_used) < 0.0 or open_order_count < 0 or available_balance > wallet_balance + 1e-12:
        return None
    readonly_positions = []
    for row in positions:
        if not isinstance(row, Mapping):
            return None
        try:
            symbol, side = str(row["symbol"]), str(row["side"])
            quantity, notional = float(row["contracts"]), float(row["notional_usdt"])
        except (KeyError, TypeError, ValueError):
            return None
        if not symbol or side not in {"long", "short"} or quantity < 0.0 or notional < 0.0:
            return None
        readonly_positions.append({"symbol": symbol, "side": side, "quantity": quantity, "notional": notional})
    readonly_positions.sort(key=lambda row: row["symbol"])
    gross_notional = sum(row["notional"] for row in readonly_positions)
    return {
        "source": "private_account_preflight", "observed_at": observed_at,
        "quote_asset": "USDT", "wallet_balance": wallet_balance,
        "available_balance": available_balance, "margin_balance": margin_balance,
        "margin_used": margin_used, "actual_gross_notional": gross_notional,
        "actual_gross_fraction": gross_notional / wallet_balance if wallet_balance > 0.0 else 0.0,
        "margin_fraction": margin_used / margin_balance if margin_balance > 0.0 else 0.0,
        "open_order_count": open_order_count, "positions": readonly_positions,
    }


def read_blocked_runtime_observation(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value, _ = _read_source(path, name=path.name)
    core = {key: item for key, item in value.items() if key != "observation_hash"}
    if (
        set(value) not in ({
            "schema_version", "artifact_type", "created_at", "observed_at",
            "status", "live_orders_allowed", "runtime_ledger_created",
            "strategy_id", "blockers", "run_id", "source_hashes",
            "observation_hash",
        }, {
            "schema_version", "artifact_type", "created_at", "observed_at",
            "status", "live_orders_allowed", "runtime_ledger_created",
            "strategy_id", "blockers", "run_id", "source_hashes",
            "account_observation", "observation_hash",
        })
        or value.get("schema_version") != BLOCKED_RUNTIME_OBSERVATION_SCHEMA_VERSION
        or value.get("artifact_type") != "qount_blocked_runtime_observation"
        or value.get("status") != "blocked"
        or value.get("live_orders_allowed") is not False
        or value.get("runtime_ledger_created") is not False
        or not isinstance(value.get("strategy_id"), str)
        or not value["strategy_id"]
        or not isinstance(value.get("blockers"), list)
        or not value["blockers"]
        or (
            "account_observation" in value
            and not isinstance(value.get("account_observation"), Mapping)
        )
        or value.get("observation_hash") != canonical_hash(core)
    ):
        raise AuthorityWriterError("blocked_runtime_observation_invalid")
    aware_datetime(str(value["created_at"]))
    aware_datetime(str(value["observed_at"]))
    return value


def _write_blocked_observation(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(_canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


@contextmanager
def _writer_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_source(path: Path, *, name: str) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise AuthorityWriterError(f"authority_source_file_invalid:{name}")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise AuthorityWriterError(f"authority_source_file_mode_invalid:{name}")
    raw = path.read_bytes()
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuthorityWriterError(
                    f"authority_source_duplicate_key:{name}:{key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate)
    except AuthorityWriterError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityWriterError(f"authority_source_json_invalid:{name}") from exc
    if not isinstance(value, dict):
        raise AuthorityWriterError(f"authority_source_must_be_object:{name}")
    return value, hashlib.sha256(raw).hexdigest()


def _resolve_run(source_root: Path) -> Path:
    if not source_root.is_symlink():
        raise AuthorityWriterError("authority_source_selector_must_be_symlink")
    try:
        run_dir = source_root.resolve(strict=True)
    except OSError as exc:
        raise AuthorityWriterError("authority_source_selector_unresolvable") from exc
    runs_root = source_root.parent.joinpath("runs").resolve()
    if run_dir.parent != runs_root or not _RUN_NAME.fullmatch(run_dir.name):
        raise AuthorityWriterError("authority_source_selector_outside_runs")
    if stat.S_IMODE(os.stat(run_dir, follow_symlinks=False).st_mode) != 0o700:
        raise AuthorityWriterError("authority_source_run_directory_mode_invalid")
    return run_dir


def _order_free(value: Mapping[str, Any]) -> bool:
    meta = value.get("meta")
    if not isinstance(meta, Mapping):
        return False
    return not any(
        bool(meta.get(name))
        for name in (
            "orders_allowed",
            "live_orders_allowed",
            "private_api_order_attempted",
            "mutating_account_method_attempted",
        )
    )


def _snapshot_hash_valid(snapshot: Mapping[str, Any]) -> bool:
    core = {
        "contract_hash": snapshot.get("contract_hash"),
        "balance": snapshot.get("balance"),
        "prices": snapshot.get("prices"),
        "positions": snapshot.get("positions"),
        "regular_open_orders": snapshot.get("regular_open_orders"),
        "conditional_open_orders": snapshot.get("conditional_open_orders"),
        "position_mode": snapshot.get("position_mode"),
        "resolved_symbols": snapshot.get("resolved_symbols"),
    }
    return snapshot.get("snapshot_hash") == canonical_hash(core)


def _readiness_hash_valid(readiness: Mapping[str, Any]) -> bool:
    contract = readiness.get("contract") or {}
    request = readiness.get("request") or {}
    signed_request = {
        name: request.get(name)
        for name in (
            "owner_requested_one_month_live",
            "capital_usdt",
            "start_date",
            "duration_days",
        )
    }
    return readiness.get("readiness_hash") == canonical_hash(
        {
            "contract_hash": contract.get("contract_hash"),
            "request": signed_request,
            "evidence": readiness.get("evidence") or {},
            "gates": readiness.get("gates") or {},
            "observations": readiness.get("observations") or {},
        }
    )


def _validate_sources(
    config: AuthorityWriterConfig,
) -> tuple[Path, dict[str, dict[str, Any]], dict[str, str]]:
    run_dir = _resolve_run(config.source_root)
    if not (run_dir / "dispatch_readiness.json").is_file():
        raise AuthorityWriterBlocked(
            ("dispatch_readiness_source_missing",), run_dir=run_dir
        )
    values: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    source_key_by_name = {
        "account_preflight.json": "preflight",
        "dispatch_readiness.json": "readiness",
        "dry_dispatch.json": "dry_dispatch",
        "exchange_rules.json": "exchange_rules",
        "latest_projection.json": "projection",
    }
    for name in _SOURCE_FILES:
        values[name], hashes[source_key_by_name[name]] = _read_source(
            run_dir / name, name=name
        )
    projection = values["latest_projection.json"]
    dispatch = values["dry_dispatch.json"]
    preflight = values["account_preflight.json"]
    readiness = values["dispatch_readiness.json"]
    snapshot = dispatch.get("account_snapshot")
    blockers: list[str] = []
    if not isinstance(snapshot, Mapping):
        blockers.append("account_snapshot_missing")
    elif not _snapshot_hash_valid(snapshot):
        blockers.append("account_snapshot_hash_invalid")
    if not all(
        _order_free(value)
        for value in (projection, dispatch, preflight, readiness)
    ):
        blockers.append("order_capable_source_artifact")
    if isinstance(snapshot, Mapping) and not _order_free(snapshot):
        blockers.append("order_capable_account_snapshot")
    for label, value in (("dispatch_readiness", readiness),):
        if not _readiness_hash_valid(value):
            blockers.append(f"{label}_hash_invalid")
        runtime_preflight = (
            (value.get("runtime_sources") or {}).get("preflight") or {}
        )
        if runtime_preflight.get("sha256") != hashes["preflight"]:
            blockers.append(f"{label}_preflight_source_mismatch")
    projection_diag = projection.get("diagnostics")
    if not isinstance(projection_diag, Mapping) or projection_diag.get("projection_ready") is not True:
        blockers.extend(
            f"projection:{value}"
            for value in tuple((projection_diag or {}).get("blockers") or ("not_ready",))
        )
    if projection.get("decision") is None:
        blockers.append("latest_completed_decision_unavailable")
    dispatch_diag = dispatch.get("diagnostics")
    if not isinstance(dispatch_diag, Mapping) or dispatch_diag.get("dry_evidence_valid") is not True:
        blockers.extend(
            f"dispatch:{value}"
            for value in tuple((dispatch_diag or {}).get("blockers") or ("not_valid",))
        )
    if dispatch.get("decision") is None:
        blockers.append("dry_dispatch_decision_unavailable")
    if not isinstance(preflight.get("diagnostics"), Mapping) or (
        preflight.get("diagnostics", {}).get("verdict") != "account_preflight_pass"
    ):
        blockers.extend(
            f"preflight:{value}"
            for value in tuple(
                (preflight.get("diagnostics") or {}).get("blockers")
                or ("not_passed",)
            )
        )
    if isinstance(snapshot, Mapping):
        snapshot_diag = snapshot.get("diagnostics")
        if not isinstance(snapshot_diag, Mapping) or snapshot_diag.get("verdict") != "account_snapshot_pass":
            blockers.extend(
                f"account_snapshot:{value}"
                for value in tuple(
                    (snapshot_diag or {}).get("blockers") or ("not_passed",)
                )
            )
        for position in snapshot.get("positions") or ():
            if (
                not isinstance(position, Mapping)
                or position.get("data_symbol") not in {"BTCUSDT", "ETHUSDT", "BNBUSDT"}
                or str(position.get("side") or "").lower() != "long"
            ):
                blockers.append("account_snapshot_unmanaged_or_short_position")
        if snapshot.get("regular_open_orders"):
            blockers.append("account_snapshot_regular_orders_present")
        for order in snapshot.get("conditional_open_orders") or ():
            if (
                not isinstance(order, Mapping)
                or order.get("data_symbol") not in {"BTCUSDT", "ETHUSDT", "BNBUSDT"}
                or not str(order.get("client_order_id") or "").startswith(
                    ("qmt-s-", "q-p-")
                )
                or not bool(order.get("close_position") or order.get("reduce_only"))
                or str(order.get("side") or "").lower() != "sell"
            ):
                blockers.append("account_snapshot_unmanaged_conditional_order")
    source_hashes = dispatch.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        blockers.append("dispatch_source_hashes_missing")
    else:
        for key in ("projection", "preflight", "readiness", "exchange_rules"):
            if source_hashes.get(key) != hashes.get(key):
                blockers.append(f"dispatch_source_hash_mismatch:{key}")
    if dispatch.get("readiness_hash") != readiness.get("readiness_hash"):
        blockers.append("dispatch_readiness_contract_mismatch")
    if blockers:
        raise AuthorityWriterBlocked(tuple(dict.fromkeys(blockers)), run_dir=run_dir)
    return run_dir, values, hashes


def _code_hash(repo_root: Path) -> str:
    paths = (
        Path("src/qount/strategies/base.py"),
        Path("src/qount/mini_trend/live_pilot.py"),
        Path("src/qount/mini_trend/pilot_projection.py"),
        Path("src/qount/mini_trend/pilot_dispatcher.py"),
        Path("src/qount/risk/legacy_dispatch.py"),
        Path("src/qount/execution/legacy_dispatch.py"),
    )
    entries: list[dict[str, str]] = []
    for relative in paths:
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            raise AuthorityWriterError(f"authority_code_source_missing:{relative}")
        entries.append({"path": relative.as_posix(), "sha256": _sha256(path)})
    return canonical_hash({"code_sources": entries})


def _float(value: object, *, name: str, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AuthorityWriterError(f"authority_{name}_invalid") from exc
    if not number == number or number in (float("inf"), float("-inf")) or number < minimum:
        raise AuthorityWriterError(f"authority_{name}_invalid")
    return number


def _account_values(snapshot: Mapping[str, Any]) -> tuple[float, float, float, float]:
    balance = snapshot.get("balance")
    if not isinstance(balance, Mapping):
        raise AuthorityWriterError("authority_account_balance_missing")
    wallet = _float(balance.get("wallet_balance"), name="wallet_balance")
    available = _float(balance.get("quote_free"), name="available_balance")
    margin = _float(balance.get("quote_used"), name="margin_used")
    positions = snapshot.get("positions") or ()
    gross = sum(
        _float(row.get("notional_usdt"), name="position_notional")
        for row in positions
        if isinstance(row, Mapping)
    )
    return wallet, available, gross, margin


def _health(
    config: AuthorityWriterConfig,
    *,
    captured_at: str,
    dependencies: HealthProbeDependencies | None,
):
    return collect_os_system_health(
        HealthProbeConfig(
            disk_path=config.dashboard_root,
            service_name=config.service_name,
            allowed_service_names=DEFAULT_ALLOWED_SERVICE_NAMES,
            backup_root=config.backup_root,
            repo_root=config.repo_root,
            state_root=config.repo_root / "state" / "mini_trend",
            operations_enabled=True,
        ),
        observed_at=captured_at,
        captured_at=captured_at,
        dependencies=dependencies,
    )


def _notification_snapshot(
    batch: Any,
    ledger_snapshot: Any,
    health: Any,
    *,
    notification_path: Path,
    captured_at: str,
) -> Any:
    store = NotificationStore(notification_path)
    alerts = list(alerts_from_verified_decision_batch(batch))
    alerts.extend(alerts_from_runtime_ledger_snapshot(ledger_snapshot))
    for row in health.observations:
        observation = SystemHealthObservation.create(
            component=str(row["component"]),
            status=str(row["status"]),
            observed_at=str(row["observed_at"]),
            detail_codes=tuple(row["detail_codes"]),
            source_id=str(row["source_id"]),
            source_hash=str(row["source_hash"]),
            trace_id_value=str(row["observation_id"]),
        )
        alerts.extend(alerts_from_system_health(observation))
    categories = {}
    for alert in alerts:
        categories.setdefault(alert.source_type, []).append(alert)
    scopes = {
        "decision_batch": ("data_quality", "portfolio_allocation", "risk_decision", "execution_plan"),
        "runtime_ledger": ("order_recovery", "accounting_residual"),
        "reconciliation": ("reconciliation",),
        "system": ("system_health",),
    }
    for source_type, category_names in scopes.items():
        scoped = tuple(
            alert
            for alert in categories.get(source_type, ())
            if alert.category in category_names
        )
        synchronize_producer_incidents(
            store,
            scoped,
            source_type=source_type,
            categories=category_names,
            observed_at=captured_at,
        )
    return build_notification_snapshot(store, captured_at=captured_at)


def _notification_path(config: AuthorityWriterConfig) -> Path:
    return (
        config.notification_store_path
        if config.notification_store_path is not None
        else config.runtime_root / "notifications.sqlite3"
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(_canonical_bytes(value))
    os.chmod(path, 0o600)


def _replace_authority(authority_root: Path, staged: Path) -> None:
    parent = authority_root.parent
    previous: Path | None = None
    if authority_root.exists() or authority_root.is_symlink():
        if authority_root.is_symlink() or not authority_root.is_dir():
            raise AuthorityWriterError("authority_root_existing_path_invalid")
        previous = parent / f".{authority_root.name}.previous-{os.getpid()}"
        os.rename(authority_root, previous)
    try:
        os.rename(staged, authority_root)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if authority_root.exists() and authority_root.is_dir():
            shutil.rmtree(authority_root)
        if previous is not None and previous.exists():
            os.rename(previous, authority_root)
        raise
    if previous is not None and previous.exists():
        shutil.rmtree(previous)


def _publish_complete_bundle(
    config: AuthorityWriterConfig,
    *,
    batch: Any,
    registry: StrategyRegistry,
    ledger_snapshot: Any,
    health: Any,
    notification: Any,
    brief: Any,
) -> str:
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{config.authority_root.name}-",
            dir=config.authority_root.parent,
        )
    )
    os.chmod(stage, 0o700)
    try:
        batch_path = stage / "decision_batch" / batch.manifest.batch_id
        publish_decision_batch(
            batch_path,
            snapshot=batch.snapshot,
            intents=batch.intents,
            target=batch.target,
            risk=batch.risk,
            plan=batch.plan,
            created_at=batch.manifest.created_at,
        )
        os.chmod(batch_path.parent, 0o700)
        write_immutable_artifact(stage / "strategy_registry.json", registry)
        for name, value in (
            ("runtime_ledger_snapshot.json", ledger_snapshot.as_dict()),
            ("notification_snapshot.json", notification.as_dict()),
            ("system_health_snapshot.json", health.as_dict()),
            ("daily_brief.json", brief.as_dict()),
        ):
            _write_json(stage / name, value)
        bundle = read_vps_authority_bundle(stage)
        authority_hash = canonical_hash(
            {
                "batch": bundle.batch.manifest.manifest_hash,
                "registry": bundle.registry.registry_hash,
                "ledger": bundle.ledger_snapshot.snapshot_hash,
                "notification": bundle.notification_snapshot.snapshot_hash,
                "health": bundle.system_health.snapshot_hash,
                "brief": bundle.daily_brief.brief_hash,
            }
        )
        _replace_authority(config.authority_root, stage)
        stage = None  # type: ignore[assignment]
        return authority_hash
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)


def write_order_free_authority_bundle(
    config: AuthorityWriterConfig,
    *,
    captured_at: str,
    health_dependencies: HealthProbeDependencies | None = None,
) -> AuthorityWriterResult:
    """Translate one complete order-free run into an immutable authority bundle."""

    config.validate()
    captured_at = aware_datetime(captured_at).isoformat()
    try:
        run_dir, sources, source_hashes = _validate_sources(config)
    except AuthorityWriterBlocked as exc:
        observation = _blocked_observation(
            config, exc, captured_at=captured_at
        )
        if observation is not None:
            _write_blocked_observation(
                _blocked_observation_path(config), observation
            )
            return AuthorityWriterResult.create(
                status="blocked_observation_written",
                generated_at=captured_at,
                run_dir=exc.run_dir,
                blockers=exc.blockers,
                authority_hash=str(observation["observation_hash"]),
                source_hashes=observation["source_hashes"],
            )
        return AuthorityWriterResult.create(
            status="blocked",
            generated_at=captured_at,
            run_dir=exc.run_dir,
            blockers=exc.blockers,
        )

    dispatch = sources["dry_dispatch.json"]
    projection = sources["latest_projection.json"]
    snapshot = dispatch["account_snapshot"]
    wallet, available, gross, margin = _account_values(snapshot)
    config.runtime_root.mkdir(parents=True, exist_ok=True)
    os.chmod(config.runtime_root, 0o700)
    config.authority_root.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(config.authority_root.parent, 0o700)

    with _writer_lock(config.lock_path):
        ledger = RuntimeLedger(config.runtime_root / "runtime.sqlite3")
        try:
            batch = build_verified_legacy_dispatch_batch(
                projection,
                dispatch,
                projection_evidence_hash=source_hashes["projection"],
                target_stress_loss_fraction=config.target_stress_loss_fraction,
                created_at=str(dispatch["created_at"]),
            )
            code_hash = _code_hash(config.repo_root)
            config_hash = canonical_hash(
                {
                    "live_pilot_contract_hash": projection["contract"][
                        "live_pilot_contract_hash"
                    ],
                    "strategy_version": BASE_STRATEGY_VERSION,
                    "target_stress_loss_fraction": config.target_stress_loss_fraction,
                    "maximum_gross": 1.0,
                }
            )
            previous_entry = None
            if config.authority_root.is_dir() and not config.authority_root.is_symlink():
                try:
                    previous_bundle = read_vps_authority_bundle(config.authority_root)
                    previous_entries = tuple(
                        entry
                        for entry in previous_bundle.registry.entries
                        if entry.strategy_id == LIVE_PILOT_CONTRACT.strategy
                    )
                    if len(previous_entries) == 1:
                        previous_entry = previous_entries[0]
                except (OSError, TypeError, ValueError):
                    previous_entry = None
            preserve_minimal_live = bool(
                previous_entry is not None
                and previous_entry.promotion_status == "minimal_live"
                and previous_entry.strategy_contract_hash == LIVE_PILOT_CONTRACT.contract_hash
                and previous_entry.code_hash == code_hash
                and previous_entry.config_hash == config_hash
            )
            registry_entry = base_strategy_registration(
                promotion_status=("minimal_live" if preserve_minimal_live else "research"),
                code_hash=code_hash,
                config_hash=config_hash,
                promotion_artifact_hash=(
                    previous_entry.promotion_artifact_hash
                    if preserve_minimal_live and previous_entry is not None
                    else None
                ),
                owner_authorization_hash=(
                    previous_entry.owner_authorization_hash
                    if preserve_minimal_live and previous_entry is not None
                    else None
                ),
                maximum_stress_loss_fraction=config.target_stress_loss_fraction,
                maximum_gross=1.0,
                registered_at=batch.manifest.created_at,
                supersedes_entry_id=(
                    previous_entry.registry_entry_id
                    if preserve_minimal_live and previous_entry is not None
                    else None
                ),
            )
            registry = StrategyRegistry.create(
                (registry_entry,), created_at=batch.manifest.created_at
            )
            ledger.record_verified_batch(batch, recorded_at=batch.manifest.created_at)
            exchange_positions = {symbol: 0.0 for symbol in TOP3}
            average_costs = {symbol: 0.0 for symbol in TOP3}
            for row in snapshot.get("positions") or ():
                symbol = str(row["data_symbol"])
                exchange_positions[symbol] += _float(
                    row.get("contracts"), name=f"{symbol}_contracts"
                )
                average_costs[symbol] = _float(
                    row.get("average_cost"), name=f"{symbol}_average_cost"
                )
            for symbol in TOP3:
                quantity = exchange_positions[symbol]
                average_cost = average_costs[symbol]
                if quantity > 0.0 and average_cost <= 0.0:
                    raise AuthorityWriterError(
                        f"authority_position_average_cost_missing:{symbol}"
                    )
                ledger.record_position_snapshot(
                    symbol=symbol,
                    quantity=quantity,
                    average_cost=average_cost if quantity > 0.0 else 0.0,
                    realized_trading_pnl=0.0,
                    occurred_at=str(snapshot["created_at"]),
                    source_hash=source_hashes["dry_dispatch"],
                )
            ledger.record_account_observation(
                batch_id=batch.manifest.batch_id,
                observed_at=str(snapshot["created_at"]),
                quote_asset="USDT",
                wallet_balance=wallet,
                available_balance=available,
                actual_gross_notional=gross,
                margin_used=margin,
                source_id=canonical_hash({"account_snapshot": snapshot["snapshot_hash"]}),
                source_hash=source_hashes["dry_dispatch"],
            )
            equity = _float(
                (snapshot.get("balance") or {}).get("margin_balance"),
                name="margin_balance",
            )
            previous_nav = ledger.latest_nav_mark()
            if previous_nav is not None and previous_nav.marked_at == str(
                snapshot["created_at"]
            ):
                nav = previous_nav
            else:
                nav = ledger.record_nav_mark(
                    marked_at=str(snapshot["created_at"]),
                    opening_equity=wallet if previous_nav is None else None,
                    equity=equity,
                    trading_pnl=(
                        0.0 if previous_nav is None else equity - previous_nav.equity
                    ),
                    residual_tolerance=0.001,
                    source_hash=source_hashes["dry_dispatch"],
                )
            reconciliation = reconcile_three_way(
                batch_id=batch.manifest.batch_id,
                reconciled_at=str(dispatch["created_at"]),
                phase="pre_dispatch",
                target_positions=ledger.position_quantities(),
                ledger_positions=ledger.position_quantities(),
                exchange_positions=exchange_positions,
                position_tolerances=dict(batch.plan.reconciliation_tolerance),
                ledger_open_order_ids=ledger.open_order_ids(),
                exchange_open_order_ids=tuple(
                    sorted(
                        str(row.get("client_order_id"))
                        for row in snapshot.get("conditional_open_orders") or ()
                        if str(row.get("client_order_id") or "").startswith("q-p-")
                    )
                ),
                equity_residual=nav.residual,
                equity_residual_tolerance=nav.residual_tolerance,
            )
            ledger.record_reconciliation(reconciliation)
            ledger_snapshot = build_runtime_ledger_snapshot(
                ledger, batch, captured_at=captured_at
            )
            health = _health(
                config,
                captured_at=captured_at,
                dependencies=health_dependencies,
            )
            notification = _notification_snapshot(
                batch,
                ledger_snapshot,
                health,
                notification_path=_notification_path(config),
                captured_at=captured_at,
            )
            brief = build_daily_brief(
                batch,
                registry,
                ledger_snapshot,
                notification,
                generated_at=captured_at,
            )
            authority_hash = _publish_complete_bundle(
                config,
                batch=batch,
                registry=registry,
                ledger_snapshot=ledger_snapshot,
                health=health,
                notification=notification,
                brief=brief,
            )
            blocked_path = _blocked_observation_path(config)
            if blocked_path.exists() and not blocked_path.is_symlink():
                blocked_path.unlink()
            return AuthorityWriterResult.create(
                status="written",
                generated_at=captured_at,
                run_dir=run_dir,
                batch_id=batch.manifest.batch_id,
                authority_hash=authority_hash,
                source_hashes=source_hashes,
            )
        except (AuthorityWriterBlocked, AuthorityWriterError):
            raise
        except (OSError, TypeError, ValueError, KeyError) as exc:
            raise AuthorityWriterError(
                f"authority_writer_failed:{type(exc).__name__}:{exc}"
            ) from exc


def refresh_authority_bundle_from_runtime(
    config: AuthorityWriterConfig,
    *,
    captured_at: str,
    health_dependencies: HealthProbeDependencies | None = None,
) -> AuthorityWriterResult:
    """Republish a current batch after its standard runtime ledger changed."""

    config.validate()
    captured_at = aware_datetime(captured_at).isoformat()
    run_dir = _resolve_run(config.source_root)
    config.authority_root.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(config.authority_root.parent, 0o700)
    config.runtime_root.mkdir(parents=True, exist_ok=True)
    os.chmod(config.runtime_root, 0o700)
    with _writer_lock(config.lock_path):
        current = read_vps_authority_bundle(config.authority_root)
        ledger = RuntimeLedger(config.runtime_root / "runtime.sqlite3")
        ledger_snapshot = build_runtime_ledger_snapshot(
            ledger,
            current.batch,
            captured_at=captured_at,
        )
        registry = current.registry
        reconciliation = ledger_snapshot.reconciliation
        should_halt = bool(
            ledger_snapshot.unresolved_order_ids
            or reconciliation.get("halt_required")
            or reconciliation.get("passed") is not True
        )
        if should_halt:
            entries: list[StrategyRegistration] = []
            for entry in current.registry.entries:
                if entry.promotion_status == "halted":
                    entries.append(entry)
                    continue
                entries.append(
                    StrategyRegistration.create(
                        strategy_id=entry.strategy_id,
                        strategy_version=entry.strategy_version,
                        strategy_kind=entry.strategy_kind,
                        promotion_status="halted",
                        strategy_contract_hash=entry.strategy_contract_hash,
                        code_hash=entry.code_hash,
                        config_hash=entry.config_hash,
                        promotion_artifact_hash=entry.promotion_artifact_hash,
                        owner_authorization_hash=entry.owner_authorization_hash,
                        maximum_stress_loss_fraction=0.0,
                        maximum_gross=0.0,
                        registered_at=captured_at,
                        supersedes_entry_id=entry.registry_entry_id,
                        halted_from_status=entry.promotion_status,
                    )
                )
            registry = StrategyRegistry.create(
                tuple(entries), created_at=captured_at
            )
        health = _health(
            config,
            captured_at=captured_at,
            dependencies=health_dependencies,
        )
        notification = _notification_snapshot(
            current.batch,
            ledger_snapshot,
            health,
            notification_path=_notification_path(config),
            captured_at=captured_at,
        )
        brief = build_daily_brief(
            current.batch,
            registry,
            ledger_snapshot,
            notification,
            generated_at=captured_at,
        )
        authority_hash = _publish_complete_bundle(
            config,
            batch=current.batch,
            registry=registry,
            ledger_snapshot=ledger_snapshot,
            health=health,
            notification=notification,
            brief=brief,
        )
        return AuthorityWriterResult.create(
            status="written",
            generated_at=captured_at,
            run_dir=run_dir,
            batch_id=current.batch.manifest.batch_id,
            authority_hash=authority_hash,
            source_hashes={
                "runtime_ledger_snapshot": ledger_snapshot.snapshot_hash,
                "notification_snapshot": notification.snapshot_hash,
                "system_health_snapshot": health.snapshot_hash,
                "daily_brief": brief.brief_hash,
                "strategy_registry": registry.registry_hash,
            },
        )


def authorize_minimal_live_authority_bundle(
    config: AuthorityWriterConfig,
    *,
    arm: Mapping[str, Any],
    arm_artifact_hash: str,
    captured_at: str,
    health_dependencies: HealthProbeDependencies | None = None,
) -> AuthorityWriterResult:
    """Atomically bind one manual arm to a minimal-live registry entry."""

    config.validate()
    captured_at = aware_datetime(captured_at).isoformat()
    run_dir = _resolve_run(config.source_root)
    if (
        arm.get("status") != "armed"
        or arm.get("capital_usdt") != LIVE_PILOT_CONTRACT.canary_capital_usdt
    ):
        raise AuthorityWriterError("minimal_live_arm_contract_invalid")
    owner_hash = arm.get("owner_authorization_hash")
    authority_batch_id = arm.get("authority_batch_id")
    ledger_snapshot_hash = arm.get("runtime_ledger_snapshot_hash")
    reconciliation_hash = arm.get("pre_dispatch_reconciliation_hash")
    for value, name in (
        (arm_artifact_hash, "arm_artifact_hash"),
        (owner_hash, "owner_authorization_hash"),
        (authority_batch_id, "authority_batch_id"),
        (ledger_snapshot_hash, "runtime_ledger_snapshot_hash"),
        (reconciliation_hash, "pre_dispatch_reconciliation_hash"),
    ):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise AuthorityWriterError(f"minimal_live_{name}_invalid")
    if owner_hash != manual_arm_owner_authorization_hash(arm):
        raise AuthorityWriterError("minimal_live_owner_authorization_hash_mismatch")
    if (
        arm.get("contract_hash") != LIVE_PILOT_CONTRACT.contract_hash
        or arm.get("governance_override", {}).get("scope")
        != "owner_authorized_100_usdt_canary"
    ):
        raise AuthorityWriterError("minimal_live_arm_scope_invalid")
    config.authority_root.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(config.authority_root.parent, 0o700)
    config.runtime_root.mkdir(parents=True, exist_ok=True)
    os.chmod(config.runtime_root, 0o700)
    with _writer_lock(config.lock_path):
        current = read_vps_authority_bundle(config.authority_root)
        if (
            current.batch.manifest.batch_id != authority_batch_id
            or current.ledger_snapshot.snapshot_hash != ledger_snapshot_hash
            or current.ledger_snapshot.reconciliation.get("report_hash")
            != reconciliation_hash
            or current.ledger_snapshot.reconciliation.get("phase") != "pre_dispatch"
            or current.ledger_snapshot.reconciliation.get("passed") is not True
            or current.ledger_snapshot.unresolved_order_ids
        ):
            raise AuthorityWriterError("minimal_live_authority_drift")
        entries = tuple(
            entry
            for entry in current.registry.entries
            if entry.strategy_id == LIVE_PILOT_CONTRACT.strategy
        )
        if len(entries) != 1:
            raise AuthorityWriterError("minimal_live_registry_entry_missing")
        previous = entries[0]
        promoted = StrategyRegistration.create(
            strategy_id=previous.strategy_id,
            strategy_version=previous.strategy_version,
            strategy_kind=previous.strategy_kind,
            promotion_status="minimal_live",
            strategy_contract_hash=previous.strategy_contract_hash,
            code_hash=previous.code_hash,
            config_hash=previous.config_hash,
            promotion_artifact_hash=arm_artifact_hash,
            owner_authorization_hash=str(owner_hash),
            maximum_stress_loss_fraction=previous.maximum_stress_loss_fraction,
            maximum_gross=previous.maximum_gross,
            registered_at=captured_at,
            supersedes_entry_id=previous.registry_entry_id,
        )
        registry = StrategyRegistry.create((promoted,), created_at=captured_at)
        # The arm binds the exact pre-dispatch snapshot hash. Registry promotion
        # must not silently recapture the ledger and invalidate that binding.
        ledger_snapshot = current.ledger_snapshot
        health = _health(
            config,
            captured_at=captured_at,
            dependencies=health_dependencies,
        )
        notification = _notification_snapshot(
            current.batch,
            ledger_snapshot,
            health,
            notification_path=_notification_path(config),
            captured_at=captured_at,
        )
        brief = build_daily_brief(
            current.batch,
            registry,
            ledger_snapshot,
            notification,
            generated_at=captured_at,
        )
        authority_hash = _publish_complete_bundle(
            config,
            batch=current.batch,
            registry=registry,
            ledger_snapshot=ledger_snapshot,
            health=health,
            notification=notification,
            brief=brief,
        )
        return AuthorityWriterResult.create(
            status="written",
            generated_at=captured_at,
            run_dir=run_dir,
            batch_id=current.batch.manifest.batch_id,
            authority_hash=authority_hash,
            source_hashes={
                "manual_arm": arm_artifact_hash,
                "runtime_ledger_snapshot": ledger_snapshot.snapshot_hash,
                "strategy_registry": registry.registry_hash,
            },
        )


__all__ = [
    "AUTHORITY_WRITER_SCHEMA_VERSION",
    "BLOCKED_RUNTIME_OBSERVATION_SCHEMA_VERSION",
    "AuthorityWriterBlocked",
    "AuthorityWriterConfig",
    "AuthorityWriterError",
    "AuthorityWriterResult",
    "authorize_minimal_live_authority_bundle",
    "refresh_authority_bundle_from_runtime",
    "read_blocked_runtime_observation",
    "write_order_free_authority_bundle",
]
