"""C×D combined-book kill-test: line D trend (S7) + line C carry (RV-C), one capital base.

The kill question (proposed 2026-06-13): line D's surviving edge is *directional* crypto-beta
trend (S7, honest forward Sharpe ~0.70, maxDD -21..-30% that parameter tuning cannot cut -- it is a
crypto-beta structural tail). Line C's surviving edge is *delta-neutral* dated-basis carry
(BTC/ETH, Sharpe ~1.4, thin +6.4%/yr, near-zero drawdown). Their tails point in **opposite**
directions: trend dies in a crash, cash-and-carry's tail is an upside short-squeeze. So a small
carry sleeve should act as ballast -- NOT a return engine (it is thin and capacity-capped to
BTC/ETH) but a Sharpe stabilizer that cuts the trend tail the trend itself cannot cut. This mirrors
line A's "金/债是压舱石非收益引擎".

Pre-registered kill criterion (write it before reading the number): adding the carry sleeve at a
**realistic capacity weight** must (a) lift combined Sharpe above trend-alone AND (b) make the
combined maxDD shallower than trend-alone. If it cannot do both at a deployable carry weight, the
combination adds nothing and is killed. Honest caveat baked into the runner: both sleeves are long
the same "crypto stays alive / contango persists" macro factor, so the diversification is real in
the short-term tail but NOT all-weather.

Carry is capacity-constrained (BTC/ETH maker only -- §7.x broke breadth), so we combine at **fixed
a-priori weights** chosen by capacity, not by inverse-vol (which would balloon the thin sleeve's
weight to a non-deployable level). Pure (no IO); reuses ``x4.portfolio`` and ``rv.stats``.
"""

from __future__ import annotations

from qount.rv.stats import returns_from_curve
from qount.x4.portfolio import correlation, sharpe_of  # re-exported for runner convenience

__all__ = ["align_curves", "combine_fixed", "kill_verdict", "correlation", "sharpe_of"]


def align_curves(
    named: dict[str, tuple[list[int], list[float]]],
    *,
    initial_capital: float = 100_000.0,
) -> tuple[list[int], dict[str, list[float]]]:
    """Align sleeve equity curves onto their common timestamps, renormalized to ``initial_capital``.

    ``named`` maps a sleeve name to ``(ts_list, curve)`` of equal length (``curve[i]`` is the
    cumulative equity at ``ts_list[i]``). Sleeves come from different engines (trend uses um klines,
    carry uses COIN-M + spot) so their bar counts and date spans differ; we intersect on actual
    timestamps (daily, UTC) and rebase every curve to start at ``initial_capital`` on the first
    common bar. Pairing by timestamp makes the half-bar convention difference between engines
    immaterial. Raises if there is no common span.
    """

    if not named:
        raise ValueError("need at least one sleeve")
    maps: dict[str, dict[int, float]] = {}
    for n, (ts, curve) in named.items():
        if len(ts) != len(curve):
            raise ValueError(f"sleeve {n!r}: ts/curve length mismatch ({len(ts)} vs {len(curve)})")
        maps[n] = dict(zip(ts, curve))
    common = sorted(set.intersection(*(set(m) for m in maps.values())))
    if len(common) < 2:
        raise ValueError("sleeves share fewer than 2 common timestamps")
    out: dict[str, list[float]] = {}
    for n, m in maps.items():
        raw = [m[t] for t in common]
        base = raw[0]
        if base <= 0:
            raise ValueError(f"sleeve {n!r}: non-positive equity at first common bar")
        out[n] = [initial_capital * x / base for x in raw]
    return common, out


def combine_fixed(
    curves: dict[str, list[float]],
    weights: dict[str, float],
    *,
    initial_capital: float = 100_000.0,
) -> list[float]:
    """Combine aligned curves at constant target ``weights``, rebalanced every bar (no look-ahead).

    Fixed weights (not inverse-vol) are the honest way to size a capacity-constrained sleeve: the
    carry allocation is decided a priori by how much BTC/ETH maker depth can absorb, not handed to a
    vol-parity rule that would over-weight the thin, low-vol sleeve into a non-deployable corner.
    Weights need not sum to 1 (the remainder sits in cash, earning 0). All curves must be equal
    length and the same length the aligner produced.
    """

    names = list(curves)
    if not names:
        raise ValueError("need at least one curve")
    length = len(curves[names[0]])
    if any(len(curves[n]) != length for n in names):
        raise ValueError("all curves must be the same length")
    missing = [n for n in names if n not in weights]
    if missing:
        raise ValueError(f"no weight for sleeve(s): {missing}")

    rets = {n: returns_from_curve(curves[n]) for n in names}
    port = [initial_capital]
    for t in range(length - 1):
        r_p = sum(weights[n] * rets[n][t] for n in names)
        port.append(port[-1] * (1.0 + r_p))
    return port


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0]
    worst = 0.0
    for x in curve:
        peak = max(peak, x)
        if peak > 0:
            worst = min(worst, x / peak - 1.0)
    return worst


def kill_verdict(
    combo: list[float],
    trend_alone: list[float],
    *,
    periods_per_year: float = 365.0,
) -> dict:
    """Pre-registered C×D verdict: the combo must beat trend-alone on BOTH Sharpe and maxDD.

    Adding a market-neutral carry sleeve is only worth it if it lifts risk-adjusted return *and*
    cuts the tail; a combo that merely dilutes return without improving Sharpe/drawdown is killed.
    Returns the two curves' Sharpe/maxDD, the deltas, and the boolean verdict.
    """

    sh_c = sharpe_of(combo, periods_per_year=periods_per_year)
    sh_t = sharpe_of(trend_alone, periods_per_year=periods_per_year)
    dd_c = _max_drawdown(combo)
    dd_t = _max_drawdown(trend_alone)
    sharpe_ok = sh_c > sh_t
    dd_ok = dd_c > dd_t  # shallower (less negative) drawdown
    return {
        "sharpe_combo": sh_c,
        "sharpe_trend": sh_t,
        "sharpe_delta": sh_c - sh_t,
        "maxdd_combo": dd_c,
        "maxdd_trend": dd_t,
        "maxdd_delta": dd_c - dd_t,
        "sharpe_ok": sharpe_ok,
        "dd_ok": dd_ok,
        "verdict": "PASS" if (sharpe_ok and dd_ok) else "FAIL",
    }
