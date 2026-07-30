"""GRID-B trend filter: SMA200 + the v0.1 §1.2 four-state machine.

The filter is a *risk gate*, not an alpha source (v0.1 §1.2). It decides when the grid
runs at full power, when it only de-risks (sells, no new buys), and when it freezes. The
same gate drives the S1 baseline: ``buy-and-hold-above-SMA200`` holds exactly when the
gate is ACTIVE, so grid-vs-hold is an apples-to-apples comparison under one filter.

States (per §1.2):
  * ACTIVE  -- ``confirm_bars`` consecutive closes ABOVE the SMA  -> grid full, baseline holds.
  * DERISK  -- price dropped BELOW the SMA but not yet confirmed   -> grid sells only, no new buys.
  * PAUSED  -- ``confirm_bars`` consecutive closes BELOW the SMA   -> deep bear, grid frozen.

Confirmation (waiting ``confirm_bars`` closes before flipping) is what stops a single
whipsaw bar from re-arming buys at a top or freezing at a bottom. MACD is named in §1.2 as
an auxiliary confirm; the baseline deliberately ships SMA200-only and leaves MACD as a
later add, so S1 judges the simplest honest filter first.
"""

from __future__ import annotations

import enum
import math


class TrendState(enum.Enum):
    ACTIVE = "ACTIVE"     # above MA, confirmed: full grid / baseline holds
    DERISK = "DERISK"     # below MA, unconfirmed: sell-only, no new buys
    PAUSED = "PAUSED"     # below MA, confirmed: frozen


class HybridRegime(enum.Enum):
    """S1e three-state regime (GRID-B v0.5 §3.1): below the SMA200 gate is the escape

    hatch (BELOW); above it, the 90-day return ``r90`` splits ACTIVE into a directional
    UPTREND (hold) vs a non-trending RANGE (seed a grid)."""

    UPTREND = "UPTREND"   # ACTIVE and r90 >= +r90_threshold -> hold full position
    RANGE = "RANGE"       # ACTIVE and r90 < +r90_threshold -> seed a range grid
    BELOW = "BELOW"       # not ACTIVE (DERISK/PAUSED/warm-up) -> flat


def sma(values: list[float], window: int) -> list[float | None]:
    """Simple moving average; ``None`` for the first ``window-1`` positions (warm-up)."""

    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    out: list[float | None] = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        out.append(running / window if i >= window - 1 else None)
    return out


def trend_states(
    closes: list[float],
    *,
    window: int = 200,
    confirm_bars: int = 2,
) -> list[TrendState]:
    """Per-bar trend state from closes vs their SMA, with ``confirm_bars`` confirmation.

    During SMA warm-up (no average yet) the state is PAUSED -- the gate is conservative
    until it can actually see the trend, so the baseline stays flat rather than holding on
    no information.

    Transition logic (mirrors the §1.2 diagram):
      * >= confirm_bars consecutive closes above SMA   -> ACTIVE
      * >= confirm_bars consecutive closes below SMA   -> PAUSED
      * just dropped below, not yet confirmed          -> DERISK
      * just bounced above from a paused state, not yet confirmed -> stay PAUSED
        (don't re-arm buys on an unconfirmed bounce -- avoids the bull trap)
    """

    if confirm_bars < 1:
        raise ValueError(f"confirm_bars must be >= 1, got {confirm_bars}")

    ma = sma(closes, window)
    states: list[TrendState] = []
    run_above = 0
    run_below = 0
    state = TrendState.PAUSED

    for close, avg in zip(closes, ma):
        if avg is None or math.isnan(avg):
            states.append(TrendState.PAUSED)
            continue

        above = close > avg
        if above:
            run_above += 1
            run_below = 0
        else:
            run_below += 1
            run_above = 0

        if run_above >= confirm_bars:
            state = TrendState.ACTIVE
        elif run_below >= confirm_bars:
            state = TrendState.PAUSED
        else:
            # within the confirmation window: a fresh drop below an ACTIVE grid de-risks;
            # an unconfirmed bounce out of PAUSED stays PAUSED until confirmed.
            if not above and state == TrendState.ACTIVE:
                state = TrendState.DERISK
            # else: keep prior state (PAUSED stays PAUSED, DERISK stays DERISK)
        states.append(state)

    return states


def hybrid_regimes(
    closes: list[float],
    *,
    window: int = 200,
    confirm_bars: int = 2,
    r90_window: int = 90,
    r90_threshold: float = 0.15,
) -> list[HybridRegime]:
    """Per-bar S1e three-state regime (GRID-B v0.5 §3.1).

    BELOW is the highest-priority gate: any bar whose :func:`trend_states` is not ACTIVE
    (DERISK/PAUSED/SMA warm-up) is BELOW, full stop -- SMA200 stays the escape hatch and
    ``r90`` only subdivides *within* an already-confirmed uptrend.

    Within ACTIVE, ``r90 = close / close[i - r90_window] - 1`` (no look-ahead: only past
    closes). ``r90 >= r90_threshold`` -> UPTREND (hold); anything else, including
    ``r90 <= -r90_threshold`` (confirmed above the MA but still deeply down over 90 days,
    i.e. a sharp-but-unconfirmed bounce), -> RANGE. Bars without ``r90_window`` prior
    closes (even if ACTIVE) -> BELOW (same "no information -> flat" stance as SMA warm-up).
    """

    states = trend_states(closes, window=window, confirm_bars=confirm_bars)
    out: list[HybridRegime] = []
    for i, (close, state) in enumerate(zip(closes, states)):
        if state != TrendState.ACTIVE or i < r90_window:
            out.append(HybridRegime.BELOW)
            continue
        r90 = close / closes[i - r90_window] - 1.0
        if r90 >= r90_threshold:
            out.append(HybridRegime.UPTREND)
        else:
            out.append(HybridRegime.RANGE)
    return out
