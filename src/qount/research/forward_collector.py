"""Extensible, research-only forward evidence collector.

The collector owns scheduling-independent evidence storage. Strategy-specific
adapters only collect public inputs or inspect another collector's status; they
do not calculate promotion metrics or access any order path.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import fcntl
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlencode
import urllib.request

from qount.contracts import canonical_hash
from qount.small_account.macro_event_trigger_study import scheduled_events


FORWARD_COLLECTOR_VERSION = "research_forward_collector_v0.1"
SOURCE_CONFIG_VERSION = "research_forward_sources_v0.1"
VALID_STATUSES = frozenset({"valid", "insufficient", "flawed", "rejected"})
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
DEFAULT_BINANCE_BASE_URL = "https://fapi.binance.com"


class ForwardCollectorConfigurationError(ValueError):
    """The collector cannot safely start with the supplied configuration."""


@dataclass(frozen=True)
class PluginResult:
    status: str
    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        if self.status not in VALID_STATUSES:
            raise ForwardCollectorConfigurationError("forward_plugin_status_invalid")
        value = dict(self.payload)
        json.dumps(value, ensure_ascii=True, allow_nan=False)
        return {"status": self.status, "payload": value}


@dataclass(frozen=True)
class CollectionContext:
    observed_at: dt.datetime
    symbols: tuple[str, ...]
    fetch_json: Callable[[str], Any]
    config: Mapping[str, Any]
    fetch_bytes: Callable[[str], bytes] | None = None


class ForwardCollectorPlugin(Protocol):
    name: str

    def collect(self, context: CollectionContext) -> PluginResult:
        """Return one deterministic, JSON-serializable evidence payload."""


class PluginRegistry:
    """Named plugin registry; external adapters can be registered at runtime."""

    def __init__(self) -> None:
        self._plugins: dict[str, ForwardCollectorPlugin] = {}

    def register(self, plugin: ForwardCollectorPlugin) -> None:
        name = str(plugin.name)
        if not name or name in self._plugins:
            raise ForwardCollectorConfigurationError("forward_plugin_name_duplicate")
        self._plugins[name] = plugin

    def resolve(self, names: tuple[str, ...]) -> tuple[ForwardCollectorPlugin, ...]:
        if not names or len(set(names)) != len(names):
            raise ForwardCollectorConfigurationError("forward_plugin_names_invalid")
        missing = [name for name in names if name not in self._plugins]
        if missing:
            raise ForwardCollectorConfigurationError(
                "forward_plugin_not_registered:" + ",".join(missing)
            )
        return tuple(self._plugins[name] for name in names)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))


def _utc_iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _plugin_identity(plugin: ForwardCollectorPlugin) -> dict[str, Any]:
    """Bind the frozen contract to the adapter implementation when available."""

    plugin_type = type(plugin)
    source_path = inspect.getsourcefile(plugin_type)
    source_hash = None
    if source_path:
        source = Path(source_path)
        if source.is_file():
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "module": plugin_type.__module__,
        "qualname": plugin_type.__qualname__,
        "source_path": source_path,
        "source_sha256": source_hash,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path.exists():
            temporary_path.unlink()


def _validate_config(
    state_root: Path,
    symbols: tuple[str, ...],
    plugin_names: tuple[str, ...],
    min_free_disk_bytes: int,
) -> tuple[Path, tuple[str, ...], tuple[str, ...]]:
    root = state_root.expanduser()
    if not root.is_absolute() or root.resolve() == Path("/"):
        raise ForwardCollectorConfigurationError("forward_state_root_must_be_absolute_non_root")
    normalized_symbols = tuple(symbol.upper() for symbol in symbols if symbol)
    if not normalized_symbols or len(set(normalized_symbols)) != len(normalized_symbols):
        raise ForwardCollectorConfigurationError("forward_symbols_invalid")
    normalized_plugins = tuple(name.strip() for name in plugin_names if name.strip())
    if not normalized_plugins or len(set(normalized_plugins)) != len(normalized_plugins):
        raise ForwardCollectorConfigurationError("forward_plugins_invalid")
    if min_free_disk_bytes < 0:
        raise ForwardCollectorConfigurationError("forward_min_free_disk_invalid")
    return root.resolve(), normalized_symbols, normalized_plugins


def _contract_path(root: Path) -> Path:
    return root / "metadata" / "collection-contract.json"


def _status_path(root: Path) -> Path:
    return root / "metadata" / "current.json"


def build_collection_contract(
    *,
    state_root: Path,
    symbols: tuple[str, ...],
    plugin_names: tuple[str, ...],
    plugin_identities: Mapping[str, Mapping[str, Any]] | None = None,
    source_config_hash: str | None = None,
) -> dict[str, Any]:
    core: dict[str, Any] = {
        "schema_version": FORWARD_COLLECTOR_VERSION,
        "artifact_type": "research_forward_collection_contract",
        "symbols": list(symbols),
        "plugins": list(plugin_names),
        "source_config_hash": source_config_hash,
        "plugin_identities": {
            name: dict((plugin_identities or {}).get(name, {})) for name in plugin_names
        },
        "cadence": "systemd_timer_invocation",
        "storage": {
            "format": "append_only_jsonl_with_sha256_chain",
            "records_root": "records/YYYY/MM/DD/cycles.jsonl",
            "status_path": "metadata/current.json",
        },
        "research_guards": {
            "research_only": True,
            "orders_authorized": False,
            "private_api_used": False,
            "pnl_evaluated": False,
            "promotion_evidence": False,
        },
    }
    return core | {
        "state_root_relative": str(state_root),
        "collection_contract_hash": canonical_hash(core),
    }


def write_or_verify_contract(
    state_root: Path,
    symbols: tuple[str, ...],
    plugin_names: tuple[str, ...],
    plugin_identities: Mapping[str, Mapping[str, Any]],
    source_config_hash: str | None = None,
) -> dict[str, Any]:
    desired = build_collection_contract(
        state_root=state_root,
        symbols=symbols,
        plugin_names=plugin_names,
        plugin_identities=plugin_identities,
        source_config_hash=source_config_hash,
    )
    path = _contract_path(state_root)
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="ascii"))
        except (OSError, json.JSONDecodeError) as error:
            raise ForwardCollectorConfigurationError("forward_contract_unreadable") from error
        if current != desired:
            raise ForwardCollectorConfigurationError("forward_contract_mismatch")
        return current
    _atomic_write_json(path, desired)
    current = json.loads(path.read_text(encoding="ascii"))
    if current != desired:
        raise ForwardCollectorConfigurationError("forward_contract_race_or_mismatch")
    return current


def _record_path(root: Path, observed_at: dt.datetime) -> Path:
    date = observed_at.astimezone(dt.UTC)
    return root / "records" / date.strftime("%Y/%m/%d") / "cycles.jsonl"


def _last_record_hash(root: Path, path: Path) -> str | None:
    status_path = _status_path(root)
    if status_path.exists():
        try:
            value = json.loads(status_path.read_text(encoding="ascii"))
            if isinstance(value, dict) and isinstance(value.get("last_record_hash"), str):
                return value["last_record_hash"]
        except (OSError, json.JSONDecodeError):
            pass
    if not path.exists():
        return None
    last: str | None = None
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                last = json.loads(line.decode("ascii"))["record_hash"]
    return last


def _append_record(root: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    observed_at = dt.datetime.fromisoformat(str(record["observed_at_utc"]).replace("Z", "+00:00"))
    path = _record_path(root, observed_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_hash = _last_record_hash(root, path)
    core = dict(record) | {"previous_record_hash": previous_hash}
    core["record_hash"] = hashlib.sha256(_canonical_bytes(core)).hexdigest()
    with path.open("a", encoding="ascii") as handle:
        handle.write(_canonical_bytes(core).decode("ascii") + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _atomic_write_json(
        _status_path(root),
        {
            "schema_version": FORWARD_COLLECTOR_VERSION,
            "status": "running",
            "last_record_hash": core["record_hash"],
            "last_observed_at_utc": core["observed_at_utc"],
            "last_record_path": str(path.relative_to(root)),
        },
    )
    return core


def _default_fetch_json(url: str, *, timeout_seconds: float, use_proxy_env: bool) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "qount-research-forward/0.1"})
    opener = (
        urllib.request.build_opener()
        if use_proxy_env
        else urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )
    with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310 - configured public URL
        return json.loads(response.read().decode("utf-8"))


def _default_fetch_bytes(url: str, *, timeout_seconds: float, use_proxy_env: bool) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qount-research-forward/0.1"})
    opener = (
        urllib.request.build_opener()
        if use_proxy_env
        else urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )
    with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310 - configured public URL
        return response.read()


class BinanceUMPublicPlugin:
    name = "binance_um_public"

    def __init__(self, *, base_url: str = DEFAULT_BINANCE_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def collect(self, context: CollectionContext) -> PluginResult:
        symbols: dict[str, Any] = {}
        errors: list[dict[str, str]] = []
        for symbol in context.symbols:
            item: dict[str, Any] = {}
            requests = {
                "klines": ("/fapi/v1/klines", {"symbol": symbol, "interval": "1d", "limit": 3}),
                "funding": ("/fapi/v1/fundingRate", {"symbol": symbol, "limit": 3}),
                "open_interest": ("/fapi/v1/openInterest", {"symbol": symbol}),
                "premium_index": ("/fapi/v1/premiumIndex", {"symbol": symbol}),
            }
            for kind, (path, params) in requests.items():
                url = f"{self.base_url}{path}?{urlencode(params)}"
                try:
                    item[kind] = context.fetch_json(url)
                except Exception as error:  # public network failures are evidence gaps
                    errors.append({"symbol": symbol, "source": kind, "error": type(error).__name__})
            symbols[symbol] = item
        status = "valid" if symbols and not errors else "insufficient"
        return PluginResult(
            status=status,
            payload={
                "source": "binance_usdm_public_rest",
                "observed_at_utc": _utc_iso(context.observed_at),
                "symbols": symbols,
                "errors": errors,
                "strategy_results_evaluated": False,
            },
        )


class FomcCalendarPlugin:
    name = "fomc_calendar"

    def collect(self, context: CollectionContext) -> PluginResult:
        events = scheduled_events("fomc")
        return PluginResult(
            status="valid" if len(events) == 20 else "insufficient",
            payload={
                "source": "federal_reserve_fomc_calendar_contract",
                "event_count": len(events),
                "events": [event.as_dict() for event in events],
                "strategy_results_evaluated": False,
            },
        )


class LiquidationStatusPlugin:
    name = "liquidation_status"

    def __init__(self, state_root: Path) -> None:
        self.state_root = Path(state_root)

    def collect(self, context: CollectionContext) -> PluginResult:
        path = self.state_root / "metadata" / "current.json"
        if not path.exists():
            return PluginResult("insufficient", {"reason": "liquidation_collector_status_missing"})
        try:
            status = json.loads(path.read_text(encoding="ascii"))
        except (OSError, json.JSONDecodeError):
            return PluginResult("insufficient", {"reason": "liquidation_collector_status_unreadable"})
        return PluginResult(
            "valid",
            {
                "source": "existing_liquidation_cascade_collector_status",
                "status": status,
                "strategy_results_evaluated": False,
            },
        )


def _resolve_source_path(raw_path: str, repo_root: Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else repo_root / path


class LocalArtifactSource:
    """Record the identity of a local historical source without mutating it."""

    def __init__(self, definition: Mapping[str, Any], *, repo_root: Path) -> None:
        self.definition = definition
        self.repo_root = repo_root

    def collect(self, context: CollectionContext) -> PluginResult:
        raw_path = self.definition.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            return PluginResult("flawed", {"reason": "local_source_path_missing"})
        path = _resolve_source_path(raw_path, self.repo_root)
        if not path.is_file():
            return PluginResult(
                "insufficient",
                {"path": str(path), "reason": "local_source_file_missing"},
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = self.definition.get("sha256")
        if expected is not None and digest != expected:
            return PluginResult(
                "flawed",
                {
                    "path": str(path),
                    "sha256": digest,
                    "expected_sha256": expected,
                    "reason": "local_source_sha256_mismatch",
                },
            )
        return PluginResult(
            "valid",
            {
                "path": str(path),
                "sha256": digest,
                "size_bytes": path.stat().st_size,
                "source_role": self.definition.get("role", "historical_input_archive"),
            },
        )


class ConfiguredArchiveSource:
    """Record a public archive contract; large historical archives are not redownloaded every cycle."""

    def __init__(self, definition: Mapping[str, Any]) -> None:
        self.definition = definition

    def collect(self, context: CollectionContext) -> PluginResult:
        base_url = self.definition.get("base_url")
        if not isinstance(base_url, str) or not base_url.startswith("https://"):
            return PluginResult("flawed", {"reason": "archive_source_url_invalid"})
        return PluginResult(
            "valid",
            {
                "base_url": base_url,
                "datasets": list(self.definition.get("datasets", [])),
                "source_role": self.definition.get("role", "historical_input_archive"),
                "network_fetch_per_cycle": False,
            },
        )


class TiingoEodSource:
    """Collect only the latest adjusted-close observation for configured research tickers."""

    def __init__(self, definition: Mapping[str, Any]) -> None:
        self.definition = definition

    def collect(self, context: CollectionContext) -> PluginResult:
        env_name = self.definition.get("api_key_env", "QOUNT_TIINGO_API_KEY")
        api_key = os.environ.get(str(env_name), "").strip()
        symbols = tuple(str(item).upper() for item in self.definition.get("symbols", []))
        if not api_key:
            return PluginResult(
                "insufficient",
                {
                    "symbols": list(symbols),
                    "api_key_env": str(env_name),
                    "reason": "source_credential_unavailable",
                },
            )
        observations: dict[str, Any] = {}
        errors: list[dict[str, str]] = []
        start_date = str(self.definition.get("start_date", "2020-01-01"))
        for symbol in symbols:
            url = (
                f"https://api.tiingo.com/tiingo/daily/{symbol.lower()}/prices"
                f"?startDate={start_date}&format=json&token={api_key}"
            )
            try:
                rows = context.fetch_json(url)
                usable = [
                    row
                    for row in rows
                    if isinstance(row, dict)
                    and isinstance(row.get("date"), str)
                    and isinstance(row.get("adjClose"), (int, float))
                    and float(row["adjClose"]) > 0
                ]
                if not usable:
                    raise ValueError("no_usable_rows")
                latest = usable[-1]
                observations[symbol] = {
                    "latest_date": latest["date"][:10],
                    "latest_adj_close": float(latest["adjClose"]),
                    "row_count": len(usable),
                }
            except Exception as error:
                errors.append({"symbol": symbol, "error": type(error).__name__})
        return PluginResult(
            "valid" if observations and not errors else "insufficient",
            {
                "source": "tiingo_daily_adjusted_close",
                "symbols": list(symbols),
                "observations": observations,
                "errors": errors,
                "api_key_used": True,
            },
        )


class ResearchLinesPlugin:
    """Collect every active research line from one configured source graph."""

    name = "research_lines"

    def __init__(self, source_config: Mapping[str, Any], *, repo_root: Path) -> None:
        self.source_config = source_config
        self.repo_root = repo_root

    def _source(self, definition: Mapping[str, Any], context: CollectionContext) -> PluginResult:
        kind = definition.get("kind")
        if kind == "binance_um_rest":
            base_url = definition.get("base_url", DEFAULT_BINANCE_BASE_URL)
            return BinanceUMPublicPlugin(base_url=str(base_url)).collect(context)
        if kind == "fomc_calendar":
            return FomcCalendarPlugin().collect(context)
        if kind == "liquidation_status":
            return LiquidationStatusPlugin(
                Path(str(definition.get("state_root", "/var/lib/qount/research/liquidation-cascade-v1")))
            ).collect(context)
        if kind == "local_artifact":
            return LocalArtifactSource(definition, repo_root=self.repo_root).collect(context)
        if kind == "public_archive_contract":
            return ConfiguredArchiveSource(definition).collect(context)
        if kind == "tiingo_eod":
            return TiingoEodSource(definition).collect(context)
        return PluginResult("flawed", {"reason": "source_kind_unknown", "kind": kind})

    @staticmethod
    def _aggregate_status(statuses: list[str]) -> str:
        if "rejected" in statuses:
            return "rejected"
        if "flawed" in statuses:
            return "flawed"
        return "valid" if statuses and all(item == "valid" for item in statuses) else "insufficient"

    def collect(self, context: CollectionContext) -> PluginResult:
        definitions = self.source_config.get("sources", {})
        source_results: dict[str, Any] = {}
        for name, definition in definitions.items():
            try:
                result = self._source(definition, context)
                source_results[str(name)] = result.as_dict()
            except Exception as error:
                source_results[str(name)] = PluginResult(
                    "insufficient", {"reason": "source_error", "error": type(error).__name__}
                ).as_dict()
        lines: dict[str, Any] = {}
        for line in self.source_config.get("research_lines", []):
            line_id = str(line["id"])
            required = tuple(str(item) for item in line.get("sources", []))
            statuses = [source_results.get(item, {}).get("status", "insufficient") for item in required]
            source_status = self._aggregate_status(statuses)
            static_data = str(line.get("data_conclusion", "insufficient"))
            if source_status == "flawed":
                data_conclusion = "flawed"
            elif source_status != "valid":
                data_conclusion = "insufficient"
            else:
                data_conclusion = static_data
            lines[line_id] = {
                "status": source_status,
                "source_refs": list(required),
                "mechanism_conclusion": str(line.get("mechanism_conclusion", "insufficient")),
                "data_conclusion": data_conclusion,
                "strategy_return_conclusion": str(
                    line.get("strategy_return_conclusion", "insufficient")
                ),
                "strategy_results_evaluated": False,
            }
        return PluginResult(
            self._aggregate_status([item["status"] for item in source_results.values()]),
            {
                "source_config_hash": self.source_config["source_config_hash"],
                "sources": source_results,
                "research_lines": lines,
                "strategy_results_evaluated": False,
            },
        )


def default_registry(
    *,
    liquidation_state_root: Path,
    source_config: Mapping[str, Any] | None = None,
    repo_root: Path | None = None,
) -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(BinanceUMPublicPlugin())
    registry.register(FomcCalendarPlugin())
    registry.register(LiquidationStatusPlugin(liquidation_state_root))
    if source_config is not None:
        registry.register(ResearchLinesPlugin(source_config, repo_root=repo_root or Path.cwd()))
    return registry


def load_source_config(path: Path, *, repo_root: Path) -> dict[str, Any]:
    """Load and hash the extensible source graph used by the unified collector."""

    try:
        raw = json.loads(path.read_text(encoding="ascii"))
    except (OSError, json.JSONDecodeError) as error:
        raise ForwardCollectorConfigurationError("forward_source_config_unreadable") from error
    if not isinstance(raw, dict) or raw.get("schema_version") != SOURCE_CONFIG_VERSION:
        raise ForwardCollectorConfigurationError("forward_source_config_version_invalid")
    sources = raw.get("sources")
    lines = raw.get("research_lines")
    if not isinstance(sources, dict) or not isinstance(lines, list) or not lines:
        raise ForwardCollectorConfigurationError("forward_source_config_shape_invalid")
    source_names = set(sources)
    line_ids: set[str] = set()
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("id"), str):
            raise ForwardCollectorConfigurationError("forward_source_line_invalid")
        line_id = line["id"]
        if line_id in line_ids or not line.get("sources"):
            raise ForwardCollectorConfigurationError("forward_source_line_duplicate_or_empty")
        line_ids.add(line_id)
        if any(item not in source_names for item in line["sources"]):
            raise ForwardCollectorConfigurationError("forward_source_line_source_missing")
    core = {key: value for key, value in raw.items() if key != "source_config_hash"}
    return core | {"source_config_hash": canonical_hash(core), "path": str(path.resolve()), "repo_root": str(repo_root.resolve())}


def run_once(
    *,
    state_root: Path,
    symbols: tuple[str, ...],
    plugin_names: tuple[str, ...],
    registry: PluginRegistry,
    min_free_disk_bytes: int = 0,
    observed_at: dt.datetime | None = None,
    fetch_json: Callable[[str], Any] | None = None,
    timeout_seconds: float = 20.0,
    use_proxy_env: bool = False,
    source_config_hash: str | None = None,
) -> dict[str, Any]:
    root, symbols, plugin_names = _validate_config(
        state_root, symbols, plugin_names, min_free_disk_bytes
    )
    plugins = registry.resolve(plugin_names)
    plugin_identities = {plugin.name: _plugin_identity(plugin) for plugin in plugins}
    root.mkdir(parents=True, exist_ok=True)
    if min_free_disk_bytes and shutil.disk_usage(root).free < min_free_disk_bytes:
        raise ForwardCollectorConfigurationError("forward_disk_guard_blocked")
    contract = write_or_verify_contract(
        root, symbols, plugin_names, plugin_identities, source_config_hash=source_config_hash
    )
    lock_path = root / "collector.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        observed = observed_at or dt.datetime.now(dt.UTC)
        if observed.tzinfo is None:
            raise ForwardCollectorConfigurationError("forward_observed_at_must_be_timezone_aware")
        fetch = fetch_json or (
            lambda url: _default_fetch_json(
                url, timeout_seconds=timeout_seconds, use_proxy_env=use_proxy_env
            )
        )
        fetch_bytes = lambda url: _default_fetch_bytes(
            url, timeout_seconds=timeout_seconds, use_proxy_env=use_proxy_env
        )
        context = CollectionContext(
            observed_at=observed,
            symbols=symbols,
            fetch_json=fetch,
            config={
                "contract_hash": contract["collection_contract_hash"],
                "source_config_hash": source_config_hash,
            },
            fetch_bytes=fetch_bytes,
        )
        plugin_results: dict[str, Any] = {}
        for plugin in plugins:
            try:
                result = plugin.collect(context)
                plugin_results[plugin.name] = result.as_dict()
            except Exception as error:
                plugin_results[plugin.name] = PluginResult(
                    "insufficient", {"reason": "plugin_error", "error": type(error).__name__}
                ).as_dict()
        record = _append_record(
            root,
            {
                "schema_version": FORWARD_COLLECTOR_VERSION,
                "record_type": "forward_collection_cycle",
                "observed_at_utc": _utc_iso(observed),
                "collection_contract_hash": contract["collection_contract_hash"],
                "plugins": plugin_results,
                "research_only": True,
                "orders_authorized": False,
                "pnl_evaluated": False,
            },
        )
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return record


def read_status(state_root: Path) -> dict[str, Any]:
    path = _status_path(Path(state_root).expanduser().resolve())
    return json.loads(path.read_text(encoding="ascii"))
