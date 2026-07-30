"""Promoted strategy adapters that emit standard qount contracts."""

from qount.strategies.base import BASE_STRATEGY_VERSION
from qount.strategies.base import base_intent_from_projection
from qount.strategies.base import base_snapshot_from_projection
from qount.strategies.base import base_strategy_registration
from qount.strategies.passive_allocation import passive_allocation_strategy_registration

__all__ = [
    "BASE_STRATEGY_VERSION",
    "base_intent_from_projection",
    "base_snapshot_from_projection",
    "base_strategy_registration",
    "passive_allocation_strategy_registration",
]
