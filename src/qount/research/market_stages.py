"""Causal, fixed market-stage hypotheses for offline directional experiments.

Six descriptive states = direction (up/down/range) x relative volatility.
Transition and observed price shock are separate flags, not hindsight labels.
Nothing in this module grants order permission or changes production features.
"""
from __future__ import annotations

import math
import statistics

from qount.research_data.regime import compute_atr, compute_ema, compute_kaufman_er


ACTION_STATES = (
    "compression", "range", "wide_range", "up_breakout", "down_breakout",
    "up_trend", "down_trend", "failed_up_breakout", "failed_down_breakout", "transition",
)


def stage_rows(bars, *, confirmation_days=2):
    """Each row uses only completed bars through its own availability time.

    High vol means vol20 exceeds the median of up to 252 PRIOR vol20 values.
    Shock compares today's log return with PRIOR 20-day volatility. Direction
    needs price/EMA50, EMA50's five-bar slope and 20-bar momentum to agree.
    These are transparent hypotheses, not fitted regime probabilities.
    """
    if confirmation_days not in (1, 2, 3):
        raise ValueError("unsupported_stage_confirmation")
    times = [b.t for b in bars]
    if times != sorted(set(times)):
        raise ValueError("stage_times_must_be_strictly_increasing")
    if any(not all(math.isfinite(v) and v > 0 for v in (b.o, b.h, b.l, b.c))
           or not b.l <= min(b.o, b.c) <= max(b.o, b.c) <= b.h for b in bars):
        raise ValueError("invalid_stage_bar")
    closes = [b.c for b in bars]
    ema20, ema50, ema200 = [compute_ema(closes, n) for n in (20, 50, 200)]
    ers = compute_kaufman_er(closes, 20)
    atrs = compute_atr(bars)
    returns = [0.] + [math.log(b / a) for a, b in zip(closes, closes[1:])]
    vols = [None if i < 20 else statistics.stdev(returns[i-19:i+1])
            for i in range(len(bars))]
    result, previous, streak = {}, None, 0
    for i in range(200, len(bars)):
        b = bars[i]
        momentum = b.c / closes[i-20] - 1
        direction = (1 if b.c > ema50[i] > ema50[i-5] and momentum > 0 else
                     -1 if b.c < ema50[i] < ema50[i-5] and momentum < 0 else 0)
        streak = streak + 1 if direction == previous else 1
        previous = direction
        history = [v for v in vols[max(20, i-252):i] if v is not None]
        threshold = statistics.median(history)
        high = vols[i] > threshold
        z = abs(returns[i]) / max(vols[i-1], 1e-12)
        lower, upper = min(x.l for x in bars[i-20:i]), max(x.h for x in bars[i-20:i])
        aligned_up, aligned_down = b.c > ema20[i] > ema50[i], b.c < ema20[i] < ema50[i]
        long_break = b.c > upper
        short_break = b.c < lower
        long_pull = b.l <= 1.02 * ema20[i] and b.c > ema20[i] and b.c > b.o
        short_pull = b.h >= .98 * ema20[i] and b.c < ema20[i] and b.c < b.o
        result[b.t] = dict(available=b.t, direction=direction,
            state=("up" if direction == 1 else "down" if direction == -1 else "range")
                  + ("_high_vol" if high else "_low_vol"),
            confirmed=streak >= confirmation_days, transition=streak < confirmation_days,
            direction_streak=streak, shock=z >= 3., shock_z=z,
            high_vol=high, volatility20=vols[i], volatility_reference=threshold,
            atr14=atrs[i], previous_atr14=atrs[i-1],
            previous_high20=upper, previous_low20=lower,
            range_position=(b.c-lower)/max(upper-lower, 1e-12),
            ema20=ema20[i], ema50=ema50[i], ema200=ema200[i], close=b.c,
            momentum20=momentum, er20=ers[i],
            structural_up=b.c > ema200[i] and ema50[i] > ema200[i] and b.c > closes[i-63],
            structural_down=b.c < ema200[i] and ema50[i] < ema200[i] and b.c < closes[i-63],
            aligned_up=aligned_up, aligned_down=aligned_down,
            long_trigger=aligned_up and ers[i] >= .28 and (long_break or long_pull),
            short_trigger=aligned_down and ers[i] >= .28 and (short_break or short_pull),
            short_setup="breakout" if short_break else "pullback" if short_pull else None)
    return result


def market_state_machine(bars, *, confirmation_days=2):
    """Ten actionable structures plus shock/unknown protective overrides.

    A close > prior high20 + .25 prior ATR starts an upward breakout (vice
    versa downward). Its original boundary stays fixed. Two closes outside
    confirm it; a close back inside within three bars confirms failure.
    Failure is observable ONLY on that later close, never backdated. A break
    remains monitored through its three-bar window after early confirmation.
    Five bars between same-side initial breaks avoid relabelling every high.

    Persistent structures and transient events are retained separately. Shock
    overrides routing for the observed bar and the next bar, while internal
    events continue advancing. Range labels use ER20<.28; compression additionally
    requires vol20<.75 historical median, wide range >1.5 median. Other uncertain
    observations go to transition. All thresholds are fixed hypotheses.
    """
    rows = stage_rows(bars, confirmation_days=confirmation_days)
    pending, last_started, cooldown = None, {-1: -100, 1: -100}, -1
    results = {}
    for i, b in enumerate(bars):
        if b.t not in rows:
            results[b.t] = dict(available=b.t, action_state="unknown", structure="unknown",
                                event=None, route_side=0, risk_scale=0.)
            continue
        row = dict(rows[b.t])
        ratio = row["volatility20"] / max(row["volatility_reference"], 1e-12)
        if row["confirmed"] and row["direction"] and row["er20"] >= .28:
            structure = "up_trend" if row["direction"] == 1 else "down_trend"
        elif row["er20"] < .28:
            structure = "compression" if ratio < .75 else "wide_range" if ratio > 1.5 else "range"
        else:
            structure = "transition"
        event, event_state = None, None
        if pending is not None:
            side, age = pending["side"], i-pending["index"]
            outside = side*(b.c-pending["boundary"]) > 0
            if not outside:
                event_state = "failed_up_breakout" if side == 1 else "failed_down_breakout"
                event = dict(pending, status="failed", observed_at=b.t, age=age,
                             resolution_close=b.c)
                pending = None
            else:
                pending["outside_closes"] += 1
                confirmed = pending["outside_closes"] >= confirmation_days
                event_state = "up_breakout" if side == 1 else "down_breakout"
                event = dict(pending, status="confirmed" if confirmed else "pending",
                             observed_at=b.t, age=age)
                if age >= 3:
                    pending = None
        if event is None:
            side = (1 if b.c > row["previous_high20"]+.25*row["previous_atr14"] else
                    -1 if b.c < row["previous_low20"]-.25*row["previous_atr14"] else 0)
            if side and i-last_started[side] >= 5:
                pending = dict(side=side, index=i, started_at=b.t,
                    boundary=row["previous_high20"] if side == 1 else row["previous_low20"],
                    trigger_close=b.c, outside_closes=1)
                last_started[side] = i
                event_state = "up_breakout" if side == 1 else "down_breakout"
                event = dict(pending, status="confirmed" if confirmation_days == 1 else "pending",
                             observed_at=b.t, age=0)
        if row["shock"]:
            cooldown = i+1
        state = "shock" if i <= cooldown else event_state or structure
        route_side = 0
        if state in ("up_breakout", "down_breakout") and event["status"] == "confirmed":
            route_side = 1 if state == "up_breakout" else -1
        elif state in ("failed_up_breakout", "failed_down_breakout"):
            route_side = -1 if state == "failed_up_breakout" else 1
        elif state == "up_trend" and row["long_trigger"]:
            route_side = 1
        elif state == "down_trend" and row["short_trigger"]:
            route_side = -1
        elif state in ("range", "wide_range"):
            # Only a boundary rejection is a mean-reversion trigger.
            if row["range_position"] <= .2 and b.c > b.o:
                route_side = 1
            elif row["range_position"] >= .8 and b.c < b.o:
                route_side = -1
        # Heuristic research tag only: NOT a calibrated confidence, approved
        # account fraction, or position instruction. Reliability comes first.
        scale = 0. if state in ("shock", "compression", "transition") else .5 if row["high_vol"] else 1.
        if state in ("range", "wide_range", "failed_up_breakout", "failed_down_breakout"):
            scale *= .5
        row.update(action_state=state, structure=structure, event=event,
                   route_side=route_side, risk_scale=scale)
        results[b.t] = row
    return results


def stage_permission(asset, market, side, *, systematic=True):
    """Environment -> asset -> risk; order triggers are evaluated separately.

    Equity indices share the SPY environment, crypto shares BTC in the separate
    portability experiment. Commodities do NOT inherit the equity direction.
    A newly observed shock blocks entries immediately; a new direction needs
    two completed observations. No certainty is assigned to a phase change.
    """
    if side not in (-1, 1):
        raise ValueError("invalid_stage_side")
    if asset is None or systematic and market is None:
        return False, 0., "stage_unknown"
    for label, row in (("asset", asset), ("market", market)) if systematic else (("asset", asset),):
        if row["shock"]:
            return False, 0., label + "_price_shock"
        if not row["confirmed"] or row["direction"] != side:
            return False, 0., label + "_direction_unconfirmed_or_conflict"
    high = asset["high_vol"] or systematic and market["high_vol"]
    return True, .5 if high else 1., "stage_allowed"


def environment_permission(asset, market, peers, *, systematic=True):
    """One predefined market/asset/trigger ablation, with no outcome inputs.

    Directional trend/breakout routes require confirmed matching benchmark
    direction and at least half of representative peers aligned. Range and
    failed-break routes only veto a confirmed opposing benchmark trend.
    Commodity proxies are independent of the equity benchmark direction.
    """
    side = asset["route_side"]
    if not side or asset["action_state"] in ("unknown", "shock"):
        return False, "no_local_trigger"
    if not systematic:
        return True, "independent_asset_class"
    if market is None or market["action_state"] in ("unknown", "shock"):
        return False, "market_unknown_or_shock"
    if asset["action_state"] in ("up_trend", "down_trend", "up_breakout", "down_breakout"):
        if not market["confirmed"] or market["direction"] != side:
            return False, "benchmark_direction_unconfirmed_or_conflict"
        known = [r for r in peers if r["action_state"] != "unknown"]
        if not known or sum(r["direction"] == side for r in known)/len(known) < .5:
            return False, "representative_breadth_conflict"
    elif market["confirmed"] and market["direction"] == -side and market["er20"] >= .28:
        return False, "countertrend_reversal_veto"
    return True, "environment_allowed"
