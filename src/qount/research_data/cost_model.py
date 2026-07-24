"""R0-COST/NAV frozen cost model contracts.

Hash-bound cost models for C×D (trend + carry legs) and CTA-R (ETF/futures).
Each cost component carries a ``source`` tag distinguishing official rates,
estimates, certified samples, and unavailable fields -- so missing evidence
is explicit, never filled with zero.

These models feed the Signal NAV and Standalone Executable NAV generators:
    Signal NAV            = cumulative(position * price_return)
    Standalone Exec NAV   = Signal NAV - cumulative(fees + slippage + funding + ...)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import fields
from typing import Any
from typing import Mapping
from typing import Sequence

from qount.contracts.hashing import canonical_hash


COST_MODEL_SCHEMA_VERSION = 1
COST_SOURCES = (
    "official_rate",
    "venue_specification",
    "certified_sample",
    "estimated",
    "unavailable",
)
COST_MODEL_TYPES = (
    "cxd_trend_leg",
    "cxd_carry_leg",
    "cta_r_etf",
    "cta_r_futures",
)


@dataclass(frozen=True)
class CostComponent:
    """One atomic cost line: rate + source + notes.

    ``rate`` is a fraction (0.0004 = 4bps taker fee).  ``source`` must be one
    of :data:`COST_SOURCES`.  When ``source == "unavailable"``, ``rate`` is
    treated as 0.0 for computation but the NAV generator must flag the result
    as ``cost_incomplete``.
    """

    name: str
    rate: float
    source: str
    notes: str

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.name:
            errors.append("cost_component_name_empty")
        try:
            r = float(self.rate)
        except (TypeError, ValueError):
            r = math.nan
        if not math.isfinite(r) or r < 0.0:
            errors.append(f"cost_component_rate_invalid:{self.name}")
        if self.source not in COST_SOURCES:
            errors.append(f"cost_component_source_invalid:{self.name}")
        return tuple(errors)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "rate": self.rate, "source": self.source, "notes": self.notes}


@dataclass(frozen=True)
class FrozenCostModel:
    """Immutable, hash-bound cost model for one candidate leg or venue.

    ``model_type`` selects the cost structure (trend leg, carry leg, ETF,
    futures).  ``components`` is a flat list of :class:`CostComponent`; the
    NAV generator knows which components apply to which computation.
    ``model_hash`` binds the entire model for audit.
    """

    model_type: str
    model_version: str
    venue: str
    components: tuple[CostComponent, ...]
    frozen_at: str
    model_hash: str

    @classmethod
    def create(
        cls,
        *,
        model_type: str,
        model_version: str,
        venue: str,
        components: Sequence[CostComponent],
        frozen_at: str,
    ) -> "FrozenCostModel":
        if model_type not in COST_MODEL_TYPES:
            raise ValueError(f"unknown cost model type {model_type!r}")
        core = {
            "model_type": model_type,
            "model_version": model_version,
            "venue": venue,
            "components": tuple(c.to_dict() for c in components),
            "frozen_at": frozen_at,
        }
        return cls(
            model_type=model_type,
            model_version=model_version,
            venue=venue,
            components=tuple(components),
            frozen_at=frozen_at,
            model_hash=canonical_hash(core),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.model_type not in COST_MODEL_TYPES:
            errors.append("cost_model_type_invalid")
        if not self.model_version:
            errors.append("cost_model_version_empty")
        if not self.venue:
            errors.append("cost_model_venue_empty")
        if not self.components:
            errors.append("cost_model_components_empty")
        for comp in self.components:
            errors.extend(comp.validate())
        core = {
            "model_type": self.model_type,
            "model_version": self.model_version,
            "venue": self.venue,
            "components": tuple(c.to_dict() for c in self.components),
            "frozen_at": self.frozen_at,
        }
        if self.model_hash != canonical_hash(core):
            errors.append("cost_model_hash_invalid")
        return tuple(errors)

    def get(self, name: str) -> CostComponent | None:
        for c in self.components:
            if c.name == name:
                return c
        return None

    @property
    def has_unavailable(self) -> bool:
        return any(c.source == "unavailable" for c in self.components)

    @property
    def total_round_trip_rate(self) -> float:
        """Sum of all per-direction rates × 2 (open + close).  Zero for
        non-turnover costs (collateral, tail) which are handled separately."""
        turnover_names = {
            "taker_fee", "maker_fee", "spread", "slippage",
            "legging_cost", "roll_cost", "fx_cost",
            "etf_fee", "futures_fee", "tax",
        }
        total = 0.0
        for c in self.components:
            if c.name in turnover_names and c.source != "unavailable":
                total += float(c.rate) * 2.0
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": self.model_type,
            "model_version": self.model_version,
            "venue": self.venue,
            "components": [c.to_dict() for c in self.components],
            "frozen_at": self.frozen_at,
            "model_hash": self.model_hash,
            "has_unavailable": self.has_unavailable,
            "total_round_trip_rate": self.total_round_trip_rate,
        }


# --- Standard cost model factories ------------------------------------------


def default_cxd_trend_cost_model(
    *,
    taker_fee: float = 0.0004,
    slippage_bps: float = 2.0,
    funding_multiplier: float = 1.0,
    frozen_at: str = "",
) -> FrozenCostModel:
    """C×D trend leg: Binance UM taker fee + slippage + funding.

    Default rates from Binance UM official fee schedule (0.04% taker) and
    conservative slippage estimate for daily-bar execution.  ``funding_multiplier``
    scales the historical funding rate; 1.0 = use actual funding.
    """

    slippage_rate = slippage_bps / 10_000.0
    return FrozenCostModel.create(
        model_type="cxd_trend_leg",
        model_version="v0.1",
        venue="binance_um",
        components=[
            CostComponent("taker_fee", taker_fee, "official_rate",
                          "Binance UM 0.04% taker fee"),
            CostComponent("slippage", slippage_rate, "estimated",
                          f"{slippage_bps:.1f}bps daily-bar arrival slippage"),
            CostComponent("funding", funding_multiplier, "official_rate",
                          "funding multiplier on historical funding rate"),
        ],
        frozen_at=frozen_at,
    )


def default_cxd_carry_cost_model(
    *,
    taker_fee: float = 0.0004,
    maker_fee: float = 0.0002,
    spread: float = 0.0001,
    slippage_bps: float = 1.0,
    legging_cost: float = 0.0005,
    collateral_cost: float = 0.0,
    tail_cost: float = 0.0,
    funding_multiplier: float = 1.0,
    frozen_at: str = "",
) -> FrozenCostModel:
    """C×D carry leg: spot + perp basis carry with multi-leg costs.

    Costs include taker/maker for both legs, spread, slippage, legging risk,
    collateral opportunity cost, funding (short perp receives/pays), and
    tail-risk insurance.  ``collateral_cost`` and ``tail_cost`` default to
    0.0 with source ``"unavailable"`` so the NAV generator flags
    ``cost_incomplete=True`` until they are properly estimated and certified.
    """

    slippage_rate = slippage_bps / 10_000.0
    return FrozenCostModel.create(
        model_type="cxd_carry_leg",
        model_version="v0.1",
        venue="binance_spot_um",
        components=[
            CostComponent("taker_fee", taker_fee, "official_rate",
                          "Binance UM 0.04% taker fee (perp leg)"),
            CostComponent("maker_fee", maker_fee, "official_rate",
                          "Binance UM 0.02% maker fee (perp leg, if filled)"),
            CostComponent("spread", spread, "estimated",
                          "half-spread cost for market entry"),
            CostComponent("slippage", slippage_rate, "estimated",
                          f"{slippage_bps:.1f}bps slippage per leg"),
            CostComponent("legging_cost", legging_cost, "estimated",
                          "legging risk: timing mismatch between spot and perp"),
            CostComponent("collateral_cost", collateral_cost, "unavailable",
                          "opportunity cost of margin collateral (not yet estimated)"),
            CostComponent("tail_cost", tail_cost, "unavailable",
                          "tail-risk insurance / forced liquidation buffer (not yet estimated)"),
            CostComponent("funding", funding_multiplier, "official_rate",
                          "funding multiplier on historical funding rate (short perp)"),
        ],
        frozen_at=frozen_at,
    )


def default_cta_r_etf_cost_model(
    *,
    etf_fee: float = 0.0003,
    spread: float = 0.0002,
    slippage_bps: float = 5.0,
    tax: float = 0.0,
    fx_cost: float = 0.0,
    frozen_at: str = "",
) -> FrozenCostModel:
    """CTA-R ETF leg: cross-asset ETF execution costs.

    ETF expense ratio is excluded (it's in the price, not a trading cost).
    ``etf_fee`` is the brokerage commission; ``tax`` is stamp duty (where
    applicable); ``fx_cost`` is currency conversion for non-USD accounts.
    """

    slippage_rate = slippage_bps / 10_000.0
    return FrozenCostModel.create(
        model_type="cta_r_etf",
        model_version="v0.1",
        venue="cn_etf_brokerage",
        components=[
            CostComponent("etf_fee", etf_fee, "estimated",
                          "brokerage commission per trade"),
            CostComponent("spread", spread, "estimated",
                          "ETF bid-ask half-spread"),
            CostComponent("slippage", slippage_rate, "estimated",
                          f"{slippage_bps:.1f}bps daily-bar slippage"),
            CostComponent("tax", tax, "official_rate",
                          "stamp duty / transaction tax (0 if N/A)"),
            CostComponent("fx_cost", fx_cost, "estimated",
                          "FX conversion cost for non-USD account"),
        ],
        frozen_at=frozen_at,
    )


def default_cta_r_futures_cost_model(
    *,
    futures_fee: float = 0.0002,
    spread: float = 0.0001,
    slippage_bps: float = 3.0,
    roll_cost: float = 0.0003,
    frozen_at: str = "",
) -> FrozenCostModel:
    """CTA-R futures leg: continuous futures execution costs.

    ``roll_cost`` is the per-roll cost for continuous-future back-adjustment
    (roll spread + slippage at each contract expiry).
    """

    slippage_rate = slippage_bps / 10_000.0
    return FrozenCostModel.create(
        model_type="cta_r_futures",
        model_version="v0.1",
        venue="us_futures_brokerage",
        components=[
            CostComponent("futures_fee", futures_fee, "estimated",
                          "futures commission per round-turn"),
            CostComponent("spread", spread, "estimated",
                          "futures bid-ask half-spread"),
            CostComponent("slippage", slippage_rate, "estimated",
                          f"{slippage_bps:.1f}bps slippage per trade"),
            CostComponent("roll_cost", roll_cost, "estimated",
                          "per-roll cost at contract expiry"),
        ],
        frozen_at=frozen_at,
    )
