"""Fixed entry confirmations on completed contract hours; no fitted thresholds."""
import bisect

from qount.research_data.regime import compute_ema


def exit_features(features, policy):
    """Replace only causal holding eligibility; entry/rank/size are unchanged."""
    if policy not in ("hold_tactical", "hold_price_trend", "hold_structural", "state_exit_price_confirm"):
        raise ValueError("unknown_tactical_exit_policy")
    if policy == "state_exit_price_confirm":
        # Both inputs already include the original structural/systemic vetoes.
        # Retain a trend on a state-label change only while its daily price
        # remains above EMA20; entries, ranks, horizons and MR holds stay frozen.
        return {s: [{**row, "hold_tactical": row["hold_tactical"] or row["hold_price_trend"]}
                    for row in rows] for s, rows in features.items()}
    return {s: [{**row, "hold_tactical": row[policy]} for row in rows] for s, rows in features.items()}


def contract_confirmations(data, clocks, mode):
    """ETF daily signal is unchanged; native contract confirmation uses <= now.

    An hourly bar becomes available at its OPEN timestamp plus3600 seconds.
    Missing prior-hour data or fewer than50 completed bars fails closed. The
    entry hour's open/high/low/close/volume never contributes to confirmation.
    """
    if mode not in ("above20", "aligned20_50"):
        raise ValueError("unknown_contract_confirmation")
    indicators = {}
    for s, d in data.items():
        rows = d["trade"]
        times = [b.t for b in rows]
        if times != sorted(set(times)):
            raise ValueError("unordered_or_duplicate_contract_hours")
        closes = [b.c for b in rows]
        indicators[s] = (rows, [t+3600 for t in times], compute_ema(closes, 20), compute_ema(closes, 50))
    result = {}
    for s, now in clocks:
        rows, times, ema20, ema50 = indicators[s]
        i = bisect.bisect_right(times, now)-1
        if i < 49 or times[i] != now or [b.t for b in rows[i-49:i+1]] != list(range(now-50*3600, now, 3600)):
            continue
        result[s, now] = dict(asof=times[i], close=rows[i].c, ema20=ema20[i], ema50=ema50[i],
                              eligible=rows[i].c > ema20[i] and (mode == "above20" or ema20[i] > ema50[i]))
    return result
