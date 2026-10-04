"""Strict public panel adapter with explicit ex-date distributions and share splits.

Yahoo OHLC and distributions are on the latest split basis. Restore nominal
historical share units using the recorded splits, then build causal total-return
indices from raw prices/events. Adj Close is an audit comparator, never an input.
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from qount.research.etf_trader.universe import US_ACCOUNT

from .artifacts import read_json, sha256, verify_files


@dataclass(frozen=True)
class Panel:
    dates: tuple[str, ...]
    symbols: tuple[str, ...]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    dividends: np.ndarray  # ex-date cash per post-split share
    splits: np.ndarray  # shares after / shares before, effective before ex-date open
    cash_open: np.ndarray
    cash_close: np.ndarray
    audit: dict

    def __post_init__(self) -> None:
        shape = (len(self.dates), len(self.symbols))
        if len(set(self.symbols)) != len(self.symbols) or not self.dates:
            raise ValueError("unique assets and a nonempty calendar required")
        if tuple(sorted(set(self.dates))) != self.dates:
            raise ValueError("calendar must be sorted and unique")
        for day in self.dates:
            dt.date.fromisoformat(day)
        for name in ("open", "high", "low", "close", "volume", "dividends", "splits"):
            arr = np.asarray(getattr(self, name))
            if arr.shape != shape:
                raise ValueError(f"{name}: panel shape mismatch")
            finite = np.isfinite(arr)
            if name == "dividends":
                if not finite.all() or (arr < 0).any():
                    raise ValueError("distributions must be known and nonnegative")
            elif name == "splits":
                if not finite.all() or (arr <= 0).any():
                    raise ValueError("split ratios must be known and positive")
            elif (arr[finite] <= 0).any():
                raise ValueError(f"{name}: nonpositive observation")
        for name in ("cash_open", "cash_close"):
            if np.shape(getattr(self, name)) != (len(self.dates),):
                raise ValueError(f"{name}: calendar mismatch")

    def prefix(self, stop: int) -> "Panel":
        fields = {name: getattr(self, name)[:stop].copy() for name in
                  ("open", "high", "low", "close", "volume", "dividends", "splits", "cash_open", "cash_close")}
        return Panel(self.dates[:stop], self.symbols, **fields, audit=self.audit)

    def reordered(self, symbols: tuple[str, ...]) -> "Panel":
        if set(symbols) != set(self.symbols) or len(symbols) != len(self.symbols):
            raise ValueError("reordering must preserve the universe")
        order = [self.symbols.index(s) for s in symbols]
        fields = {name: getattr(self, name)[:, order].copy() for name in
                  ("open", "high", "low", "close", "volume", "dividends", "splits")}
        return Panel(self.dates, symbols, **fields, cash_open=self.cash_open.copy(),
                     cash_close=self.cash_close.copy(), audit=self.audit)


def total_return_index(price: np.ndarray, dividends: np.ndarray, splits: np.ndarray) -> np.ndarray:
    """Fractional units, distributions reinvested at the same ex-date mark.

    A buyer at ex-date open gets no distribution for that date. A holder selling
    at that open retains it. Gaps break the index; downstream windows must require
    continuous observations. No future normalization or vendor factor is used.
    """
    price = np.asarray(price, dtype=float)
    if price.shape != np.shape(dividends) or price.shape != np.shape(splits):
        raise ValueError("event and price shapes differ")
    out = np.full_like(price, np.nan)
    for t in range(len(price)):
        valid = np.isfinite(price[t]) & (price[t] > 0)
        if t == 0:
            out[t] = np.where(valid, price[t], np.nan)
        else:
            continuing = valid & np.isfinite(price[t - 1]) & np.isfinite(out[t - 1])
            gross = (splits[t] * (price[t] + dividends[t])) / price[t - 1]
            out[t] = np.where(continuing, out[t - 1] * gross, np.where(valid, price[t], np.nan))
    return out


def _date(timestamp: int, zone: str) -> str:
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).astimezone(ZoneInfo(zone)).date().isoformat()


def _series(root: Path, symbol: str, entry: dict, start: str, end: str) -> dict:
    raw = read_json(root / entry["raw_file"])
    if raw["meta"]["symbol"] != symbol:
        raise ValueError(f"{symbol}: source identity mismatch")
    zone = raw["meta"]["exchangeTimezoneName"]
    dates = [_date(t, zone) for t in raw["timestamp"]]
    if dates != sorted(set(dates)):
        raise ValueError(f"{symbol}: unsorted/duplicate source sessions")
    quote = raw["indicators"]["quote"][0]
    names = ("open", "high", "low", "close", "volume")
    arrays = {k: np.asarray([np.nan if v is None else v for v in quote[k]], float) for k in names}
    if any(len(v) != len(dates) for v in arrays.values()):
        raise ValueError(f"{symbol}: source array length mismatch")
    dividends, splits = np.zeros(len(dates)), np.ones(len(dates))
    positions = {d: i for i, d in enumerate(dates)}
    events = raw.get("events", {})
    if len(events.get("splits", {})) != entry["split_events"]:
        raise ValueError(f"{symbol}: split declaration mismatch")
    for kind in ("dividends", "splits"):
        for event in events.get(kind, {}).values():
            day = _date(event["date"], zone)
            if day not in positions:
                raise ValueError(f"{symbol}: event outside source sessions")
            i = positions[day]
            if kind == "dividends":
                dividends[i] += float(event["amount"])
            else:
                ratio = float(event["numerator"]) / float(event["denominator"])
                if not np.isfinite(ratio) or ratio <= 0:
                    raise ValueError(f"{symbol}: invalid split")
                splits[i] *= ratio
    if any(entry.get("missing_dates", [])):
        raise ValueError(f"{symbol}: source manifest has missing sessions")
    csv_rows = {}
    previous = ""
    with (root / entry["file"]).open(newline="") as stream:
        for row in csv.DictReader(stream):
            day = row["Date"]
            if day <= previous:
                raise ValueError(f"{symbol}: unsorted/duplicate canonical sessions")
            previous = day
            csv_rows[day] = row
    adjusted = np.asarray(raw["indicators"]["adjclose"][0]["adjclose"], float)
    for i, day in enumerate(dates):
        if not start <= day <= end:
            continue
        row = csv_rows.get(day)
        if row is None or not np.allclose([float(row[k]) for k in ("Open", "Close", "Adj Close", "Volume")],
                                          [arrays["open"][i], arrays["close"][i], adjusted[i], arrays["volume"][i]],
                                          rtol=0, atol=1e-10):
            raise ValueError(f"{symbol}: source/canonical disagreement on {day}")
    # Reverse the source's future split adjustment. Cash ETF volume is not traded;
    # historical volume adjustment conventions remain a stated source limitation.
    future_splits = np.ones(len(dates))
    for i in range(len(dates) - 2, -1, -1):
        future_splits[i] = future_splits[i + 1] * splits[i + 1]
    for name in ("open", "high", "low", "close"):
        arrays[name] *= future_splits
    arrays["volume"] /= future_splits
    dividends *= future_splits
    take = np.array([start <= day <= end for day in dates])
    selected = tuple(day for day in dates if start <= day <= end)
    fields = {name: arr[take] for name, arr in arrays.items()}
    if any(not np.isfinite(arr).all() or (arr <= 0).any() for arr in fields.values()):
        raise ValueError(f"{symbol}: invalid/missing OHLCV")
    if np.any(fields["low"] > np.minimum(fields["open"], fields["close"]) + 1e-5) or np.any(
        fields["high"] < np.maximum(fields["open"], fields["close"]) - 1e-5):
        raise ValueError(f"{symbol}: invalid OHLC ordering")
    return fields | {"dates": selected, "dividends": dividends[take], "splits": splits[take],
                     "vendor_adjusted": adjusted[take], "event_counts": {k: len(v) for k, v in events.items()}}


def load_public_panel(root: Path, end: str = "2026-10-01") -> Panel:
    manifest = read_json(root / "manifest.json")
    if manifest.get("research_only") is not True or manifest.get("orders_authorized") is not False:
        raise ValueError("research-only source contract required")
    required = (*US_ACCOUNT.symbols, US_ACCOUNT.cash_symbol)
    if not set(required).issubset(manifest["files"]):
        raise ValueError("complete nine-ETF plus BIL source required")
    files = {}
    for symbol in required:
        entry = manifest["files"][symbol]
        files[entry["file"]] = entry["sha256"]
        files[entry["raw_file"]] = entry["raw_sha256"]
    verify_files(root, files)
    end = min(end, manifest["end"])
    series = {s: _series(root, s, manifest["files"][s], manifest["start"], end) for s in required}
    dates = series["SPY"]["dates"]
    if not dates or any(v["dates"] != dates for v in series.values()):
        raise ValueError("calendar mismatch; no common-date deletion is allowed")
    if any(dt.date.fromisoformat(day).weekday() >= 5 for day in dates):
        raise ValueError("unexpected weekend session")
    risk = {name: np.column_stack([series[s][name] for s in US_ACCOUNT.symbols]) for name in
            ("open", "high", "low", "close", "volume", "dividends", "splits")}
    cash = series["BIL"]
    cash_open = total_return_index(cash["open"], cash["dividends"], cash["splits"])
    cash_close = total_return_index(cash["close"], cash["dividends"], cash["splits"])
    reconciliation = {}
    for s in required:
        item = series[s]
        rebuilt = total_return_index(item["close"], item["dividends"], item["splits"])
        vendor = item["vendor_adjusted"]
        difference = rebuilt[1:] / rebuilt[:-1] - vendor[1:] / vendor[:-1]
        ex_date = item["dividends"][1:] > 0
        reconciliation[s] = {"maximum_daily_return_difference": float(np.max(np.abs(difference))),
                             "maximum_non_ex_date_difference": float(np.max(np.abs(difference[~ex_date]))) if (~ex_date).any() else None,
                             "interpretation": "event-based cash return and vendor multiplicative adjustment are different conventions"}
    audit = {"source": manifest["source"], "source_root": str(root),
             "source_manifest_sha256": sha256(root / "manifest.json"), "files": files,
             "observed_at": manifest["observed_at"], "first": dates[0], "last": dates[-1],
             "sessions": len(dates), "excluded_calendar_dates": [], "value_enabled": False,
             "calendar": "exact ten-source session agreement; independent exchange calendar not supplied",
             "availability": "OHLCV/event-date information used only after that close; retrospective source snapshot",
             "historical_asof_provenance": False, "distribution_payment_dates_available": False,
             "event_counts": {s: series[s]["event_counts"] for s in required},
             "vendor_reconciliation": reconciliation,
             "cash": "BIL event-based total-return proxy, no BIL share orders or transaction costs",
             "price_basis": "nominal OHLC reconstructed from recorded split events; adjusted close audit only"}
    return Panel(dates, US_ACCOUNT.symbols, **risk, cash_open=cash_open, cash_close=cash_close, audit=audit)
