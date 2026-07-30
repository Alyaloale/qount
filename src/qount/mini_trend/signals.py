"""MiniTrend signal and target-weight derivation."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping

from qount.research_data.market_data import Bar
from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.models import GateState, SignalResult
from qount.research_data.indicators import ATR
from qount.legacy.x4.portfolio import correlation


def sma(xs: list[float], n: int) -> float | None:
    if n < 1:
        raise ValueError("n must be >= 1")
    if len(xs) < n:
        return None
    return sum(xs[-n:]) / n


def _bar_date(bars_by_symbol: Mapping[str, list[Bar]], cfg: MiniTrendConfig) -> str | None:
    bars = bars_by_symbol.get(cfg.gate_symbol)
    if not bars:
        bars = next((v for v in bars_by_symbol.values() if v), None)
    if not bars:
        return None
    return dt.datetime.fromtimestamp(bars[-1].ts_ms / 1000, dt.UTC).strftime("%Y-%m-%d")


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _returns(closes: list[float], lookback: int) -> list[float]:
    start = len(closes) - lookback
    return [closes[i] / closes[i - 1] - 1.0 for i in range(start, len(closes))]


def _atr_pct(bars: list[Bar], lookback: int) -> float | None:
    atr = ATR(lookback)
    last = None
    for bar in bars:
        last = atr.update(bar)
    close = bars[-1].close if bars else 0.0
    if last is None or close <= 0:
        return None
    return last / close


def _trend_up(closes: list[float], cfg: MiniTrendConfig) -> bool:
    trend = sma(closes, cfg.trend_sma)
    fast = sma(closes, cfg.fast_sma)
    slow = sma(closes, cfg.slow_sma)
    if trend is None or fast is None or slow is None:
        return False
    return closes[-1] > trend and fast > slow


def _breadth(bars_by_symbol: Mapping[str, list[Bar]], cfg: MiniTrendConfig) -> tuple[float, bool]:
    if not cfg.universe:
        return 0.0, False
    above = 0
    for symbol in cfg.universe:
        bars = bars_by_symbol.get(symbol) or []
        closes = [b.close for b in bars]
        trend = sma(closes, cfg.trend_sma)
        if trend is not None and closes[-1] > trend:
            above += 1
    value = above / len(cfg.universe)
    return value, value >= cfg.breadth_gate


def _gate_state(bars_by_symbol: Mapping[str, list[Bar]], cfg: MiniTrendConfig) -> GateState:
    gate_bars = bars_by_symbol.get(cfg.gate_symbol) or []
    gate_closes = [b.close for b in gate_bars]
    gate_sma = sma(gate_closes, cfg.gate_sma)
    btc_close = gate_closes[-1] if gate_closes else None
    btc_gate = bool(gate_sma is not None and btc_close is not None and btc_close > gate_sma)
    breadth, breadth_gate = _breadth(bars_by_symbol, cfg)
    return GateState(
        risk_on=btc_gate or breadth_gate,
        btc_close=btc_close,
        btc_sma200=gate_sma,
        breadth=breadth,
        btc_gate=btc_gate,
        breadth_gate=breadth_gate,
    )


def _raw_weights(
    windows: dict[str, list[float]],
    scale: dict[str, float],
    cfg: MiniTrendConfig,
) -> dict[str, float]:
    raw = {s: (1.0 / _std(rets) if _std(rets) > 0 else 0.0) for s, rets in windows.items()}
    if not raw:
        return {}
    if cfg.corr_penalty and len(raw) > 1:
        adjusted = {}
        for symbol in raw:
            cs = [correlation(windows[symbol], windows[other]) for other in raw if other != symbol]
            avg_corr = sum(cs) / len(cs) if cs else 0.0
            adjusted[symbol] = raw[symbol] / max(avg_corr, cfg.corr_floor)
        raw = adjusted
    total = sum(raw.values())
    if total <= 0:
        return {}
    weights = {s: (raw[s] / total) * scale[s] for s in raw}
    gross = sum(weights.values())
    if gross > cfg.max_gross:
        weights = {s: w * cfg.max_gross / gross for s, w in weights.items()}
    return weights


def target_weights(
    bars_by_symbol: Mapping[str, list[Bar]],
    cfg: MiniTrendConfig | None = None,
) -> SignalResult:
    """Return deterministic long/cash target weights for the configured universe."""

    cfg = cfg or MiniTrendConfig()
    gate = _gate_state(bars_by_symbol, cfg)
    targets = {s: 0.0 for s in cfg.universe}

    if gate.risk_on:
        windows: dict[str, list[float]] = {}
        scale: dict[str, float] = {}
        need = max(cfg.trend_sma, cfg.slow_sma, cfg.vol_lookback + 1, cfg.atr_lookback)
        for symbol in cfg.universe:
            bars = bars_by_symbol.get(symbol) or []
            closes = [b.close for b in bars]
            if len(closes) < need or not _trend_up(closes, cfg):
                continue
            atr_pct = _atr_pct(bars, cfg.atr_lookback)
            if atr_pct is None or atr_pct <= 0:
                continue
            windows[symbol] = _returns(closes, cfg.vol_lookback)
            scale[symbol] = min(cfg.max_symbol_weight, cfg.vol_target / atr_pct)
        targets.update(_raw_weights(windows, scale, cfg))

    return SignalResult(
        schema_version=1,
        strategy=cfg.strategy,
        bar=_bar_date(bars_by_symbol, cfg),
        universe=tuple(cfg.universe),
        gate=gate,
        targets=targets,
        diagnostics={
            "vol_target": cfg.vol_target,
            "rebalance_band": cfg.rebalance_band,
            "max_gross": cfg.max_gross,
            "market": cfg.market,
            "direction": cfg.direction,
        },
    )
