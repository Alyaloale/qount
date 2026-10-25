#!/usr/bin/env python3
"""Small offline depth/latency/partial-fill study; public archives only."""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import hashlib
import io
import json
import math
import urllib.request
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import cost_case
from qount.research.lines.macro_1atr import inputs
from qount.research.macro_depth_execution import DepthExecution, limit_depth_lower_bound
from qount.strategies.perpetual import grid

ROOT = Path("state/research_cache")
OLD_TAPE = ROOT/"macro_execution_tape_20261019"
NEW_TAPE = ROOT/"macro_depth_execution_20261020"
RUNS = Path("state/research_runs")


def archive(symbol, day, kind, download):
    name = f"{symbol}-{kind}-{day}.zip"
    path = OLD_TAPE/name if (OLD_TAPE/name).exists() else NEW_TAPE/name
    if not path.exists():
        if not download:
            raise FileNotFoundError(path)
        base = f"https://data.binance.vision/data/futures/um/daily/{kind}/{symbol}/{name}"
        with urllib.request.urlopen(base+".CHECKSUM", timeout=20) as response:
            checksum = response.read(4096).decode()
        with urllib.request.urlopen(base, timeout=30) as response:
            raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError("archive_exceeds_small_study_budget")
        if hashlib.sha256(raw).hexdigest() != checksum.split()[0]:
            raise ValueError("archive_checksum_mismatch")
        NEW_TAPE.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as file:
            file.write(raw)
        with path.with_suffix(".zip.CHECKSUM").open("x") as file:
            file.write(checksum)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != path.with_suffix(".zip.CHECKSUM").read_text().split()[0]:
        raise ValueError("retained_archive_checksum_mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if len(z.namelist()) != 1:
            raise ValueError("archive_csv_count")
        with z.open(z.namelist()[0]) as file:
            rows = list(csv.DictReader(io.TextIOWrapper(file)))
    return rows, dict(path=str(path), sha256=digest, bytes=len(raw))


def depth_context(key, download):
    symbol, now = key
    day = dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()
    rows, source = archive(symbol, day, "bookDepth", download)
    snapshots = {}
    for row in rows:
        stamp = int(dt.datetime.fromisoformat(row["timestamp"]).replace(tzinfo=dt.timezone.utc).timestamp())
        if now <= stamp <= now+150:
            level = float(row["percentage"])
            levels = snapshots.setdefault(stamp, {})
            if level in levels:
                raise ValueError("duplicate_depth_level")
            levels[level] = (float(row["depth"]), float(row["notional"]))
    return [dict(time=t, levels=levels) for t, levels in sorted(snapshots.items())], source


def load_context(key, download):
    symbol, now = key
    day = dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()
    snapshots, source = depth_context(key, download)
    if len(snapshots) < 3:
        raise ValueError(f"insufficient_entry_snapshots:{symbol}:{now}")
    tape, tape_source = archive(symbol, day, "aggTrades", download)
    tape = [dict(time=int(r["transact_time"])/1000, price=float(r["price"]), quantity=float(r["quantity"]))
            for r in tape if now*1000 <= int(r["transact_time"]) < (now+150)*1000]
    if any(a["time"] > b["time"] for a, b in zip(tape, tape[1:])):
        raise ValueError("unordered_trade_tape")
    print("inputs", symbol, day, len(snapshots), "snapshots", len(tape), "prints", flush=True)
    return key, snapshots, tape, [source, tape_source]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--output", type=Path, default=RUNS/"macro_depth_execution_20261020/comparison.json")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new --output; existing results are retained")
    old = json.loads((RUNS/"macro_small_capital_review_20261019/comparison.json").read_text())["results"]
    venue = json.loads((RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json").read_text())
    book, signals, gates, caps, _ = inputs(
        ROOT/"binance_macro_attack_20261015",
        [ROOT/n for n in ("binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730",
                         "binance_macro_attack_20261015")],
        ROOT/"binance_macro_liquidity_20261015", "2026-04-07", "2026-10-15")
    for symbol, data in book.items():
        data["rule"] = dict(data["rule"], leverage_brackets=venue["symbols"][symbol]["brackets"])
    contexts, tapes, sources = {}, {}, []
    keys = sorted(key for key, gate in gates.items() if gate["eligible"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        for key, snapshots, tape, provenance in pool.map(lambda key: load_context(key, args.download), keys):
            contexts[key], tapes[key] = snapshots, tape
            sources.extend(provenance)
    results, baseline_checks = {}, []
    # Paired execution assumptions: keep the original volume-sized control
    # next to each depth-sized arm. Do not optimize depth survival fractions.
    scenarios = [("survival25", .25, 30), ("survival5", .05, 30),
                 ("survival1", .01, 30), ("delay60", .25, 60)]
    for costs in ("base", "double_cost"):
        expected = old[f"current_{costs}_capital15.2711"]
        parameters = copy.deepcopy(expected["parameters"])
        parameters.pop("capacity_multiplier")
        data = cost_case(book, costs)
        baseline = replay(data, signals, entry_confirmations=gates, entry_liquidity_caps=caps, **parameters)
        clean = [{k: v for k, v in t.items() if k not in ("sizing_diagnostic", "pnl_components")}
                 for t in expected["trades"]]
        assert baseline["trades"] == clean and baseline["curve"] == expected["curve"]
        results["original_"+costs] = baseline
        baseline_checks.append(costs+": exact retained trades and curve")
        for name, survival, latency in scenarios:
            for sizing in ("volume", "depth"):
                model = DepthExecution(contexts, use_depth_sizing=sizing == "depth",
                                       fill_fraction=survival, latency_seconds=latency)
                result = replay(data, signals, entry_confirmations=gates, entry_liquidity_caps=caps,
                                entry_execution_model=model, **parameters)
                key = f"{sizing}_{name}_{costs}"
                summary = result["summary"]
                assert math.isclose(parameters["capital"]+sum(t["net_pnl"] for t in result["trades"]),
                                    summary["final_equity"], abs_tol=1e-8)
                for trade in result["trades"]:
                    assert trade["feature_available"] < trade["entry_time"] < trade["entry_fill_time"]
                    assert trade["entry_fill_time"] <= trade["entry_time"]+90
                    assert trade["stress_risk_usdt"] <= trade["risk_budget_usdt"]+1e-8
                    assert trade["entry_price"] <= trade["entry_execution"]["price_limit"]
                summary.update(
                    closed_net_pnl=sum(t["net_pnl"] for t in result["trades"] if t["exit_reason"] != "end_of_sample"),
                    censored_net_pnl=sum(t["net_pnl"] for t in result["trades"] if t["exit_reason"] == "end_of_sample"),
                    execution_counts=dict(Counter(r["status"] for r in result["execution_attempts"])),
                    entry_hour_risk_exits=sum(t["exit_time"] == t["entry_time"]+3600
                        and t["exit_reason"] in ("stop", "liquidation_proxy") for t in result["trades"]))
                # Prints are diagnostic only; a historical aggressor print
                # neither guarantees nor rules out a new IOC's own fill.
                for attempt in result["execution_attempts"]:
                    now, symbol = attempt["decision_time"], attempt["symbol"]
                    tape = tapes[symbol, now]
                    arrival = attempt.get("arrival_time")
                    attempt["tape_diagnostic"] = dict(
                        prints_before_deadline=len([t for t in tape if t["time"] <= now+90]),
                        volume_at_or_below_limit_after_arrival=sum(
                            t["quantity"] for t in tape if arrival is not None
                            and arrival <= t["time"] <= now+90 and t["price"] <= attempt["price_limit"]))
                result["parameters"] = dict(parameters, sizing=sizing, quote_fraction=.25,
                                             survival_fraction=survival, latency_seconds=latency)
                results[key] = result
                print(key, json.dumps({k: summary[k] for k in (
                    "net_return", "max_drawdown", "trade_count", "closed_net_pnl",
                    "censored_net_pnl", "execution_counts", "entry_hour_risk_exits")}), flush=True)
    # Specific execution-risk check: larger entries are only useful if their
    # realized strategy exits also have displayed bid quantity near the
    # modeled exit price. This check does not change entry selection or NAV.
    exit_keys = sorted({(t["symbol"], t["exit_time"]) for key, result in results.items()
                       if key.startswith("depth_") for t in result["trades"]
                       if t["exit_reason"] != "end_of_sample"})
    exit_contexts = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for key, value in zip(exit_keys, pool.map(lambda key: depth_context(key, args.download), exit_keys)):
            exit_contexts[key] = value[0]
            sources.append(value[1])
    exit_checks = {}
    for key, result in results.items():
        if not key.startswith("depth_"):
            continue
        checks = []
        for trade in result["trades"]:
            if trade["exit_reason"] == "end_of_sample":
                continue
            symbol, now = trade["symbol"], trade["exit_time"]
            tick = next(f["tickSize"] for f in book[symbol]["rule"]["filters"] if f["filterType"] == "PRICE_FILTER")
            # A sell limit must round UP to promise the model's price floor.
            limit = grid(trade["exit_price"], tick, up=True)
            snapshots = [r for r in exit_contexts[symbol, now] if now+5 <= r["time"] <= now+90]
            bounds = []
            for snapshot in snapshots:
                try:
                    quantity = limit_depth_lower_bound(snapshot["levels"], limit, side=-1)["quantity"]
                    bounds.append(dict(time=snapshot["time"], quantity=quantity))
                except ValueError as exc:
                    # Official archive checksums do not certify economic
                    # consistency. Preserve unknown evidence, never fill zero.
                    bounds.append(dict(time=snapshot["time"], quantity=None, error=str(exc)))
            usable = bounds and all(r["quantity"] is not None for r in bounds)
            minimum = min(r["quantity"] for r in bounds) if usable else None
            checks.append(dict(symbol=symbol, time=now, exit_reason=trade["exit_reason"],
                quantity=trade["quantity"], modeled_exit_price=trade["exit_price"], price_floor=limit,
                status=("available" if usable else "inconsistent_exit_snapshots" if bounds
                        else "missing_exit_snapshots"),
                snapshots=bounds, minimum_displayed_lower_bound=minimum,
                covered_at_fraction={str(f): None if minimum is None else minimum*f >= trade["quantity"]
                                     for f in (.25, .05, .01)}))
        exit_checks[key] = checks
        print("exit_depth", key, "orders", len(checks), "covered25/5/1",
              [sum(r["covered_at_fraction"][str(f)] is True for r in checks) for f in (.25, .05, .01)],
              "unknown", sum(r["status"] != "available" for r in checks), flush=True)
    output = dict(
        research_only=True, orders_authorized=False,
        hypothesis="Replace historical volume sizing with discounted depth inside an unchanged limit; "
                   "test net results under identical delayed and partial-fill assumptions.",
        sample_start="2026-04-07", sample_end_exclusive="2026-10-15", initial_capital=15.27112826,
        symbols=list(book), benchmark="cash 0%", baseline_checks=baseline_checks, sources=sources,
        limitations=[
            "Conditional execution stress, NOT historical IOC fills or independent OOS.",
            "First quote >= signal+5s; arrival at first snapshot >= quote+30s/60s; reject beyond signal+90s.",
            "Quote uses 25% static lower bound; assumed surviving arrival depth 25%, 5%, 1%. Fractions not calibrated.",
            "One IOC only; partial fills accepted including below submission minimum; no topup or repeated-depth summation.",
            "Full signal-hour stop/liquidation extrema remain pessimistically active; entry-hour risk-exit count reported.",
            "Funding before modeled fill is excluded; hold/renewal clocks stay anchored to original decision as in live.",
            "Partial fills scale pretrade funding allowance as live does; no new budget from unfilled quantity.",
            "Native protection assumed immediate and successful; no live timing, impact, matching or L2 validation.",
            "Current tiers applied historically; base fee/exit slip 5/25bp, double 10/50bp with adverse regular funding doubled.",
            "All fills valued at tick-rounded limit; terminal valuation is censored, not a strategy exit.",
            "Exit depth check uses first 5-90s snapshots and the unchanged modeled price floor; no fill claim or NAV adjustment.",
        ], results=results, exit_depth_checks=exit_checks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as file:
        file.write(json.dumps(output, allow_nan=False)+"\n")
    print("saved", args.output, flush=True)


if __name__ == "__main__":
    main()
