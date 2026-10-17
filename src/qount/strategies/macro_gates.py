"""Native ATR and signal gap rules shared by research and execution."""
import bisect
from qount.research_data.bars import aggregate, atr
from qount.strategies.macro_funding import feature_at

def available_atr(hours):
    daily = aggregate(hours, 86400, 3600)
    values = atr(daily)
    return [(b.t+86400, values[i]) for i, b in enumerate(daily) if values[i] is not None]


def mean_reversion_gap_confirmations(data, features, clocks):
    """One fixed ATR14 cap on positive signal-close to execution-open movement.

    ATR availability is bounded by the ETF signal timestamp, not entry time.
    Trend setups bypass this new gate. No holding/ranking changes, no fitted
    tolerance and no dependence on the entry hour's high/low/close/volume.
    """
    prices = {s:{b.t:b for b in d["trade"]} for s,d in data.items()}
    vols = {s:available_atr(d["trade"]) for s,d in data.items()}
    vol_times = {s:[t for t,_ in rows] for s,rows in vols.items()}
    result = {}
    for s,now in clocks:
        f = feature_at(features[s],now)
        if f is None or not 0 < now-f["available"] <= 4*86400:
            continue
        context = dict(asof=now, feature_available=f["available"], setup=f["tactical_setup"],
                       eligible=True, reason="mean_reversion_signal_gap")
        if f["tactical_setup"] == "mean_reversion":
            signal = prices[s].get(f["available"]-3600)
            current = prices[s].get(now)
            vi = bisect.bisect_right(vol_times[s],f["available"])-1
            if signal is None or current is None or vi < 0 or f["available"]-vols[s][vi][0]>86400:
                context.update(eligible=False,reason="mean_reversion_signal_price_or_atr_unknown")
            else:
                known, atr = vols[s][vi]
                gap = current.o-signal.c
                context.update(signal_close=signal.c, signal_atr=atr, atr_available=known,
                    entry_open=current.o, gap_return=current.o/signal.c-1,
                    gap_atr=gap/atr if atr>0 else None, eligible=atr>0 and gap<=atr+1e-12)
        result[s,now] = context
    return result
