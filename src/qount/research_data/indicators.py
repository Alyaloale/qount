"""Shared incremental indicators (pure, no IO): ATR and Kalman hedge ratio.

Shared by the dynamic-parameter optimizations: S3/S4 volatility-parity position sizing and the S1
ATR dynamic grid both need a running Average True Range. Kept pure and incremental (one bar at a
time, no look-ahead) so it is trivially offline-testable and reusable across drivers.
"""

from __future__ import annotations

from collections import deque

from qount.research_data.market_data import Bar


class ATR:
    """Average True Range over ``lookback`` bars (simple mean of true ranges).

    True range = max(high−low, |high−prev_close|, |low−prev_close|). :meth:`update` takes one bar and
    returns the current ATR (absolute price units), or ``None`` until ``lookback`` bars are seen.
    """

    def __init__(self, lookback: int = 14) -> None:
        if lookback < 1:
            raise ValueError(f"lookback must be >= 1, got {lookback}")
        self.lookback = lookback
        self._trs: deque[float] = deque(maxlen=lookback)
        self._prev_close: float | None = None

    def update(self, bar: Bar) -> float | None:
        if self._prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(bar.high - bar.low, abs(bar.high - self._prev_close),
                     abs(bar.low - self._prev_close))
        self._prev_close = bar.close
        self._trs.append(tr)
        if len(self._trs) < self.lookback:
            return None
        return sum(self._trs) / self.lookback


class KalmanHedge:
    """1-D Kalman filter tracking a *dynamic* hedge ratio β for a pair (S2 optimization, §12).

    Model (the standard Kalman pairs-trading form): the dependent leg ``y`` (ETH) is a time-varying
    multiple of the independent leg ``x`` (BTC), ``y_t = β_t · x_t + e_t``, with β a random walk
    (``β_t = β_{t-1} + w_t``). Each :meth:`update` runs predict→correct and returns
    ``(β, e, z)`` where ``e`` is the forecast error (the spread vs the *current* dynamic ratio) and
    ``z = e / √Q`` its standardized value (Q = forecast variance). Trading off ``z`` replaces the
    static rolling z-score: β adapts smoothly to a regime shift instead of the OLS window lagging it.

    ``delta`` sets the process noise (``Vw = delta/(1−delta)``, larger => β adapts faster); ``r`` is
    the observation variance ``Ve``. Defaults follow Chan's *Algorithmic Trading*.
    """

    def __init__(self, *, delta: float = 1e-4, r: float = 1e-3, beta0: float = 1.0,
                 p0: float = 1.0) -> None:
        if not (0.0 < delta < 1.0):
            raise ValueError(f"delta must be in (0,1), got {delta}")
        self.beta = beta0
        self.P = p0
        self.Vw = delta / (1.0 - delta)
        self.Ve = r

    def update(self, x: float, y: float) -> tuple[float, float, float]:
        p_pred = self.P + self.Vw                 # predict β variance (β itself a random walk)
        e = y - self.beta * x                     # forecast error = spread vs current ratio
        q = x * p_pred * x + self.Ve              # forecast variance
        k = p_pred * x / q if q > 0 else 0.0      # Kalman gain
        self.beta = self.beta + k * e             # correct β
        self.P = p_pred - k * x * p_pred
        z = e / (q ** 0.5) if q > 0 else 0.0
        return self.beta, e, z
