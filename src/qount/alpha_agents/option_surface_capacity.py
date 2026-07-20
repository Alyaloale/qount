from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings


OPTION_SURFACE_CAPACITY_VERSION = "alpha_agent_option_surface_capacity_v0.1"
DERIBIT_API_BASE = "https://www.deribit.com/api/v2/public"
FetchBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class HistoricalOptionProbe:
    instrument_name: str
    start_timestamp_ms: int
    end_timestamp_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OptionSurfaceCapacityConfig:
    currencies: tuple[str, ...] = ("BTC", "ETH")
    historical_trade_start_ms: int = 1_704_067_200_000
    historical_trade_end_ms: int = 1_704_153_600_000
    historical_probes: tuple[HistoricalOptionProbe, ...] = (
        HistoricalOptionProbe("BTC-25JUN21-40000-C", 1_617_235_200_000, 1_624_608_000_000),
        HistoricalOptionProbe("ETH-25JUN21-2000-P", 1_624_271_317_000, 1_624_608_000_000),
        HistoricalOptionProbe("BTC-29MAR24-60000-C", 1_704_067_200_000, 1_711_699_200_000),
        HistoricalOptionProbe("ETH-29MAR24-3000-P", 1_704_067_200_000, 1_711_699_200_000),
        HistoricalOptionProbe("BTC-28MAR25-100000-C", 1_735_689_600_000, 1_743_148_800_000),
    )
    chart_resolution_minutes: int = 60
    request_retries: int = 3
    request_timeout_seconds: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["historical_probes"] = [probe.to_dict() for probe in self.historical_probes]
        return payload


def _url(method: str, **params: Any) -> str:
    query = urllib.parse.urlencode(params)
    return f"{DERIBIT_API_BASE}/{method}?{query}"


def _default_fetch(url: str, *, timeout_seconds: float, retries: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qount-option-surface-capacity/0.1"})
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


def _fetch_json(*, probe_id: str, url: str, fetch: FetchBytes) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    evidence: dict[str, Any] = {
        "probe_id": probe_id,
        "url": url,
        "status": "error",
        "available": False,
    }
    try:
        raw = fetch(url)
        payload = json.loads(raw)
        if payload.get("error") is not None:
            raise ValueError(f"Deribit API error: {payload['error']}")
        evidence.update(
            {
                "status": "available",
                "available": True,
                "response_bytes": len(raw),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        return payload, evidence
    except Exception as exc:  # pragma: no cover - live network failures are nondeterministic
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        return None, evidence


def _instrument_probe(probe: HistoricalOptionProbe, fetch: FetchBytes) -> dict[str, Any]:
    url = _url("get_instrument", instrument_name=probe.instrument_name)
    payload, evidence = _fetch_json(
        probe_id=f"instrument_{probe.instrument_name}", url=url, fetch=fetch
    )
    result = payload.get("result") if payload else None
    valid = isinstance(result, dict) and result.get("instrument_name") == probe.instrument_name
    evidence.update(
        {
            "probe_type": "instrument_metadata",
            "instrument_name": probe.instrument_name,
            "metadata_valid": valid,
            "creation_timestamp": result.get("creation_timestamp") if valid else None,
            "expiration_timestamp": result.get("expiration_timestamp") if valid else None,
            "strike": result.get("strike") if valid else None,
            "option_type": result.get("option_type") if valid else None,
        }
    )
    evidence["available"] = bool(evidence["available"] and valid)
    evidence["status"] = "available" if evidence["available"] else "invalid"
    return evidence


def _chart_probe(probe: HistoricalOptionProbe, config: OptionSurfaceCapacityConfig, fetch: FetchBytes) -> dict[str, Any]:
    url = _url(
        "get_tradingview_chart_data",
        instrument_name=probe.instrument_name,
        start_timestamp=probe.start_timestamp_ms,
        end_timestamp=probe.end_timestamp_ms,
        resolution=config.chart_resolution_minutes,
    )
    payload, evidence = _fetch_json(
        probe_id=f"chart_{probe.instrument_name}", url=url, fetch=fetch
    )
    result = payload.get("result") if payload else None
    required = {"ticks", "open", "high", "low", "close", "volume", "cost"}
    keys = set(result) if isinstance(result, dict) else set()
    lengths = {
        key: len(result[key])
        for key in required
        if isinstance(result, dict) and isinstance(result.get(key), list)
    }
    consistent = len(lengths) == len(required) and len(set(lengths.values())) == 1
    count = lengths.get("ticks", 0)
    volume = result.get("volume", []) if isinstance(result, dict) else []
    evidence.update(
        {
            "probe_type": "historical_price_chart",
            "instrument_name": probe.instrument_name,
            "result_keys": sorted(keys),
            "row_count": count,
            "array_lengths_consistent": consistent,
            "first_timestamp_ms": result["ticks"][0] if count else None,
            "last_timestamp_ms": result["ticks"][-1] if count else None,
            "nonzero_volume_count": sum(float(value or 0.0) > 0 for value in volume),
            "direct_iv_available": "iv" in keys,
            "direct_index_price_available": "index_price" in keys,
            "direct_mark_price_available": "mark_price" in keys,
        }
    )
    valid = bool(evidence["available"] and result.get("status") == "ok" and consistent and count > 0)
    evidence["available"] = valid
    evidence["status"] = "available" if valid else "invalid"
    return evidence


def _historical_trade_probe(currency: str, config: OptionSurfaceCapacityConfig, fetch: FetchBytes) -> dict[str, Any]:
    url = _url(
        "get_last_trades_by_currency_and_time",
        currency=currency,
        kind="option",
        start_timestamp=config.historical_trade_start_ms,
        end_timestamp=config.historical_trade_end_ms,
        count=1000,
        sorting="asc",
    )
    payload, evidence = _fetch_json(
        probe_id=f"historical_trades_{currency}", url=url, fetch=fetch
    )
    result = payload.get("result") if payload else None
    trades = result.get("trades", []) if isinstance(result, dict) else []
    field_coverage = {
        field: sum(row.get(field) is not None for row in trades if isinstance(row, dict))
        for field in ("iv", "index_price", "mark_price", "instrument_name", "timestamp")
    }
    evidence.update(
        {
            "probe_type": "historical_option_trades_with_iv",
            "currency": currency,
            "trade_count": len(trades),
            "has_more": result.get("has_more") if isinstance(result, dict) else None,
            "field_coverage": field_coverage,
            "historical_iv_available": bool(trades and field_coverage["iv"] == len(trades)),
        }
    )
    return evidence


def _expired_inventory_probe(currency: str, fetch: FetchBytes) -> dict[str, Any]:
    url = _url("get_instruments", currency=currency, kind="option", expired="true")
    payload, evidence = _fetch_json(
        probe_id=f"expired_inventory_{currency}", url=url, fetch=fetch
    )
    instruments = payload.get("result", []) if payload else []
    expiries = [
        int(row["expiration_timestamp"])
        for row in instruments
        if isinstance(row, dict) and row.get("expiration_timestamp") is not None
    ]
    evidence.update(
        {
            "probe_type": "expired_instrument_inventory",
            "currency": currency,
            "instrument_count": len(instruments),
            "unique_expiry_count": len(set(expiries)),
            "min_expiration_timestamp": min(expiries) if expiries else None,
            "max_expiration_timestamp": max(expiries) if expiries else None,
            "contains_2024_or_earlier": any(value < 1_735_689_600_000 for value in expiries),
        }
    )
    return evidence


def _current_surface_probe(currency: str, fetch: FetchBytes) -> dict[str, Any]:
    url = _url("get_book_summary_by_currency", currency=currency, kind="option")
    payload, evidence = _fetch_json(
        probe_id=f"current_surface_{currency}", url=url, fetch=fetch
    )
    rows = payload.get("result", []) if payload else []
    coverage = {
        field: sum(row.get(field) is not None for row in rows if isinstance(row, dict))
        for field in ("mark_iv", "bid_iv", "ask_iv", "mark_price", "underlying_price")
    }
    evidence.update(
        {
            "probe_type": "current_option_surface",
            "currency": currency,
            "instrument_count": len(rows),
            "field_coverage": coverage,
            "current_mark_iv_available": bool(rows and coverage["mark_iv"] == len(rows)),
        }
    )
    return evidence


def build_option_surface_capacity(
    config: OptionSurfaceCapacityConfig = OptionSurfaceCapacityConfig(),
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    if set(config.currencies) != {"BTC", "ETH"}:
        raise ValueError("option-surface capacity requires frozen BTC and ETH currencies")
    if not config.historical_probes:
        raise ValueError("at least one historical instrument probe is required")
    if config.chart_resolution_minutes != 60:
        raise ValueError("option-surface capacity v0 requires 60-minute chart probes")
    actual_fetch = fetch or (
        lambda url: _default_fetch(
            url,
            timeout_seconds=config.request_timeout_seconds,
            retries=config.request_retries,
        )
    )
    metadata = [_instrument_probe(probe, actual_fetch) for probe in config.historical_probes]
    charts = [_chart_probe(probe, config, actual_fetch) for probe in config.historical_probes]
    historical_trades = [
        _historical_trade_probe(currency, config, actual_fetch) for currency in config.currencies
    ]
    inventories = [_expired_inventory_probe(currency, actual_fetch) for currency in config.currencies]
    current_surfaces = [_current_surface_probe(currency, actual_fetch) for currency in config.currencies]
    probes = [*metadata, *charts, *historical_trades, *inventories, *current_surfaces]

    network_complete = all(probe.get("available") for probe in probes)
    metadata_complete = all(probe.get("metadata_valid") for probe in metadata)
    charts_complete = all(probe.get("available") for probe in charts)
    charts_have_direct_surface = all(
        probe.get("direct_iv_available")
        and probe.get("direct_index_price_available")
        and probe.get("direct_mark_price_available")
        for probe in charts
    )
    historical_iv_available = all(
        probe.get("historical_iv_available") for probe in historical_trades
    )
    historical_chain_enumerable = all(
        probe.get("contains_2024_or_earlier") and int(probe.get("unique_expiry_count", 0)) > 1
        for probe in inventories
    )
    current_surface_available = all(
        probe.get("current_mark_iv_available") for probe in current_surfaces
    )
    blockers: list[str] = []
    if not network_complete:
        blockers.append("official_probe_incomplete")
    if not historical_chain_enumerable:
        blockers.append("official_historical_instrument_chain_not_enumerable")
    if not historical_iv_available:
        blockers.append("historical_trade_iv_unavailable")
    if not charts_have_direct_surface:
        blockers.append("historical_chart_missing_iv_index_mark")
    blockers.append("price_only_iv_inversion_requires_unregistered_model_and_strike_search")
    point_in_time_surface_reconstructable = not blockers
    basis = {"config": config.to_dict(), "probes": probes, "blockers": blockers}
    return {
        "schema_version": OPTION_SURFACE_CAPACITY_VERSION,
        "artifact_type": "option_surface_source_capacity",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "strategy_results_evaluated": False,
            "data_hash": hashlib.sha256(
                json.dumps(basis, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
        "config": config.to_dict(),
        "source_references": [
            "https://docs.deribit.com/api-reference/market-data/public-get_instruments",
            "https://docs.deribit.com/api-reference/market-data/public-get_instrument",
            "https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_currency_and_time",
            "https://docs.deribit.com/api-reference/market-data/public-get_tradingview_chart_data",
            "https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency",
        ],
        "diagnostics": {
            "verdict": "eligible_g0" if point_in_time_surface_reconstructable else "block_g0",
            "blockers": blockers,
            "metadata_complete": metadata_complete,
            "historical_price_charts_complete": charts_complete,
            "historical_trade_iv_available": historical_iv_available,
            "historical_chain_enumerable": historical_chain_enumerable,
            "charts_have_direct_iv_index_mark": charts_have_direct_surface,
            "current_surface_available": current_surface_available,
            "point_in_time_surface_reconstructable": point_in_time_surface_reconstructable,
            "strategy_results_evaluated": False,
            "preregistration_allowed": point_in_time_surface_reconstructable,
            "next_action": (
                "freeze one skew G0 before reading returns"
                if point_in_time_surface_reconstructable
                else "do not preregister skew; audit a licensed historical surface dataset or move to liquidation/L2 capacity"
            ),
        },
        "probes": probes,
    }


def write_option_surface_capacity_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-option-surface-capacity",
        path_key="artifact_path",
        default_filename="alpha_agent_option_surface_capacity.json",
        explicit_path=explicit_path,
    )
