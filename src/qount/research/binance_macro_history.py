"""Fixed-horizon ETF signal diagnostics, separate from any perpetual replay."""
import datetime as dt
import math
import statistics

from qount.research_data.bars import Bar, NY


def adjusted_bars(payload):
    """Same OHLC adjustment as macro_features; timestamp is the close, not midnight."""
    result = payload["chart"]["result"][0]
    quotes = result["indicators"]["quote"][0]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, stamp in enumerate(result["timestamp"]):
        day = dt.datetime.fromtimestamp(stamp, NY).date()
        available = int(dt.datetime.combine(day, dt.time(16), NY).timestamp())
        prices = [quotes[k][i] for k in ("open", "high", "low", "close")]
        if any(x is None or not math.isfinite(x) or x <= 0 for x in prices+[adjusted[i]]):
            raise ValueError("invalid_historical_ohlc")
        factor = adjusted[i]/prices[-1]
        b = Bar(available, *(x*factor for x in prices), float(quotes["volume"][i] or 0))
        if not 0 < b.l <= min(b.o, b.c)+1e-7 <= max(b.o, b.c)+1e-7 <= b.h+1e-7:
            raise ValueError("invalid_historical_ohlc_order")
        bars.append(b)
    if [b.t for b in bars] != sorted({b.t for b in bars}):
        raise ValueError("invalid_historical_bar_order")
    return bars


def forward_label(bars, signal_index, sessions):
    """Signal after session i; buy next open, sell the Nth held session close.

    Labels are diagnostics, never entry features. Missing maturity is censored;
    no last-price substitute. Costs exclude funding, stops and account constraints.
    """
    if sessions <= 0 or signal_index < 0 or signal_index >= len(bars):
        raise ValueError("invalid_forward_horizon")
    end = signal_index+sessions
    if end >= len(bars):
        return dict(censored=True)
    entry, exit_bar = bars[signal_index+1], bars[end]
    entry_day = dt.datetime.fromtimestamp(entry.t, NY).date()
    entry_time = int(dt.datetime.combine(entry_day, dt.time(9, 30), NY).timestamp())
    if entry_time <= bars[signal_index].t:
        raise ValueError("entry_before_signal")
    raw = exit_bar.c/entry.o
    values = {}
    for name, fee, slip in (("base", .0005, .0025), ("double_cost", .001, .005)):
        ratio = raw*(1-slip)/(1+slip)
        values[name] = ratio-1-fee*(1+ratio)
    return dict(censored=False, entry_time=entry_time, exit_available=exit_bar.t,
                entry_open=entry.o, exit_close=exit_bar.c, gross_return=raw-1, **values)


def first_episodes(features, bars, start="2017-01-01", end="2026-01-01"):
    indices = {b.t: i for i, b in enumerate(bars)}
    events = []
    previous = None
    last_purged_exit = -1
    for f in features:
        i = indices[f["available"]]
        setup = f["tactical_setup"] if f["entry_tactical"] else None
        first = setup is not None and setup != previous
        previous = setup
        if not first or not start <= f["date"] < end:
            continue
        # Select before filtering or observing returns. Purge the full longest
        # outcome interval per asset; correlated events across assets remain.
        nonoverlap = i+1 > last_purged_exit
        if nonoverlap:
            last_purged_exit = i+15
        events.append(dict(signal_date=f["date"], signal_available=f["available"],
                           signal_index=i, setup=setup, year=f["date"][:4],
                           daily_reversal=bars[i].c > bars[i-1].c,
                           nonoverlap=nonoverlap,
                           outcomes={str(n): forward_label(bars, i, n) for n in (5, 15)}))
    return events


def distribution(events, sessions, scenario):
    labels = [e["outcomes"][str(sessions)] for e in events]
    values = [r[scenario] for r in labels if not r["censored"]]
    total = sum(values)
    best = max(values) if values else None
    return dict(events=len(events), mature=len(values), censored=len(labels)-len(values),
                mean=statistics.mean(values) if values else None,
                median=statistics.median(values) if values else None,
                win_fraction=sum(v > 0 for v in values)/len(values) if values else None,
                worst=min(values) if values else None, best=best,
                mean_ex_best=(total-best)/(len(values)-1) if len(values)>1 else None)


def account_concentration(account):
    """Frozen-quantity PnL attribution; subtracting a trade is NOT a new replay."""
    trades = account["trades"]
    minutes = account["minute_checks"]
    if len(trades) != len(minutes):
        raise ValueError("incomplete_minute_attribution")
    rows = []
    for t, m in zip(trades, minutes):
        if t["entry_time"] != m["entry_time"] or t["exit_time"] != m["exit_time"]:
            raise ValueError("minute_trade_alignment")
        rows.append(dict(symbol=t["symbol"], entry_time=t["entry_time"],
                         censored=t["exit_reason"] == "end_of_sample", net_pnl=m["net_pnl"]))
    closed = [r for r in rows if not r["censored"]]
    closed_sum = sum(r["net_pnl"] for r in closed)
    best = max(closed, key=lambda r: r["net_pnl"]) if closed else None
    return dict(trades=len(rows), closed=len(closed), censored=len(rows)-len(closed),
                total_pnl=sum(r["net_pnl"] for r in rows), closed_pnl=closed_sum,
                censored_pnl=sum(r["net_pnl"] for r in rows if r["censored"]),
                best_closed=best,
                closed_ex_best_pnl=closed_sum-best["net_pnl"] if best else None,
                best_closed_share=best["net_pnl"]/closed_sum if best and closed_sum>0 else None,
                by_symbol={s:sum(r["net_pnl"] for r in rows if r["symbol"]==s)
                           for s in sorted({r["symbol"] for r in rows})})
