"""Safe, read-only validation for Qount environment configuration.

The environment contract is intentionally separate from ``Settings.from_env``.
This module never creates state, connects to a network, or includes configured
values in its return values.  It is safe to use as the first command on a new
host.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tomllib
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = PROJECT_ROOT / "config" / "environment-contract.toml"
SUPPORTED_PROFILES = frozenset({"mac", "wsl", "vps"})


@dataclass(frozen=True)
class EnvironmentVariable:
    """One machine-readable environment-variable contract entry."""

    name: str
    domain: str
    value_type: str
    sensitive: bool
    allowed_hosts: tuple[str, ...]
    required_when: str
    default_policy: str
    consumers: tuple[str, ...]
    legacy: bool


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, EnvironmentVariable]:
    """Load and validate the repository environment-variable contract."""

    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    entries = raw.get("variables")
    if not isinstance(entries, list):
        raise ValueError("environment contract must contain a [[variables]] list")

    required_fields = {
        "name",
        "domain",
        "type",
        "sensitive",
        "allowed_hosts",
        "required_when",
        "default_policy",
        "consumers",
        "legacy",
    }
    result: dict[str, EnvironmentVariable] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("environment contract entries must be tables")
        missing = required_fields.difference(entry)
        if missing:
            raise ValueError(
                "environment contract entry is missing fields: " + ", ".join(sorted(missing))
            )
        name = entry["name"]
        if not isinstance(name, str) or not name:
            raise ValueError("environment contract variable names must be non-empty strings")
        if name in result:
            raise ValueError(f"duplicate environment contract entry: {name}")
        hosts = tuple(str(host) for host in entry["allowed_hosts"])
        unknown_hosts = set(hosts).difference(SUPPORTED_PROFILES)
        if unknown_hosts:
            raise ValueError(f"{name} has unsupported hosts: {', '.join(sorted(unknown_hosts))}")
        result[name] = EnvironmentVariable(
            name=name,
            domain=str(entry["domain"]),
            value_type=str(entry["type"]),
            sensitive=bool(entry["sensitive"]),
            allowed_hosts=hosts,
            required_when=str(entry["required_when"]),
            default_policy=str(entry["default_policy"]),
            consumers=tuple(str(consumer) for consumer in entry["consumers"]),
            legacy=bool(entry["legacy"]),
        )
    return result


def parse_env_file(path: Path) -> dict[str, str]:
    """Read a simple dotenv file without shell evaluation or variable expansion.

    Values are returned only to the caller; validation deliberately reports
    names and categories, never values.  ``export KEY=value`` is accepted so
    that the non-secret WSL topology file can be preflighted too.
    """

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise ValueError(f"invalid environment assignment at {path}:{line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or not name.replace("_", "").isalnum() or not name[0].isalpha():
            raise ValueError(f"invalid environment variable name at {path}:{line_number}")
        values[name] = value.strip().strip('"').strip("'")
    return values


def _is_managed_name(name: str) -> bool:
    return name.startswith("QOUNT_") or name in {
        "BINANCE_API_KEY",
        "BINANCE_SECRET",
        "BINANCE_SECRET_KEY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "OPENAI_API_KEY",
        "TIINGO_API_TOKEN",
        "TUSHARE_TOKEN",
        "LD_LIBRARY_PATH",
    }


def _permission_issue(path: Path) -> bool:
    """Return whether an existing env file is group/world readable or writable."""

    mode = stat.S_IMODE(path.stat().st_mode)
    return bool(mode & (stat.S_IRWXG | stat.S_IRWXO))


def _required_for_profile(variable: EnvironmentVariable, profile: str) -> bool:
    return variable.required_when in {"always", f"profile:{profile}"}


def check_environment(
    *,
    profile: str,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
    contract_path: Path = CONTRACT_PATH,
) -> dict[str, Any]:
    """Return a value-free configuration report suitable for JSON output."""

    if profile not in SUPPORTED_PROFILES:
        raise ValueError(f"unsupported configuration profile: {profile}")
    contract = load_contract(contract_path)
    source = dict(environ if environ is not None else os.environ)
    source_name = "process-environment"
    permission_issues: list[str] = []
    if env_file is not None:
        if not env_file.is_file():
            raise ValueError(f"environment file does not exist: {env_file}")
        source = parse_env_file(env_file)
        source_name = str(env_file)
        # A tracked, value-free template is expected to be world-readable.
        # Enforce 0600 only once the file actually contains a configured secret.
        has_configured_secret = any(
            name in contract and contract[name].sensitive and bool(value.strip())
            for name, value in source.items()
        )
        if has_configured_secret and _permission_issue(env_file):
            permission_issues.append("environment_file_permissions")

    configured = {name for name, value in source.items() if value.strip()}
    managed = {name for name in source if _is_managed_name(name)}
    missing = sorted(
        variable.name
        for variable in contract.values()
        if _required_for_profile(variable, profile) and variable.name not in configured
    )
    unknown = sorted(managed.difference(contract))
    disallowed = sorted(
        name
        for name in configured.intersection(contract)
        if profile not in contract[name].allowed_hosts
    )
    legacy = sorted(name for name in configured.intersection(contract) if contract[name].legacy)
    conflicts: list[str] = []
    if source.get("QOUNT_LIVE_ENABLE", "").strip().lower() in {"1", "true", "yes", "on", "live"}:
        conflicts.append("live_enable_requested")
    for name in (
        "QOUNT_FOMC_LIVE_ENABLE",
        "QOUNT_MINI_TREND_LIVE_ENABLE",
        "QOUNT_X4_LIVE_ENABLE",
        "QOUNT_RV_LIVE_ENABLE",
        "QOUNT_CXD_CARRY_ENABLE",
    ):
        if source.get(name, "").strip().lower() in {"1", "true", "yes", "on", "live"}:
            conflicts.append(f"disabled_strategy_requested:{name}")

    return {
        "ok": not any((missing, unknown, disallowed, permission_issues, conflicts)),
        "profile": profile,
        "source": source_name,
        "missing": missing,
        "unknown": unknown,
        "host_not_allowed": disallowed,
        "unsafe_permissions": permission_issues,
        "mutually_exclusive_or_unsafe": conflicts,
        "legacy_configured": legacy,
        "configured_managed_count": len(managed),
        "contract_variable_count": len(contract),
        "values_redacted": True,
    }
