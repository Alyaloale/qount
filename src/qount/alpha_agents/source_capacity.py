from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings


SOURCE_CAPACITY_VERSION = "alpha_agent_source_capacity_v0.1"
OPTIONS_DVOL_PREREGISTRATION_VERSION = "alpha_agent_options_dvol_preregistration_v0.3"
DERIBIT_DVOL_URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
BINANCE_UM_ARCHIVE_URL = "https://data.binance.vision/data/futures/um"
FetchBytes = Callable[[str, str, bytes | None], bytes]


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceCapacityConfig:
    deribit_currencies: tuple[str, ...] = ("BTC", "ETH")
    deribit_probe_dates: tuple[str, ...] = ("2021-04-01", "2025-01-01")
    cross_venue_coins: tuple[str, ...] = ("BTC", "ETH", "BNB", "SOL")
    cross_venue_probe_date: str = "2024-01-01"
    binance_symbol: str = "BTCUSDT"
    binance_probe_date: str = "2024-01-01"
    request_retries: int = 3
    request_timeout_seconds: float = 20.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrozenOptionsDvolContract:
    contract_id: str = "eth_btc_dvol_spread_z720_entry2_hold24_cooldown24_reversion_v1"
    source_feature: str = "completed_hour_eth_dvol_close_minus_btc_dvol_close"
    hypothesis: str = (
        "an extreme ETH-versus-BTC options-implied-volatility spread reflects relative hedging "
        "stress and predicts 24-hour BTC-beta-residual mean reversion in liquid alt futures"
    )
    hourly_alignment: str = (
        "use only Deribit DVOL candles whose hour has completed; decide at candle timestamp plus 1h"
    )
    normalization_lookback_hours: int = 720
    normalization_min_periods: int = 720
    beta_lookback_hours: int = 720
    polarity: int = -1
    entry_zscore: float = 2.0
    holding_hours: int = 24
    cooldown_hours: int = 24
    minimum_entry_count_per_symbol: int = 20
    direct_flip_allowed: bool = False
    fee_pct_per_position_change: float = 0.0005
    slippage_pct_per_position_change: float = 0.0002
    funding_included: bool = True
    account_equity_usdt: float = 400.0
    target_notional_fraction: float = 1.0
    leverage: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def contract_hash(self) -> str:
        return _stable_hash(self.to_dict())


FROZEN_OPTIONS_DVOL_CONTRACT = FrozenOptionsDvolContract()


@dataclass(frozen=True)
class OptionsDvolProtocol:
    protocol_id: str = "options_dvol_cross_symbol_discovery_v1"
    source_currencies: tuple[str, ...] = ("BTC", "ETH")
    discovery_symbols: tuple[str, ...] = ("ETHUSDT", "BNBUSDT", "SOLUSDT")
    benchmark_symbol: str = "BTCUSDT"
    price_interval: str = "1h"
    primary_target: str = "24h_btc_beta_residual_net_return_pct"
    discovery_window: str = "2021-04-01T00:00:00Z..2024-12-31T23:00:00Z"
    historical_replication_window: str = "2025-01-01T00:00:00Z..2025-12-31T23:00:00Z"
    reserved_forward_oos_window: str = "2026-07-17T00:00:00Z..2026-10-16T23:00:00Z"
    discovery_holdout_role: str = "discovery_pool"
    historical_replication_role: str = "research_replication_not_promotion"
    reserved_forward_holdout_role: str = "forward_validation_v1_once_only"
    contract_hash: str = FROZEN_OPTIONS_DVOL_CONTRACT.contract_hash
    selection_trials: int = 1
    minimum_passing_symbol_count: int = 2
    minimum_symbol_rank_ic: float = 0.02
    minimum_symbol_net_residual_pct: float = 0.0
    minimum_positive_rank_ic_count: int = 2
    minimum_positive_residual_count: int = 2
    minimum_median_rank_ic: float = 0.02
    minimum_mean_net_residual_pct: float = 0.0
    minimum_filter_coverage: float = 1.0
    minimum_feature_coverage: float = 0.999
    minimum_price_coverage: float = 0.999
    maximum_rolling_24h_turnover: float = 2.0
    discovery_consumption_rule: str = (
        "all registered discovery symbols stay in the denominator and the feature, polarity, "
        "lookback, threshold, holding period, costs, and gates cannot change after preregistration"
    )
    replication_consumption_rule: str = (
        "do not evaluate 2025 returns unless the frozen discovery report passes its cross-symbol gates"
    )
    promotion_rule: str = (
        "historical discovery and replication cannot promote; only the once-only forward window may "
        "enter G4-G6 after DSR, PBO, purged-CV, breadth, cost, and capacity evidence"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def protocol_hash(self) -> str:
        return _stable_hash(self.to_dict())


FROZEN_OPTIONS_DVOL_PROTOCOL = OptionsDvolProtocol()


def _utc_day_bounds(raw: str) -> tuple[int, int]:
    day = dt.date.fromisoformat(raw)
    start = dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC)
    return int(start.timestamp() * 1000), int((start + dt.timedelta(days=1)).timestamp() * 1000)


def _validate_config(config: SourceCapacityConfig) -> None:
    if set(config.deribit_currencies) != {"BTC", "ETH"}:
        raise ValueError("Deribit capacity audit requires frozen BTC and ETH currencies")
    if set(config.cross_venue_coins) != {"BTC", "ETH", "BNB", "SOL"}:
        raise ValueError("cross-venue capacity audit requires frozen BTC/ETH/BNB/SOL denominator")
    if len(config.deribit_probe_dates) < 2:
        raise ValueError("at least two Deribit boundary probe dates are required")
    for raw in (*config.deribit_probe_dates, config.cross_venue_probe_date, config.binance_probe_date):
        dt.date.fromisoformat(raw)
    if config.request_retries < 0:
        raise ValueError("request_retries must be non-negative")
    if config.request_timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be positive")


def _default_fetch(
    method: str,
    url: str,
    body: bytes | None,
    *,
    timeout_seconds: float,
    retries: int,
) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "qount-source-capacity/0.1",
        },
    )
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


def _json_probe(
    *,
    probe_id: str,
    method: str,
    url: str,
    body: bytes | None,
    fetch: FetchBytes,
    row_path: tuple[str, ...],
    expected_min_rows: int,
    expected_width: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "probe_id": probe_id,
        "method": method,
        "url": url,
        "request_body_sha256": hashlib.sha256(body).hexdigest() if body else None,
        "status": "error",
        "available": False,
    }
    try:
        raw = fetch(method, url, body)
        payload = json.loads(raw)
        rows: Any = payload
        for key in row_path:
            rows = rows[key]
        if not isinstance(rows, list):
            raise ValueError("row payload is not a list")
        schema_valid = all(
            isinstance(row, list) and len(row) == expected_width
            if expected_width is not None
            else isinstance(row, dict)
            for row in rows
        )
        enough_rows = len(rows) >= expected_min_rows
        result.update(
            {
                "response_bytes": len(raw),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "row_count": len(rows),
                "schema_valid": schema_valid,
                "available": bool(schema_valid and enough_rows),
                "status": "available" if schema_valid and enough_rows else "insufficient",
            }
        )
        if rows:
            first = rows[0]
            last = rows[-1]
            result["first_timestamp_ms"] = int(first[0] if isinstance(first, list) else first["time"])
            result["last_timestamp_ms"] = int(last[0] if isinstance(last, list) else last["time"])
        if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            result["continuation"] = payload["result"].get("continuation")
    except urllib.error.HTTPError as exc:
        result["status"] = "missing" if exc.code == 404 else "error"
        result["http_status"] = exc.code
    except Exception as exc:  # pragma: no cover - live network failures are nondeterministic
        result["error"] = f"{type(exc).__name__}: {exc}"
    return {key: value for key, value in result.items() if value is not None}


def _archive_probe(*, dataset: str, config: SourceCapacityConfig, fetch: FetchBytes) -> dict[str, Any]:
    symbol = config.binance_symbol
    date = config.binance_probe_date
    filename = f"{symbol}-{dataset}-{date}.zip"
    url = f"{BINANCE_UM_ARCHIVE_URL}/daily/{dataset}/{symbol}/{filename}.CHECKSUM"
    result: dict[str, Any] = {
        "probe_id": f"binance_{dataset}_{date}",
        "method": "GET",
        "url": url,
        "dataset": dataset,
        "status": "error",
        "available": False,
    }
    try:
        raw = fetch("GET", url, None)
        parts = raw.decode("utf-8").strip().split()
        digest = parts[0].lower() if parts else ""
        declared = parts[-1].lstrip("*") if len(parts) >= 2 else ""
        valid = len(digest) == 64 and declared == filename
        result.update(
            {
                "response_bytes": len(raw),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "checksum_sha256": digest if len(digest) == 64 else None,
                "checksum_valid": valid,
                "available": valid,
                "status": "available" if valid else "invalid_checksum",
            }
        )
    except urllib.error.HTTPError as exc:
        result["status"] = "missing" if exc.code == 404 else "error"
        result["http_status"] = exc.code
    except FileNotFoundError:
        result["status"] = "missing"
    except Exception as exc:  # pragma: no cover - live network failures are nondeterministic
        result["error"] = f"{type(exc).__name__}: {exc}"
    return {key: value for key, value in result.items() if value is not None}


def _deribit_probes(config: SourceCapacityConfig, fetch: FetchBytes) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for currency in config.deribit_currencies:
        for raw_date in config.deribit_probe_dates:
            start_ms, end_ms = _utc_day_bounds(raw_date)
            url = (
                f"{DERIBIT_DVOL_URL}?currency={currency}&start_timestamp={start_ms}"
                f"&end_timestamp={end_ms}&resolution=3600"
            )
            probe = _json_probe(
                probe_id=f"deribit_dvol_{currency}_{raw_date}",
                method="GET",
                url=url,
                body=None,
                fetch=fetch,
                row_path=("result", "data"),
                expected_min_rows=24,
                expected_width=5,
            )
            probe.update({"source": "deribit_dvol", "currency": currency, "probe_date": raw_date})
            probes.append(probe)
    return probes


def _cross_venue_probes(config: SourceCapacityConfig, fetch: FetchBytes) -> list[dict[str, Any]]:
    start_ms, end_ms = _utc_day_bounds(config.cross_venue_probe_date)
    probes: list[dict[str, Any]] = []
    for coin in config.cross_venue_coins:
        body = json.dumps(
            {
                "type": "fundingHistory",
                "coin": coin,
                "startTime": start_ms,
                "endTime": end_ms,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        probe = _json_probe(
            probe_id=f"hyperliquid_funding_{coin}_{config.cross_venue_probe_date}",
            method="POST",
            url=HYPERLIQUID_INFO_URL,
            body=body,
            fetch=fetch,
            row_path=(),
            expected_min_rows=20,
        )
        probe.update(
            {
                "source": "hyperliquid_funding_premium",
                "coin": coin,
                "probe_date": config.cross_venue_probe_date,
            }
        )
        probes.append(probe)
    return probes


def build_source_capacity_matrix(
    config: SourceCapacityConfig = SourceCapacityConfig(),
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    _validate_config(config)
    actual_fetch = fetch or (
        lambda method, url, body: _default_fetch(
            method,
            url,
            body,
            timeout_seconds=config.request_timeout_seconds,
            retries=config.request_retries,
        )
    )
    deribit = _deribit_probes(config, actual_fetch)
    cross_venue = _cross_venue_probes(config, actual_fetch)
    archives = [
        _archive_probe(dataset=dataset, config=config, fetch=actual_fetch)
        for dataset in ("forceOrder", "depth", "bookDepth")
    ]
    all_probes = [*deribit, *cross_venue, *archives]
    dvol_ready = all(probe["available"] for probe in deribit)
    cross_venue_ready = all(probe["available"] for probe in cross_venue)
    archive_by_dataset = {probe["dataset"]: probe for probe in archives}

    candidates = [
        {
            "candidate_id": "binance_liquidation_force_order",
            "information_mechanism": "forced-liquidation side and notional stress",
            "source": "Binance USD-M forceOrder public stream",
            "official_public": True,
            "point_in_time": True,
            "historical_discovery_ready": archive_by_dataset["forceOrder"]["available"],
            "historical_replication_ready": False,
            "estimated_local_storage": "forward-only and event-dependent",
            "status": "forward_only",
            "blockers": ["official_historical_archive_unavailable", "new_long_vps_collector_prohibited"],
        },
        {
            "candidate_id": "binance_replayable_l2_queue",
            "information_mechanism": "diff-depth queue imbalance and order-flow imbalance",
            "source": "Binance USD-M depth stream or an audited external historical source",
            "official_public": True,
            "point_in_time": True,
            "historical_discovery_ready": archive_by_dataset["depth"]["available"],
            "historical_replication_ready": False,
            "aggregate_book_depth_available": archive_by_dataset["bookDepth"]["available"],
            "estimated_local_storage": "unknown external history; live stream requires forward collection",
            "status": "external_history_required",
            "blockers": [
                "official_replayable_depth_archive_unavailable",
                "bookDepth_is_percentage_aggregate_not_l2",
                "new_long_vps_collector_prohibited",
            ],
        },
        {
            "candidate_id": "deribit_options_dvol_relative_stress",
            "information_mechanism": "ETH-versus-BTC options-implied-volatility hedging stress",
            "source": "Deribit public DVOL hourly OHLC API",
            "official_public": True,
            "point_in_time": True,
            "historical_discovery_ready": dvol_ready,
            "historical_replication_ready": dvol_ready,
            "estimated_local_storage": "hourly BTC/ETH OHLC; low single-digit MiB for multi-year history",
            "status": "eligible_g0" if dvol_ready else "capacity_incomplete",
            "blockers": [] if dvol_ready else ["dvol_boundary_or_schema_probe_failed"],
            "caveats": [
                "API responses have no exchange checksum sidecar; persist exact raw response SHA-256",
                "DVOL is a volatility index, not historical option-surface skew",
            ],
        },
        {
            "candidate_id": "hyperliquid_cross_venue_funding_premium",
            "information_mechanism": "venue-specific funding and premium crowding divergence",
            "source": "Hyperliquid public fundingHistory API plus Binance public premium/funding",
            "official_public": True,
            "point_in_time": True,
            "historical_discovery_ready": cross_venue_ready,
            "historical_replication_ready": cross_venue_ready,
            "estimated_local_storage": "hourly four-coin rows; low single-digit MiB per year",
            "status": "eligible_but_deprioritized" if cross_venue_ready else "capacity_incomplete",
            "blockers": [] if cross_venue_ready else ["cross_venue_boundary_or_schema_probe_failed"],
            "caveats": [
                "mechanism overlaps prior failed funding/cross-venue research",
                "research availability does not provide multi-venue execution infrastructure",
            ],
        },
    ]
    selected = "deribit_options_dvol_relative_stress" if dvol_ready else None
    basis = {"config": config.to_dict(), "candidates": candidates, "probes": all_probes}
    return {
        "schema_version": SOURCE_CAPACITY_VERSION,
        "artifact_type": "source_capacity_matrix",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "probe_method": "official public API rows and small Binance CHECKSUM sidecars only",
            "data_hash": _stable_hash(basis),
        },
        "config": config.to_dict(),
        "source_references": [
            "https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data",
            "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint#retrieve-funding-history",
            "https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams",
            "https://github.com/binance/binance-public-data",
        ],
        "candidates": candidates,
        "probes": all_probes,
        "diagnostics": {
            "verdict": "select_single_g0_candidate" if selected else "capacity_incomplete",
            "selected_candidate_id": selected,
            "selection_reason": (
                "only audited candidate with long public history, independent options information, "
                "small storage, and no account or long collector requirement"
                if selected
                else None
            ),
            "strategy_results_evaluated": False,
            "promotion_evidence": False,
            "next_action": (
                "bind this artifact in the single options-DVOL G0 preregistration"
                if selected
                else "repair source-capacity probes without evaluating strategy returns"
            ),
        },
    }


def build_options_dvol_preregistration(
    capacity_path: str | Path,
    protocol: OptionsDvolProtocol = FROZEN_OPTIONS_DVOL_PROTOCOL,
    contract: FrozenOptionsDvolContract = FROZEN_OPTIONS_DVOL_CONTRACT,
) -> dict[str, Any]:
    source = Path(capacity_path).expanduser().resolve()
    blob = source.read_bytes()
    capacity = json.loads(blob)
    diagnostics = capacity.get("diagnostics", {})
    if (
        capacity.get("schema_version") != SOURCE_CAPACITY_VERSION
        or capacity.get("artifact_type") != "source_capacity_matrix"
        or diagnostics.get("verdict") != "select_single_g0_candidate"
        or diagnostics.get("selected_candidate_id") != "deribit_options_dvol_relative_stress"
        or diagnostics.get("strategy_results_evaluated") is not False
    ):
        raise ValueError("capacity artifact does not authorize the frozen options-DVOL G0 candidate")
    candidate = next(
        (
            row
            for row in capacity.get("candidates", [])
            if row.get("candidate_id") == "deribit_options_dvol_relative_stress"
        ),
        None,
    )
    if not candidate or candidate.get("status") != "eligible_g0" or candidate.get("blockers"):
        raise ValueError("selected options-DVOL source has unresolved capacity blockers")
    if protocol.contract_hash != contract.contract_hash:
        raise ValueError("options-DVOL protocol and contract hashes do not match")
    return {
        "schema_version": OPTIONS_DVOL_PREREGISTRATION_VERSION,
        "artifact_type": "preregistration",
        "created_at": utc_now().isoformat(),
        "capacity_binding": {
            "path": str(source),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "data_hash": capacity.get("meta", {}).get("data_hash"),
            "selected_candidate_id": diagnostics["selected_candidate_id"],
        },
        "contract": {
            **contract.to_dict(),
            "contract_hash": contract.contract_hash,
        },
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "diagnostics": {
            "verdict": "preregistered_g0",
            "supersedes_schema_versions": [
                "alpha_agent_options_dvol_preregistration_v0.1",
                "alpha_agent_options_dvol_preregistration_v0.2",
            ],
            "source_capacity_passed": True,
            "strategy_results_evaluated": False,
            "discovery_consumed": False,
            "historical_replication_consumed": False,
            "reserved_forward_oos_consumed": False,
            "parameter_tuning_allowed": False,
            "a10_enabled": False,
            "promotion_allowed": False,
            "next_action": "implement checksum-like raw-response hashing and the exact DVOL discovery loader",
        },
        "hard_boundaries": [
            "The Deribit source contributes completed public DVOL candles only; it is not option-surface skew or executable option pricing.",
            "All three registered Binance target symbols remain in the denominator; failed symbols cannot be dropped.",
            "The feature, direction, normalization and beta lookbacks, threshold, minimum entries, holding, cooldown, costs, trial count, and gates are frozen before returns are read.",
            "2021-2024 is discovery and 2025 is research replication because historical crypto returns have been exposed elsewhere in the project.",
            "Only the 2026-07-17 onward once-only forward window can become validation evidence; it is not yet available or consumed.",
            "This artifact cannot authorize A10, paper, live, VPS changes, private API access, or order placement.",
        ],
    }


def write_source_capacity_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    preregistration = payload.get("artifact_type") == "preregistration"
    return write_research_json_artifact(
        settings,
        payload,
        kind=(
            "alpha-agent-options-dvol-preregistration"
            if preregistration
            else "alpha-agent-source-capacity"
        ),
        path_key="artifact_path",
        default_filename=(
            "alpha_agent_options_dvol_preregistration.json"
            if preregistration
            else "alpha_agent_source_capacity.json"
        ),
        explicit_path=explicit_path,
    )
