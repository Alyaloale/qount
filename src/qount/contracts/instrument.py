"""Cross-asset instrument identity and product-level trading capabilities."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.contracts.trace import trace_id


INSTRUMENT_CONTRACT_SCHEMA_VERSION = 1

ASSET_CLASSES = (
    "commodity",
    "crypto",
    "equity",
    "etf",
    "fx",
    "index",
)
PRODUCT_KINDS = (
    "cash_equity",
    "equity_perpetual",
    "future",
    "option",
    "perpetual",
    "spot",
    "tokenized_equity",
)

_LOWER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MARKET_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._:/-]{0,127}$")
_INSTRUMENT_KEY_RE = re.compile(
    r"^[a-z][a-z0-9_]{0,63}\|[a-z][a-z0-9_]{0,63}"
    r"\|[a-z][a-z0-9_]{0,63}\|[A-Z0-9][A-Z0-9._:/-]{0,127}"
    r"\|[A-Z0-9][A-Z0-9._:/-]{0,127}$"
)


@dataclass(frozen=True)
class InstrumentId:
    """Canonical identity for one venue product, not merely its underlying."""

    schema_version: int
    instrument_id: str
    instrument_key: str
    venue: str
    symbol: str
    asset_class: str
    product_kind: str
    underlying: str
    price_currency: str
    settlement_asset: str
    multiplier: float
    session_calendar: str
    instrument_hash: str

    @classmethod
    def create(
        cls,
        *,
        venue: str,
        symbol: str,
        asset_class: str,
        product_kind: str,
        underlying: str,
        price_currency: str,
        settlement_asset: str,
        multiplier: float = 1.0,
        session_calendar: str = "continuous",
    ) -> InstrumentId:
        normalized_venue = str(venue).lower()
        normalized_symbol = str(symbol).upper()
        normalized_asset_class = str(asset_class).lower()
        normalized_product_kind = str(product_kind).lower()
        normalized_underlying = str(underlying).upper()
        normalized_price_currency = str(price_currency).upper()
        normalized_settlement = str(settlement_asset).upper()
        normalized_calendar = str(session_calendar).lower()
        normalized_multiplier = float(multiplier)
        instrument_key = "|".join(
            (
                normalized_venue,
                normalized_asset_class,
                normalized_product_kind,
                normalized_symbol,
                normalized_settlement,
            )
        )
        core = {
            "schema_version": INSTRUMENT_CONTRACT_SCHEMA_VERSION,
            "instrument_key": instrument_key,
            "venue": normalized_venue,
            "symbol": normalized_symbol,
            "asset_class": normalized_asset_class,
            "product_kind": normalized_product_kind,
            "underlying": normalized_underlying,
            "price_currency": normalized_price_currency,
            "settlement_asset": normalized_settlement,
            "multiplier": normalized_multiplier,
            "session_calendar": normalized_calendar,
        }
        instrument_hash = canonical_hash(core)
        instrument = cls(
            **core,
            instrument_id=trace_id(
                "instrument_identity",
                {"instrument_hash": instrument_hash},
            ),
            instrument_hash=instrument_hash,
        )
        errors = instrument.validate()
        if errors:
            raise ValueError(f"instrument_id_invalid:{','.join(errors)}")
        return instrument

    def _core(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "instrument_key": self.instrument_key,
            "venue": self.venue,
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "product_kind": self.product_kind,
            "underlying": self.underlying,
            "price_currency": self.price_currency,
            "settlement_asset": self.settlement_asset,
            "multiplier": self.multiplier,
            "session_calendar": self.session_calendar,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != INSTRUMENT_CONTRACT_SCHEMA_VERSION:
            errors.append("instrument_schema_version_invalid")
        for name in ("venue", "session_calendar"):
            if not _LOWER_NAME_RE.fullmatch(str(getattr(self, name))):
                errors.append(f"instrument_{name}_invalid")
        if self.asset_class not in ASSET_CLASSES:
            errors.append("instrument_asset_class_invalid")
        if self.product_kind not in PRODUCT_KINDS:
            errors.append("instrument_product_kind_invalid")
        for name in (
            "symbol",
            "underlying",
            "price_currency",
            "settlement_asset",
        ):
            if not _MARKET_CODE_RE.fullmatch(str(getattr(self, name))):
                errors.append(f"instrument_{name}_invalid")
        try:
            multiplier = float(self.multiplier)
        except (TypeError, ValueError):
            multiplier = math.nan
        if not math.isfinite(multiplier) or multiplier <= 0.0:
            errors.append("instrument_multiplier_invalid")
        expected_key = "|".join(
            (
                self.venue,
                self.asset_class,
                self.product_kind,
                self.symbol,
                self.settlement_asset,
            )
        )
        if (
            not _INSTRUMENT_KEY_RE.fullmatch(str(self.instrument_key))
            or self.instrument_key != expected_key
        ):
            errors.append("instrument_key_invalid")
        expected_hash = canonical_hash(self._core())
        if self.instrument_hash != expected_hash:
            errors.append("instrument_hash_invalid")
        expected_id = trace_id(
            "instrument_identity",
            {"instrument_hash": expected_hash},
        )
        if self.instrument_id != expected_id:
            errors.append("instrument_id_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class ProductCapability:
    """Observed execution permissions for one exact instrument product."""

    schema_version: int
    capability_id: str
    instrument_key: str
    observed_at: str
    source_hash: str
    long_allowed: bool
    short_allowed: bool
    buy_allowed: bool
    sell_allowed: bool
    sell_close_only: bool
    reduce_only_supported: bool
    fractional_supported: bool
    funding_applicable: bool
    order_types: tuple[str, ...]
    trading_sessions: tuple[str, ...]
    capability_hash: str

    @classmethod
    def create(
        cls,
        *,
        instrument_key: str,
        observed_at: str,
        source_hash: str,
        long_allowed: bool,
        short_allowed: bool,
        buy_allowed: bool,
        sell_allowed: bool,
        sell_close_only: bool,
        reduce_only_supported: bool,
        fractional_supported: bool,
        funding_applicable: bool,
        order_types: Sequence[str],
        trading_sessions: Sequence[str],
    ) -> ProductCapability:
        normalized_order_types = tuple(str(value).upper() for value in order_types)
        normalized_sessions = tuple(str(value).upper() for value in trading_sessions)
        core = {
            "schema_version": INSTRUMENT_CONTRACT_SCHEMA_VERSION,
            "instrument_key": str(instrument_key),
            "observed_at": observed_at,
            "source_hash": source_hash,
            "long_allowed": long_allowed,
            "short_allowed": short_allowed,
            "buy_allowed": buy_allowed,
            "sell_allowed": sell_allowed,
            "sell_close_only": sell_close_only,
            "reduce_only_supported": reduce_only_supported,
            "fractional_supported": fractional_supported,
            "funding_applicable": funding_applicable,
            "order_types": normalized_order_types,
            "trading_sessions": normalized_sessions,
        }
        capability_hash = canonical_hash(core)
        capability = cls(
            **core,
            capability_id=trace_id(
                "product_capability",
                {"capability_hash": capability_hash},
            ),
            capability_hash=capability_hash,
        )
        errors = capability.validate()
        if errors:
            raise ValueError(f"product_capability_invalid:{','.join(errors)}")
        return capability

    def _core(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "instrument_key": self.instrument_key,
            "observed_at": self.observed_at,
            "source_hash": self.source_hash,
            "long_allowed": self.long_allowed,
            "short_allowed": self.short_allowed,
            "buy_allowed": self.buy_allowed,
            "sell_allowed": self.sell_allowed,
            "sell_close_only": self.sell_close_only,
            "reduce_only_supported": self.reduce_only_supported,
            "fractional_supported": self.fractional_supported,
            "funding_applicable": self.funding_applicable,
            "order_types": tuple(self.order_types),
            "trading_sessions": tuple(self.trading_sessions),
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != INSTRUMENT_CONTRACT_SCHEMA_VERSION:
            errors.append("product_capability_schema_version_invalid")
        if not _INSTRUMENT_KEY_RE.fullmatch(str(self.instrument_key)):
            errors.append("product_capability_instrument_key_invalid")
        try:
            aware_datetime(self.observed_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("product_capability_observed_at_invalid")
        if not is_sha256(self.source_hash):
            errors.append("product_capability_source_hash_invalid")
        for name in (
            "long_allowed",
            "short_allowed",
            "buy_allowed",
            "sell_allowed",
            "sell_close_only",
            "reduce_only_supported",
            "fractional_supported",
            "funding_applicable",
        ):
            if not isinstance(getattr(self, name), bool):
                errors.append(f"product_capability_{name}_invalid")
        if self.long_allowed and not self.buy_allowed:
            errors.append("product_capability_long_without_buy")
        if self.short_allowed and not self.sell_allowed:
            errors.append("product_capability_short_without_sell")
        if self.sell_close_only and not self.sell_allowed:
            errors.append("product_capability_sell_close_without_sell")
        if self.sell_close_only and self.short_allowed:
            errors.append("product_capability_sell_close_allows_short")
        if not self.order_types:
            errors.append("product_capability_order_types_empty")
        elif len(self.order_types) != len(set(self.order_types)):
            errors.append("product_capability_order_types_duplicate")
        if not self.trading_sessions:
            errors.append("product_capability_trading_sessions_empty")
        elif len(self.trading_sessions) != len(set(self.trading_sessions)):
            errors.append("product_capability_trading_sessions_duplicate")
        for name, values in (
            ("order_type", self.order_types),
            ("trading_session", self.trading_sessions),
        ):
            for value in values:
                if not _MARKET_CODE_RE.fullmatch(str(value)):
                    errors.append(f"product_capability_{name}_invalid:{value}")
        expected_hash = canonical_hash(self._core())
        if self.capability_hash != expected_hash:
            errors.append("product_capability_hash_invalid")
        expected_id = trace_id(
            "product_capability",
            {"capability_hash": expected_hash},
        )
        if self.capability_id != expected_id:
            errors.append("product_capability_id_invalid")
        return tuple(errors)
