"""Compatibility import for the migrated Base strategy intent adapter."""

from qount.strategies.base import base_intent_from_projection
from qount.strategies.base import base_snapshot_from_projection

__all__ = ["base_intent_from_projection", "base_snapshot_from_projection"]
