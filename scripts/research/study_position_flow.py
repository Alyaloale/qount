#!/usr/bin/env python3
"""Offline pilot: does following large-account positioning beat fading it?

Public archive ratios describe groups, not identifiable profitable traders.
This is an event study with exact funding, not a deployable account backtest.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import urllib.request
import zipfile

import numpy as np

HOUR = 3_600_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def fetch_metrics(symbol, day, cache):
    name = f"{symbol}-metrics-{day}.zip"
    path = cache / name
    if not path.exists():
        url = f"https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/{name}"
        with urllib.request.urlopen(url, timeout=15) as response:
            blob = response.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            assert archive.testzip() is None
        path.write_bytes(blob)
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            rows = list(csv.DictReader(io.TextIOWrapper(stream)))
    for row in rows:
        assert row["symbol"] == symbol
    return rows


def rolling(x, n, operation="mean"):
    y = np.full_like(x, np.nan, dtype=float)
    for t in range(n - 1, len(x)):
        a = x[t - n + 1:t + 1]
        y[t] = np.mean(a) if operation == "mean" else np.std(a, ddof=1)
    return y


def diff(x, lag):
    y = np.full_like(x, np.nan)
    y[lag:] = x[lag:] - x[:-lag]
    return y


def asof_metrics(rows, times):
    parsed = []
    for row in rows:
        stamp = int(datetime.fromisoformat(row["create_time"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
        try:
            vals = [float(row[k]) for k in ("sum_open_interest", "sum_toptrader_long_short_ratio",
                                           "count_toptrader_long_short_ratio", "count_long_short_ratio")]
        except (ValueError, TypeError):
            continue  # Historical archive contains blank measurements; never fill them.
        if all(np.isfinite(vals)) and min(vals) > 0:
            parsed.append((stamp, vals))
    parsed.sort(key=lambda a: a[0])
    if not parsed:
        raise ValueError("no_valid_metric_rows")
    stamps = np.asarray([a[0] for a in parsed], np.int64)
    assert len(np.unique(stamps)) == len(stamps), "duplicate_metric_timestamp"
    values = np.asarray([a[1] for a in parsed])
    # At hourly close, allow five minutes publication lag. Never interpolate.
    decision = times + HOUR
    ids = np.searchsorted(stamps, decision - 300_000, side="right") - 1
    good = (ids >= 0) & ((decision - stamps[np.maximum(ids, 0)]) <= 1_200_000)
    out = np.full((len(times), 4), np.nan)
    out[good] = values[ids[good]]
    return out, dict(raw_rows=len(rows), valid_rows=len(parsed), invalid_rows=len(rows)-len(parsed), hourly_matches=int(good.sum()),
                     hourly_missing=int((~good).sum()), lag_minutes=5, maximum_age_minutes=20)


def signal_set(future, spot, metrics, btc_returns):
    logprice = np.log(future[:, 4])
    r = diff(logprice, 1)
    cov = rolling(r * btc_returns, 168) - rolling(r, 168) * rolling(btc_returns, 168)
    var = rolling(btc_returns ** 2, 168) - rolling(btc_returns, 168) ** 2
    beta = cov / np.maximum(var, 1e-12)
    top_change = diff(np.log(metrics[:, 1]), 24)
    crowd_change = diff(np.log(metrics[:, 3]), 24)
    divergence = top_change - crowd_change
    oi6 = diff(np.log(metrics[:, 0]), 6)
    spot_flow = 2 * rolling(spot[:, 10], 6) / rolling(spot[:, 7], 6) - 1
    spot_r6 = diff(np.log(spot[:, 4]), 6)
    vol6 = rolling(diff(np.log(spot[:, 4]), 1), 24, "std") * np.sqrt(6)

    def extreme(x):
        # Threshold uses only preceding seven days, not the current observation.
        threshold = np.full_like(x, np.nan)
        for t in range(168, len(x)):
            a = np.abs(x[t - 168:t])
            if np.isfinite(a).sum() >= 150:
                threshold[t] = np.nanquantile(a, .75)
        return np.where(np.isfinite(x) & (np.abs(x) > threshold), np.sign(x), 0)

    top_signal, divergence_signal = extreme(top_change), extreme(divergence)
    absorption = np.where((spot_flow < -.08) & (spot_r6 > -.5 * vol6), 1,
                  np.where((spot_flow > .08) & (spot_r6 < .5 * vol6), -1, 0))
    confluence = np.where((divergence_signal != 0) & (oi6 > 0) &
                         (divergence_signal * spot_flow > .03), divergence_signal, 0)
    spot_oi = np.where((oi6 > 0) & (np.abs(spot_flow) > .03), np.sign(spot_flow), 0)
    # Position share versus account-count share: concentration proxy, not identities.
    concentration = top_change - diff(np.log(metrics[:, 2]), 24)
    concentration_signal = extreme(concentration)
    concentration_confluence = np.where((concentration_signal != 0) & (oi6 > 0) &
                                       (concentration_signal * spot_flow > .03), concentration_signal, 0)
    return dict(top_position_follow=top_signal, top_vs_crowd_follow=divergence_signal,
                spot_absorption=absorption, positioning_spot_oi_confluence=confluence,
                spot_oi_without_top_control=spot_oi, concentration_follow=concentration_signal,
                concentration_spot_oi_confluence=concentration_confluence), beta


def event_study(symbol, times, future, signals, beta, funding, *, entry_start_ms=None, end_ms=None):
    events = []
    for name, signal in signals.items():
        next_signal = 0
        for t in range(200, len(times) - 26):
            if t < next_signal or not signal[t] or not np.isfinite(beta[t]):
                continue
            # Full extra hour after close allows metrics/data retrieval latency.
            entry = t + 2
            if entry_start_ms is not None and times[entry] < entry_start_ms:
                continue
            if end_ms is not None and times[entry + 24] > end_ms:
                continue
            price = future[entry, 1]
            side = int(signal[t])
            event = dict(symbol=symbol, hypothesis=name, side=side, signal_ms=int(times[t] + HOUR),
                         entry_ms=int(times[entry]), beta=float(beta[t]))
            if name == "spot_oi_without_top_control":
                event["top_confirms"] = bool(signals["top_vs_crowd_follow"][t] == side)
            for h in (6, 24):
                exit_ms = times[entry + h]
                ret = future[entry + h, 1] / price - 1
                # Boundary funding belongs to the position held before exit.
                payments = sum(float(r["fundingRate"]) * float(r["markPrice"]) / price for r in funding
                               if times[entry] < int(r["fundingTime"]) <= exit_ms)
                event[f"gross_{h}h_bp"] = side * ret * 10000
                event[f"funding_{h}h_bp"] = -side * payments * 10000
            events.append(event)
            # Per hypothesis/symbol: no overlapping 24-hour holding intervals.
            next_signal = t + 24
    return events


def summarize(events, cost_bp):
    if not events:
        return dict(count=0)
    y = np.array([e["gross_24h_bp"] + e["funding_24h_bp"] - 2 * cost_bp for e in events])
    months = {}
    for e, value in zip(events, y):
        month = datetime.fromtimestamp(e["entry_ms"] / 1000, timezone.utc).strftime("%Y-%m")
        months.setdefault(month, []).append(float(value))
    # Calendar-week cluster bootstrap keeps all simultaneous symbols together.
    weeks = {}
    for e, value in zip(events, y):
        dt = datetime.fromtimestamp(e["entry_ms"] / 1000, timezone.utc)
        key = f"{dt.isocalendar().year}-{dt.isocalendar().week:02d}"
        weeks.setdefault(key, []).append(float(value))
    blocks = list(weeks.values())
    rng = np.random.default_rng(271027)
    ids = rng.integers(0, len(blocks), size=(2000, len(blocks)))
    sums = np.array([sum(b) for b in blocks]); counts = np.array([len(b) for b in blocks])
    estimates = sums[ids].sum(axis=1) / counts[ids].sum(axis=1)
    return dict(count=len(y), mean_net_24h_bp=float(y.mean()), median_net_24h_bp=float(np.median(y)),
                long_events=sum(e["side"] > 0 for e in events),
                short_events=sum(e["side"] < 0 for e in events),
                mean_without_best_bp=float(np.delete(y, np.argmax(y)).mean()) if len(y) > 1 else None,
                mean_without_best3_bp=float(np.sort(y)[:-3].mean()) if len(y) > 3 else None,
                mean_beta_residual_gross_bp=float(np.mean([e["beta_residual_gross_24h_bp"] for e in events]))
                    if all("beta_residual_gross_24h_bp" in e for e in events) else None,
                win_rate=float(np.mean(y > 0)), mean_gross_24h_bp=float(np.mean([e["gross_24h_bp"] for e in events])),
                mean_funding_24h_bp=float(np.mean([e["funding_24h_bp"] for e in events])),
                mean_net_6h_bp=float(np.mean([e["gross_6h_bp"] + e["funding_6h_bp"] - 2 * cost_bp for e in events])),
                week_cluster_ci95_bp=np.quantile(estimates, [.025, .975]).tolist(),
                calendar_weeks=len(blocks), monthly_mean_net_bp={k:float(np.mean(v)) for k,v in months.items()},
                by_symbol={s:dict(count=sum(e["symbol"] == s for e in events),
                    mean_net_bp=float(np.mean([v for e,v in zip(events,y) if e["symbol"] == s])))
                    for s in SYMBOLS if any(e["symbol"] == s for e in events)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("state/research_cache/position_flow_20261027"))
    parser.add_argument("--hourly", type=Path, help="Defaults to hourly.json within cache")
    parser.add_argument("--start-date", default="2026-07-20", help="First metric date including warmup")
    parser.add_argument("--end-date", default="2026-10-27", help="Exclusive data end")
    parser.add_argument("--evaluation-start", help="First permitted entry date after warmup")
    parser.add_argument("--evaluation-end", help="Exclusive evaluation end; no exits after this boundary")
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/position_flow_20261027"))
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True); args.output.mkdir(parents=True, exist_ok=True)
    raw = json.loads((args.hourly or args.cache / "hourly.json").read_text())["data"]
    funding_raw = json.loads(Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json").read_text())["data"]
    start, end = date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
    days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days)]
    cutoff_ms = int(datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
    entry_start_ms = int(datetime.fromisoformat(args.evaluation_start).replace(tzinfo=timezone.utc).timestamp() * 1000) if args.evaluation_start else None
    eval_end_ms = int(datetime.fromisoformat(args.evaluation_end).replace(tzinfo=timezone.utc).timestamp() * 1000) if args.evaluation_end else None
    rows = {s: [] for s in SYMBOLS}; failures = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(fetch_metrics, s, d, args.cache): (s, d) for s in SYMBOLS for d in days}
        for job in as_completed(jobs):
            s, d = jobs[job]
            try:
                rows[s].extend(job.result())
            except Exception as exc:
                failures.append(dict(symbol=s, day=d, error=type(exc).__name__))
    futures = {s:np.asarray(raw[s + "_futures"], float) for s in SYMBOLS}
    times = futures["BTCUSDT"][:, 0].astype(np.int64)
    btc_returns = diff(np.log(futures["BTCUSDT"][:, 4]), 1)
    events, coverage = [], {}
    for s in SYMBOLS:
        future, spot = futures[s], np.asarray(raw[s + "_spot"], float)
        assert np.array_equal(future[:, 0], times) and np.array_equal(spot[:, 0], times)
        assert np.all(np.diff(times) == HOUR)
        assert np.all(np.isfinite(future)) and np.all(np.isfinite(spot))
        assert future[-1, 6] < cutoff_ms
        metric, coverage[s] = asof_metrics(rows[s], times)
        signals, beta = signal_set(future, spot, metric, btc_returns)
        rates = [r for r in funding_raw[s + "_funding"] if int(r["fundingTime"]) >= times[0]]
        assert all(r.get("markPrice") for r in rates)
        events.extend(event_study(s, times, future, signals, beta, rates,
                                  entry_start_ms=entry_start_ms, end_ms=eval_end_ms))
    for event in events:
        entry = int(np.searchsorted(times, event["entry_ms"]))
        btc = futures["BTCUSDT"]
        market_return = btc[entry + 24, 1] / btc[entry, 1] - 1
        event["beta_residual_gross_24h_bp"] = event["gross_24h_bp"] - event["side"] * event["beta"] * market_return * 10000
    results = {}
    for name in sorted({e["hypothesis"] for e in events}):
        subset = [e for e in events if e["hypothesis"] == name]
        reverse = [dict(e, side=-e["side"], **{k:-v for k,v in e.items() if k.startswith(("gross_", "funding_", "beta_residual_"))}) for e in subset]
        results[name] = {f"follow_{cost}bp":summarize(subset, cost) for cost in (10, 30)}
        results[name].update({f"reverse_{cost}bp":summarize(reverse, cost) for cost in (10, 30)})
    payload = dict(research_only=True, orders_authorized=False, independent_oos=False,
                   scope=f"{args.start_date} to {args.end_date} exclusive BTC ETH SOL; nonoverlapping per-asset 24h events; not portfolio CAGR",
                   evaluation_start=args.evaluation_start, evaluation_end=args.evaluation_end,
                   decision="hour close; metrics lag5min/maxage20min; entry next-next hourly open",
                   costs="one-way 5bp fee +5bp friction base;30bp stress; actual funding separately",
                   source="Binance official public archive metrics plus public MCP spot/futures klines",
                   coverage=coverage, failures=failures, results=results, events=events)
    (args.output / "results.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k:v for k,v in payload.items() if k not in ("events", "results")}, indent=2))
    for n, r in results.items():
        print(n, {k:(v["count"], round(v.get("mean_net_24h_bp",0),2), v.get("week_cluster_ci95_bp")) for k,v in r.items()})


if __name__ == "__main__":
    main()
