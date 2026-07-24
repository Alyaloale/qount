"""R0-DATA point-in-time symbol lifecycle collection.

Collects Binance spot / USD-M (UM) / COIN-M (CM) exchangeInfo and turns each
symbol into a :class:`PointInTimeSymbolLifecycle` record with a listing date
(``valid_from``), optional delisting date (``valid_to``), lifecycle state, and
a hash of the trading rules at observation time.

The lifecycle records feed :func:`build_point_in_time_universe` to produce
frozen universe revisions that respect ``valid_from <= as_of < valid_to`` --
never using future listings or post-delisting survival to back-fill the past.

Pure parsing is split from IO (``fetch_exchange_info`` takes an injectable
fetcher; tests never touch the network).  The module is stdlib-only at import
time.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import urllib.request
from typing import Any
from typing import Callable
from typing import Mapping

from qount.governance.research_records import PointInTimeSymbolLifecycle


# --- Market endpoints -------------------------------------------------------

EXCHANGE_INFO_URLS: dict[str, str] = {
    "spot": "https://data-api.binance.vision/api/v3/exchangeInfo",
    "um": "https://fapi.binance.com/fapi/v1/exchangeInfo",
    "cm": "https://dapi.binance.com/dapi/v1/exchangeInfo",
}

VENUE_BY_MARKET: dict[str, str] = {
    "spot": "binance_spot",
    "um": "binance_um",
    "cm": "binance_cm",
}

# Binance status -> lifecycle state mapping.
_STATUS_MAP: dict[str, str] = {
    "TRADING": "active",
    "PENDING_TRADING": "suspended",
    "BREAK": "suspended",
    "HALT": "suspended",
    "END_OF_DAY": "suspended",
    "SETTLING": "suspended",
    "CLOSE": "delisted",
    "EXPIRED": "delisted",
}

DEFAULT_FETCH_TIMEOUT = 30


# --- IO (injectable fetcher) ------------------------------------------------


def _default_fetch(url: str) -> bytes:  # pragma: no cover - network
    with urllib.request.urlopen(url, timeout=DEFAULT_FETCH_TIMEOUT) as resp:
        return resp.read()


def fetch_exchange_info(
    *,
    market: str,
    fetch: Callable[[str], bytes] | None = None,
) -> tuple[dict[str, Any], str]:
    """Fetch exchangeInfo for *market* and return ``(payload, source_hash)``.

    ``source_hash`` is the SHA-256 of the raw response bytes, binding all
    downstream lifecycle records to the exact observation.
    """

    if market not in EXCHANGE_INFO_URLS:
        raise ValueError(f"unknown market {market!r} (expected spot/um/cm)")
    url = EXCHANGE_INFO_URLS[market]
    blob = (fetch or _default_fetch)(url)
    source_hash = hashlib.sha256(blob).hexdigest()
    payload = json.loads(blob.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise ValueError(f"{market} exchangeInfo payload must be an object with symbols list")
    return payload, source_hash


# --- Pure parsing -----------------------------------------------------------


def _normalize_ts(ts: int) -> int:
    """Normalize a possibly-microsecond epoch to milliseconds."""

    return ts // 1000 if ts >= 1_000_000_000_000_000 else ts


def _ts_to_iso(ts_ms: int) -> str:
    """Epoch-ms to an ISO-8601 UTC string."""

    return _dt.datetime.fromtimestamp(ts_ms / 1000, _dt.UTC).isoformat()


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _filter_map(symbol_info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in symbol_info.get("filters", []):
        if isinstance(item, dict) and item.get("filterType"):
            result[str(item["filterType"])] = item
    return result


def parse_lifecycle_state(symbol_info: dict[str, Any]) -> str:
    """Map a Binance symbol ``status`` to a lifecycle state."""

    status = str(symbol_info.get("status", "")).upper()
    return _STATUS_MAP.get(status, "unknown")


def parse_valid_from(symbol_info: dict[str, Any]) -> str | None:
    """Extract the listing date as ISO-8601, or ``None`` if not available.

    UM/CM exchangeInfo includes ``onboardDate``; spot does not (in the public
    API) -- the caller must fill that gap from the first available kline.
    """

    for key in ("onboardDate", "onboard_date"):
        ts = _safe_int(symbol_info.get(key))
        if ts is not None and ts > 0:
            return _ts_to_iso(_normalize_ts(ts))
    return None


def parse_valid_to(symbol_info: dict[str, Any]) -> str | None:
    """Extract the delisting / delivery date as ISO-8601, or ``None``.

    For CM dated quarterly contracts, ``deliveryDate`` is the settlement date.
    For delisted UM symbols, we rely on the availability scanner or external
    delisting records to provide the exact date; this returns ``None`` unless
    ``deliveryDate`` is present.
    """

    for key in ("deliveryDate", "delivery_date"):
        ts = _safe_int(symbol_info.get(key))
        if ts is not None and ts > 0:
            return _ts_to_iso(_normalize_ts(ts))
    return None


def build_rules_dict(symbol_info: dict[str, Any], *, market: str) -> dict[str, Any]:
    """Extract the tradeable rules into a canonical, hashable dict.

    The dict is deliberately flat and sorted so that the SHA-256 is stable
    across observation runs for unchanged rules.
    """

    filters = _filter_map(symbol_info)
    price = filters.get("PRICE_FILTER", {})
    lot = filters.get("LOT_SIZE", {})
    market_lot = filters.get("MARKET_LOT_SIZE", {})
    min_notional = filters.get("MIN_NOTIONAL", {})
    notional = filters.get("NOTIONAL", {})

    rules: dict[str, Any] = {
        "market": market,
        "symbol": str(symbol_info.get("symbol", "")).upper(),
        "status": str(symbol_info.get("status", "")).upper(),
        "tick_size": price.get("tickSize", ""),
        "step_size": lot.get("stepSize", ""),
        "market_step_size": market_lot.get("stepSize", ""),
        "min_qty": lot.get("minQty", ""),
        "max_qty": lot.get("maxQty", ""),
        "min_notional": min_notional.get("notional", min_notional.get("minNotional", notional.get("minNotional", ""))),
    }

    # UM/CM-specific fields.
    contract_type = symbol_info.get("contractType")
    if contract_type:
        rules["contract_type"] = str(contract_type)
    pair = symbol_info.get("pair")
    if pair:
        rules["pair"] = str(pair)

    return dict(sorted(rules.items()))


def build_rules_hash(rules_dict: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON encoding of *rules_dict*."""

    encoded = json.dumps(rules_dict, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def parse_symbol_symbol(symbol_info: dict[str, Any]) -> str:
    return str(symbol_info.get("symbol", "")).upper()


# --- Lifecycle record builder -----------------------------------------------


def build_lifecycle_from_symbol(
    symbol_info: dict[str, Any],
    *,
    market: str,
    source_hash: str,
    valid_from_override: str | None = None,
    valid_to_override: str | None = None,
) -> PointInTimeSymbolLifecycle | None:
    """Build one lifecycle record from a single exchangeInfo symbol entry.

    Returns ``None`` when the symbol has no listing date and no override is
    provided -- the caller may fill it later from the availability scanner.
    """

    symbol = parse_symbol_symbol(symbol_info)
    if not symbol:
        return None

    valid_from = valid_from_override or parse_valid_from(symbol_info)
    if valid_from is None:
        return None

    valid_to = valid_to_override or parse_valid_to(symbol_info)
    state = parse_lifecycle_state(symbol_info)

    # A delisted symbol without a known end date gets valid_to = valid_from
    # as a lower-bound sentinel? No -- the contract requires valid_to > valid_from.
    # If delisted but no deliveryDate, leave valid_to as None; the universe
    # builder will still exclude it because state != "active".
    if valid_to is not None:
        # Ensure valid_to > valid_from; otherwise drop it.
        try:
            from qount.contracts.trace import aware_datetime
            if aware_datetime(valid_to) <= aware_datetime(valid_from):
                valid_to = None
        except Exception:
            valid_to = None

    rules_dict = build_rules_dict(symbol_info, market=market)
    rules_hash = build_rules_hash(rules_dict)
    venue = VENUE_BY_MARKET.get(market, f"binance_{market}")

    return PointInTimeSymbolLifecycle.create(
        symbol=symbol,
        venue=venue,
        valid_from=valid_from,
        valid_to=valid_to,
        state=state,
        rules_hash=rules_hash,
        source_hash=source_hash,
    )


def build_lifecycle_from_exchange_info(
    exchange_info: dict[str, Any],
    *,
    market: str,
    source_hash: str,
    valid_from_overrides: Mapping[str, str] | None = None,
) -> list[PointInTimeSymbolLifecycle]:
    """Build lifecycle records for all symbols in an exchangeInfo payload.

    ``valid_from_overrides`` maps ``symbol -> ISO datetime`` for symbols that
    lack ``onboardDate`` (e.g. spot symbols whose listing date must come from
    the first available kline).
    """

    overrides = valid_from_overrides or {}
    records: list[PointInTimeSymbolLifecycle] = []
    symbols = exchange_info.get("symbols")
    if not isinstance(symbols, list):
        raise ValueError("exchangeInfo payload must contain symbols list")
    for item in symbols:
        if not isinstance(item, dict):
            continue
        record = build_lifecycle_from_symbol(
            item,
            market=market,
            source_hash=source_hash,
            valid_from_override=overrides.get(parse_symbol_symbol(item)),
        )
        if record is not None:
            errors = record.validate()
            if not errors:
                records.append(record)
    return records


# --- Availability probe (lightweight, no full download) --------------------


def probe_kline_month(
    symbol: str,
    year: int,
    month: int,
    *,
    market: str = "spot",
    fetch: Callable[[str], bytes] | None = None,
) -> bool:
    """Return ``True`` if a monthly kline zip exists on data.binance.vision.

    Uses a HEAD-like GET (data.binance.vision does not support HEAD); the
    fetcher is injectable so tests never hit the network.  Any exception
    (404, timeout, corrupt zip) is treated as ``False``.
    """

    from qount.grid.data import month_url

    url = month_url(symbol, "1d", year, month, market=market)
    try:
        blob = (fetch or _default_fetch)(url)
        return len(blob) > 0
    except Exception:
        return False


def infer_spot_listing_date(
    symbol: str,
    *,
    fetch: Callable[[str], bytes] | None = None,
    earliest_year: int = 2017,
) -> str | None:
    """Binary-search the first month with kline data to approximate listing.

    Only used for spot symbols that lack ``onboardDate``.  The search scans
    monthly from *earliest_year* to the current month.  Returns an ISO-8601
    UTC datetime for the first day of the first month with data.
    """

    now = _dt.datetime.now(_dt.UTC)
    # First pass: find the first year with any data.
    first_year: int | None = None
    first_month: int | None = None
    for year in range(earliest_year, now.year + 1):
        start_month = 1
        end_month = 12 if year < now.year else now.month
        for month in range(start_month, end_month + 1):
            if probe_kline_month(symbol, year, month, market="spot", fetch=fetch):
                first_year = year
                first_month = month
                break
        if first_year is not None:
            break

    if first_year is None or first_month is None:
        return None

    dt = _dt.datetime(first_year, first_month, 1, tzinfo=_dt.UTC)
    return dt.isoformat()


# --- Summary ----------------------------------------------------------------


def summarize_lifecycle_batch(
    records: list[PointInTimeSymbolLifecycle],
    *,
    market: str,
    source_hash: str,
    observed_at: str,
) -> dict[str, Any]:
    """Build a manifest summary for one market's lifecycle batch."""

    states: dict[str, int] = {}
    for record in records:
        states[record.state] = states.get(record.state, 0) + 1
    return {
        "market": market,
        "venue": VENUE_BY_MARKET.get(market, f"binance_{market}"),
        "observed_at": observed_at,
        "source_hash": source_hash,
        "total_symbols": len(records),
        "state_counts": dict(sorted(states.items())),
        "active_symbols": states.get("active", 0),
        "delisted_symbols": states.get("delisted", 0),
        "suspended_symbols": states.get("suspended", 0),
    }
