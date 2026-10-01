"""Economic plausibility rejection sampling (design §7.2).

A world's parameters are drawn from the prior, a long sample (default 100 years after a
10-year warmup) is simulated, and the draw is discarded if any range below fails.  The
rejection rate is reported; above 50% the prior itself needs revision.  Ranges are the
§7.2 table; ``REAL_ASSET_SHARPE`` widens the single-asset Sharpe band for gold/commodity,
which have no cash-flow anchor (the table's 0–0.6 applies to equity and bond ETFs).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..baselines import oracle_weights
from ..universe import ACCOUNTS
from .params import YEAR, WorldParams, sample_world
from .specs import ACCOUNT_SPECS, BOND, EQUITY
from .structural import World, simulate_world

ERP_RANGE = (0.02, 0.08)
TERM_PREMIUM_RANGE = (-0.01, 0.03)
REAL_CASH_RANGE = (-0.03, 0.04)
GOLD_REAL_RANGE = (-0.02, 0.03)
CORE_SHARPE = (0.0, 0.6)
REAL_ASSET_SHARPE = (-0.4, 0.6)
ORACLE_SHARPE_MAX = 1.5
PE_RANGE = (5.0, 60.0)
Y10_RANGE = {"us": (-0.01, 0.15), "cn": (0.005, 0.08)}
STOCK_BOND_CORR = (-0.7, 0.7)
DEFAULT_YEARS = 100.0
MAX_REJECTION = 0.5


def _annual_excess(simple: np.ndarray, cash: np.ndarray) -> float:
    return float(np.mean(simple - cash) * YEAR)


def _sharpe(x: np.ndarray) -> float:
    sd = float(np.std(x, ddof=1))
    return float(np.mean(x) / sd * np.sqrt(YEAR)) if sd > 0 else 0.0


def world_stats(world: World) -> dict[str, float]:
    spec, d, tr, s = world.spec, world.data, world.truth, world.start
    simple = d.close_adj[s + 1 :] / d.close_adj[s:-1] - 1.0
    cash = d.cash_return[s + 1 :]
    kinds = [a.kind for a in spec.assets]
    home_eq = next(i for i, a in enumerate(spec.assets) if a.kind == EQUITY and a.economy == "home" and a.beta == 1.0)
    bonds = [i for i, k in enumerate(kinds) if k == BOND and spec.assets[i].economy == "home"]
    b10 = min(bonds, key=lambda i: abs(spec.assets[i].maturity - 10.0))
    long_b = max(bonds, key=lambda i: spec.assets[i].duration)
    gold = kinds.index("gold")
    # Gold's real return is about gold itself: strip FX and deflate by its pricing economy.
    g_asset = spec.assets[gold]
    g_ec = 0 if g_asset.economy == "home" else 1
    gold_local = np.log1p(simple[:, gold]) - (tr.fx_log[s + 1 :] if g_asset.fx else 0.0)

    excess = simple - cash[:, None]
    stats: dict[str, float] = {
        "erp": _annual_excess(simple[:, home_eq], cash),
        "term_premium": _annual_excess(simple[:, b10], cash),
        "real_cash": float(np.mean(tr.rate[s:, 0] - tr.pi[s:, 0])),
        "gold_real": float(np.mean(gold_local) * YEAR - np.mean(tr.pi[s + 1 :, g_ec])),
    }
    for i, a in enumerate(spec.assets):
        stats[f"sharpe_{i}"] = _sharpe(excess[:, i])
    w = oracle_weights(tr.mu[s:-1], tr.var[s:-1], d.cash_return[s + 1 :], ACCOUNTS[spec.name])
    stats["oracle_sharpe"] = _sharpe((w * excess).sum(axis=1))
    eq = [i for i, k in enumerate(kinds) if k == EQUITY]
    stats["pe_min"] = float(np.nanmin(tr.pe[s:, eq]))
    stats["pe_max"] = float(np.nanmax(tr.pe[s:, eq]))
    stats["y10_min"] = float(np.min(tr.y10[s:, 0]))
    stats["y10_max"] = float(np.max(tr.y10[s:, 0]))
    corr = _rolling_corr(simple[:, home_eq], simple[:, long_b], int(YEAR))
    stats["sb_corr_min"] = float(np.nanmin(corr))
    stats["sb_corr_max"] = float(np.nanmax(corr))
    return stats


def _rolling_corr(x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    def rs(v):
        c = np.concatenate([[0.0], np.cumsum(v)])
        return c[window:] - c[:-window]

    n = float(window)
    sx, sy, sxx, syy, sxy = rs(x), rs(y), rs(x * x), rs(y * y), rs(x * y)
    cov = sxy - sx * sy / n
    vx, vy = sxx - sx * sx / n, syy - sy * sy / n
    return np.divide(cov, np.sqrt(vx * vy), out=np.full(cov.shape, np.nan), where=(vx > 0) & (vy > 0))


def _within(x: float, rng: tuple[float, float]) -> bool:
    return bool(np.isfinite(x) and rng[0] <= x <= rng[1])


def check(world: World) -> tuple[dict[str, float], list[str]]:
    """Return ``(stats, failed_rule_names)``; empty list = plausible."""
    stats = world_stats(world)
    spec = world.spec
    fails = []
    for key, rng in (("erp", ERP_RANGE), ("term_premium", TERM_PREMIUM_RANGE),
                     ("real_cash", REAL_CASH_RANGE), ("gold_real", GOLD_REAL_RANGE)):
        if not _within(stats[key], rng):
            fails.append(key)
    for i, a in enumerate(spec.assets):
        band = CORE_SHARPE if a.kind in (EQUITY, BOND) else REAL_ASSET_SHARPE
        if not _within(stats[f"sharpe_{i}"], band):
            fails.append(f"sharpe_{i}")
    if not stats["oracle_sharpe"] <= ORACLE_SHARPE_MAX:
        fails.append("oracle_sharpe")
    if not (stats["pe_min"] >= PE_RANGE[0] and stats["pe_max"] <= PE_RANGE[1]):
        fails.append("pe")
    lo, hi = Y10_RANGE[spec.home]
    if not (stats["y10_min"] >= lo and stats["y10_max"] <= hi):
        fails.append("y10")
    if not (stats["sb_corr_min"] >= STOCK_BOND_CORR[0] and stats["sb_corr_max"] <= STOCK_BOND_CORR[1]):
        fails.append("stock_bond_corr")
    return stats, fails


@dataclass
class SamplingReport:
    account: str
    accepted: list[WorldParams] = field(default_factory=list)
    draws: int = 0
    fail_counts: dict[str, int] = field(default_factory=dict)

    @property
    def rejection_rate(self) -> float:
        return 1.0 - len(self.accepted) / self.draws if self.draws else 0.0

    @property
    def prior_needs_revision(self) -> bool:
        return self.rejection_rate > MAX_REJECTION

    def summary(self) -> dict[str, object]:
        return {
            "account": self.account,
            "draws": self.draws,
            "accepted": len(self.accepted),
            "rejection_rate": round(self.rejection_rate, 4),
            "prior_needs_revision": self.prior_needs_revision,
            "fail_counts": dict(sorted(self.fail_counts.items(), key=lambda kv: -kv[1])),
        }


def sample_plausible(
    account: str,
    n_worlds: int,
    rng: np.random.Generator,
    years: float = DEFAULT_YEARS,
    max_draws: int | None = None,
) -> SamplingReport:
    """Draw until ``n_worlds`` pass or ``max_draws`` (default 10×) is reached."""
    spec = ACCOUNT_SPECS[account]
    report = SamplingReport(account)
    limit = 10 * n_worlds if max_draws is None else max_draws
    while len(report.accepted) < n_worlds and report.draws < limit:
        params = sample_world(account, rng)
        report.draws += 1
        _, fails = check(simulate_world(spec, params, years=years))
        if fails:
            for f in fails:
                report.fail_counts[f] = report.fail_counts.get(f, 0) + 1
        else:
            report.accepted.append(params)
    return report
