"""Public historical panels for exploratory, no-order ETF evaluation.

Require every risk asset and the cash ETF. Never invent missing prices or volume.
Yahoo quote OHLC is split-adjusted, but not dividend-adjusted; Adj Close includes
distributions. Reject splits in the panel because the share simulator has no split
event support. The public Yahoo source is an explicit alternative to the P0 Tiingo
contract, not certification of that contract.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import urllib.request
from pathlib import Path

import numpy as np

from .costs import cost_params_for
from .env import MarketData
from .scorer import daily_returns, rolling_mean, rolling_std
from .universe import Account, US_ACCOUNT


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download_public_panel(out: Path, start: str, end: str) -> dict:
    """Fetch all ten US ETFs, including raw open/close and adjusted close.

    Dates are inclusive. The downloader has no credential input or env loading.
    Refuse existing outputs; a failed download never creates a complete manifest.
    """
    out.mkdir(parents=True, exist_ok=False)
    first = int(dt.datetime.combine(dt.date.fromisoformat(start), dt.time(), dt.timezone.utc).timestamp())
    last = int(dt.datetime.combine(dt.date.fromisoformat(end) + dt.timedelta(days=1), dt.time(), dt.timezone.utc).timestamp())
    manifest = {"source": "Yahoo Finance public chart", "start": start, "end": end,
                "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "research_only": True, "orders_authorized": False, "files": {}}
    for symbol in (*US_ACCOUNT.symbols, US_ACCOUNT.cash_symbol):
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               f"?period1={first}&period2={last}&interval=1d&events=div%2Csplits")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
        result = body["chart"]["result"][0]
        splits = result.get("events", {}).get("splits", {})
        if splits and symbol != US_ACCOUNT.cash_symbol:
            raise ValueError(f"{symbol}: split events need a split-aware accounting engine")
        raw = out / f"{symbol}.source.json"
        raw.write_text(json.dumps(result, separators=(",", ":")))
        quote = result["indicators"]["quote"][0]
        adjusted = result["indicators"]["adjclose"][0]["adjclose"]
        path = out / f"{symbol}_daily.csv"
        count = 0
        missing = []
        with path.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Date", "Open", "Close", "Adj Close", "Volume"])
            for i, timestamp in enumerate(result["timestamp"]):
                date = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date().isoformat()
                values = [quote["open"][i], quote["close"][i], adjusted[i], quote["volume"][i]]
                if not start <= date <= end:
                    continue
                if any(v is None for v in values):
                    missing.append(date)
                    continue
                writer.writerow([date, *values])
                count += 1
        if not count:
            raise ValueError(f"{symbol}: no valid daily bars")
        manifest["files"][symbol] = {"file": path.name, "sha256": file_hash(path), "rows": count,
                                      "raw_file": raw.name, "raw_sha256": file_hash(raw),
                                      "url": url, "missing_dates": missing, "split_events": len(splits),
                                      "split_use": "cash adjusted-return only" if symbol == US_ACCOUNT.cash_symbol else "no splits"}
        print(f"{symbol}: {count} bars", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_panel(root: Path, account: Account, end: str) -> tuple[MarketData, list[str], dict]:
    """Load all history up to end; warmup is retained before the evaluation start."""
    manifest = json.loads((root / "manifest.json").read_text())
    series = {}
    hashes = {}
    for symbol in (*account.symbols, account.cash_symbol):
        entry = manifest["files"][symbol]
        if symbol != account.cash_symbol and entry.get("split_events") != 0:
            raise ValueError(f"{symbol}: split audit missing or nonzero")
        path = root / f"{symbol}_daily.csv"
        digest = file_hash(path)
        if digest != entry["sha256"]:
            raise ValueError(f"{symbol}: source hash mismatch")
        hashes[path.name] = digest
        rows = {}
        previous = ""
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"Date", "Open", "Close", "Adj Close", "Volume"}.issubset(reader.fieldnames or []):
                raise ValueError(f"{symbol}: raw and adjusted prices plus volume required")
            for row in reader:
                date = row["Date"]
                dt.date.fromisoformat(date)
                if date <= previous:
                    raise ValueError(f"{symbol}: duplicate or unsorted date")
                previous = date
                values = np.array([float(row[k]) for k in ("Open", "Close", "Adj Close", "Volume")])
                if not np.isfinite(values).all() or np.any(values[:3] <= 0) or values[3] <= 0:
                    raise ValueError(f"{symbol}: invalid bar on {date}")
                if date <= end:
                    rows[date] = values
        if not rows:
            raise ValueError(f"{symbol}: empty history")
        series[symbol] = rows
    first = max(min(rows) for rows in series.values())
    last = min(max(rows) for rows in series.values())
    sets = [{d for d in rows if first <= d <= last} for rows in series.values()]
    common, union = set.intersection(*sets), set.union(*sets)
    if len(common) < 0.995 * len(union):
        raise ValueError("common calendar coverage below 99.5%")
    dates = sorted(common)
    panel = np.stack([[series[s][d] for s in account.symbols] for d in dates])
    opn, close, adjusted, volume = [panel[:, :, k] for k in range(4)]
    adv = rolling_mean(volume * close, 20)
    sigma = rolling_std(daily_returns(adjusted), 63)
    cash_close = np.array([series[account.cash_symbol][d][2] for d in dates])
    cash_return = np.r_[0.0, cash_close[1:] / cash_close[:-1] - 1.0]
    half = np.tile(cost_params_for(account).half_spread, (len(dates), 1))
    # Warmup rows are never traded. Keep finite early placeholders out of policy
    # decisions by requiring a complete feature warmup in the evaluation adapter.
    data = MarketData(adjusted, close, opn, np.nan_to_num(adv), np.nan_to_num(sigma), cash_return, spread=half)
    audit = {"source": manifest["source"], "source_manifest_sha256": file_hash(root / "manifest.json"),
             "files": hashes, "first": dates[0], "last": dates[-1], "rows": len(dates),
             "excluded_calendar_dates": sorted(union - common), "cash_source": account.cash_symbol,
             "value_enabled": False, "spread": "repository static estimates; not observed quotes",
             "prices": "split-consistent OHLC; adjusted close for total-return distributions"}
    return data, dates, audit
