"""Pure frozen G20, C60 and D15 decisions with no I/O or order path."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean
from typing import Mapping, Sequence

from qount.contracts import MarketSnapshot
from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash

from qount.dual_engine.contracts import C60_STRATEGY_ID
from qount.dual_engine.contracts import C60_STRATEGY_VERSION
from qount.dual_engine.contracts import C60_SYMBOLS
from qount.dual_engine.contracts import DualEngineContractError
from qount.dual_engine.contracts import DualEnginePaperContract
from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.dual_engine.contracts import G20_STRATEGY_ID
from qount.dual_engine.contracts import G20_STRATEGY_VERSION


@dataclass(frozen=True)
class G20Decision:
    selected_symbol: str
    momentum_63d: Mapping[str, float]
    target_weights: Mapping[str, float]
    state_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "selected_symbol": self.selected_symbol,
            "momentum_63d": dict(self.momentum_63d),
            "target_weights": dict(self.target_weights),
            "state_hash": self.state_hash,
        }


@dataclass(frozen=True)
class C60Decision:
    candidates: tuple[str, ...]
    momentum_90d: Mapping[str, float]
    btc_system_gate: bool
    own_sma20_gate: Mapping[str, bool]
    eligible_count: int
    volatility_scalar: float
    pre_scale_weights: Mapping[str, float]
    target_weights: Mapping[str, float]
    state_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "candidates": self.candidates,
            "momentum_90d": dict(self.momentum_90d),
            "btc_system_gate": self.btc_system_gate,
            "own_sma20_gate": dict(self.own_sma20_gate),
            "eligible_count": self.eligible_count,
            "volatility_scalar": self.volatility_scalar,
            "pre_scale_weights": dict(self.pre_scale_weights),
            "target_weights": dict(self.target_weights),
            "state_hash": self.state_hash,
        }


def _prices(values: Sequence[float], *, minimum_length: int, name: str) -> tuple[float, ...]:
    try:
        normalized = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise DualEngineContractError(f"{name}_invalid") from exc
    if len(normalized) < minimum_length or any(not math.isfinite(value) or value <= 0.0 for value in normalized):
        raise DualEngineContractError(f"{name}_invalid")
    return normalized


def _return(values: Sequence[float], lookback: int) -> float:
    return float(values[-1]) / float(values[-lookback - 1]) - 1.0


def build_g20_decision(
    proxy_closes: Mapping[str, Sequence[float]],
    *,
    contract: DualEnginePaperContract | None = None,
) -> G20Decision:
    """Select the lexicographically stable 63-session Top1 without an absolute gate."""

    contract = contract or DualEnginePaperContract.frozen_v1()
    contract.validate()
    if set(proxy_closes) != set(G20_EXECUTION_TO_PROXY.values()):
        raise DualEngineContractError("g20_proxy_universe_invalid")
    momentum: dict[str, float] = {}
    for execution_symbol, proxy_symbol in G20_EXECUTION_TO_PROXY.items():
        closes = _prices(proxy_closes[proxy_symbol], minimum_length=64, name=f"g20_proxy:{proxy_symbol}")
        momentum[execution_symbol] = _return(closes, 63)
    selected = sorted(momentum, key=lambda symbol: (-momentum[symbol], symbol))[0]
    weights = {"BIL": 1.0 - contract.g20_risk_weight, selected: contract.g20_risk_weight}
    core = {
        "strategy_id": G20_STRATEGY_ID,
        "strategy_version": G20_STRATEGY_VERSION,
        "selected_symbol": selected,
        "momentum_63d": dict(sorted(momentum.items())),
        "target_weights": dict(sorted(weights.items())),
        "absolute_momentum_gate": False,
    }
    return G20Decision(
        selected_symbol=selected,
        momentum_63d=dict(sorted(momentum.items())),
        target_weights=dict(sorted(weights.items())),
        state_hash=canonical_hash(core),
    )

def _sample_covariance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise DualEngineContractError("c60_covariance_window_invalid")
    left_mean = fmean(left)
    right_mean = fmean(right)
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True)) / (len(left) - 1)


def _portfolio_volatility(
    closes_by_symbol: Mapping[str, tuple[float, ...]],
    weights: Mapping[str, float],
    *,
    window: int,
) -> float:
    active = [symbol for symbol, weight in weights.items() if weight > 0.0]
    if not active:
        return 0.0
    returns: dict[str, tuple[float, ...]] = {}
    for symbol in active:
        closes = closes_by_symbol[symbol]
        values = tuple(closes[index] / closes[index - 1] - 1.0 for index in range(len(closes) - window, len(closes)))
        if len(values) != window:
            raise DualEngineContractError("c60_volatility_history_invalid")
        returns[symbol] = values
    variance = 0.0
    for left in active:
        for right in active:
            variance += weights[left] * weights[right] * _sample_covariance(returns[left], returns[right])
    if variance < -1e-15:
        raise DualEngineContractError("c60_covariance_not_positive_semidefinite")
    return math.sqrt(max(0.0, variance) * 365.0)


def build_c60_decision(
    crypto_closes: Mapping[str, Sequence[float]],
    *,
    contract: DualEnginePaperContract | None = None,
) -> C60Decision:
    """Build the frozen C60 target, keeping rejected candidate weight in cash."""

    contract = contract or DualEnginePaperContract.frozen_v1()
    contract.validate()
    if set(crypto_closes) != set(C60_SYMBOLS):
        raise DualEngineContractError("c60_universe_invalid")
    closes = {
        symbol: _prices(values, minimum_length=91, name=f"c60_history:{symbol}")
        for symbol, values in crypto_closes.items()
    }
    momentum = {symbol: _return(values, 90) for symbol, values in closes.items()}
    candidates = tuple(
        symbol
        for symbol in sorted(momentum, key=lambda item: (-momentum[item], item))
        if momentum[symbol] > 0.0
    )[:2]
    btc = closes["BTCUSDT"]
    btc_gate = btc[-1] > fmean(btc[-50:])
    own_gate = {
        symbol: closes[symbol][-1] > fmean(closes[symbol][-20:])
        for symbol in C60_SYMBOLS
    }
    base_weight = 0.0 if not candidates else 1.0 / len(candidates)
    pre_scale = {symbol: 0.0 for symbol in C60_SYMBOLS}
    for symbol in candidates:
        allowed = own_gate[symbol] and (btc_gate or symbol == "PAXGUSDT")
        if allowed:
            pre_scale[symbol] = base_weight
    annualized_volatility = _portfolio_volatility(
        closes,
        pre_scale,
        window=contract.c60_volatility_window,
    )
    gross = sum(pre_scale.values())
    if gross == 0.0:
        scalar = 0.0
    elif annualized_volatility == 0.0:
        scalar = 1.0
    else:
        scalar = min(1.0, contract.c60_volatility_target / annualized_volatility)
    target = {
        symbol: weight * scalar
        for symbol, weight in pre_scale.items()
        if weight * scalar > 0.0
    }
    eligible_count = sum(1 for symbol in candidates if own_gate[symbol])
    core = {
        "strategy_id": C60_STRATEGY_ID,
        "strategy_version": C60_STRATEGY_VERSION,
        "candidates": candidates,
        "momentum_90d": dict(sorted(momentum.items())),
        "btc_system_gate": btc_gate,
        "own_sma20_gate": dict(sorted(own_gate.items())),
        "eligible_count": eligible_count,
        "volatility_scalar": scalar,
        "pre_scale_weights": dict(sorted(pre_scale.items())),
        "target_weights": dict(sorted(target.items())),
        "paxg_system_gate_exempt": True,
        "rejected_weight_redistributed": False,
    }
    return C60Decision(
        candidates=candidates,
        momentum_90d=dict(sorted(momentum.items())),
        btc_system_gate=btc_gate,
        own_sma20_gate=dict(sorted(own_gate.items())),
        eligible_count=eligible_count,
        volatility_scalar=scalar,
        pre_scale_weights=dict(sorted(pre_scale.items())),
        target_weights=dict(sorted(target.items())),
        state_hash=canonical_hash(core),
    )


def d15_c60_budget(
    decision: C60Decision,
    *,
    contract: DualEnginePaperContract | None = None,
) -> float:
    contract = contract or DualEnginePaperContract.frozen_v1()
    contract.validate()
    defensive, balanced, offensive, strong = contract.d15_budgets
    if not decision.btc_system_gate or decision.eligible_count == 0:
        return defensive
    if decision.eligible_count == 1:
        return balanced
    return offensive if decision.volatility_scalar < 0.75 else strong


def build_strategy_intents(
    snapshot: MarketSnapshot,
    g20: G20Decision,
    c60: C60Decision,
    *,
    evidence_hash: str,
) -> tuple[StrategyIntent, StrategyIntent]:
    """Project pure decisions into standard, order-free StrategyIntent contracts."""

    if snapshot.validate():
        raise DualEngineContractError("dual_engine_market_snapshot_invalid")
    evidence = canonical_hash(
        {
            "external_evidence_hash": evidence_hash,
            "snapshot_hash": snapshot.snapshot_hash,
            "g20_state_hash": g20.state_hash,
            "c60_state_hash": c60.state_hash,
        }
    )
    return (
        StrategyIntent.create(
            strategy_id=G20_STRATEGY_ID,
            strategy_version=G20_STRATEGY_VERSION,
            snapshot_id=snapshot.snapshot_id,
            decision_time=snapshot.decision_time,
            data_cutoff=snapshot.data_cutoff,
            target_weights=g20.target_weights,
            expected_holding_bars=21,
            target_stress_loss_fraction=0.20,
            reason_codes=("G20_63D_PROXY_TOP1", "G20_ABSOLUTE_GATE_DISABLED"),
            evidence_hash=evidence,
            state_hash=g20.state_hash,
        ),
        StrategyIntent.create(
            strategy_id=C60_STRATEGY_ID,
            strategy_version=C60_STRATEGY_VERSION,
            snapshot_id=snapshot.snapshot_id,
            decision_time=snapshot.decision_time,
            data_cutoff=snapshot.data_cutoff,
            target_weights=c60.target_weights,
            expected_holding_bars=1,
            target_stress_loss_fraction=0.60,
            reason_codes=(
                "C60_90D_POSITIVE_TOP2",
                "C60_SMA20_ASSET_GATE",
                "C60_BTC_SMA50_SYSTEM_GATE",
                "C60_VOLATILITY_CAP_60",
            ),
            evidence_hash=evidence,
            state_hash=c60.state_hash,
        ),
    )
