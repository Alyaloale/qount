"""Per-trade cost model on unadjusted prices (design §6).

``cost_i = max(rate·|N|, min_fee) + fees(N, side) + half_spread·|N| + k·σ_daily·sqrt(|N|/ADV)·|N|``

``N`` is the signed traded notional (buy > 0), ``ADV`` the 20-day average traded value and
``σ_daily`` the daily return vol.  A single day's fill is capped at ``max_adv_fraction·ADV``;
the rest is deferred to the next session (:func:`cap_by_adv`).  All defaults are the §6
table values and still need P0 data / owner confirmation (§12.5–12.7).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .universe import Account

# SEC Section 31: USD 20.60 per million of *sell* notional (§6 value; the SEC resets it yearly).
SEC_FEE_RATE = 20.60e-6
# FINRA TAF on covered sales, per share with a per-trade cap. Values from memory; P0 must verify.
FINRA_TAF_PER_SHARE = 0.000166
FINRA_TAF_MAX = 8.30

# US half spreads in bp (§6 table). IWM/TLT are not listed there; 1 bp is a placeholder until P0.
US_HALF_SPREAD_BP = {
    "SPY": 0.5, "QQQ": 0.5, "IWM": 1.0, "EFA": 1.5, "EEM": 1.5,
    "IEF": 0.5, "TLT": 1.0, "GLD": 1.5, "DBC": 5.0,
}

EVAL_COST_MULTIPLIERS = (1.0, 2.0, 3.0)
RANDOMIZATION_RANGE = (0.5, 2.0)


class CostModelError(ValueError):
    pass


@dataclass(frozen=True)
class CostParams:
    commission_rate: float
    min_fee: float
    sec_fee_rate: float
    taf_per_share: float
    taf_max: float
    half_spread: tuple[float, ...]  # fractional, per asset, before the tick floor
    tick: float
    k_impact: float
    max_adv_fraction: float = 0.05
    spread_mult: float = 1.0  # randomization multiplier, also applied to a supplied spread series

    def scaled(self, spread_mult: float = 1.0, impact_mult: float = 1.0) -> "CostParams":
        """Training randomization: only base spread and impact are multiplied (§6)."""
        if spread_mult <= 0 or impact_mult <= 0:
            raise CostModelError("multipliers must be positive")
        return replace(
            self,
            half_spread=tuple(h * spread_mult for h in self.half_spread),
            k_impact=self.k_impact * impact_mult,
            spread_mult=self.spread_mult * spread_mult,
        )


def cost_params_for(account: Account) -> CostParams:
    if account.name == "us":
        return CostParams(
            commission_rate=0.0,
            min_fee=0.0,
            sec_fee_rate=SEC_FEE_RATE,
            taf_per_share=FINRA_TAF_PER_SHARE,
            taf_max=FINRA_TAF_MAX,
            half_spread=tuple(US_HALF_SPREAD_BP[s] * 1e-4 for s in account.symbols),
            tick=account.tick,
            k_impact=0.1,
        )
    if account.name == "cn":
        # 0.85‰ includes exchange fees; no stamp duty on ETFs. Spread is the half-tick floor.
        return CostParams(
            commission_rate=0.85e-3,
            min_fee=5.0,
            sec_fee_rate=0.0,
            taf_per_share=0.0,
            taf_max=0.0,
            half_spread=(0.0,) * account.n_assets,
            tick=account.tick,
            k_impact=0.2,
        )
    raise CostModelError(f"no cost defaults for account {account.name!r}")


def randomize(params: CostParams, rng: np.random.Generator) -> CostParams:
    lo, hi = RANDOMIZATION_RANGE
    return params.scaled(spread_mult=float(rng.uniform(lo, hi)), impact_mult=float(rng.uniform(lo, hi)))


def effective_half_spread(params: CostParams, price: np.ndarray, series: np.ndarray | None = None) -> np.ndarray:
    """Half spread floored at half a tick over the unadjusted price.

    ``series`` (a generator/P0 per-day estimate) replaces the static base and is scaled by
    ``spread_mult``; the static base is already scaled.
    """
    price = np.asarray(price, dtype=float)
    if np.any(price <= 0):
        raise CostModelError("unadjusted prices must be positive")
    base = np.asarray(params.half_spread) if series is None else params.spread_mult * np.asarray(series, dtype=float)
    return np.maximum(base, 0.5 * params.tick / price)


def cap_by_adv(notional: np.ndarray, adv: np.ndarray, fraction: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Split a signed desired notional into (executed today, deferred)."""
    notional = np.asarray(notional, dtype=float)
    limit = fraction * np.maximum(np.asarray(adv, dtype=float), 0.0)
    executed = np.clip(notional, -limit, limit)
    return executed, notional - executed


def trade_cost(
    notional: np.ndarray,
    price: np.ndarray,
    adv: np.ndarray,
    sigma_daily: np.ndarray,
    params: CostParams,
    multiplier: float = 1.0,
    half_spread: np.ndarray | None = None,
) -> np.ndarray:
    """Per-asset cost in account currency for signed notionals executed at ``price``.

    ``multiplier`` is the evaluation stress (1×/2×/3×) and scales every component.
    """
    n = np.asarray(notional, dtype=float)
    adv = np.asarray(adv, dtype=float)
    sigma = np.asarray(sigma_daily, dtype=float)
    size = np.abs(n)
    traded = size > 0
    if np.any(traded & (adv <= 0)):
        raise CostModelError("cannot trade an asset with non-positive ADV")

    commission = np.where(traded, np.maximum(params.commission_rate * size, params.min_fee), 0.0)
    sells = n < 0
    shares = size / np.asarray(price, dtype=float)
    fees = np.where(
        sells,
        params.sec_fee_rate * size + np.minimum(params.taf_per_share * shares, params.taf_max),
        0.0,
    )
    spread = effective_half_spread(params, price, half_spread) * size
    participation = np.divide(size, adv, out=np.zeros_like(size), where=adv > 0)
    impact = params.k_impact * sigma * np.sqrt(participation) * size
    return multiplier * (commission + fees + spread + impact)
