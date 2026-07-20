from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.settings import Settings


HISTORICAL_MICROSTRUCTURE_VERSION = "alpha_agent_historical_microstructure_v0.1"
PUBLIC_ARCHIVE_BASE_URL = "https://data.binance.vision/data/futures/um"
FetchBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class HistoricalMicrostructureConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    daily_dates: tuple[str, ...] = ("2024-01-01", "2026-07-10")
    monthly_months: tuple[str, ...] = ("2024-01",)
    datasets: tuple[str, ...] = ("aggTrades", "bookTicker", "bookDepth", "metrics")
    request_retries: int = 3
    request_timeout_seconds: float = 20.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DATASET_CONTRACTS: dict[str, dict[str, Any]] = {
    "aggTrades": {
        "archive_cadences": ["daily", "monthly"],
        "historical_feature_use": "event-time aggregate trade flow and signed-volume features",
        "runtime_parity": "same exchange aggregate-trade source, without local receive time or connection evidence",
        "replaces_live_stream": False,
        "replacement_blockers": ["receive_latency_missing", "connection_gap_evidence_missing"],
    },
    "bookTicker": {
        "archive_cadences": ["daily", "monthly"],
        "historical_feature_use": "best-bid/ask spread and top-of-book state where archive coverage exists",
        "runtime_parity": "archive coverage varies by period and omits local receive/connection timing",
        "replaces_live_stream": False,
        "replacement_blockers": ["coverage_varies_by_period", "receive_latency_missing"],
    },
    "bookDepth": {
        "archive_cadences": ["daily"],
        "historical_feature_use": "percentage-bucket aggregate depth/notional snapshots",
        "runtime_parity": "not Binance diff-depth; rows are timestamp, percentage, depth, notional",
        "replaces_live_stream": False,
        "replacement_blockers": ["no_update_ids", "no_pu_u_sequence", "not_replayable_l2"],
    },
    "metrics": {
        "archive_cadences": ["daily"],
        "historical_feature_use": "5m open-interest and trader/taker-ratio research features",
        "runtime_parity": "historical summary rows, not raw trades or order-book events",
        "replaces_live_stream": False,
        "replacement_blockers": ["summary_only", "no_receive_latency"],
    },
    "forceOrder": {
        "archive_cadences": [],
        "historical_feature_use": "requires another audited history source or forward collection",
        "runtime_parity": "no matching USD-M public archive prefix in the current source contract",
        "replaces_live_stream": False,
        "replacement_blockers": ["official_archive_source_unavailable"],
    },
}


def _validate_config(config: HistoricalMicrostructureConfig) -> None:
    if not config.symbols:
        raise ValueError("at least one symbol is required")
    if not config.datasets:
        raise ValueError("at least one dataset is required")
    unknown = sorted(set(config.datasets) - set(DATASET_CONTRACTS))
    if unknown:
        raise ValueError(f"unsupported datasets: {','.join(unknown)}")
    for raw in config.daily_dates:
        dt.date.fromisoformat(raw)
    for raw in config.monthly_months:
        dt.datetime.strptime(raw, "%Y-%m")
    if config.request_retries < 0:
        raise ValueError("request_retries must be non-negative")
    if config.request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be positive")


def archive_url(*, dataset: str, symbol: str, cadence: str, period: str) -> str:
    if cadence == "daily":
        filename = f"{symbol}-{dataset}-{period}.zip"
    elif cadence == "monthly":
        filename = f"{symbol}-{dataset}-{period}.zip"
    else:
        raise ValueError(f"unsupported cadence: {cadence}")
    return f"{PUBLIC_ARCHIVE_BASE_URL}/{cadence}/{dataset}/{symbol}/{filename}"


def _default_fetch(url: str, *, timeout_seconds: float, retries: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qount-historical-coverage/0.1"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError):
            if attempt >= retries:
                raise
            time.sleep(0.25 * (2**attempt))
    raise AssertionError("unreachable")


def _parse_checksum(payload: bytes, expected_filename: str) -> dict[str, Any]:
    text = payload.decode("utf-8").strip()
    parts = text.split()
    digest = parts[0].lower() if parts else ""
    declared_filename = parts[-1].lstrip("*") if len(parts) >= 2 else ""
    valid_digest = len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)
    return {
        "checksum_sha256": digest if valid_digest else None,
        "checksum_declared_filename": declared_filename or None,
        "checksum_valid": valid_digest and declared_filename == expected_filename,
    }


def _probe_archive(
    *,
    dataset: str,
    symbol: str,
    cadence: str,
    period: str,
    fetch: FetchBytes,
) -> dict[str, Any]:
    url = archive_url(dataset=dataset, symbol=symbol, cadence=cadence, period=period)
    filename = url.rsplit("/", 1)[-1]
    checksum_url = f"{url}.CHECKSUM"
    result: dict[str, Any] = {
        "dataset": dataset,
        "symbol": symbol,
        "cadence": cadence,
        "period": period,
        "archive_url": url,
        "checksum_url": checksum_url,
        "available": False,
        "status": "missing",
        "error": None,
    }
    try:
        checksum = fetch(checksum_url)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            result["status"] = "error"
            result["error"] = f"HTTP {exc.code}"
        return result
    except FileNotFoundError:
        return result
    except Exception as exc:  # pragma: no cover - exercised by live network failures
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    checksum_result = _parse_checksum(checksum, filename)
    result.update(checksum_result)
    result["available"] = bool(checksum_result["checksum_valid"])
    result["status"] = "available" if result["available"] else "invalid_checksum"
    return result


def build_historical_microstructure_coverage(
    config: HistoricalMicrostructureConfig,
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    _validate_config(config)
    actual_fetch = fetch or (
        lambda url: _default_fetch(
            url,
            timeout_seconds=config.request_timeout_seconds,
            retries=config.request_retries,
        )
    )
    probes: list[dict[str, Any]] = []
    contracts: dict[str, dict[str, Any]] = {}
    for dataset in config.datasets:
        contract = dict(DATASET_CONTRACTS[dataset])
        contracts[dataset] = contract
        for cadence in contract["archive_cadences"]:
            periods = config.daily_dates if cadence == "daily" else config.monthly_months
            for symbol in config.symbols:
                for period in periods:
                    probes.append(
                        _probe_archive(
                            dataset=dataset,
                            symbol=symbol,
                            cadence=cadence,
                            period=period,
                            fetch=actual_fetch,
                        )
                    )

    status_counts: dict[str, int] = {}
    by_dataset: dict[str, dict[str, Any]] = {}
    for probe in probes:
        status = str(probe["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        summary = by_dataset.setdefault(
            str(probe["dataset"]),
            {"probe_count": 0, "available_count": 0, "missing_count": 0, "error_count": 0},
        )
        summary["probe_count"] += 1
        if probe["available"]:
            summary["available_count"] += 1
        elif status == "missing":
            summary["missing_count"] += 1
        else:
            summary["error_count"] += 1

    basis = {
        "config": config.to_dict(),
        "contracts": contracts,
        "probes": [
            {key: value for key, value in probe.items() if key not in {"error"} or value is not None}
            for probe in probes
        ],
    }
    data_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    historical_first_eligible = sorted(
        dataset
        for dataset, summary in by_dataset.items()
        if summary["available_count"] > 0 and dataset in {"aggTrades", "bookTicker", "bookDepth", "metrics"}
    )
    return {
        "schema_version": HISTORICAL_MICROSTRUCTURE_VERSION,
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "archive_base_url": PUBLIC_ARCHIVE_BASE_URL,
            "probe_method": "small CHECKSUM sidecar only",
            "data_hash": data_hash,
        },
        "config": config.to_dict(),
        "dataset_contracts": contracts,
        "diagnostics": {
            "probe_count": len(probes),
            "status_counts": status_counts,
            "by_dataset": by_dataset,
            "historical_first_eligible": historical_first_eligible,
            "live_only_or_external_source": ["forceOrder", "replayable_diff_depth", "receive_latency"],
            "verdict": "coverage_mapped" if probes and not status_counts.get("error") else "coverage_incomplete",
            "promotion_note": "Archive availability is source coverage, not alpha or paper/live evidence.",
        },
        "probes": probes,
    }


def write_historical_microstructure_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-historical-microstructure",
        path_key="artifact_path",
        default_filename="alpha_agent_historical_microstructure.json",
        explicit_path=explicit_path,
    )
