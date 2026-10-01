"""World parameters and their priors (design §7.1).

Factor premia are not inputs: ``FactorParams`` sets the *mechanisms* (news absorption lag
K, valuation reversion that shows up in returns, leverage constraint), and premia emerge
from them.  Momentum and value strength are drawn jointly with correlation ≈ −0.5.
All priors are proposals to be frozen in the preregistration; §7.2 rejection sampling
removes implausible draws.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import erf, sqrt

import numpy as np

YEAR = 252.0


def _u(rng: np.random.Generator, lo: float, hi: float) -> float:
    return float(rng.uniform(lo, hi))


def _phi(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


@dataclass(frozen=True)
class EconomyParams:
    r_star: float  # neutral real short rate
    pi_star: float  # inflation target / long-run mean
    i_floor: float
    phi_pi: float
    phi_x: float
    rate_smooth_hl: float  # days
    gap_sigma: float  # stationary σ of the output gap (pct points / 100)
    gap_hl: float  # days
    pi_sigma: float
    pi_hl: float
    rho_growth_infl: float  # corr of gap and π shocks
    infl_passthrough: float  # θ: long-run inflation expectation moves θ·(π − π*)
    curve_hl_years: float  # policy-rate expected reversion half-life for the curve
    tp_mean: float  # 10y term premium
    tp_sigma: float
    tp_hl: float
    erp: float  # long-run equity risk premium
    erp_gap: float  # ERP change per unit of (gap / gap_sigma), negative = countercyclical
    erp_pi: float  # ERP change per unit of (π − π*) / π σ
    erp_crisis: float  # ERP add-on in crisis
    erp_hl: float  # days, smoothing of the crisis add-on
    equity_duration: float  # price sensitivity to discount-rate changes
    div_gap_load: float  # cash-flow news: log price per unit Δ output gap (dividends load on growth)
    dy_bar: float  # long-run dividend yield
    eq_vol: float  # annual vol of the equity noise component in expansion
    garch_alpha: float
    garch_gamma: float
    garch_beta: float
    t_df: float
    fx_vol: float  # annual, this economy's currency vs the other


@dataclass(frozen=True)
class FactorParams:
    momentum_share: float  # 1 − f: share of news absorbed with delay (0 → no momentum)
    momentum_lag_days: float  # mean absorption lag K
    value_reversion_hl: float  # days, log P/D mispricing half-life
    value_return_share: float  # ψ: share of P/D reversion that runs through prices
    value_obs_noise: float  # σ of the persistent valuation measurement noise (log)
    value_obs_hl: float
    cashflow_share: float  # q: share of noise news that is cash-flow news
    leverage_cost: float  # low-risk premium: ERP haircut per unit of (β − 1), annual

    @staticmethod
    def null() -> "FactorParams":
        """All premia off: no momentum, no value predictability, no low-risk premium."""
        return FactorParams(0.0, 1.0, 1260.0, 0.0, 0.05, 250.0, 0.5, 0.0)


@dataclass(frozen=True)
class AssetClassParams:
    gold_real_beta: float  # gold log return per unit of Δ real 10y (negative)
    gold_real_return: float  # long-run real drift
    gold_vol: float
    gold_jump_share: float  # gold jump = −share × equity crisis jump
    cmdty_roll: float
    cmdty_infl_beta: float  # per unit Δπ
    cmdty_gap_beta: float  # per unit Δgap
    cmdty_vol: float
    crisis_jump_rate: float  # per year at multiplier 1
    crisis_jump_mean: float  # log, negative
    crisis_jump_sd: float
    rebound_share: float  # share of a crisis jump reversed within ~a month
    flight_to_quality: float  # 10y yield change per unit of equity jump (positive → yields fall)


@dataclass(frozen=True)
class MicroParams:
    tv_hl: float  # days, traded value AR half-life
    tv_sigma: float  # log σ of the traded value AR
    tv_vol_beta: float  # log TV per log (vol / vol_bar)
    tv_abs_beta: float  # log TV per |r| / σ
    tv_trend: float  # log per year
    spread_vol_beta: float
    spread_tv_beta: float  # negative
    drought_rate: float  # per asset-year
    drought_days: float
    drought_tv_mult: float
    drought_spread_mult: float
    overnight_share: float
    overnight_noise: float  # × daily σ
    premium_hl: float  # QDII premium half-life, days
    premium_sigma: float  # daily
    quota_rate: float  # per year
    quota_days: float
    quota_premium: float  # premium target during quota
    holiday_gap_days: tuple[int, ...]  # CN long closures per year (calendar days closed)


@dataclass(frozen=True)
class WorldParams:
    home: EconomyParams
    foreign: EconomyParams
    factors: FactorParams
    assets: AssetClassParams
    micro: MicroParams
    rho_global: float  # corr of home and foreign growth shocks
    contagion: float  # P(foreign crisis | home enters crisis) and vice versa
    regime_duration_scale: float
    payout_ratio: float  # PE = PD / payout, for the valuation feed
    idio_scale: float  # multiplies each asset's idio vol
    stale_share: float  # θ: share of asset news absorbed with delay (CN nonsync trading)
    stale_decay: float  # a: geometric decay of the delayed absorption
    seed: int

    def with_factors(self, factors: FactorParams) -> "WorldParams":
        return replace(self, factors=factors)


PROFILES = ("us", "cn", "row")


def sample_economy(profile: str, rng: np.random.Generator) -> EconomyParams:
    if profile not in PROFILES:
        raise ValueError(f"unknown economy profile {profile!r}")
    cn = profile == "cn"
    row = profile == "row"
    garch_alpha = _u(rng, 0.02, 0.06)
    garch_gamma = _u(rng, 0.04, 0.12)
    garch_beta_lo, garch_beta_hi = (0.83, 0.91) if cn else (0.88, 0.95)
    garch_beta = min(_u(rng, garch_beta_lo, garch_beta_hi), 0.995 - garch_alpha - garch_gamma / 2)
    eq_vol_lo, eq_vol_hi = (0.15, 0.20) if cn else (0.08, 0.12)
    pi_sigma_lo, pi_sigma_hi = (0.004, 0.008) if cn else (0.004, 0.012)
    tp_mean_lo, tp_mean_hi = (0.0, 0.010) if cn else (0.0, 0.02)
    return EconomyParams(
        r_star=_u(rng, 0.005, 0.02) if cn else _u(rng, -0.01, 0.02),
        pi_star=_u(rng, 0.01, 0.03) if cn else _u(rng, 0.015, 0.035),
        i_floor=0.01 if cn else (-0.005 if row else 0.0),
        phi_pi=_u(rng, 0.3, 1.0),
        phi_x=_u(rng, 0.1, 0.4) if cn else _u(rng, 0.2, 0.6),
        rate_smooth_hl=_u(rng, 40, 120),
        gap_sigma=_u(rng, 0.01, 0.025) if cn else _u(rng, 0.015, 0.035),
        gap_hl=_u(rng, 250, 750),
        pi_sigma=_u(rng, pi_sigma_lo, pi_sigma_hi),
        pi_hl=_u(rng, 400, 1000),
        rho_growth_infl=_u(rng, -0.1, 0.3),
        infl_passthrough=_u(rng, 0.1, 0.4),
        curve_hl_years=_u(rng, 2.0, 6.0),
        tp_mean=_u(rng, tp_mean_lo, tp_mean_hi),
        tp_sigma=_u(rng, 0.001, 0.003) if cn else _u(rng, 0.002, 0.006),
        tp_hl=_u(rng, 250, 1000),
        erp=_u(rng, 0.03, 0.065),
        erp_gap=-_u(rng, 0.003, 0.012),
        erp_pi=_u(rng, 0.0, 0.006),
        erp_crisis=_u(rng, 0.02, 0.06),
        erp_hl=_u(rng, 40, 150),
        equity_duration=_u(rng, 4.0, 10.0),
        div_gap_load=_u(rng, 1.5, 3.5),
        dy_bar=_u(rng, 0.02, 0.035) if cn else _u(rng, 0.015, 0.035),
        eq_vol=_u(rng, eq_vol_lo, eq_vol_hi),
        garch_alpha=garch_alpha,
        garch_gamma=garch_gamma,
        garch_beta=garch_beta,
        t_df=_u(rng, 4.0, 8.0),
        fx_vol=_u(rng, 0.03, 0.06) if cn else _u(rng, 0.07, 0.11),
    )


def sample_factors(rng: np.random.Generator) -> FactorParams:
    """Momentum and value strength via a Gaussian copula with ρ ≈ −0.5; each can be 0."""
    z = rng.multivariate_normal([0.0, 0.0], [[1.0, -0.5], [-0.5, 1.0]])
    u_mom, u_val = _phi(float(z[0])), _phi(float(z[1]))
    momentum_share = 0.0 if u_mom < 0.2 else 0.25 * (u_mom - 0.2) / 0.8
    value_share = 0.0 if u_val < 0.2 else (u_val - 0.2) / 0.8
    return FactorParams(
        momentum_share=momentum_share,
        momentum_lag_days=_u(rng, 1, 9) * 21,
        value_reversion_hl=_u(rng, 1.5, 5) * YEAR,
        value_return_share=value_share,
        value_obs_noise=_u(rng, 0.02, 0.15),
        value_obs_hl=_u(rng, 60, 500),
        cashflow_share=_u(rng, 0.3, 0.6),
        leverage_cost=0.0 if rng.random() < 0.3 else _u(rng, 0.0, 0.03),
    )


def sample_asset_classes(rng: np.random.Generator) -> AssetClassParams:
    return AssetClassParams(
        gold_real_beta=-_u(rng, 5.0, 15.0),
        gold_real_return=_u(rng, 0.0, 0.02),
        gold_vol=_u(rng, 0.11, 0.16),
        gold_jump_share=_u(rng, 0.0, 0.3),
        cmdty_roll=_u(rng, -0.04, 0.01),
        cmdty_infl_beta=_u(rng, 3.0, 8.0),
        cmdty_gap_beta=_u(rng, 1.0, 4.0),
        cmdty_vol=_u(rng, 0.13, 0.20),
        crisis_jump_rate=_u(rng, 1.0, 4.0),
        crisis_jump_mean=-_u(rng, 0.03, 0.07),
        crisis_jump_sd=_u(rng, 0.01, 0.03),
        rebound_share=_u(rng, 0.2, 0.6),
        flight_to_quality=_u(rng, 0.002, 0.008),
    )


def sample_micro(rng: np.random.Generator) -> MicroParams:
    return MicroParams(
        tv_hl=_u(rng, 20, 120),
        tv_sigma=_u(rng, 0.2, 0.4),
        tv_vol_beta=_u(rng, 0.5, 1.0),
        tv_abs_beta=_u(rng, 0.1, 0.3),
        tv_trend=_u(rng, 0.0, 0.08),
        spread_vol_beta=_u(rng, 0.5, 1.0),
        spread_tv_beta=-_u(rng, 0.3, 0.6),
        drought_rate=_u(rng, 0.02, 0.1),
        drought_days=_u(rng, 20, 60),
        drought_tv_mult=_u(rng, 0.1, 0.3),
        drought_spread_mult=_u(rng, 3.0, 5.0),
        overnight_share=_u(rng, 0.2, 0.5),
        overnight_noise=_u(rng, 0.1, 0.3),
        premium_hl=_u(rng, 3, 15),
        premium_sigma=_u(rng, 0.001, 0.003),
        quota_rate=_u(rng, 0.1, 0.5),
        quota_days=_u(rng, 60, 250),
        quota_premium=_u(rng, 0.03, 0.15),
        holiday_gap_days=(9, 7),  # Spring Festival, National Day
    )


def sample_world(account: str, rng: np.random.Generator, seed: int | None = None) -> WorldParams:
    """Draw one world's parameters (before §7.2 rejection)."""
    from .specs import ACCOUNT_SPECS

    spec = ACCOUNT_SPECS[account]
    cn = spec.home == "cn"
    return WorldParams(
        home=sample_economy(spec.home, rng),
        foreign=sample_economy(spec.foreign, rng),
        factors=sample_factors(rng),
        assets=sample_asset_classes(rng),
        micro=sample_micro(rng),
        rho_global=_u(rng, 0.3, 0.7),
        contagion=_u(rng, 0.2, 0.6),
        regime_duration_scale=_u(rng, 0.6, 1.5),
        payout_ratio=_u(rng, 0.35, 0.6),
        idio_scale=_u(rng, 0.7, 1.3),
        stale_share=_u(rng, 0.07, 0.10) if cn else 0.0,
        stale_decay=_u(rng, 0.25, 0.35) if cn else 0.0,
        seed=int(rng.integers(2**31)) if seed is None else seed,
    )
