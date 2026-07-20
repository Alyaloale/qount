"""Append-only Coin Metrics snapshots for future point-in-time evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_onchain import COINMETRICS_ASSET_METRICS_URL
from qount.mini_trend.regime_onchain import ONCHAIN_METRICS
from qount.models import utc_now
from qount.settings import Settings


ONCHAIN_VINTAGE_VERSION = "mini_trend_coinmetrics_vintage_snapshot_v0.1"
FetchBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class OnchainVintageConfig:
    asset: str = "btc"
    frequency: str = "1d"
    decision_lag_days: int = 1
    request_timeout_seconds: float = 30.0

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "metrics": list(ONCHAIN_METRICS),
                "storage": "one immutable raw response per retrieval timestamp",
                "orders_allowed": False,
            }
        )


def snapshot_url(source_date: str, config: OnchainVintageConfig) -> str:
    dt.date.fromisoformat(source_date)
    query = urllib.parse.urlencode(
        {
            "assets": config.asset,
            "metrics": ",".join(ONCHAIN_METRICS),
            "frequency": config.frequency,
            "start_time": source_date,
            "end_time": source_date,
            "page_size": 10,
        }
    )
    return f"{COINMETRICS_ASSET_METRICS_URL}?{query}"


def _default_fetch(url: str, *, timeout_seconds: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "qount-onchain-vintage/0.1"}
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _retrieval_id(retrieved_at: dt.datetime) -> str:
    return retrieved_at.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def parse_vintage_response(
    raw: bytes,
    *,
    source_date: str,
    retrieved_at: dt.datetime,
    config: OnchainVintageConfig,
) -> dict[str, Any]:
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    expected_date = dt.date.fromisoformat(source_date)
    retrieved_at = retrieved_at.astimezone(dt.UTC)
    if expected_date >= retrieved_at.date():
        raise ValueError("snapshot source date must be a completed day before retrieval")
    payload = json.loads(raw)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Coin Metrics vintage response must contain exactly one daily row")
    row = rows[0]
    if row.get("asset") != config.asset or str(row.get("time", ""))[:10] != source_date:
        raise ValueError("Coin Metrics vintage row does not match the requested asset/date")
    values = {}
    for metric in ONCHAIN_METRICS:
        try:
            value = float(row[metric])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid snapshot metric {metric}") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"non-finite or negative snapshot metric {metric}")
        values[metric] = value
    statuses = {
        metric: {
            "status": row.get(f"{metric}-status"),
            "status_time": row.get(f"{metric}-status-time"),
        }
        for metric in ("FlowInExUSD", "FlowOutExUSD")
    }
    raw_hash = hashlib.sha256(raw).hexdigest()
    decision_date = expected_date + dt.timedelta(days=config.decision_lag_days)
    return {
        "schema_version": ONCHAIN_VINTAGE_VERSION,
        "artifact_type": "mini_trend_coinmetrics_vintage_snapshot",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "future_append_only_observation",
            "public_data_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "metrics": list(ONCHAIN_METRICS),
            "contract_hash": config.contract_hash,
        },
        "snapshot": {
            "retrieval_id": _retrieval_id(retrieved_at),
            "retrieved_at": retrieved_at.isoformat(),
            "source_date": source_date,
            "decision_date": decision_date.isoformat(),
            "retrieval_lag_days": (retrieved_at.date() - expected_date).days,
            "values": values,
            "statuses": statuses,
            "raw_response_bytes": len(raw),
            "raw_response_sha256": raw_hash,
        },
        "diagnostics": {
            "verdict": "append_future_vintage",
            "provider_publication_timestamp_available": False,
            "local_retrieval_timestamp_bound": True,
            "strategy_results_evaluated": False,
            "promotion_evidence": False,
            "paper_or_live_allowed": False,
        },
        "snapshot_hash": canonical_hash(
            {
                "contract_hash": config.contract_hash,
                "retrieved_at": retrieved_at.isoformat(),
                "source_date": source_date,
                "values": values,
                "statuses": statuses,
                "raw_response_sha256": raw_hash,
            }
        ),
    }


def collect_onchain_vintage(
    *,
    raw_root: str | Path,
    source_date: str,
    retrieved_at: dt.datetime | None = None,
    config: OnchainVintageConfig | None = None,
    fetch: FetchBytes | None = None,
) -> tuple[dict[str, Any], Path]:
    config = config or OnchainVintageConfig()
    retrieved_at = (retrieved_at or utc_now()).astimezone(dt.UTC)
    url = snapshot_url(source_date, config)
    actual_fetch = fetch or (
        lambda target: _default_fetch(
            target, timeout_seconds=config.request_timeout_seconds
        )
    )
    raw = actual_fetch(url)
    snapshot = parse_vintage_response(
        raw,
        source_date=source_date,
        retrieved_at=retrieved_at,
        config=config,
    )
    retrieval_id = snapshot["snapshot"]["retrieval_id"]
    source = dt.date.fromisoformat(source_date)
    raw_path = (
        Path(raw_root).expanduser()
        / f"{source.year:04d}"
        / f"{source.month:02d}"
        / f"{retrieval_id}-source-{source_date}.json"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists():
        if raw_path.read_bytes() != raw:
            raise ValueError("refusing to overwrite a mismatched vintage raw response")
    else:
        partial = raw_path.with_suffix(raw_path.suffix + ".part")
        partial.write_bytes(raw)
        os.replace(partial, raw_path)
    snapshot["source"] = {
        "url": url,
        "raw_path": str(raw_path),
        "official_reference": "https://docs.coinmetrics.io/api/v4",
    }
    return snapshot, raw_path


def write_onchain_vintage_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-coinmetrics-vintage-snapshot",
        path_key="artifact_path",
        default_filename="mini_trend_coinmetrics_vintage_snapshot.json",
        explicit_path=explicit_path,
    )
