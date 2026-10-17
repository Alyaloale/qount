"""The single Binance USD-M asset mapping used by QOUNT boundaries.

The file is intentionally small and declarative. It describes identity and data source;
it does not grant order authority or replace live exchange rule snapshots.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ASSET_PATH = "config/binance-assets.json"
STATUSES = frozenset({"active", "reference", "disabled"})


@dataclass(frozen=True)
class BinanceAsset:
    asset_id: str
    signal_symbol: str
    execution_symbol: str
    venue: str
    status: str
    price_source: str

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        for field in ("asset_id", "signal_symbol", "execution_symbol", "price_source"):
            if not getattr(self, field).strip():
                errors.append(f"{field}_empty")
        if self.venue != "binance_usdm":
            errors.append("venue_invalid")
        if self.status not in STATUSES:
            errors.append("status_invalid")
        if self.execution_symbol != self.execution_symbol.upper():
            errors.append("execution_symbol_not_uppercase")
        if not self.execution_symbol.endswith("USDT"):
            errors.append("execution_symbol_not_usdt")
        return tuple(errors)

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _asset_path(path: str | os.PathLike[str] | None) -> Path:
    return Path(path or os.environ.get("QOUNT_BINANCE_ASSETS_PATH", DEFAULT_ASSET_PATH))


def _parse_assets(payload: Any, source: Path) -> tuple[BinanceAsset, ...]:
    if not isinstance(payload, dict) or payload.get("venue") != "binance_usdm":
        raise ValueError(f"binance_asset_mapping_invalid_venue:{source}")
    if payload.get("quote_asset") != "USDT":
        raise ValueError(f"binance_asset_mapping_invalid_quote:{source}")
    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ValueError(f"binance_asset_mapping_empty:{source}")

    assets: list[BinanceAsset] = []
    for index, raw in enumerate(raw_assets):
        if not isinstance(raw, dict):
            raise ValueError(f"binance_asset_mapping_row_invalid:{source}:{index}")
        try:
            asset = BinanceAsset(
                asset_id=str(raw["asset_id"]),
                signal_symbol=str(raw["signal_symbol"]),
                execution_symbol=str(raw["execution_symbol"]),
                venue=str(raw["venue"]),
                status=str(raw["status"]),
                price_source=str(raw["price_source"]),
            )
        except KeyError as exc:
            raise ValueError(f"binance_asset_mapping_field_missing:{source}:{index}:{exc.args[0]}") from exc
        errors = asset.validate()
        if errors:
            raise ValueError(f"binance_asset_mapping_row_invalid:{source}:{index}:{','.join(errors)}")
        assets.append(asset)

    ids = [asset.asset_id for asset in assets]
    signals = [asset.signal_symbol for asset in assets]
    executions = [asset.execution_symbol for asset in assets]
    for label, values in (("asset_id", ids), ("signal_symbol", signals), ("execution_symbol", executions)):
        if len(values) != len(set(values)):
            raise ValueError(f"binance_asset_mapping_duplicate:{label}:{source}")
    return tuple(assets)


def load_binance_assets(path: str | os.PathLike[str] | None = None) -> tuple[BinanceAsset, ...]:
    source = _asset_path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"binance_asset_mapping_unreadable:{source}:{type(exc).__name__}") from exc
    return _parse_assets(payload, source)


def asset_by_execution_symbol(symbol: str, *, assets: Iterable[BinanceAsset] | None = None) -> BinanceAsset | None:
    wanted = str(symbol).strip().upper()
    candidates = load_binance_assets() if assets is None else assets
    return next((asset for asset in candidates if asset.execution_symbol == wanted), None)


def asset_by_signal_symbol(symbol: str, *, assets: Iterable[BinanceAsset] | None = None) -> BinanceAsset | None:
    wanted = str(symbol).strip().upper()
    candidates = load_binance_assets() if assets is None else assets
    return next((asset for asset in candidates if asset.signal_symbol == wanted), None)


def execution_to_signal_map(
    *,
    assets: Iterable[BinanceAsset] | None = None,
    asset_ids: set[str] | frozenset[str] | None = None,
) -> dict[str, str]:
    candidates = load_binance_assets() if assets is None else assets
    return {
        asset.execution_symbol: asset.signal_symbol
        for asset in candidates
        if asset.status != "disabled" and (asset_ids is None or asset.asset_id in asset_ids)
    }


def asset_mapping_payload(*, assets: Iterable[BinanceAsset] | None = None) -> dict[str, Any]:
    selected = tuple(load_binance_assets() if assets is None else assets)
    return {
        "schema_version": 1,
        "venue": "binance_usdm",
        "quote_asset": "USDT",
        "assets": [asset.as_dict() for asset in selected],
    }

