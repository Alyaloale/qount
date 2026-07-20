"""Latest-vintage Coin Metrics daily on-chain dataset for discovery research."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.futures_recovery import canonical_hash
from qount.models import utc_now
from qount.settings import Settings


ONCHAIN_DATASET_VERSION = "mini_trend_coinmetrics_onchain_daily_v0.1"
COINMETRICS_ASSET_METRICS_URL = (
    "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
)
ONCHAIN_METRICS = (
    "CapMVRVCur",
    "AdrActCnt",
    "TxCnt",
    "HashRate",
    "FlowInExUSD",
    "FlowOutExUSD",
)
FetchBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class OnchainDatasetConfig:
    asset: str = "btc"
    start_date: str = "2020-01-01"
    end_date: str = "2026-06-30"
    frequency: str = "1d"
    decision_lag_days: int = 1
    zscore_window_days: int = 90
    mvrv_zscore_window_days: int = 365
    minimum_raw_coverage: float = 0.995
    request_timeout_seconds: float = 60.0
    request_retries: int = 3

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "metrics": list(ONCHAIN_METRICS),
                "source_vintage": "latest_available_response_not_historical_vintage",
                "promotion_allowed": False,
            }
        )


def coinmetrics_url(config: OnchainDatasetConfig) -> str:
    query = urllib.parse.urlencode(
        {
            "assets": config.asset,
            "metrics": ",".join(ONCHAIN_METRICS),
            "frequency": config.frequency,
            "start_time": config.start_date,
            "end_time": config.end_date,
            "page_size": 10000,
        }
    )
    return f"{COINMETRICS_ASSET_METRICS_URL}?{query}"


def _default_fetch(url: str, *, timeout: float, retries: int) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "qount-onchain-capacity/0.1"}
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, TimeoutError):
            if attempt >= retries:
                raise
            time.sleep(0.25 * (2**attempt))
    raise AssertionError("unreachable")


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.part")
    partial.write_bytes(raw)
    os.replace(partial, path)


def _validate_config(config: OnchainDatasetConfig) -> tuple[dt.date, dt.date]:
    start = dt.date.fromisoformat(config.start_date)
    end = dt.date.fromisoformat(config.end_date)
    if end < start:
        raise ValueError("on-chain end date must not precede start date")
    if config.asset != "btc" or config.frequency != "1d":
        raise ValueError("on-chain v0.1 supports BTC daily metrics only")
    if config.decision_lag_days < 1:
        raise ValueError("on-chain features require at least a one-day decision lag")
    if config.zscore_window_days < 20 or config.mvrv_zscore_window_days < 60:
        raise ValueError("on-chain z-score windows are too short")
    if not 0 < config.minimum_raw_coverage <= 1:
        raise ValueError("minimum raw coverage must be in (0, 1]")
    return start, end


def _parse_rows(
    raw: bytes, config: OnchainDatasetConfig
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    payload = json.loads(raw)
    if set(payload) - {"data", "next_page_token", "next_page_url"}:
        raise ValueError("unexpected Coin Metrics response envelope")
    if payload.get("next_page_token") or payload.get("next_page_url"):
        raise ValueError("Coin Metrics response unexpectedly requires pagination")
    source = payload.get("data")
    if not isinstance(source, list):
        raise ValueError("Coin Metrics response is missing data rows")
    rows = []
    statuses: dict[str, int] = {}
    previous: dt.date | None = None
    for index, item in enumerate(source, start=1):
        if not isinstance(item, dict) or item.get("asset") != config.asset:
            raise ValueError(f"invalid Coin Metrics asset row at {index}")
        date = dt.date.fromisoformat(str(item.get("time", ""))[:10])
        if previous is not None and date <= previous:
            raise ValueError("Coin Metrics dates are not strictly increasing")
        values: dict[str, float] = {}
        for metric in ONCHAIN_METRICS:
            try:
                value = float(item[metric])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"missing or invalid {metric} at {date}") from exc
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"non-finite or negative {metric} at {date}")
            values[metric] = value
        for metric in ("FlowInExUSD", "FlowOutExUSD"):
            status = str(item.get(f"{metric}-status") or "missing")
            key = f"{metric}:{status}"
            statuses[key] = statuses.get(key, 0) + 1
        rows.append({"date": date.isoformat(), **values})
        previous = date
    return rows, statuses


def _zscore(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    sample = values[-window:]
    deviation = statistics.stdev(sample)
    return (sample[-1] - statistics.fmean(sample)) / deviation if deviation > 0 else 0.0


def _features(
    rows: list[dict[str, Any]], config: OnchainDatasetConfig
) -> list[dict[str, Any]]:
    histories: dict[str, list[float]] = {
        "mvrv": [],
        "net_flow": [],
        "gross_flow": [],
        "active_addresses": [],
        "tx_count": [],
        "hashrate": [],
    }
    features = []
    for row in rows:
        histories["mvrv"].append(float(row["CapMVRVCur"]))
        inflow = float(row["FlowInExUSD"])
        outflow = float(row["FlowOutExUSD"])
        histories["net_flow"].append(inflow - outflow)
        histories["gross_flow"].append(inflow + outflow)
        histories["active_addresses"].append(float(row["AdrActCnt"]))
        histories["tx_count"].append(float(row["TxCnt"]))
        histories["hashrate"].append(float(row["HashRate"]))
        current = {
            "mvrv_level": histories["mvrv"][-1],
            "mvrv_z365": _zscore(
                histories["mvrv"], config.mvrv_zscore_window_days
            ),
            "exchange_net_flow_z90": _zscore(
                histories["net_flow"], config.zscore_window_days
            ),
            "exchange_gross_flow_z90": _zscore(
                histories["gross_flow"], config.zscore_window_days
            ),
            "active_addresses_z90": _zscore(
                histories["active_addresses"], config.zscore_window_days
            ),
            "tx_count_z90": _zscore(
                histories["tx_count"], config.zscore_window_days
            ),
            "hashrate_z90": _zscore(
                histories["hashrate"], config.zscore_window_days
            ),
        }
        if any(value is None for value in current.values()):
            continue
        source_date = dt.date.fromisoformat(row["date"])
        decision_date = source_date + dt.timedelta(days=config.decision_lag_days)
        features.append(
            {
                "source_date": source_date.isoformat(),
                "decision_date": decision_date.isoformat(),
                **{key: float(value) for key, value in current.items()},
            }
        )
    return features


def build_onchain_dataset(
    cache_path: str | Path,
    config: OnchainDatasetConfig | None = None,
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    config = config or OnchainDatasetConfig()
    start, end = _validate_config(config)
    path = Path(cache_path).expanduser()
    cache_hit = path.exists()
    url = coinmetrics_url(config)
    if cache_hit:
        raw = path.read_bytes()
    else:
        actual_fetch = fetch or (
            lambda target: _default_fetch(
                target,
                timeout=config.request_timeout_seconds,
                retries=config.request_retries,
            )
        )
        raw = actual_fetch(url)
        _atomic_write(path, raw)
    rows, statuses = _parse_rows(raw, config)
    expected = (end - start).days + 1
    actual_dates = {row["date"] for row in rows}
    expected_dates = {
        (start + dt.timedelta(days=offset)).isoformat() for offset in range(expected)
    }
    missing = sorted(expected_dates - actual_dates)
    coverage = len(actual_dates & expected_dates) / expected
    features = _features(rows, config)
    blockers = []
    if coverage < config.minimum_raw_coverage:
        blockers.append("raw_daily_coverage_below_gate")
    if not features:
        blockers.append("no_causal_lagged_features")
    raw_hash = hashlib.sha256(raw).hexdigest()
    return {
        "schema_version": ONCHAIN_DATASET_VERSION,
        "artifact_type": "mini_trend_coinmetrics_onchain_daily_dataset",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "public_data_only": True,
            "private_exchange_data": False,
            "source": "Coin Metrics community API",
            "source_vintage": "latest_available_response_not_historical_vintage",
            "point_in_time_promotion_ready": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "metrics": list(ONCHAIN_METRICS),
            "contract_hash": config.contract_hash,
        },
        "source": {
            "url": url,
            "cache_path": str(path),
            "cache_hit": cache_hit,
            "response_bytes": len(raw),
            "response_sha256": raw_hash,
            "official_reference": "https://docs.coinmetrics.io/api/v4",
        },
        "diagnostics": {
            "verdict": "pass_latest_vintage_dataset" if not blockers else "block_data",
            "blockers": blockers,
            "expected_daily_rows": expected,
            "actual_daily_rows": len(rows),
            "coverage_ratio": coverage,
            "missing_count": len(missing),
            "first_missing_date": missing[0] if missing else None,
            "feature_rows": len(features),
            "feature_start": features[0]["decision_date"] if features else None,
            "feature_end": features[-1]["decision_date"] if features else None,
            "flow_status_counts": statuses,
            "strategy_results_evaluated": False,
            "promotion_evidence": False,
        },
        "daily_features": features,
        "data_hash": canonical_hash(
            {
                "contract_hash": config.contract_hash,
                "raw_response_sha256": raw_hash,
                "daily_features": features,
            }
        ),
    }


def write_onchain_dataset_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-coinmetrics-onchain-dataset",
        path_key="artifact_path",
        default_filename="mini_trend_coinmetrics_onchain_daily.json",
        explicit_path=explicit_path,
    )
