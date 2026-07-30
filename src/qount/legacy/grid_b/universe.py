"""GRID-B H3 point-in-time universe selection (docs/archive/legacy/grid-b/grid-binance-h3-plan.md 洞2).

The H3 kill-test must not hand-pick high-funding winners (selection bias). Instead the
universe is chosen *point-in-time* by liquidity: at each rebalance timestamp, rank the
pre-registered candidate symbols by trailing average dollar volume (ADV) and take the
top-N. Funding is an *observed* quantity, never a selection input. Dead names (e.g. a
collapsed coin) drop out of the ranking automatically once their data ends -- their tail
loss is carried by the per-symbol run, not excluded.

Pure and offline-testable (inject bars); no network here.
"""

from __future__ import annotations

from qount.research_data.market_data import Bar

_DAY_MS = 86_400_000


def trailing_adv(bars: list[Bar], at_ts: int, *, window_days: int = 30) -> float:
    """Average daily dollar volume over ``[at_ts - window_days, at_ts]``.

    Dollar volume per bar ≈ ``close × volume``; summed over the trailing window and
    divided by ``window_days`` to get a per-day figure. Bars must be ascending by ts.
    Returns 0.0 when no bar falls in the window (e.g. before listing / after delisting).
    """

    lo = at_ts - window_days * _DAY_MS
    total = 0.0
    seen = False
    for b in bars:
        if b.ts_ms < lo:
            continue
        if b.ts_ms > at_ts:
            break
        total += b.close * b.volume
        seen = True
    return total / window_days if seen else 0.0


def select_universe(
    candidate_bars: dict[str, list[Bar]],
    at_ts: int,
    *,
    top_n: int,
    window_days: int = 30,
    min_adv: float = 0.0,
) -> list[str]:
    """Top-``top_n`` candidate symbols by trailing ADV at ``at_ts`` (point-in-time).

    Only symbols with ADV > ``min_adv`` are eligible -- this drops names not yet listed,
    delisted, or too thin at this moment. Ties break by symbol name for determinism.
    Returns at most ``top_n`` symbols, fewer if not enough clear the floor.
    """

    ranked = []
    for sym, bars in candidate_bars.items():
        adv = trailing_adv(bars, at_ts, window_days=window_days)
        if adv > min_adv:
            ranked.append((adv, sym))
    ranked.sort(key=lambda t: (-t[0], t[1]))
    return [sym for _, sym in ranked[:top_n]]
