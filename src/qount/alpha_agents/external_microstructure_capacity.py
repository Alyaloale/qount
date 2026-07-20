from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings


EXTERNAL_MICROSTRUCTURE_CAPACITY_VERSION = "alpha_agent_external_microstructure_capacity_v0.1"
TARDIS_EXCHANGE_URL = "https://api.tardis.dev/v1/exchanges/binance-futures"
TARDIS_FEED_URL = "https://api.tardis.dev/v1/data-feeds/binance-futures"
FetchResponse = Callable[[str], tuple[int, dict[str, str], bytes]]


@dataclass(frozen=True)
class ExternalMicrostructureCapacityConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    sample_start: str = "2024-01-01T00:00:00Z"
    sample_end: str = "2024-01-01T00:01:00Z"
    horizon_end: str = "2024-01-02T00:00:00Z"
    l2_sample_symbol: str = "BTCUSDT"
    maximum_source_cache_budget_bytes: int = 32 * 1024**3
    request_retries: int = 3
    request_timeout_seconds: float = 60.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decode_response_body(raw: bytes, headers: dict[str, str]) -> bytes:
    if headers.get("content-encoding", "").lower() == "gzip":
        return gzip.decompress(raw)
    return raw


def _default_fetch(url: str, *, timeout_seconds: float, retries: int) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "qount-external-capacity/0.1",
            "Accept-Encoding": "gzip",
        },
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                headers = {key.lower(): value for key, value in response.headers.items()}
                return response.status, headers, _decode_response_body(response.read(), headers)
        except urllib.error.HTTPError as exc:
            headers = {key.lower(): value for key, value in exc.headers.items()}
            return exc.code, headers, _decode_response_body(exc.read(), headers)
        except (OSError, TimeoutError, urllib.error.URLError):
            if attempt >= retries:
                raise
            time.sleep(0.25 * (2**attempt))
    raise AssertionError("unreachable")


def _feed_url(*, start: str, end: str, channel: str, symbols: tuple[str, ...]) -> str:
    filters = json.dumps(
        [{"channel": channel, "symbols": [symbol.lower() for symbol in symbols]}],
        separators=(",", ":"),
    )
    return f"{TARDIS_FEED_URL}?{urllib.parse.urlencode({'from': start, 'to': end, 'filters': filters})}"


def _parse_timestamp(raw: str) -> dt.datetime:
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    return dt.datetime.fromisoformat(normalized)


def _returned_slice_minutes(probe: dict[str, Any]) -> int:
    try:
        return int(probe.get("x_slice_size") or 0)
    except (TypeError, ValueError):
        return 0


def parse_tardis_raw_feed(raw: bytes) -> dict[str, Any]:
    event_counts: dict[str, int] = {}
    symbol_counts: dict[str, int] = {}
    first_receive_time: str | None = None
    last_receive_time: str | None = None
    depth_previous_u: dict[str, int] = {}
    depth_sequence_break_count = 0
    invalid_line_count = 0
    parsed_count = 0
    for line in raw.decode("utf-8").splitlines():
        try:
            receive_time, json_text = line.split(" ", 1)
            payload = json.loads(json_text)
            data = payload["data"]
            event = str(data["e"])
            symbol = str(data.get("s") or data.get("o", {}).get("s") or "").upper()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            invalid_line_count += 1
            continue
        parsed_count += 1
        first_receive_time = first_receive_time or receive_time
        last_receive_time = receive_time
        event_counts[event] = event_counts.get(event, 0) + 1
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        if event == "depthUpdate":
            previous_u = depth_previous_u.get(symbol)
            pu = int(data["pu"])
            if previous_u is not None and pu != previous_u:
                depth_sequence_break_count += 1
            depth_previous_u[symbol] = int(data["u"])
    duration_seconds = 0.0
    if first_receive_time and last_receive_time:
        duration_seconds = max(
            0.0,
            (_parse_timestamp(last_receive_time) - _parse_timestamp(first_receive_time)).total_seconds(),
        )
    return {
        "raw_bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "line_count": len(raw.splitlines()),
        "parsed_event_count": parsed_count,
        "invalid_line_count": invalid_line_count,
        "first_receive_time": first_receive_time,
        "last_receive_time": last_receive_time,
        "observed_duration_seconds": duration_seconds,
        "event_counts": event_counts,
        "symbol_counts": symbol_counts,
        "depth_sequence_break_count": depth_sequence_break_count,
    }


def _probe_metadata(config: ExternalMicrostructureCapacityConfig, fetch: FetchResponse) -> dict[str, Any]:
    status, headers, raw = fetch(TARDIS_EXCHANGE_URL)
    result: dict[str, Any] = {
        "probe_id": "tardis_binance_futures_metadata",
        "url": TARDIS_EXCHANGE_URL,
        "http_status": status,
        "response_bytes": len(raw),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "available": False,
    }
    try:
        payload = json.loads(raw)
        symbols = {
            str(row["id"]).upper(): row
            for row in payload.get("datasets", {}).get("symbols", [])
            if isinstance(row, dict) and row.get("id")
        }
        by_symbol = {}
        for symbol in config.symbols:
            row = symbols.get(symbol, {})
            data_types = list(row.get("dataTypes", []))
            by_symbol[symbol] = {
                "available_since": row.get("availableSince"),
                "available_to": row.get("availableTo"),
                "data_types": data_types,
                "incremental_l2_available": "incremental_book_L2" in data_types,
                "liquidations_available": "liquidations" in data_types,
            }
        complete = status == 200 and all(
            row["incremental_l2_available"] and row["liquidations_available"]
            for row in by_symbol.values()
        )
        result.update(
            {
                "available": complete,
                "exchange_id": payload.get("id"),
                "exchange_name": payload.get("name"),
                "exported_from": payload.get("datasets", {}).get("exportedFrom"),
                "exported_until": payload.get("datasets", {}).get("exportedUntil"),
                "formats": payload.get("datasets", {}).get("formats"),
                "by_symbol": by_symbol,
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _probe_feed(
    *,
    probe_id: str,
    start: str,
    end: str,
    channel: str,
    symbols: tuple[str, ...],
    fetch: FetchResponse,
) -> dict[str, Any]:
    url = _feed_url(start=start, end=end, channel=channel, symbols=symbols)
    status, headers, raw = fetch(url)
    parsed = parse_tardis_raw_feed(raw) if status == 200 else {
        "raw_bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "line_count": 0,
        "parsed_event_count": 0,
        "invalid_line_count": 0,
        "observed_duration_seconds": 0.0,
        "event_counts": {},
        "symbol_counts": {},
        "depth_sequence_break_count": 0,
    }
    requested_seconds = (_parse_timestamp(end) - _parse_timestamp(start)).total_seconds()
    return {
        "probe_id": probe_id,
        "url": url,
        "channel": channel,
        "symbols": list(symbols),
        "http_status": status,
        "x_slice_size": headers.get("x-slice-size"),
        "x_suggested_slice_size": headers.get("x-suggested-slice-size"),
        "x_name": headers.get("x-name"),
        "requested_duration_seconds": requested_seconds,
        "available": status == 200 and parsed["parsed_event_count"] > 0,
        **parsed,
    }


def build_external_microstructure_capacity(
    config: ExternalMicrostructureCapacityConfig = ExternalMicrostructureCapacityConfig(),
    *,
    fetch: FetchResponse | None = None,
) -> dict[str, Any]:
    if set(config.symbols) != {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"}:
        raise ValueError("external microstructure audit requires frozen BTC/ETH/BNB/SOL")
    if config.l2_sample_symbol not in config.symbols:
        raise ValueError("L2 sample symbol must be in the frozen universe")
    if config.maximum_source_cache_budget_bytes <= 0:
        raise ValueError("source cache budget must be positive")
    actual_fetch = fetch or (
        lambda url: _default_fetch(
            url,
            timeout_seconds=config.request_timeout_seconds,
            retries=config.request_retries,
        )
    )
    metadata = _probe_metadata(config, actual_fetch)
    l2_sample = _probe_feed(
        probe_id="tardis_btc_l2_one_minute",
        start=config.sample_start,
        end=config.sample_end,
        channel="depth",
        symbols=(config.l2_sample_symbol,),
        fetch=actual_fetch,
    )
    liquidation_sample = _probe_feed(
        probe_id="tardis_four_symbol_liquidation_one_minute",
        start=config.sample_start,
        end=config.sample_end,
        channel="forceOrder",
        symbols=config.symbols,
        fetch=actual_fetch,
    )
    liquidation_horizon = _probe_feed(
        probe_id="tardis_four_symbol_liquidation_requested_day",
        start=config.sample_start,
        end=config.horizon_end,
        channel="forceOrder",
        symbols=config.symbols,
        fetch=actual_fetch,
    )
    probes = [metadata, l2_sample, liquidation_sample, liquidation_horizon]
    l2_semantics_pass = bool(
        l2_sample["available"]
        and l2_sample["event_counts"].get("depthUpdate", 0) > 0
        and l2_sample["invalid_line_count"] == 0
        and l2_sample["depth_sequence_break_count"] == 0
    )
    liquidation_semantics_pass = bool(
        liquidation_sample["available"]
        and liquidation_sample["event_counts"].get("forceOrder", 0) > 0
        and liquidation_sample["invalid_line_count"] == 0
    )
    anonymous_full_horizon_access = bool(
        liquidation_horizon["available"]
        and _returned_slice_minutes(liquidation_horizon) * 60
        >= liquidation_horizon["requested_duration_seconds"]
    )
    l2_raw_bytes_per_day_estimate = int(l2_sample["raw_bytes"] * 24 * 60)
    l2_raw_bytes_90d_estimate = l2_raw_bytes_per_day_estimate * 90
    l2_within_budget = l2_raw_bytes_90d_estimate <= config.maximum_source_cache_budget_bytes
    blockers: list[str] = []
    if not metadata["available"]:
        blockers.append("provider_metadata_incomplete")
    if not l2_semantics_pass:
        blockers.append("replayable_l2_sample_failed")
    if not liquidation_semantics_pass:
        blockers.append("liquidation_sample_failed")
    if not anonymous_full_horizon_access:
        blockers.append("licensed_full_history_access_not_authorized")
        blockers.append("anonymous_history_truncated_to_sample_slice")
    if not l2_within_budget:
        blockers.append("raw_l2_90d_download_exceeds_local_cache_budget")
    preregistration_allowed = not blockers
    basis = {"config": config.to_dict(), "probes": probes, "blockers": blockers}
    return {
        "schema_version": EXTERNAL_MICROSTRUCTURE_CAPACITY_VERSION,
        "artifact_type": "external_microstructure_source_capacity",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "public_metadata_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "strategy_results_evaluated": False,
            "purchase_or_subscription_performed": False,
            "data_hash": hashlib.sha256(
                json.dumps(basis, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
        "config": config.to_dict(),
        "source_references": [
            "https://api.tardis.dev/v1/exchanges/binance-futures",
            "https://docs.tardis.dev/api/http#data-feeds-exchange",
            "https://docs.tardis.dev/historical-data-details/binance-futures",
            "https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Diff-Book-Depth-Streams",
            "https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Liquidation-Order-Streams",
        ],
        "diagnostics": {
            "verdict": "eligible_g0" if preregistration_allowed else "block_g0_access_capacity",
            "blockers": blockers,
            "provider_metadata_complete": metadata["available"],
            "replayable_l2_sample_pass": l2_semantics_pass,
            "liquidation_sample_pass": liquidation_semantics_pass,
            "anonymous_full_horizon_access": anonymous_full_horizon_access,
            "l2_raw_bytes_per_day_estimate": l2_raw_bytes_per_day_estimate,
            "l2_raw_bytes_90d_estimate": l2_raw_bytes_90d_estimate,
            "l2_within_cache_budget": l2_within_budget,
            "liquidation_preferred_if_access_authorized": bool(
                metadata["available"] and liquidation_semantics_pass
            ),
            "strategy_results_evaluated": False,
            "preregistration_allowed": preregistration_allowed,
            "next_action": (
                "freeze one external microstructure G0 before returns"
                if preregistration_allowed
                else "request explicit owner decision on licensed liquidation-only history or use Mac-only forward collection"
            ),
        },
        "probes": probes,
    }


def write_external_microstructure_capacity_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-external-microstructure-capacity",
        path_key="artifact_path",
        default_filename="alpha_agent_external_microstructure_capacity.json",
        explicit_path=explicit_path,
    )
