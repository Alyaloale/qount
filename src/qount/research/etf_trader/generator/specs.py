"""Static specs for the structural generator: regimes and per-asset mapping (design §7.1).

Each account world simulates two economies: ``home`` (account currency, cash, domestic
assets) and ``foreign`` (US for the CN account's QDII / gold pricing, rest-of-world for
the US account's EFA/EEM).  Assets reference an economy and say whether their return is
converted by the home/foreign FX rate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

REGIMES = ("expansion", "slowdown", "recession", "stagflation", "crisis")
EXPANSION, SLOWDOWN, RECESSION, STAGFLATION, CRISIS = range(5)

# Regimes scale shock variances and shift macro targets; they never set asset drift directly.
REGIME_GAP_TARGET = np.array([0.5, -0.5, -2.0, -1.0, -3.0])  # output-gap mean, × gap σ
REGIME_PI_SHIFT = np.array([0.0, 0.0, -0.5, 2.0, -0.5])  # inflation mean shift, × π σ
REGIME_GROWTH_VOL = np.array([1.0, 1.2, 1.8, 1.4, 2.5])
REGIME_INFL_VOL = np.array([1.0, 1.0, 1.0, 2.5, 1.2])
REGIME_EQ_VOL = np.array([1.0, 1.2, 1.6, 1.5, 2.8])  # GARCH long-run level multiplier
REGIME_JUMP = np.array([0.0, 0.0, 0.5, 0.5, 4.0])  # crisis-jump intensity multiplier

# Mean durations in months (world-level scale factor multiplies these) and exit destinations.
REGIME_DURATION_MONTHS = np.array([48.0, 12.0, 12.0, 18.0, 4.0])
REGIME_EXIT = np.array(
    [
        [0.0, 0.70, 0.10, 0.10, 0.10],
        [0.60, 0.0, 0.30, 0.05, 0.05],
        [0.70, 0.20, 0.0, 0.05, 0.05],
        [0.40, 0.30, 0.25, 0.0, 0.05],
        [0.10, 0.20, 0.70, 0.0, 0.0],
    ]
)
DAYS_PER_MONTH = 21

EQUITY, BOND, GOLD, COMMODITY = "equity", "bond", "gold", "commodity"


@dataclass(frozen=True)
class AssetSpec:
    kind: str
    economy: str  # "home" | "foreign"
    fx: bool = False  # convert from the foreign currency
    beta: float = 1.0  # loading on the economy's common equity news
    idio_vol: float = 0.0  # annual idiosyncratic vol
    maturity: float = 0.0  # bonds: years, for the curve weight
    duration: float = 0.0
    convexity: float = 0.0
    qdii: bool = False  # CN cross-border: premium process and quota
    price0: float = 100.0  # starting unadjusted price
    adv0: float = 1e9  # starting daily traded value, account currency
    half_spread_bp: float = 1.0  # base half spread before vol/volume scaling and tick floor
    stale: float = 0.0  # CN partial-adjustment/nonsync trading: 1 = most stale, 0 = instant


@dataclass(frozen=True)
class AccountSpec:
    name: str
    home: str  # economy profile key: "us" | "cn"
    foreign: str  # "row" | "us"
    tick: float
    price_limit: float | None
    cn_calendar: bool
    assets: tuple[AssetSpec, ...]

    @property
    def n(self) -> int:
        return len(self.assets)


US_SPEC = AccountSpec(
    name="us",
    home="us",
    foreign="row",
    tick=0.01,
    price_limit=None,
    cn_calendar=False,
    assets=(
        AssetSpec(EQUITY, "home", beta=1.00, idio_vol=0.00, price0=100.0, adv0=3e10, half_spread_bp=0.5),  # SPY
        AssetSpec(EQUITY, "home", beta=1.15, idio_vol=0.08, price0=60.0, adv0=1.5e10, half_spread_bp=0.5),  # QQQ
        AssetSpec(EQUITY, "home", beta=1.20, idio_vol=0.10, price0=60.0, adv0=4e9, half_spread_bp=1.0),  # IWM
        AssetSpec(EQUITY, "foreign", fx=True, beta=1.00, idio_vol=0.04, price0=50.0, adv0=1.5e9, half_spread_bp=1.5),  # EFA
        AssetSpec(EQUITY, "foreign", fx=True, beta=1.30, idio_vol=0.10, price0=40.0, adv0=1.5e9, half_spread_bp=1.5),  # EEM
        AssetSpec(BOND, "home", maturity=7.0, duration=7.5, convexity=65.0, price0=90.0, adv0=6e8, half_spread_bp=0.5),  # IEF
        AssetSpec(BOND, "home", maturity=20.0, duration=17.0, convexity=350.0, price0=90.0, adv0=1.5e9, half_spread_bp=1.0),  # TLT
        AssetSpec(GOLD, "home", price0=90.0, adv0=1.2e9, half_spread_bp=1.5),  # GLD
        AssetSpec(COMMODITY, "home", price0=25.0, adv0=6e7, half_spread_bp=5.0),  # DBC
    ),
)

# A-share ETFs: the spread floor is half a 0.001 tick; base spread 0 matches costs.py.
CN_SPEC = AccountSpec(
    name="cn",
    home="cn",
    foreign="us",
    tick=0.001,
    price_limit=0.10,
    cn_calendar=True,
    assets=(
        AssetSpec(EQUITY, "home", beta=1.00, idio_vol=0.00, price0=3.5, adv0=4e9, half_spread_bp=0.0, stale=0.2),  # 510300 CSI300
        AssetSpec(EQUITY, "home", beta=1.15, idio_vol=0.10, price0=5.5, adv0=1.5e9, half_spread_bp=0.0, stale=0.8),  # 510500 CSI500
        AssetSpec(EQUITY, "home", beta=1.35, idio_vol=0.14, price0=2.0, adv0=1.2e9, half_spread_bp=0.0, stale=1.0),  # 159915 ChiNext
        AssetSpec(EQUITY, "home", beta=0.90, idio_vol=0.06, price0=2.6, adv0=1.5e9, half_spread_bp=0.0, stale=0.0),  # 510050 SSE50
        AssetSpec(GOLD, "foreign", fx=True, price0=4.0, adv0=6e8, half_spread_bp=0.0, stale=0.0),  # 518880
        AssetSpec(BOND, "home", maturity=5.0, duration=4.5, convexity=25.0, price0=120.0, adv0=1e8, half_spread_bp=0.0, stale=0.0),  # 511010
        AssetSpec(EQUITY, "foreign", fx=True, beta=1.15, idio_vol=0.08, qdii=True, price0=4.5, adv0=8e8, half_spread_bp=0.0, stale=0.0),  # 513100
        AssetSpec(EQUITY, "foreign", fx=True, beta=1.00, idio_vol=0.00, qdii=True, price0=1.5, adv0=4e8, half_spread_bp=0.0, stale=0.0),  # 513500
    ),
)

ACCOUNT_SPECS = {US_SPEC.name: US_SPEC, CN_SPEC.name: CN_SPEC}


def transition_matrix(duration_scale: float = 1.0) -> np.ndarray:
    """Daily regime transition matrix from mean durations (months) × ``duration_scale``."""
    if duration_scale <= 0:
        raise ValueError("duration_scale must be positive")
    exit_p = 1.0 / (REGIME_DURATION_MONTHS * duration_scale * DAYS_PER_MONTH)
    P = REGIME_EXIT * exit_p[:, None]
    P[np.diag_indices(len(REGIMES))] = 1.0 - exit_p
    return P


def ten_year_weight(maturity: float, halflife_years: float = 8.0) -> float:
    """Share of the long-run anchor (vs the current policy rate) in a ``maturity`` yield."""
    k = np.log(2.0) / halflife_years
    return float(1.0 - (1.0 - np.exp(-k * maturity)) / (k * maturity)) if maturity > 0 else 0.0
