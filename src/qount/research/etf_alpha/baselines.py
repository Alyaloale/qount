"""Predeclared cash, allocation and momentum diagnostics through one P3 engine."""
from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from qount.research.etf_trader import baselines as P2
from qount.research.etf_trader import constraints as C
from qount.research.etf_trader.costs import cost_params_for
from qount.research.etf_trader.env import Decision, max_drawdown
from qount.research.etf_trader.scorer import daily_returns, rolling_std, shift
from qount.research.etf_trader.universe import US_ACCOUNT

from .data import Panel, total_return_index
from .execution import execution_inputs, project_caps, simulate
from .features import Features


@dataclass(frozen=True)
class Baseline:
    baseline_id: str
    variant: str
    rule: str
    targets: np.ndarray
    every: int = 21


def _risk_parity(cov: np.ndarray) -> np.ndarray:
    """Fixed cyclic coordinate solve for equal risk contributions, then normalize."""
    n = len(cov)
    x = np.ones(n)
    for _ in range(100):
        for i in range(n):
            diagonal = cov[i, i]
            if diagonal <= 1e-14:
                return np.zeros(n)
            linear = cov[i] @ x - diagonal * x[i]
            x[i] = (-linear + np.sqrt(linear ** 2 + 4 * diagonal / n)) / (2 * diagonal)
    return x / x.sum()


def declared_baselines(panel: Panel, features: Features) -> list[Baseline]:
    T, n = panel.close.shape
    close_tr = total_return_index(panel.close, panel.dividends, panel.splits)
    vol = rolling_std(daily_returns(close_tr), 63)
    momentum = close_tr / shift(close_tr, 252) - 1
    cash_momentum = panel.cash_close / shift(panel.cash_close, 252) - 1
    equal = np.full((T, n), 1 / n)
    sp = np.zeros((T, n)); sp[:, panel.symbols.index("SPY")] = 1
    sf = P2.sixty_forty(close_tr, US_ACCOUNT)
    rotation, dual, trend, rp, vt = [np.zeros((T, n)) for _ in range(5)]
    for t in range(T):
        valid = np.isfinite(momentum[t]) & np.isfinite(vol[t]) & (vol[t] > 1e-12)
        qualified = valid & (momentum[t] > cash_momentum[t])
        for target, count in ((rotation, 3), (dual, 1), (trend, n)):
            candidates = np.flatnonzero(qualified)
            # Stable ties use a symbol name, not an asset's array position.
            chosen = sorted(candidates, key=lambda i: (-momentum[t, i], panel.symbols[i]))[:count]
            if chosen:
                inv = 1 / vol[t, chosen]
                target[t, chosen] = inv / inv.sum()
        cov = features.covariance_annual[t]
        if np.isfinite(cov).all():
            rp[t] = _risk_parity(cov)
            base = np.divide(1, vol[t], out=np.zeros(n), where=np.isfinite(vol[t]) & (vol[t] > 0))
            if base.sum() > 0:
                base = project_caps(base / base.sum(), US_ACCOUNT)
                sigma = float(np.sqrt(base @ cov @ base))
                vt[t] = base * min(1, 0.12 / sigma) if sigma > 1e-12 else base
    baseline = [Baseline("cash", "BIL_proxy", "all cash; event-based BIL close total-return carry", np.zeros((T, n))),
                Baseline("equal_weight", "constraint_matched", "nine equal weights, 21-session rebalance", equal),
                Baseline("risk_parity", "constraint_matched", "60-session covariance, shrink 0.2, 100 fixed ERC iterations", rp),
                Baseline("vol_target", "constraint_matched", "63-session inverse-vol, 12% target, trailing60 shrink covariance", vt),
                Baseline("12m_momentum", "constraint_matched", "252-session return above trailing BIL; qualified inverse-vol", trend),
                Baseline("dual_momentum", "constraint_matched", "Top-1 252-session relative strength above trailing BIL", dual),
                Baseline("top3_momentum", "constraint_matched", "Top-3 252-session relative strength above trailing BIL", rotation),
                Baseline("fixed_factor", "p2_rule_p3_execution", "frozen four-factor prior, neutral Value; P3 event accounting", P2.fixed_scorer(close_tr, US_ACCOUNT))]
    for name, rule, weights, every in (("spy_buy_hold", "SPY entry once; natural reference retains its 100% allocation", sp, T + 1),
                                       ("sixty_forty", "SPY60/IEF40 every 21 sessions", sf, 21)):
        baseline.extend([Baseline(name, "natural", rule + "; no single/group/DD reductions", weights, every),
                         Baseline(name, "constraint_matched", rule + "; P3 single/group/DD limits", weights, every)])
    return baseline


def scorecard(result, cash_returns: np.ndarray, dates: tuple[str, ...]) -> dict:
    start = result.start
    r = result.returns[start + 1:]
    rf = cash_returns[start + 1:]
    excess = r - rf
    sd = np.std(excess, ddof=1)
    zero_sd = np.std(r, ddof=1)
    quantile = np.quantile(r, 0.05)
    tail = r[r <= quantile]
    cagr = float((result.equity[-1] / result.equity[start]) ** (252 / len(r)) - 1)
    mdd = max_drawdown(result.equity[start:])
    annual = {}
    for year in sorted({day[:4] for day in dates[start + 1:]}):
        selected = np.array([d.startswith(year) for d in dates[start + 1:]])
        annual[year] = {"return": float(np.prod(1 + r[selected]) - 1), "days": int(selected.sum()),
                        "period_status": "complete" if selected.sum() >= 240 else "partial"}
    return {"cagr": cagr, "sharpe_excess_cash": float(excess.mean() * np.sqrt(252) / sd) if sd > 1e-14 else None,
            "sharpe_zero": float(r.mean() * np.sqrt(252) / zero_sd) if zero_sd > 1e-14 else None,
            "max_drawdown": mdd, "calmar": cagr / mdd if mdd > 1e-14 else None,
            "cvar95_daily_return": float(tail.mean()), "cvar95_loss": float(max(0, -tail.mean())),
            "trading_days": len(r), "annual": annual, "total_costs": float(result.costs.sum()),
            "distribution_cash": float(result.distributions.sum()), "cash_carry": float(result.cash_carry.sum()),
            "mean_cash_weight": float(np.mean(1 - result.weights[start + 1:].sum(axis=1))),
            "max_rolling_voluntary": float(max(np.convolve(result.voluntary_turnover[start + 1:], np.ones(min(252, len(r))), 'valid'))),
            "forced_breaches": int(result.forced_breach.sum()), "minimum_cash": float(np.nanmin(result.cash)),
            "state": {"last_close": dates[-1], "cash": result.state.cash, "shares": result.state.shares.tolist(),
                      "dd_peak": result.state.derisk.peak, "dd_cap": result.state.derisk.cap,
                      "turnover_used": result.state.budget.used_voluntary,
                      "forced_turnover_used": result.state.budget.used_forced}}


def write_curve(path: Path, result, dates: tuple[str, ...], symbols: tuple[str, ...]) -> None:
    with path.open("x", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["date", "equity", "cash", "net_return", "cost", "distribution_cash", "cash_carry",
                         "voluntary_turnover", "forced_turnover", "gross_cap", *[f"weight_{s}" for s in symbols],
                         *[f"shares_{s}" for s in symbols]])
        for t in range(result.start, len(dates)):
            writer.writerow([dates[t], result.equity[t], result.cash[t], result.returns[t], result.costs[t],
                             result.distributions[t], result.cash_carry[t], result.voluntary_turnover[t],
                             result.forced_turnover[t], result.gross_cap[t], *result.weights[t], *result.shares[t]])


def run_baselines(panel: Panel, baseline: list[Baseline], out: Path,
                  start: str = "2015-01-01", progress=None) -> dict:
    first = int(np.searchsorted(panel.dates, start))
    costs = cost_params_for(US_ACCOUNT)
    prepared = execution_inputs(panel, costs)
    reports = {}
    for item in baseline:
        label = f"{item.baseline_id}__{item.variant}"
        account = replace(US_ACCOUNT, single_cap=1, group_cap=1) if item.variant == "natural" else US_ACCOUNT
        report = {"baseline_id": item.baseline_id, "baseline_variant": item.variant, "rule": item.rule, "costs": {}}
        for multiplier in (1.0, 2.0, 3.0):
            controller = C.DeRisk(d1=0.999, d2=0.9999) if item.variant == "natural" else C.DeRisk()
            policy = P2.scheduled_policy(item.targets, first, item.every)
            result = simulate(panel, policy, start=first, account=account, costs=costs,
                              cost_multiplier=multiplier, inputs=prepared, derisk=controller)
            report["costs"][f"{multiplier:g}x"] = scorecard(result, prepared.cash_returns, panel.dates)
            write_curve(out / f"{label}_{multiplier:g}x.csv", result, panel.dates, panel.symbols)
        reports[label] = report
        if progress:
            progress(label)
    return reports
