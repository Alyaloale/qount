"""X4 strategy library: the four bake-off contestants (线 D). Plan: §2.

Every strategy implements the directional :class:`Strategy` protocol — ``on_bar(bar)`` returns a
signed **target weight** in ``[-1, 1]`` (equity-normalized; the backtest driver sizes it against
current equity). Returning ``0.0`` means flat (used during warm-up, with no look-ahead — a bar's
decision uses only that bar's close and prior bars).

Implemented here (the clean single-asset directional pair):
  * :class:`TrendFollow` (S3-CTA): dual-SMA crossover, long above / short below.
  * :class:`MomentumBreakout` (S4-MOM): Donchian high/low breakout gated by a volume surge.

The two multi-shape contestants — :class:`GridStrategy` (S1, a ladder over one asset, reusing
``grid.engine``/``grid.trend``) and :class:`PairStrategy` (S2, a two-leg BTC-ETH z-score) — need
their own non-single-weight drivers and land in the next B0 increment; their classes are declared
below with the agreed signatures so the package shape is complete.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol

from qount.grid.data import Bar


class Strategy(Protocol):
    """A single-asset directional strategy: one signed target weight per bar."""

    name: str

    def on_bar(self, bar: Bar) -> float:
        """Return the signed target weight in [-1, 1] for this bar (0.0 = flat)."""
        ...


class TrendFollow:
    """S3-CTA: dual-SMA crossover trend follower (long above, short below).

    Maintains the fast/slow simple moving averages of closes incrementally. Until both
    windows are warm the target is flat (0.0) — no look-ahead. Once warm: fast SMA above the
    slow SMA => target ``+1`` (long), below => ``-1`` (short). (Bollinger-band confirmation
    from plan §2 S3 is a later refinement; the baseline ships the simplest honest crossover.)
    """

    def __init__(self, *, fast: int = 20, slow: int = 100, allow_short: bool = True,
                 regime_sma: int = 0, adx_min: float = 0.0, adx_period: int = 14) -> None:
        if fast < 1 or slow <= fast:
            raise ValueError(f"need 1 <= fast < slow, got fast={fast}, slow={slow}")
        self.name = "S3-CTA"
        self.fast = fast
        self.slow = slow
        self.allow_short = allow_short  # False => long-biased (down-trend -> flat, not short)
        # regime_sma>0: a long-term trend gate -- a long is only held above this SMA (sidesteps
        # bear-market bull traps, e.g. 2022). 0 = off.
        self.regime_sma = regime_sma
        # adx_min>0: require ADX >= adx_min to take a long (§21.C chop filter). 0 = off.
        self.adx_min = adx_min
        self.adx_period = adx_period
        need = max(slow, regime_sma, (2 * adx_period + 2) if adx_min else 0)
        self._closes: deque[float] = deque(maxlen=need)
        self._highs: deque[float] = deque(maxlen=need)
        self._lows: deque[float] = deque(maxlen=need)

    def _adx(self) -> float | None:
        """Wilder-style ADX from the rolling window (None until warm). No look-ahead (uses closed bars)."""
        n = self.adx_period
        highs, lows, closes = list(self._highs), list(self._lows), list(self._closes)
        if len(closes) < 2 * n + 1:
            return None
        trs, pdm, mdm = [], [], []
        for i in range(1, len(closes)):
            up, dn = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
            pdm.append(up if (up > dn and up > 0) else 0.0)
            mdm.append(dn if (dn > up and dn > 0) else 0.0)
            trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                           abs(lows[i] - closes[i - 1])))
        dxs = []
        for j in range(n - 1, len(trs)):
            atr = sum(trs[j - n + 1:j + 1])
            pdi = 100 * sum(pdm[j - n + 1:j + 1]) / atr if atr > 0 else 0.0
            mdi = 100 * sum(mdm[j - n + 1:j + 1]) / atr if atr > 0 else 0.0
            denom = pdi + mdi
            dxs.append(100 * abs(pdi - mdi) / denom if denom > 0 else 0.0)
        if len(dxs) < n:
            return None
        return sum(dxs[-n:]) / n

    def on_bar(self, bar: Bar) -> float:
        self._closes.append(bar.close)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        if len(self._closes) < self.slow:
            return 0.0
        closes = list(self._closes)
        fast_ma = sum(closes[-self.fast:]) / self.fast
        slow_ma = sum(closes[-self.slow:]) / self.slow
        if self.regime_sma:
            if len(closes) < self.regime_sma:
                return 0.0  # regime warm-up: flat
            if bar.close <= sum(closes[-self.regime_sma:]) / self.regime_sma:
                return 0.0  # below the long-term trend: don't fight the regime (no long, no short)
        if self.adx_min:
            adx = self._adx()
            if adx is None or adx < self.adx_min:
                return 0.0  # warm-up or too choppy: skip the long (no whipsaw entry)
        if fast_ma > slow_ma:
            return 1.0
        return -1.0 if self.allow_short else 0.0


class MomentumBreakout:
    """S4-MOM: Donchian breakout gated by a volume surge (plan §2 S4).

    Long when the close breaks above the highest high of the prior ``lookback`` bars *and* the
    bar's volume >= ``vol_mult`` × the prior-window average volume; short on the symmetric
    downside break. The position persists until the opposite breakout fires (let winners run,
    cut on reversal). Warm-up (fewer than ``lookback`` prior bars) is flat.

    The optional open-interest (OI) confirmation from plan §2 S4 is added once the metrics dump
    lands in ``x4/data.py``; this baseline is the price+volume two-factor degrade noted there.
    """

    def __init__(self, *, lookback: int = 20, vol_mult: float = 1.5, exit_lookback: int | None = None,
                 allow_short: bool = True, regime_sma: int = 0) -> None:
        if lookback < 1:
            raise ValueError(f"lookback must be >= 1, got {lookback}")
        self.name = "S4-MOM"
        self.lookback = lookback
        self.vol_mult = vol_mult
        # Turtle-style asymmetric channel: exit on a shorter channel than entry (faster to flatten).
        self.exit_lookback = exit_lookback or lookback
        self.allow_short = allow_short  # False => long-only Donchian (down-break -> flat, not short)
        # regime_sma>0: a long-term trend gate -- no long entry below it, and a regime break exits.
        self.regime_sma = regime_sma
        self._bars: deque[Bar] = deque(maxlen=max(lookback, self.exit_lookback))
        self._closes: deque[float] = deque(maxlen=regime_sma) if regime_sma else deque(maxlen=1)
        self._target = 0.0

    def on_bar(self, bar: Bar) -> float:
        prior = list(self._bars)
        self._bars.append(bar)
        self._closes.append(bar.close)
        regime_ma = None
        if self.regime_sma and len(self._closes) >= self.regime_sma:
            regime_ma = sum(self._closes) / self.regime_sma
        if len(prior) < self.lookback:
            return self._target  # warm-up: flat (target starts at 0.0)
        entry = prior[-self.lookback:]
        exit_ = prior[-self.exit_lookback:]
        hh = max(b.high for b in entry)
        ll = min(b.low for b in entry)
        vavg = sum(b.volume for b in entry) / len(entry)
        surge = bar.volume >= self.vol_mult * vavg
        regime_ok = regime_ma is None or bar.close > regime_ma
        if surge and bar.close > hh and regime_ok:
            self._target = 1.0
        elif surge and bar.close < ll:
            self._target = -1.0 if self.allow_short else self._target
        # long-only exit: drop a long on a short-channel break OR a long-term regime break
        if not self.allow_short and self._target > 0:
            if bar.close < min(b.low for b in exit_) or (regime_ma is not None and bar.close <= regime_ma):
                self._target = 0.0
        return self._target


def _vol_adj_momentum(closes: list[float], t: int, lookback: int) -> float | None:
    """Volatility-adjusted momentum at index ``t``: ``(close_t/close_{t-lb} − 1) / σ(returns)``.

    Returns ``None`` if there isn't ``lookback`` history or the vol is zero. Uses only closes up to
    ``t`` (no look-ahead). The vol scaling makes cross-symbol ranks comparable (a 20% move in a calm
    coin outranks a 20% move in a wild one)."""

    if t < lookback or t - lookback < 0:
        return None
    base = closes[t - lookback]
    if base <= 0:
        return None
    mom = closes[t] / base - 1.0
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(t - lookback + 1, t + 1) if closes[i - 1] > 0]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
    vol = var ** 0.5
    return mom / vol if vol > 0 else None


def cross_sectional_rank(closes_by_sym: dict[str, list[float]], t: int, *, lookback: int,
                         regime_sma: int, top_k: int) -> list[str]:
    """Select the ``top_k`` symbols by vol-adjusted momentum at index ``t`` (S6-XMOM signal, §16).

    A symbol is eligible only if it is **above its own ``regime_sma``-day SMA** (per-symbol trend gate)
    and has enough history for the momentum/vol. Ties broken by symbol name for determinism. No
    look-ahead (only closes ≤ ``t``). Returns ``[]`` when nothing qualifies (-> sit in cash).
    """

    scores: dict[str, float] = {}
    for sym, closes in closes_by_sym.items():
        if t < regime_sma - 1 or t >= len(closes):
            continue
        sma = sum(closes[t - regime_sma + 1:t + 1]) / regime_sma
        if closes[t] <= sma:                       # per-symbol SMA200 regime gate
            continue
        sc = _vol_adj_momentum(closes, t, lookback)
        if sc is not None and sc > 0:              # only positive (strong) momentum
            scores[sym] = sc
    return sorted(scores, key=lambda s: (-scores[s], s))[:top_k]


def sma_regime_mask(closes: list[float], window: int) -> list[bool]:
    """Per-bar mask: is ``closes[t]`` above its trailing ``window``-bar SMA? (§19 master gate).

    Used as the S7-TREND-PORT big-picture (BTC) risk-off overlay: when the market leader is below
    its long SMA the whole portfolio sits in cash. ``mask[t]`` uses only ``closes[:t+1]`` (no
    look-ahead); the warm-up region (``t < window-1``) is ``False`` (gate off = flat until warm).
    ``window <= 0`` returns all-``True`` (gate disabled).
    """

    n = len(closes)
    if window <= 0:
        return [True] * n
    mask = [False] * n
    for t in range(window - 1, n):
        sma = sum(closes[t - window + 1:t + 1]) / window
        mask[t] = closes[t] > sma
    return mask


class EnsembleStrategy:
    """Parameter-ensemble wrapper: average the signals of N sub-strategies (§14).

    A single trend/breakout parameter set (e.g. SMA 20/100) sits on a *parameter cliff* — a small
    shift can flip a whole trade. Spreading capital across a fan of periods and averaging their target
    weights (consensus sizing) keeps the full trend capture while smoothing the chop-driven flip-flops:
    when the members disagree the net position is small, when they align it is full. The mean weight
    stays in ``[-1, 1]`` so it drops straight into :func:`~qount.x4.backtest.run_directional` (and its
    vol-parity sizing). Each member keeps its own state and is fed every bar.
    """

    def __init__(self, members: list, *, name: str = "ENS") -> None:
        if not members:
            raise ValueError("ensemble needs >= 1 member")
        self.members = members
        self.name = name

    def on_bar(self, bar: Bar) -> float:
        return sum(m.on_bar(bar) for m in self.members) / len(self.members)


class VelocityScalper:
    """S5-VEL: minute-level ultra-short momentum-burst scalper (velocity + acceleration).

    The owner's hypothesis: catch an *accelerating* micro-trend and take profit fast ("见好就收").
    Velocity = the rate-of-change of price over ``vel_window`` bars (1st derivative); acceleration =
    the change in that velocity over ``accel_lag`` bars (2nd derivative). It emits an **entry** signal
    (``1.0``) only when price is both rising *and* accelerating beyond ``vel_threshold`` — a fresh
    impulse, not a tired trend. It does NOT manage exits: the take-profit / stop / timeout ("见好就收")
    live in the driver :func:`~qount.x4.backtest.run_scalper`, which can fill them intrabar.

    Honest prior (write it on the tin): at 1m, a taker round-trip costs ~taker+slip on each leg; the
    burst has to clear that to net positive. This strategy exists to *measure* whether the impulse
    edge survives retail fees, not because it is assumed to.
    """

    def __init__(self, *, vel_window: int = 5, accel_lag: int = 3, vel_threshold: float = 0.001) -> None:
        if vel_window < 1 or accel_lag < 1:
            raise ValueError(f"vel_window/accel_lag must be >= 1, got {vel_window}/{accel_lag}")
        self.name = "S5-VEL"
        self.vel_window = vel_window
        self.accel_lag = accel_lag
        self.vel_threshold = vel_threshold
        self._closes: deque[float] = deque(maxlen=vel_window + accel_lag + 1)

    def on_bar(self, bar: Bar) -> float:
        self._closes.append(bar.close)
        need = self.vel_window + self.accel_lag + 1
        if len(self._closes) < need:
            return 0.0  # warm-up
        c = list(self._closes)
        v_now = c[-1] / c[-1 - self.vel_window] - 1.0                       # ROC now (velocity)
        v_prev = c[-1 - self.accel_lag] / c[-1 - self.accel_lag - self.vel_window] - 1.0
        accel = v_now - v_prev                                              # 2nd derivative
        return 1.0 if (v_now > self.vel_threshold and accel > 0.0) else 0.0


@dataclass(frozen=True)
class GridStrategy:
    """S1-GRID config: long-only geometric grid + SMA200 trend gate (plan §2 S1).

    Not a single-weight directional strategy — it's a *ladder* over one asset, so its logic lives
    in the driver :func:`~qount.x4.backtest.run_grid`, which reuses ``grid.engine.GridLadder``
    (ladder math + buy/sell pairing) and ``grid.trend`` (the SMA200 risk gate: ACTIVE = full grid,
    DERISK = sell-only, PAUSED = liquidate to cash). This dataclass just carries the parameters.

    ``half_width`` seeds the grid range at ``close × (1 ± half_width)`` on each (re)arm; ``n`` is the
    fixed grid count (plan §2 S1 = 20). Defaults are pre-registered (no per-line tuning).
    """

    name: str = "S1-GRID"
    n: int = 20
    half_width: float = 0.15
    sma_window: int = 200
    confirm_bars: int = 2


@dataclass(frozen=True)
class PairStrategy:
    """S2-PAIR config: BTC-ETH ratio z-score statistical arbitrage (plan §2 S2).

    A two-leg strategy — long one / short the other on z-score extremes of the ETH/BTC ratio — so
    its logic lives in the driver :func:`~qount.x4.backtest.run_pair`. ``z > +entry_z`` (ETH rich)
    => short ETH / long BTC; ``z < -entry_z`` => the reverse; ``|z| < exit_z`` => flat. Each leg is
    sized ``leg_leverage × equity`` (dollar-neutral). This is a *soft* pair (cointegration can break,
    plan §2 杀手1) — included as one bake-off contestant, not asserted to be robust.
    """

    name: str = "S2-PAIR"
    window: int = 90
    entry_z: float = 2.0
    exit_z: float = 0.5
    leg_leverage: float = 1.0
    stop_z: float = 0.0   # 0 = disabled; else force-exit (and latch flat) when |z| > stop_z
                          # -- cuts a cointegration break (the spread runs away, not reverts)


@dataclass(frozen=True)
class KalmanPair:
    """S2-K config: BTC-ETH pair on a Kalman *dynamic* hedge ratio (§12 optimization of S2-PAIR).

    Replaces the static rolling z-score with :class:`~qount.x4.indicators.KalmanHedge`: β (the hedge
    ratio) adapts online, so the signal is the standardized Kalman forecast error rather than an
    OLS-window z that lags a regime shift. Driver: :func:`~qount.x4.backtest.run_kalman_pair`. Same
    entry/exit/stop semantics on ``z`` as :class:`PairStrategy`; ``delta``/``r`` are the filter knobs.
    """

    name: str = "S2-K"
    delta: float = 1e-4
    r: float = 1e-3
    entry_z: float = 2.0
    exit_z: float = 0.5
    leg_leverage: float = 1.0
    stop_z: float = 0.0
    warmup: int = 30   # bars to let β settle before trading (no look-ahead)
