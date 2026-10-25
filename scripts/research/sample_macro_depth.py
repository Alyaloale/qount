#!/usr/bin/env python3
"""Bounded public REST L2 observation, with no orders or persistent collector."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

from qount.research_data.binance_history import public_get


def fetch(symbol):
    start, mono = time.time(), time.monotonic()
    try:
        book = public_get("/fapi/v1/depth", dict(symbol=symbol, limit=100))
        return dict(symbol=symbol, start=start, received=time.time(),
                    elapsed=time.monotonic()-mono, book=book)
    except Exception as exc:
        return dict(symbol=symbol, start=start, received=time.time(),
                    elapsed=time.monotonic()-mono, error=type(exc).__name__)


def visible(book, limit, side):
    levels = [(float(p), float(q)) for p, q in book["asks" if side == 1 else "bids"]]
    quantity = sum(q for p, q in levels if p <= limit) if side == 1 else sum(
        q for p, q in levels if p >= limit)
    complete = levels[-1][0] > limit if side == 1 else levels[-1][0] < limit
    return quantity, complete


def analyze(rows, offset):
    output = {}
    for symbol in sorted({r["symbol"] for r in rows}):
        records = [r for r in rows if r["symbol"] == symbol]
        valid = []
        invalid = 0
        for row in records:
            if "book" not in row:
                continue
            book = row["book"]
            bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
            age = row["received"]+offset-book["T"]/1000
            if not 0 < bid < ask or not -.5 <= age <= 5:
                invalid += 1
                continue
            valid.append(dict(row, midpoint=(bid+ask)/2, age=age,
                              spread_bps=(ask-bid)/((bid+ask)/2)*10000))
        comparisons = {}
        for side, label in ((1, "buy"), (-1, "sell")):
            for horizon in (2, 10, 30, 60):
                pairs = []
                for quote in valid:
                    arrival = next((r for r in valid if r["received"] >= quote["received"]+horizon), None)
                    if arrival is None or arrival["received"]-quote["received"] > horizon+3:
                        continue
                    # Anchor each price ONCE. Re-centering at arrival would hide
                    # movement out of the originally executable price range.
                    limit = quote["midpoint"]*(1+side*.0025)
                    initial, first_complete = visible(quote["book"], limit, side)
                    remaining, last_complete = visible(arrival["book"], limit, side)
                    if initial <= 0:
                        continue
                    pairs.append(dict(quote_time=quote["received"], arrival_time=arrival["received"],
                        limit=limit, initial_quantity=initial, later_quantity=remaining,
                        ratio=remaining/initial, complete=first_complete and last_complete))
                exact = [p for p in pairs if p["complete"]]
                comparisons[f"{label}_{horizon}s"] = dict(
                    pairs=len(pairs), complete_pairs=len(exact),
                    minimum_ratio=min((p["ratio"] for p in exact), default=None),
                    below_fraction={str(f): sum(p["ratio"] < f for p in exact) for f in (.25, .05, .01)},
                    observations=pairs)
        output[symbol] = dict(requests=len(records), errors=sum("error" in r for r in records),
            invalid_or_stale=invalid, valid=len(valid),
            unique_updates=len({r["book"]["lastUpdateId"] for r in valid}),
            maximum_age_seconds=max((r["age"] for r in valid), default=None),
            maximum_request_seconds=max((r["elapsed"] for r in records), default=None),
            maximum_spread_bps=max((r["spread_bps"] for r in valid), default=None),
            comparisons=comparisons)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 60 <= args.seconds <= 180:
        parser.error("bounded experiment requires 60..180 seconds")
    raw_path = args.output.with_suffix(".jsonl")
    if args.output.exists() or raw_path.exists():
        parser.error("choose new paths; observations are never overwritten")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    before = time.time()
    server = public_get("/fapi/v1/time")["serverTime"]/1000
    after = time.time()
    offset = server-(before+after)/2
    start, deadline = time.monotonic(), time.monotonic()+args.seconds
    started = dt.datetime.now(dt.timezone.utc)
    rows, cycles = [], 0
    with raw_path.open("x") as file, ThreadPoolExecutor(max_workers=3) as pool:
        while time.monotonic() <= deadline:
            for row in pool.map(fetch, ("XLEUSDT", "IWMUSDT", "CLUSDT")):
                rows.append(row)
                file.write(json.dumps(row, allow_nan=False)+"\n")
                file.flush()
            cycles += 1
            if cycles % 10 == 0:
                print("cycles", cycles, "elapsed", round(time.monotonic()-start, 1), flush=True)
            time.sleep(max(0, min(2, start+cycles*2-time.monotonic())))
    result = dict(research_only=True, orders_authorized=False,
        started_utc=started.isoformat(), started_new_york=started.astimezone(ZoneInfo("America/New_York")).isoformat(),
        seconds=time.monotonic()-start, server_offset_estimate_seconds=offset,
        clock_offset_uncertainty_seconds=(after-before)/2, raw_path=str(raw_path),
        method="Fixed initial midpoint +/-25bp; later displayed quantity at the SAME limit. "
               "Fresh noncrossed REST snapshots only. Truncated ranges excluded from ratio summaries.",
        limitations="Overlapping overnight observations; not independent samples, order survival, "
                    "market impact, IOC fills, normal-session calibration or investment performance.",
        symbols=analyze(rows, offset))
    with args.output.open("x") as file:
        file.write(json.dumps(result, allow_nan=False)+"\n")
    print("saved", args.output, "records", len(rows), flush=True)


if __name__ == "__main__":
    main()
