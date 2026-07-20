"""MiniTrend spot-only small-account strategy core."""

from qount.mini_trend.config import DEFAULT_UNIVERSE, MiniTrendConfig
from qount.mini_trend.execution import compute_orders
from qount.mini_trend.risk import evaluate_risk
from qount.mini_trend.signals import target_weights
from qount.mini_trend.backtest import run_backtest

__all__ = [
    "DEFAULT_UNIVERSE",
    "MiniTrendConfig",
    "compute_orders",
    "evaluate_risk",
    "run_backtest",
    "target_weights",
]
