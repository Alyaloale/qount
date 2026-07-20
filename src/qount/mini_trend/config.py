"""MiniTrend configuration.

This module deliberately does not read env vars. Runtime wrappers may translate env/config files into
this dataclass, while the core stays deterministic and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_UNIVERSE = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")


@dataclass(frozen=True)
class MiniTrendConfig:
    strategy: str = "MiniTrend-5"
    universe: tuple[str, ...] = DEFAULT_UNIVERSE
    quote: str = "USDT"
    market: str = "spot"
    direction: str = "long_cash"

    capital_cap_usdt: float = 400.0
    vol_target: float = 0.015
    max_gross: float = 1.0
    max_symbol_weight: float = 1.0
    rebalance_band: float = 0.35
    min_order_usdt: float = 5.0
    max_order_usdt: float = 400.0

    gate_symbol: str = "BTCUSDT"
    gate_sma: int = 200
    breadth_gate: float = 0.5
    trend_sma: int = 200
    fast_sma: int = 20
    slow_sma: int = 60
    vol_lookback: int = 20
    atr_lookback: int = 14
    corr_penalty: bool = True
    corr_floor: float = 0.2

    max_daily_loss_pct: float = 0.02
    max_weekly_loss_pct: float = 0.05
    min_notional_coverage: float = 0.80

    scorecard_max_drawdown_pct: float = 25.0
    scorecard_expected_fee_to_notional_pct: float = 0.10
    scorecard_max_order_count: int = 500

    position_epsilon: float = 1e-12

    def __post_init__(self) -> None:
        if self.market != "spot":
            raise ValueError("MiniTrend v0.2 core is spot-only")
        if self.direction != "long_cash":
            raise ValueError("MiniTrend v0.2 core is long/cash only")
        if not self.universe:
            raise ValueError("universe must not be empty")
        if self.gate_symbol not in self.universe:
            raise ValueError("gate_symbol must be in universe")
        if self.capital_cap_usdt <= 0:
            raise ValueError("capital_cap_usdt must be positive")
        if not (0.0 < self.max_gross <= 1.0):
            raise ValueError("spot max_gross must be in (0, 1]")
        for name in ("gate_sma", "trend_sma", "fast_sma", "slow_sma", "vol_lookback", "atr_lookback"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        if self.fast_sma >= self.slow_sma:
            raise ValueError("fast_sma must be smaller than slow_sma")
        if not (0.0 <= self.rebalance_band <= 1.0):
            raise ValueError("rebalance_band must be in [0, 1]")
        if not (0.0 <= self.min_notional_coverage <= 1.0):
            raise ValueError("min_notional_coverage must be in [0, 1]")
