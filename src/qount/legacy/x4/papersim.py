"""X4 forward paper-sim engine: the §17-validated deployable 3-sleeve portfolio (线 D §18, B2).

Deploys S1-GRID + S3-CTA + S4-MOM (S2 excluded -- walk-forward证伪, §17) on equal capital, each its
own ledger, combined equal-weight. The engine is deliberately a thin orchestration over the *exact*
backtest drivers: every paper day it re-runs the deterministic, causal backtest on all accumulated
bars and snapshots the latest equity. Because the backtest has no look-ahead, re-running the full
history == an incremental step, and **fidelity to the backtest is guaranteed by construction** (the
paper IS the backtest, replayed daily). No real orders -- pure simulation.

``run_paper`` is pure (bars in, curves + snapshot out); IO (fetching the latest bars, persisting the
daily snapshot log) lives in ``scripts/archive/research-legacy/x4/x4_paper.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from qount.research_data.market_data import Bar
from qount.legacy.x4.backtest import max_drawdown, run_directional, run_grid
from qount.legacy.x4.portfolio import combine, sharpe_of
from qount.legacy.x4.strategies import GridStrategy, MomentumBreakout, TrendFollow

DEPLOYED_SLEEVES = ("S1-GRID", "S3-CTA", "S4-MOM")  # S2 excluded (§17 walk-forward FAIL)


@dataclass(frozen=True)
class PaperConfig:
    """The §17-validated deployable configuration (the params that passed walk-forward / generalize)."""

    initial_capital: float = 100_000.0
    taker_fee: float = 0.0005
    slippage: float = 0.0002
    # S1-GRID
    grid_atr_mult: float = 5.0
    # S3-CTA
    cta_fast: int = 20
    cta_slow: int = 100
    cta_regime_sma: int = 200
    # S4-MOM
    mom_lookback: int = 20
    mom_exit_lookback: int = 10
    mom_regime_sma: int = 200
    mom_chandelier_mult: float = 4.0
    # shared directional sizing (vol-parity)
    vol_target: float = 0.03
    max_leverage: float = 2.0
    rebalance_band: float = 0.25
    portfolio_scheme: str = "equal"
    bars_per_year: float = 365.0


@dataclass
class PaperResult:
    dates: list[str]
    sleeve_curves: dict[str, list[float]]
    portfolio_curve: list[float]
    snapshot: dict = field(default_factory=dict)


def _metrics(curve: list[float], cap: float, ppy: float) -> dict:
    return {
        "equity": round(curve[-1], 2),
        "total_return": curve[-1] / cap - 1.0,
        "sharpe": sharpe_of(curve, periods_per_year=ppy),
        "max_drawdown": max_drawdown(curve),
    }


def run_paper(
    btc_bars: list[Bar],
    eth_bars: list[Bar] | None = None,
    *,
    config: PaperConfig = PaperConfig(),
    funding: Callable[[Bar], float] | None = None,
) -> PaperResult:
    """Run the deployable 3-sleeve paper portfolio over ``btc_bars`` (S1/S3/S4 trade BTC).

    ``eth_bars`` is accepted for signature symmetry with the bake-off but unused here (S2, the only
    ETH-using sleeve, is excluded). ``funding`` (optional) feeds perp funding to the directional
    sleeves. Returns per-sleeve + portfolio equity curves and a latest-bar snapshot.
    """

    cap = config.initial_capital
    ppy = config.bars_per_year
    s1 = run_grid(btc_bars, GridStrategy(), initial_capital=cap, taker_fee=config.taker_fee,
                  slippage=config.slippage, atr_mult=config.grid_atr_mult, periods_per_year=ppy)
    s3 = run_directional(
        btc_bars, TrendFollow(fast=config.cta_fast, slow=config.cta_slow, allow_short=False,
                              regime_sma=config.cta_regime_sma),
        initial_capital=cap, taker_fee=config.taker_fee, slippage=config.slippage, funding=funding,
        rebalance_band=config.rebalance_band, vol_target=config.vol_target,
        max_leverage=config.max_leverage, periods_per_year=ppy)
    s4 = run_directional(
        btc_bars, MomentumBreakout(lookback=config.mom_lookback, exit_lookback=config.mom_exit_lookback,
                                   vol_mult=1.0, allow_short=False, regime_sma=config.mom_regime_sma),
        initial_capital=cap, taker_fee=config.taker_fee, slippage=config.slippage, funding=funding,
        rebalance_band=config.rebalance_band, vol_target=config.vol_target,
        max_leverage=config.max_leverage, chandelier_mult=config.mom_chandelier_mult,
        chandelier_lookback=22, periods_per_year=ppy)

    sleeves = {"S1-GRID": s1.equity_curve, "S3-CTA": s3.equity_curve, "S4-MOM": s4.equity_curve}
    portfolio = combine(sleeves, scheme=config.portfolio_scheme, initial_capital=cap)

    snapshot = {
        "date": btc_bars[-1].date if btc_bars else None,
        "n_bars": len(btc_bars),
        "sleeves": {nm: _metrics(c, cap, ppy) for nm, c in sleeves.items()},
        "portfolio": _metrics(portfolio, cap, ppy),
        "positions": {
            "S3-CTA": {"weight": s3.extra.get("final_weight", 0.0)},
            "S4-MOM": {"weight": s4.extra.get("final_weight", 0.0)},
            "S1-GRID": {"inventory_base": s1.extra.get("final_inventory_base", 0.0)},
        },
        "fees_to_date": round(s1.fees_paid + s3.fees_paid + s4.fees_paid, 2),
    }
    return PaperResult([b.date for b in btc_bars], sleeves, portfolio, snapshot)
