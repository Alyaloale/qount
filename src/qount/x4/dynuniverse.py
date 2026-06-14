"""X4 dynamic-universe trend portfolio (线 D §22 Phase 2) — point-in-time, ragged-listing, no look-ahead.

The fixed-universe S7 "always holds yesterday's winners". A trend system should instead follow where
liquidity *is now*. This runs the same per-coin S3 trend sleeve, but the **membership is re-ranked
monthly by trailing dollar-volume** from a broad candidate pool, with three biases defended by
construction:

  * **look-ahead**: at each rebalance, rank using only bars up to the as-of date; trade the NEXT month.
  * **ragged listing / listing-time crossover**: a coin is eligible only once it has >= ``min_history``
    bars as of the rebalance date AND is still trading (a recent bar) — never used before it listed
    or after it stops printing (a delisted coin's data simply ends -> it drops out, realistically).
  * **survivorship**: the candidate pool is supplied by the caller and is meant to include
    declined/dead + late-listed names (the engine is agnostic; honesty lives in the pool).

Pure / network-free; reuses ``run_directional`` (per-coin sleeve) + ``sma_regime_mask`` + ``_std``.
Does not modify any line B/C/D module.
"""
from __future__ import annotations

from collections import deque

from qount.grid.data import Bar
from qount.x4.backtest import run_directional
from qount.x4.portfolio import _std
from qount.x4.strategies import TrendFollow, sma_regime_mask


def trailing_dollar_volume(bars: list[Bar], asof_ts: int, window: int) -> float:
    """Sum of close×volume over the last ``window`` bars with ``ts_ms <= asof_ts`` (0 if none)."""
    vals = [b.close * b.volume for b in bars if b.ts_ms <= asof_ts]
    if not vals:
        return 0.0
    return sum(vals[-window:])


def select_universe(bars_by_sym: dict[str, list[Bar]], asof_ts: int, *, k: int,
                    vol_window: int = 30, min_history: int = 200,
                    max_stale_ms: int = 7 * 86_400_000) -> list[str]:
    """Top-``k`` symbols by trailing dollar-volume among those *eligible at* ``asof_ts``.

    Eligible = has >= ``min_history`` bars up to ``asof_ts`` (listed long enough) AND a bar within
    ``max_stale_ms`` of ``asof_ts`` (still trading). Uses only data <= ``asof_ts`` -> no look-ahead."""
    ranked: list[tuple[float, str]] = []
    for s, bars in bars_by_sym.items():
        upto = [b for b in bars if b.ts_ms <= asof_ts]
        if len(upto) < min_history:
            continue
        if asof_ts - upto[-1].ts_ms > max_stale_ms:
            continue  # stopped printing (delisted / illiquid) -> not tradeable now
        ranked.append((trailing_dollar_volume(bars, asof_ts, vol_window), s))
    ranked.sort(reverse=True)
    return [s for _, s in ranked[:k]]


def _month_key(ts_ms: int) -> tuple[int, int]:
    import datetime as _dt
    d = _dt.datetime.fromtimestamp(ts_ms / 1000, _dt.UTC)
    return (d.year, d.month)


def run_dynamic_trend_portfolio(
    bars_by_sym: dict[str, list[Bar]],
    *,
    k: int = 7,
    vol_window: int = 30,
    min_history: int = 200,
    fast: int = 20,
    slow: int = 100,
    regime_sma: int = 200,
    vol_target: float = 0.02,
    max_leverage: float = 1.0,
    rebalance_band: float = 0.25,
    weighting: str = "inverse_vol",
    vol_lookback: int = 30,
    master_gate_sym: str = "BTCUSDT",
    master_gate_sma: int = 200,
    initial_capital: float = 100_000.0,
    taker_fee: float = 0.0005,
    slippage: float = 0.0002,
    turnover_fee: float | None = None,
    periods_per_year: float | None = None,
) -> dict:
    """Monthly-rebalanced dynamic-universe trend portfolio. Returns ``{equity_curve, dates, extra}``.

    The spine is ``master_gate_sym``'s timeline (it exists throughout). Per-coin sleeves are the S3
    long-only trend (with each coin's own regime gate), combined by inverse-vol among the *currently
    selected* members; membership is reselected each month from data up to the prior bar. A
    ``turnover_fee`` (default = ``taker_fee``) is charged on the fraction of the book rotated when
    membership changes (the cost the fixed-universe engine doesn't pay)."""

    if master_gate_sym not in bars_by_sym:
        raise ValueError(f"master_gate_sym {master_gate_sym!r} not in pool")
    if turnover_fee is None:
        turnover_fee = taker_fee
    spine = [b.ts_ms for b in bars_by_sym[master_gate_sym]]
    spine_set = set(spine)

    # per-coin sleeve daily returns keyed by the bar ts they accrue ON (ret[t] accrues over t-1 -> t)
    sleeve_ret: dict[str, dict[int, float]] = {}
    for s, bars in bars_by_sym.items():
        res = run_directional(
            bars, TrendFollow(fast=fast, slow=slow, allow_short=False, regime_sma=regime_sma),
            initial_capital=initial_capital, taker_fee=taker_fee, slippage=slippage,
            rebalance_band=rebalance_band, vol_target=vol_target, max_leverage=max_leverage,
            periods_per_year=periods_per_year)
        curve = res.equity_curve
        d: dict[int, float] = {}
        for i in range(len(bars) - 1):
            d[bars[i + 1].ts_ms] = (curve[i + 1] / curve[i] - 1.0) if curve[i] > 0 else 0.0
        sleeve_ret[s] = d

    btc_mask = sma_regime_mask([b.close for b in bars_by_sym[master_gate_sym]], master_gate_sma)
    gate_at = {ts: btc_mask[i] for i, ts in enumerate(spine)}

    # monthly membership: select as of the last spine ts strictly before the month's first traded bar
    members_by_month: dict[tuple[int, int], list[str]] = {}
    prev_ts = None
    for ts in spine:
        mk = _month_key(ts)
        if mk not in members_by_month:
            asof = prev_ts if prev_ts is not None else ts
            members_by_month[mk] = select_universe(bars_by_sym, asof, k=k, vol_window=vol_window,
                                                    min_history=min_history)
        prev_ts = ts

    windows: dict[str, deque] = {}
    equity = [initial_capital]
    dates = [bars_by_sym[master_gate_sym][0].date]
    cur_members: list[str] = []
    membership_log: list[tuple[str, list[str]]] = []
    n_rebal = 0
    gate_active = 0

    for i in range(1, len(spine)):
        ts = spine[i]
        mk = _month_key(ts)
        new_members = members_by_month.get(mk, cur_members)
        eq = equity[-1]
        gate_open = gate_at.get(ts, True)
        if new_members != cur_members:
            # turnover cost only when deployed (gate open); rotating while in cash is free
            if gate_open:
                old, new = set(cur_members), set(new_members)
                churn = len(old.symmetric_difference(new)) / (2 * max(len(new), 1))
                eq *= (1.0 - turnover_fee * churn)
            cur_members = new_members
            membership_log.append((bars_by_sym[master_gate_sym][i].date, list(new_members)))
            n_rebal += 1

        if not gate_open:
            equity.append(eq)   # BTC gate shut -> cash this step
            dates.append(bars_by_sym[master_gate_sym][i].date)
            for s in cur_members:
                windows.setdefault(s, deque(maxlen=vol_lookback))
            continue
        gate_active += 1

        # inverse-vol weights among members with a warm trailing window; equal otherwise
        rets = {s: sleeve_ret.get(s, {}).get(ts, 0.0) for s in cur_members}
        if cur_members and weighting == "inverse_vol" and all(
                len(windows.get(s, ())) >= 2 for s in cur_members):
            invs = {s: (1.0 / _std(windows[s]) if _std(windows[s]) > 0 else 0.0) for s in cur_members}
            tot = sum(invs.values())
            w = {s: (invs[s] / tot if tot > 0 else 1.0 / len(cur_members)) for s in cur_members}
        elif cur_members:
            w = {s: 1.0 / len(cur_members) for s in cur_members}
        else:
            w = {}
        r_p = sum(w[s] * rets[s] for s in cur_members)
        equity.append(eq * (1.0 + r_p))
        dates.append(bars_by_sym[master_gate_sym][i].date)
        for s in cur_members:
            windows.setdefault(s, deque(maxlen=vol_lookback)).append(rets[s])

    extra = {
        "n_rebalances": n_rebal,
        "gate_active_frac": gate_active / max(1, len(spine) - 1),
        "membership_log": membership_log,
        "final_members": cur_members,
        "candidate_pool_size": len(bars_by_sym),
    }
    return {"equity_curve": equity, "dates": dates, "extra": extra}
