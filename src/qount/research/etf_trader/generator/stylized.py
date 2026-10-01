"""Stylized-fact gates for generator acceptance (design §7.3).

Each check maps one world's daily data to a statistic and a pass flag; :func:`gate_pass_rate`
aggregates over worlds.  A fact passes when ≥ 80% of worlds fall inside the target range.
Thresholds are the §7.3 values; the drawdown-frequency target needs calibration data and is
returned as a statistic only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PASS_SHARE = 0.80
TRADING_DAYS = 252


def autocorr(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size <= lag + 1:
        return float("nan")
    a, b = x[:-lag] - x.mean(), x[lag:] - x.mean()
    denom = float(np.sum((x - x.mean()) ** 2))
    return float(np.sum(a * b) / denom) if denom > 0 else float("nan")


def kurtosis(x: np.ndarray) -> float:
    """Non-excess kurtosis (normal = 3)."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    c = x - x.mean()
    v = float(np.mean(c * c))
    return float(np.mean(c**4) / v**2) if v > 0 else float("nan")


def monthly(log_r: np.ndarray, days: int = 21) -> np.ndarray:
    x = np.asarray(log_r, dtype=float)
    m = x.shape[0] // days
    return x[: m * days].reshape(m, days, *x.shape[1:]).sum(axis=1)


def leverage_corr(r: np.ndarray, horizon: int = 21) -> float:
    """corr(r_t, realized variance over t+1..t+horizon)."""
    r = np.asarray(r, dtype=float)
    sq = r * r
    cs = np.concatenate([[0.0], np.cumsum(sq)])
    fwd = cs[1 + horizon : len(r) + 1] - cs[1 : len(r) + 1 - horizon]
    return float(np.corrcoef(r[: fwd.size], fwd)[0, 1])


def predictive_r2(y: np.ndarray, x: np.ndarray) -> float:
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3 or np.std(x[ok]) == 0:
        return float("nan")
    return float(np.corrcoef(x[ok], y[ok])[0, 1] ** 2)


def dividend_yield_r2(log_r: np.ndarray, log_dy: np.ndarray, horizon: int) -> float:
    """R² of log dividend yield at t on the cumulative log return over t+1..t+horizon."""
    r = np.asarray(log_r, dtype=float)
    cs = np.concatenate([[0.0], np.cumsum(r)])
    n = len(r) - horizon
    if n < 3:
        return float("nan")
    fwd = cs[1 + horizon : 1 + horizon + n] - cs[1 : 1 + n]
    return predictive_r2(fwd, np.asarray(log_dy, dtype=float)[:n])


def tsmom_sharpe(log_r: np.ndarray, lookback: int = TRADING_DAYS) -> float:
    """Gross Sharpe of an equal-risk 12-month sign strategy across columns (daily rebalanced)."""
    r = np.asarray(log_r, dtype=float)
    cs = np.vstack([np.zeros((1, r.shape[1])), np.cumsum(r, axis=0)])
    past = cs[lookback:-1] - cs[: -lookback - 1]  # return over t-lookback+1..t
    sign = np.sign(past)
    vol = np.array([np.std(r[max(0, t - 63) : t + 1], axis=0, ddof=1) for t in range(lookback - 1, len(r) - 1)])
    pos = np.divide(sign, vol, out=np.zeros_like(sign), where=vol > 0)
    pos /= np.maximum(np.abs(pos).sum(axis=1, keepdims=True), 1e-12)
    pnl = (pos * (np.exp(r[lookback:]) - 1.0)).sum(axis=1)
    sd = np.std(pnl, ddof=1)
    return float(np.mean(pnl) / sd * np.sqrt(TRADING_DAYS)) if sd > 0 else 0.0


def max_drawdown_from_log(log_r: np.ndarray) -> float:
    lvl = np.concatenate([[0.0], np.cumsum(np.asarray(log_r, dtype=float))])
    return float(np.max(1.0 - np.exp(lvl - np.maximum.accumulate(lvl))))


@dataclass(frozen=True)
class WorldSample:
    log_returns: np.ndarray  # (T, n) daily log returns
    equity_mask: np.ndarray  # (n,) bool, equity-like columns
    traded_value: np.ndarray | None = None  # (T, n)
    log_dividend_yield: np.ndarray | None = None  # (T, n_equity) for equity columns


def world_checks(w: WorldSample) -> dict[str, tuple[float, bool]]:
    """``fact -> (statistic, in_range)`` for one world. Equity stats average the equity columns."""
    r = np.asarray(w.log_returns, dtype=float)
    eq = np.flatnonzero(np.asarray(w.equity_mask, dtype=bool))
    if eq.size == 0:
        raise ValueError("need at least one equity column")
    out: dict[str, tuple[float, bool]] = {}

    ac = max(abs(autocorr(r[:, j], lag)) for j in range(r.shape[1]) for lag in range(1, 6))
    out["return_autocorr_max"] = (ac, ac < 0.05)

    kd = float(np.mean([kurtosis(r[:, j]) for j in eq]))
    km = float(np.mean([kurtosis(monthly(r[:, j])) for j in eq]))
    out["kurtosis_daily"] = (kd, 5.0 <= kd <= 30.0)
    out["kurtosis_monthly_lower"] = (km, km < kd)

    ac50 = float(np.mean([autocorr(np.abs(r[:, j]), 50) for j in eq]))
    out["abs_return_autocorr_50"] = (ac50, ac50 > 0.05)

    lev = float(np.mean([leverage_corr(r[:, j]) for j in eq]))
    out["leverage_effect"] = (lev, lev < 0.0)

    if w.traded_value is not None:
        tv = np.asarray(w.traded_value, dtype=float)
        vc = float(np.mean([np.corrcoef(tv[:, j], np.abs(r[:, j]))[0, 1] for j in range(r.shape[1])]))
        out["volume_abs_return_corr"] = (vc, vc > 0.0)

    dd = float(np.mean([max_drawdown_from_log(r[:, j]) >= 0.30 for j in eq]))
    out["equity_drawdown_ge_30_share"] = (dd, True)  # compared against calibration frequency

    if w.log_dividend_yield is not None:
        dy = np.asarray(w.log_dividend_yield, dtype=float)
        r5 = float(np.mean([dividend_yield_r2(r[:, j], dy[:, k], 5 * TRADING_DAYS) for k, j in enumerate(eq)]))
        r1 = float(np.mean([dividend_yield_r2(r[:, j], dy[:, k], 21) for k, j in enumerate(eq)]))
        out["dy_r2_5y"] = (r5, 0.1 <= r5 <= 0.5)
        out["dy_r2_1m"] = (r1, r1 < 0.02)

    ts = tsmom_sharpe(r)
    out["tsmom_12m_sharpe"] = (ts, True)  # gate is on the cross-world median, see gate_pass_rate
    return out


def gate_pass_rate(results: list[dict[str, tuple[float, bool]]]) -> dict[str, dict[str, float | bool]]:
    """Aggregate per-world checks into §7.3 gates."""
    facts = sorted(set().union(*results)) if results else []
    out: dict[str, dict[str, float | bool]] = {}
    for f in facts:
        vals = [r[f] for r in results if f in r]
        stats = np.array([v[0] for v in vals], dtype=float)
        share = float(np.mean([v[1] for v in vals]))
        entry: dict[str, float | bool] = {"median": float(np.nanmedian(stats)), "share_in_range": share}
        if f == "tsmom_12m_sharpe":
            entry["passed"] = bool(0.3 <= entry["median"] <= 0.8)
        elif f == "equity_drawdown_ge_30_share":
            entry["passed"] = False  # undecidable until calibration frequency is supplied
            entry["needs_calibration"] = True
        else:
            entry["passed"] = share >= PASS_SHARE
        out[f] = entry
    return out
