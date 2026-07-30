"""Backward-compatible imports for shared research metrics.

The implementation lives in :mod:`qount.research_data.metrics`; RV strategy
code can be archived without taking common statistical utilities with it.
"""

from qount.research_data.metrics import deflated_sharpe_ratio
from qount.research_data.metrics import expected_max_sharpe
from qount.research_data.metrics import pbo_cscv
from qount.research_data.metrics import returns_from_curve
from qount.research_data.metrics import sharpe
from qount.research_data.metrics import _moments

__all__ = [
    "deflated_sharpe_ratio",
    "expected_max_sharpe",
    "pbo_cscv",
    "returns_from_curve",
    "sharpe",
]
