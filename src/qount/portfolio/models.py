"""Portfolio NAV attribution and sleeve risk-budget models."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping


PROMOTION_NAV = "standalone_executable_nav"
PORTFOLIO_ACCOUNT_NAV = "portfolio_realized_nav"


@dataclass(frozen=True)
class NavAttribution:
    strategy_id: str
    signal_nav: float
    standalone_executable_nav: float
    portfolio_realized_nav: float
    standalone_netting_savings: float = 0.0

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.strategy_id:
            errors.append("strategy_id_empty")
        for name in (
            "signal_nav",
            "standalone_executable_nav",
            "portfolio_realized_nav",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                errors.append(f"{name}_invalid")
        if abs(float(self.standalone_netting_savings)) > 1e-12:
            errors.append("netting_savings_must_not_enter_standalone_nav")
        return tuple(errors)

    @property
    def promotion_nav(self) -> float:
        errors = self.validate()
        if errors:
            raise ValueError(",".join(errors))
        return self.standalone_executable_nav

    @property
    def account_nav(self) -> float:
        errors = self.validate()
        if errors:
            raise ValueError(",".join(errors))
        return self.portfolio_realized_nav


@dataclass(frozen=True)
class SleeveRiskBudget:
    """A stress-loss contribution budget, never a cash allocation."""

    strategy_id: str
    target_stress_loss_fraction: float
    estimated_standalone_stress_loss_fraction: float
    capacity_scalar_cap: float = 1.0

    def risk_scalar(self) -> float:
        values = (
            self.target_stress_loss_fraction,
            self.estimated_standalone_stress_loss_fraction,
            self.capacity_scalar_cap,
        )
        if not self.strategy_id:
            raise ValueError("strategy_id_empty")
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("risk_budget_non_finite")
        if not 0.0 <= self.target_stress_loss_fraction <= 1.0:
            raise ValueError("target_stress_loss_fraction_out_of_range")
        if not 0.0 < self.estimated_standalone_stress_loss_fraction <= 1.0:
            raise ValueError("estimated_standalone_stress_loss_fraction_out_of_range")
        if not 0.0 <= self.capacity_scalar_cap <= 1.0:
            raise ValueError("capacity_scalar_cap_out_of_range")
        return min(
            self.capacity_scalar_cap,
            self.target_stress_loss_fraction
            / self.estimated_standalone_stress_loss_fraction,
        )


def scale_standalone_weights(
    weights: Mapping[str, float], budget: SleeveRiskBudget
) -> dict[str, float]:
    scalar = budget.risk_scalar()
    scaled = {}
    for symbol, raw_weight in weights.items():
        weight = float(raw_weight)
        if not symbol or not math.isfinite(weight):
            raise ValueError(f"invalid_weight:{symbol}")
        scaled[symbol] = weight * scalar
    return scaled
