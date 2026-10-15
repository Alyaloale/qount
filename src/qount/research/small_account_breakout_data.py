"""Public-only, checksum-verified inputs for an isolated breakout experiment."""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import hashlib
import io
import json
import random
import os
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

UTC = dt.timezone.utc
BASE = "https://data.binance.vision/data/futures/um"


def timestamp(date: str) -> int:
    return int(dt.datetime.fromisoformat(date).replace(tzinfo=UTC).timestamp())


def selected_weeks(as_of: str, seed: int, count: int) -> list[str]:
    today = dt.date.fromisoformat(as_of)
    first = dt.date(today.year, 1, 1)
    first += dt.timedelta(days=(-first.weekday()) % 7)
    population = []
    while first + dt.timedelta(days=7) <= today:
        population.append(first.isoformat())
        first += dt.timedelta(days=7)
    rng = random.Random(seed)
    result = []
    for _ in range(count):
        value = rng.choice(population)
        population.remove(value)
        result.append(value)
    return result


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False) + "\n")


def _fetch(path: Path, url: str) -> None:
    if path.exists():
        return
    # No API key, account client, environment file or private endpoint.
    body = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                body = response.read()
            break
        except (OSError, urllib.error.URLError):
            if attempt == 2:
                raise
            time.sleep(1+2*attempt)
    if body is None:
        raise RuntimeError("public_download_failed")
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(body)
    temporary.replace(path)


def _archive(cache: Path, kind: str, symbol: str, interval: str,
             date: str, frequency: str) -> dict:
    name = f"{symbol}-{interval}-{date}.zip"
    url = f"{BASE}/{frequency}/{kind}/{symbol}/{interval}/{name}"
    path = cache / f"{kind}-{name}"
    _fetch(path, url)
    check = path.with_suffix(".zip.CHECKSUM")
    _fetch(check, url + ".CHECKSUM")
    expected = check.read_text().split()[0]
    if sha(path) != expected:
        raise ValueError(f"archive_checksum_mismatch:{path.name}")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"archive_crc_mismatch:{path.name}")
    return {"file": path.name, "url": url, "sha256": expected,
            "bytes": path.stat().st_size, "official_checksum_verified": True}


def archive_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise ValueError("expected_single_csv")
        with archive.open(names[0]) as raw:
            return [row for row in csv.reader(io.TextIOWrapper(raw))
                    if row and row[0].isdigit()]


def acquire(config: dict, cache: Path) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    weeks = selected_weeks(config["as_of"], config["random_seed"], config["week_count"])
    if weeks != config["draw_order"]:
        raise ValueError("sampling_mismatch")
    symbols = config["crypto_symbols"] + config["stock_symbols"]
    jobs = set()
    for week in weeks:
        start = dt.date.fromisoformat(week)
        for symbol in symbols:
            # Two days of continuous 15m warmup for equity contracts.
            for offset in range(-2 if symbol in config["stock_symbols"] else 0, 7):
                day = (start + dt.timedelta(days=offset)).isoformat()
                jobs.add(("klines", symbol, "1m", day, "daily"))
                jobs.add(("markPriceKlines", symbol, "1m", day, "daily"))
            if symbol in config["crypto_symbols"]:
                # Full calendar-month files, later cropped; future rows never enter features.
                for offset in range(-35, 7):
                    day = start + dt.timedelta(days=offset)
                    month = day.strftime("%Y-%m")
                    last_day = dt.date(day.year, day.month,
                                       calendar.monthrange(day.year, day.month)[1])
                    if last_day < dt.date.fromisoformat(config["as_of"]):
                        jobs.add(("klines", symbol, "1h", month, "monthly"))
                    else:
                        for offset in range(1, day.day + 1):
                            jobs.add(("klines", symbol, "1h",
                                      dt.date(day.year, day.month, offset).isoformat(), "daily"))
    receipts = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_archive, cache, *job) for job in sorted(jobs)]
        for i, future in enumerate(as_completed(futures), 1):
            receipts.append(future.result())
            if i % 50 == 0:
                print(f"verified archives {i}/{len(jobs)}", flush=True)
    _fetch(cache / "exchange-info.json", "https://fapi.binance.com/fapi/v1/exchangeInfo")
    receipts.append({"file": "exchange-info.json", "sha256": sha(cache / "exchange-info.json"),
                     "url": "https://fapi.binance.com/fapi/v1/exchangeInfo",
                     "historical_snapshot": False})
    for week in weeks:
        start = timestamp(week)
        for symbol in symbols:
            name = f"funding-{symbol}-{week}.json"
            # Prior 72h are for causal forecasts; following settlements only for accounting.
            url = (f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}"
                   f"&startTime={(start-3*86400)*1000}&endTime={(start+7*86400)*1000-1}"
                   "&limit=1000")
            _fetch(cache / name, url)
            rows = json.loads((cache / name).read_text())
            if not isinstance(rows, list) or not rows or len(rows) >= 1000:
                raise ValueError(f"incomplete_funding:{name}")
            times = [int(row["fundingTime"]) for row in rows]
            # Allow Special (dividend) funding at the same timestamp, never drop it.
            regular = sorted(int(row["fundingTime"]) for row in rows
                             if row.get("rateType", "Regular") == "Regular")
            if any(b-a > 8*3600*1000+10000 for a,b in zip(regular, regular[1:])):
                raise ValueError(f"funding_gap:{name}")
            if min(times) > (start-2*86400)*1000 or max(times) < (start+6*86400)*1000:
                raise ValueError(f"funding_edge_missing:{name}")
            receipts.append({"file": name, "sha256": sha(cache / name), "url": url,
                             "records": len(rows)})
    manifest = {"research_only": True, "orders_authorized": False,
                "observed_at": dt.datetime.now(UTC).isoformat(),
                "files": sorted(receipts, key=lambda row: row["file"])}
    write_json(cache / "manifest.json", manifest)
    return manifest


def acquire_continuous(config: dict, study: dict, cache: Path, reuse: Path) -> dict:
    """Extend public daily inputs in a separate cache; never change the pilot cache."""
    start = dt.date.fromisoformat(study["development_start"])
    end = dt.date.fromisoformat(study["development_end_exclusive"])
    if start.weekday() or (end-start).days % 7 or end <= start:
        raise ValueError("expected_complete_utc_weeks")
    cache.mkdir(parents=True, exist_ok=True)
    old = json.loads((reuse / "manifest.json").read_text())
    for row in old["files"]:
        source = reuse / row["file"]
        if sha(source) != row["sha256"]:
            raise ValueError(f"reuse_hash_mismatch:{source.name}")
        target = cache / source.name
        if not target.exists():
            os.link(source, target)
        check = source.with_suffix(source.suffix+".CHECKSUM")
        if check.exists() and not target.with_suffix(target.suffix+".CHECKSUM").exists():
            os.link(check, target.with_suffix(target.suffix+".CHECKSUM"))
    jobs = set()
    for symbol in config["crypto_symbols"]:
        for offset in range((end-start).days):
            date = (start+dt.timedelta(days=offset)).isoformat()
            for kind in ("klines", "markPriceKlines"):
                jobs.add((kind,symbol,"1m",date,"daily"))
        for offset in range(-35,(end-start).days):
            day = start+dt.timedelta(days=offset)
            last = dt.date(day.year,day.month,calendar.monthrange(day.year,day.month)[1])
            jobs.add(("klines",symbol,"1h",day.strftime("%Y-%m") if last < end else day.isoformat(),
                      "monthly" if last < end else "daily"))
    receipts = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_archive,cache,*job) for job in sorted(jobs)]
        for i,future in enumerate(as_completed(futures),1):
            receipts.append(future.result())
            if i % 100 == 0:
                print(f"continuous archives verified {i}/{len(jobs)}",flush=True)
    receipts.append({"file":"exchange-info.json","sha256":sha(cache/"exchange-info.json"),
                     "historical_snapshot":False,"source":"reused pilot snapshot"})
    for offset in range(0,(end-start).days,7):
        week = (start+dt.timedelta(days=offset)).isoformat()
        t = timestamp(week)
        for symbol in config["crypto_symbols"]:
            name = f"funding-{symbol}-{week}.json"
            url = (f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}"
                   f"&startTime={(t-3*86400)*1000}&endTime={(t+7*86400)*1000-1}&limit=1000")
            _fetch(cache/name,url)
            rows = json.loads((cache/name).read_text())
            if not isinstance(rows,list) or not rows or len(rows)>=1000:
                raise ValueError(f"incomplete_funding:{name}")
            regular = sorted(int(r["fundingTime"]) for r in rows if r.get("rateType","Regular")=="Regular")
            if (not regular or regular[0]>(t-2*86400)*1000 or regular[-1]<(t+6*86400)*1000
                    or any(b-a>8*3600000+15000 for a,b in zip(regular,regular[1:]))):
                raise ValueError(f"funding_coverage_gap:{name}")
            receipts.append({"file":name,"sha256":sha(cache/name),"url":url,"records":len(rows)})
    result = {"research_only":True,"orders_authorized":False,"files":sorted(receipts,key=lambda r:r["file"]),
              "funding_interval_snapshots":[],"funding_interval_history_status":"missing_use_causal_assumption"}
    write_json(cache/"continuous-manifest.json",result)
    return result
