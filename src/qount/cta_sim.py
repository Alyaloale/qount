"""Local CTA paper-sim: a self-contained vertical slice of the CTA-R rebuild.

This is the Phase 0 deliverable of ``docs/rebuild-plan.md``. It wires the whole
Signal -> PortfolioConstruction -> Risk -> Execution chain into one runnable loop,
on a *synthetic* cross-asset price panel so it runs fully offline on any host (pure
stdlib, no numpy / ccxt / broker). Swapping in real data later is just replacing the
data layer (``generate_synthetic_panel`` -> a broker/CSV adapter); the signal,
portfolio, risk and execution logic stay identical.

Design (mirrors the plan's layering):

- DataLayer: ``generate_synthetic_panel`` builds daily prices with a per-asset-class
  block-correlation structure + regime-switching drift, so trend-following has a real
  (but noisy) signal to capture. ``load_prices_csv`` loads a real wide table instead.
- SignalLayer: multi-lookback time-series-momentum ensemble (mean of ``sign(P_t/P_{t-L}-1)``)
  scaled by inverse trailing volatility. Strictly decision-time only (no lookahead).
- PortfolioConstruction: gross-normalize, then vol-target the portfolio to ``target_vol``.
- RiskManager: cap leverage, and de-leverage while in drawdown.
- ExecutionLayer (sim): rebalance every ``rebalance_days``, fill at the next bar, charge
  ``cost_per_side_pct`` on turnover.
- Metrics: annualized return / vol / Sharpe, max drawdown, turnover, and the reused
  ``_panel_effective_breadth`` so the breadth thesis is reported in production.

research/sim-only; nothing here is imported by the live / ``run-once`` path.
"""

from __future__ import annotations

import csv
import itertools
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CTA_SIM_VERSION = "cta_sim_v1"
TRADING_DAYS_PER_YEAR = 252


# Inlined (not imported) so this module stays pure-stdlib and runs offline without ccxt.
# Same Grinold effective-breadth diagnostic used across the research harness:
# effective_breadth = N / (1 + (N-1)·r̄), r̄ = mean absolute pairwise return correlation.
def _pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _panel_effective_breadth(return_panel: dict[str, list[float | None]]) -> dict[str, Any]:
    tokens = list(return_panel)
    n = len(tokens)
    if n < 2:
        return {"symbol_count": n, "mean_abs_pairwise_corr": None, "effective_breadth": float(n)}
    abs_corrs: list[float] = []
    for left, right in itertools.combinations(tokens, 2):
        xs: list[float] = []
        ys: list[float] = []
        for a, b in zip(return_panel[left], return_panel[right]):
            if a is not None and b is not None:
                xs.append(a)
                ys.append(b)
        corr = _pearson_correlation(xs, ys)
        if corr is not None:
            abs_corrs.append(abs(corr))
    r_bar = (sum(abs_corrs) / len(abs_corrs)) if abs_corrs else 0.0
    effective = n / (1.0 + (n - 1) * r_bar)
    return {"symbol_count": n, "mean_abs_pairwise_corr": r_bar, "effective_breadth": effective}


# --------------------------------------------------------------------------------------
# Data layer
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AssetSpec:
    """One synthetic instrument. ``annual_vol`` and ``trend_strength`` are annualized."""

    name: str
    asset_class: str
    annual_vol: float = 0.16
    trend_strength: float = 0.35  # annualized drift magnitude drawn at each regime
    regime_flip_prob: float = 0.012  # per-day probability the drift regime changes
    class_load: float = 0.7  # within-class factor loading -> within-class corr = load^2


# A liquid cross-asset panel spanning six asset classes. Cross-class correlation is ~0
# by construction, within-class is ~load^2, so effective breadth lands well above the
# crypto-majors ~1.6 ceiling -- the whole point of the cross-asset thesis.
DEFAULT_UNIVERSE: tuple[AssetSpec, ...] = (
    AssetSpec("SPX", "equity", annual_vol=0.16),
    AssetSpec("NDX", "equity", annual_vol=0.22),
    AssetSpec("RUT", "equity", annual_vol=0.20),
    AssetSpec("UST10", "rates", annual_vol=0.06, trend_strength=0.18),
    AssetSpec("UST2", "rates", annual_vol=0.03, trend_strength=0.10),
    AssetSpec("UST30", "rates", annual_vol=0.11, trend_strength=0.22),
    AssetSpec("GOLD", "metals", annual_vol=0.15),
    AssetSpec("SILVER", "metals", annual_vol=0.28),
    AssetSpec("CRUDE", "energy", annual_vol=0.35, trend_strength=0.45),
    AssetSpec("COPPER", "energy", annual_vol=0.26, trend_strength=0.38),
    AssetSpec("EUR", "fx", annual_vol=0.08, trend_strength=0.12),
    AssetSpec("AUD", "fx", annual_vol=0.11, trend_strength=0.16),
    AssetSpec("BTC", "crypto", annual_vol=0.60, trend_strength=0.80),
    AssetSpec("ETH", "crypto", annual_vol=0.75, trend_strength=0.90),
)


def generate_synthetic_panel(
    universe: tuple[AssetSpec, ...] | list[AssetSpec],
    n_days: int,
    seed: int,
    start_price: float = 100.0,
) -> dict[str, list[float]]:
    """Daily prices with per-class block correlation + regime-switching drift.

    Each day draws a standardized factor per asset class; an asset's shock is
    ``load * class_factor + sqrt(1-load^2) * idio`` (unit variance), giving within-class
    correlation ``load^2`` and ~0 cross-class correlation. Drift switches regime with a
    small per-day probability, producing the persistent trends TSMOM is meant to harvest.
    """

    if n_days < 2:
        raise ValueError("n_days must be >= 2")
    rng = random.Random(seed)
    classes = sorted({a.asset_class for a in universe})
    prices: dict[str, list[float]] = {a.name: [start_price] for a in universe}
    # Current annualized drift per asset (starts flat, flips into regimes over time).
    drift: dict[str, float] = {a.name: 0.0 for a in universe}

    for _ in range(n_days - 1):
        class_factor = {c: rng.gauss(0.0, 1.0) for c in classes}
        for a in universe:
            if rng.random() < a.regime_flip_prob:
                drift[a.name] = rng.gauss(0.0, a.trend_strength)
            idio = rng.gauss(0.0, 1.0)
            load = max(0.0, min(1.0, a.class_load))
            shock = load * class_factor[a.asset_class] + math.sqrt(1.0 - load * load) * idio
            daily_vol = a.annual_vol / math.sqrt(TRADING_DAYS_PER_YEAR)
            daily_drift = drift[a.name] / TRADING_DAYS_PER_YEAR
            ret = daily_drift + daily_vol * shock
            prev = prices[a.name][-1]
            prices[a.name].append(max(prev * (1.0 + ret), 1e-9))
    return prices


def load_prices_csv(path: str | Path) -> dict[str, list[float]]:
    """Load a wide price table: first column = date, remaining columns = tickers.

    Rows must be chronologically sorted; blank cells become ``None`` (skipped in PnL).
    This is the seam where real broker/Norgate data plugs in without touching the
    signal/portfolio/risk code.
    """

    path = Path(path)
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if not header or len(header) < 2:
            raise ValueError("CSV needs a date column plus at least one ticker column")
        tickers = [h.strip() for h in header[1:]]
        series: dict[str, list[float | None]] = {t: [] for t in tickers}
        for row in reader:
            if not row:
                continue
            for idx, ticker in enumerate(tickers, start=1):
                raw = row[idx].strip() if idx < len(row) else ""
                series[ticker].append(float(raw) if raw else None)
    # Forward-fill leading/embedded gaps so prices are a clean float series.
    cleaned: dict[str, list[float]] = {}
    for ticker, values in series.items():
        filled: list[float] = []
        last: float | None = None
        for v in values:
            if v is not None:
                last = v
            filled.append(last if last is not None else start_first_valid(values))
        cleaned[ticker] = filled
    return cleaned


def start_first_valid(values: list[float | None]) -> float:
    for v in values:
        if v is not None:
            return v
    raise ValueError("price column has no valid values")


# --------------------------------------------------------------------------------------
# Config + small stats helpers
# --------------------------------------------------------------------------------------


@dataclass
class SimConfig:
    lookback_days: tuple[int, ...] = (63, 126, 252)
    vol_lookback_days: int = 63
    rebalance_days: int = 5
    target_vol: float = 0.12  # annualized portfolio volatility target
    max_leverage: float = 3.0
    cost_per_side_pct: float = 0.0002
    dd_threshold: float = 0.10  # drawdown depth at which de-leveraging starts
    dd_factor: float = 0.5  # leverage multiplier while in drawdown
    long_only: bool = False  # if True, drop short legs (negative trend -> 0 weight)
    max_weight: float = 1.0  # per-asset cap as a fraction of gross (1.0 = no cap)


# Risk-appetite presets for a cash A-share ETF account (long-only, no leverage). They set
# vol target, per-asset cap, and which asset classes to drop. Conservative keeps the bond
# ballast (low vol/DD); balanced caps any single name; aggressive drops bonds entirely to
# ride pure risk assets (equity/gold/foreign) -> high vol/return/drawdown.
MODE_PRESETS: dict[str, dict[str, Any]] = {
    "conservative": {"target_vol": 0.12, "max_weight": 1.0, "max_leverage": 1.0,
                     "long_only": True, "exclude_classes": ()},
    "balanced": {"target_vol": 0.15, "max_weight": 0.30, "max_leverage": 1.0,
                 "long_only": True, "exclude_classes": ()},
    "aggressive": {"target_vol": 0.25, "max_weight": 0.35, "max_leverage": 1.0,
                   "long_only": True, "exclude_classes": ("bond",)},
}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std_sample(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = _mean(values)
    var = sum((v - mu) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = float("-inf")
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def _sign(x: float) -> float:
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def _cap_unit_weights(weights: dict[str, float], cap: float) -> dict[str, float]:
    """Cap each name's gross share at ``cap`` (of gross=1), water-filling onto the rest.

    Inverse-vol weighting dumps capital into the lowest-vol asset (the bond ETF takes ~61%);
    this caps any single name and redistributes the excess to the uncapped names, keeping
    sum(|w|)=1. Used to de-concentrate the book in the balanced/aggressive risk modes.
    """

    if cap <= 0.0 or cap >= 1.0:
        return weights
    w = dict(weights)
    capped: dict[str, float] = {}
    for _ in range(len(w) + 1):
        free = {k: v for k, v in w.items() if k not in capped}
        free_gross = sum(abs(v) for v in free.values())
        if free_gross <= 0.0:
            break
        budget = 1.0 - sum(abs(v) for v in capped.values())
        if budget <= 0.0:
            for k in free:
                w[k] = 0.0
            break
        scale = budget / free_gross
        newly: dict[str, float] = {}
        for name, value in free.items():
            scaled = value * scale
            if abs(scaled) > cap + 1e-9:
                newly[name] = math.copysign(cap, value)
            else:
                w[name] = scaled
        if not newly:
            break
        for name, value in newly.items():
            w[name] = value
            capped[name] = value
    return w


# --------------------------------------------------------------------------------------
# Signal + portfolio + risk (decision-time only, no lookahead)
# --------------------------------------------------------------------------------------


def _target_weights(
    prices: dict[str, list[float]],
    rets: dict[str, list[float | None]],
    t: int,
    config: SimConfig,
    equity: float,
    peak_equity: float,
) -> dict[str, float]:
    """Weights decided at end of day ``t`` using only data through ``t``."""

    names = list(prices)
    raw: dict[str, float] = {}
    for name in names:
        # Inverse-vol from trailing window (decision-time).
        window = [
            rets[name][k]
            for k in range(max(1, t - config.vol_lookback_days + 1), t + 1)
            if rets[name][k] is not None
        ]
        vol = _std_sample(window)
        if vol <= 0.0:
            continue
        # Multi-lookback trend ensemble in [-1, 1].
        signs: list[float] = []
        for lookback in config.lookback_days:
            if t - lookback < 0:
                continue
            p_now = prices[name][t]
            p_then = prices[name][t - lookback]
            if p_then > 0.0:
                signs.append(_sign(p_now / p_then - 1.0))
        if not signs:
            continue
        ensemble = _mean(signs)
        if config.long_only and ensemble < 0.0:
            ensemble = 0.0  # cash A-share account can't short: drop the short leg
        if ensemble == 0.0:
            continue
        raw[name] = ensemble / vol

    gross = sum(abs(w) for w in raw.values())
    if gross <= 0.0:
        return {}
    unit = {name: w / gross for name, w in raw.items()}
    if config.max_weight < 1.0:
        unit = _cap_unit_weights(unit, config.max_weight)

    # Portfolio vol target: estimate the unit portfolio's daily vol on trailing returns.
    port_hist: list[float] = []
    for k in range(max(1, t - config.vol_lookback_days + 1), t + 1):
        day = 0.0
        priced = False
        for name, w in unit.items():
            r = rets[name][k]
            if r is not None:
                day += w * r
                priced = True
        if priced:
            port_hist.append(day)
    port_vol = _std_sample(port_hist)
    target_daily_vol = config.target_vol / math.sqrt(TRADING_DAYS_PER_YEAR)
    leverage = config.max_leverage if port_vol <= 0.0 else target_daily_vol / port_vol
    leverage = min(leverage, config.max_leverage)

    # Drawdown de-leverage.
    if peak_equity > 0.0 and (peak_equity - equity) / peak_equity > config.dd_threshold:
        leverage *= config.dd_factor

    return {name: w * leverage for name, w in unit.items()}


# --------------------------------------------------------------------------------------
# Execution sim + main loop
# --------------------------------------------------------------------------------------


def run_paper_sim(prices: dict[str, list[float]], config: SimConfig | None = None) -> dict[str, Any]:
    """Run the full sim and return a metrics + equity-curve result dict."""

    config = config or SimConfig()
    names = list(prices)
    if not names:
        raise ValueError("prices is empty")
    length = len(prices[names[0]])
    if any(len(prices[n]) != length for n in names):
        raise ValueError("all price series must be the same length")
    if length < max(config.lookback_days) + config.rebalance_days + 2:
        raise ValueError("not enough price history for the configured lookbacks")

    rets: dict[str, list[float | None]] = {}
    for name in names:
        series: list[float | None] = [None]
        for t in range(1, length):
            prev = prices[name][t - 1]
            series.append(prices[name][t] / prev - 1.0 if prev > 0.0 else None)
        rets[name] = series

    warmup = max(max(config.lookback_days), config.vol_lookback_days) + 1
    equity = 1.0
    peak_equity = 1.0
    equity_curve: list[float] = [1.0]
    weights: dict[str, float] = {}
    total_turnover = 0.0
    rebalances = 0
    gross_exposures: list[float] = []

    for t in range(1, length):
        # Realize today's return with weights set at the previous rebalance.
        port_ret = 0.0
        for name, w in weights.items():
            r = rets[name][t]
            if r is not None:
                port_ret += w * r
        equity *= 1.0 + port_ret
        peak_equity = max(peak_equity, equity)

        # Rebalance at end of day t (data through t), effective from t+1.
        if t >= warmup and t % config.rebalance_days == 0:
            new_weights = _target_weights(prices, rets, t, config, equity, peak_equity)
            union = set(new_weights) | set(weights)
            turnover = sum(abs(new_weights.get(n, 0.0) - weights.get(n, 0.0)) for n in union)
            equity *= 1.0 - config.cost_per_side_pct * turnover
            total_turnover += turnover
            gross_exposures.append(sum(abs(w) for w in new_weights.values()))
            rebalances += 1
            weights = new_weights
            peak_equity = max(peak_equity, equity)

        equity_curve.append(equity)

    # Net daily returns derived from the equity curve (cost included) for honest metrics.
    net_daily = [
        equity_curve[i] / equity_curve[i - 1] - 1.0
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0.0
    ]
    ann_return = _mean(net_daily) * TRADING_DAYS_PER_YEAR
    ann_vol = _std_sample(net_daily) * math.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = ann_return / ann_vol if ann_vol > 0.0 else None
    max_dd = _max_drawdown(equity_curve)
    breadth = _panel_effective_breadth({n: rets[n] for n in names})
    years = (length - 1) / TRADING_DAYS_PER_YEAR
    cagr = (equity ** (1.0 / years) - 1.0) if years > 0 and equity > 0 else None

    return {
        "version": CTA_SIM_VERSION,
        "config": {
            "lookback_days": list(config.lookback_days),
            "vol_lookback_days": config.vol_lookback_days,
            "rebalance_days": config.rebalance_days,
            "target_vol": config.target_vol,
            "max_leverage": config.max_leverage,
            "cost_per_side_pct": config.cost_per_side_pct,
            "dd_threshold": config.dd_threshold,
            "dd_factor": config.dd_factor,
            "long_only": config.long_only,
            "max_weight": config.max_weight,
        },
        "universe_size": len(names),
        "universe": names,
        "trading_days": length,
        "years": years,
        "rebalances": rebalances,
        "final_equity": equity,
        "total_return_pct": equity - 1.0,
        "cagr": cagr,
        "annualized_return": ann_return,
        "annualized_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "total_turnover": total_turnover,
        "avg_gross_exposure": _mean(gross_exposures),
        "effective_breadth": breadth,
        "equity_curve_sampled": _downsample(equity_curve, 60),
        # Full net daily return series (cost included). Kept out of the sampled curve;
        # the gate scan (cta_eval) consumes it for DSR/PBO/time-fold robustness.
        "net_daily_returns": net_daily,
    }


def _downsample(series: list[float], target_points: int) -> list[float]:
    if len(series) <= target_points:
        return [round(v, 6) for v in series]
    step = len(series) / target_points
    return [round(series[min(len(series) - 1, int(i * step))], 6) for i in range(target_points)]


def render_summary(result: dict[str, Any]) -> str:
    """Compact human-readable summary, including an ASCII equity sparkline."""

    def pct(x: Any) -> str:
        return f"{x * 100:+.2f}%" if isinstance(x, (int, float)) else "n/a"

    def num(x: Any, digits: int = 2) -> str:
        return f"{x:.{digits}f}" if isinstance(x, (int, float)) else "n/a"

    breadth = result.get("effective_breadth", {})
    lines = [
        f"CTA-R paper-sim ({result['version']})",
        f"  universe        : {result['universe_size']} assets, {num(result['years'],2)}y, "
        f"{result['trading_days']} bars, {result['rebalances']} rebalances",
        f"  effective breadth: {num(breadth.get('effective_breadth'),2)} "
        f"(r̄={num(breadth.get('mean_abs_pairwise_corr'),3)})",
        f"  total return    : {pct(result['total_return_pct'])}   CAGR: {pct(result['cagr'])}",
        f"  ann return / vol: {pct(result['annualized_return'])} / {pct(result['annualized_vol'])}",
        f"  Sharpe          : {num(result['sharpe'],2)}",
        f"  max drawdown    : {pct(result['max_drawdown'])}",
        f"  avg gross / turn: {num(result['avg_gross_exposure'],2)} / {num(result['total_turnover'],1)}",
        f"  equity          : {_sparkline(result['equity_curve_sampled'])}",
    ]
    return "\n".join(lines)


def _sparkline(series: list[float]) -> str:
    if not series:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(series), max(series)
    span = hi - lo
    if span <= 0:
        return blocks[0] * len(series)
    return "".join(blocks[min(len(blocks) - 1, int((v - lo) / span * (len(blocks) - 1)))] for v in series)


# --------------------------------------------------------------------------------------
# Standalone entry: ``python -m qount.cta_sim`` runs the local paper-sim with zero
# third-party deps (no ccxt/openai), so it works offline on any host. The same command
# is also wired into ``qount.main`` for hosts that already have the full stack.
# --------------------------------------------------------------------------------------


def _build_arg_parser():  # pragma: no cover - thin argparse wiring
    import argparse

    parser = argparse.ArgumentParser(prog="qount.cta_sim", description="Offline CTA-R paper-sim.")
    parser.add_argument("--data-source", choices=["synthetic", "csv", "tiingo", "ibkr", "norgate", "tqsdk", "binance", "openquant", "akshare"], default="synthetic", help="Where prices come from.")
    parser.add_argument("--days", type=int, default=1500, help="Synthetic trading days (synthetic source only).")
    parser.add_argument("--seed", type=int, default=7, help="Synthetic data RNG seed.")
    parser.add_argument("--prices-csv", default=None, help="Wide price CSV (date + ticker columns) for --data-source csv.")
    parser.add_argument("--tickers", nargs="+", default=None, help="Override the ticker/symbol panel (tiingo).")
    parser.add_argument("--tiingo-api-key", default=None, help="Tiingo key (else QOUNT_TIINGO_API_KEY env).")
    parser.add_argument("--start-date", default="2010-01-01", help="History start date for tiingo/norgate (YYYY-MM-DD).")
    parser.add_argument("--ibkr-host", default="127.0.0.1", help="IBKR TWS/Gateway host.")
    parser.add_argument("--ibkr-port", type=int, default=7497, help="IBKR API port (paper TWS 7497, paper Gateway 4002).")
    parser.add_argument("--ibkr-client-id", type=int, default=17, help="IBKR API client id.")
    parser.add_argument("--ibkr-duration", default="10 Y", help="IBKR historical duration string.")
    parser.add_argument("--ibkr-bar-size", default="1 day", help="IBKR bar size.")
    parser.add_argument("--tqsdk-user", default=None, help="TqSdk 天勤 account (else QOUNT_TQSDK_USER env).")
    parser.add_argument("--tqsdk-pass", default=None, help="TqSdk 天勤 password (else QOUNT_TQSDK_PASS env).")
    parser.add_argument("--tqsdk-bars", type=int, default=2000, help="Daily bars to pull per domestic contract.")
    parser.add_argument("--binance-timeframe", default="1d", help="Binance OHLCV timeframe (1d default; 4h/1h for intraday).")
    parser.add_argument("--binance-limit", type=int, default=1000, help="Bars to pull per Binance pair.")
    parser.add_argument("--binance-market", choices=["spot", "future"], default="spot", help="Binance market type (spot or USDT-margined perpetuals).")
    parser.add_argument("--openquant-db", default=None, help="Path to OpenQuant market_data.sqlite (else QOUNT_OPENQUANT_DB env).")
    parser.add_argument("--openquant-table", choices=["index_bars", "price_bars"], default="index_bars", help="OpenQuant table: index_bars (cross-sector indices) or price_bars (single stocks).")
    parser.add_argument("--akshare-zip", default=None, help="Path to local etf_data.zip; seeds the date,close cache on first use (avoids API rate-limit).")
    parser.add_argument("--akshare-cache-dir", default=None, help="ETF cache dir (default state/etf_cache).")
    parser.add_argument("--akshare-online", action="store_true", help="Best-effort online akshare top-up of the cache tail (domestic, no proxy).")
    parser.add_argument("--lookback-days", nargs="+", type=int, default=None, help="Trend lookbacks (days); default 63 126 252.")
    parser.add_argument("--vol-lookback-days", type=int, default=63)
    parser.add_argument("--rebalance-days", type=int, default=5)
    parser.add_argument("--target-vol", type=float, default=0.12)
    parser.add_argument("--max-leverage", type=float, default=3.0)
    parser.add_argument("--cost-per-side-pct", type=float, default=0.0002)
    parser.add_argument("--dd-threshold", type=float, default=0.10)
    parser.add_argument("--dd-factor", type=float, default=0.5)
    parser.add_argument("--long-only", action="store_true", help="Drop short legs (negative trend -> 0 weight); pair with --max-leverage 1.0 to model a cash, no-short A-share/ETF account.")
    parser.add_argument("--max-weight", type=float, default=1.0, help="Per-asset weight cap as a fraction of gross (1.0 = no cap); de-concentrates the inverse-vol book.")
    parser.add_argument("--mode", choices=["conservative", "balanced", "aggressive"], default=None, help="Risk-appetite preset for a cash ETF account (overrides --target-vol/--max-weight/--max-leverage/--long-only and drops asset classes, e.g. aggressive drops bonds).")
    parser.add_argument("--gate-scan", action="store_true", help="Run the parameter grid through the DSR/PBO/time-fold gate and emit a pass/fail verdict instead of a single sim.")
    parser.add_argument("--walk-forward", action="store_true", help="Selection-free robustness: equal-weight ensemble + past-only walk-forward OOS + fixed a-priori config (no parameter pick -> PBO does not apply).")
    parser.add_argument("--output-path", default=None, help="Write the sim JSON here; default under state/research_runs/.")
    parser.add_argument("--no-artifact", action="store_true", help="Skip writing the JSON artifact.")
    return parser


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - exercised via CLI test
    import json as _json
    import sys as _sys
    from datetime import datetime, timezone

    import os as _os

    from .cta_data import load_panel  # lazy to avoid a circular import at module load

    args = _build_arg_parser().parse_args(argv)
    prices, data_source = load_panel(
        args.data_source,
        days=args.days,
        seed=args.seed,
        prices_csv=args.prices_csv,
        tickers=args.tickers,
        api_key=args.tiingo_api_key or _os.environ.get("QOUNT_TIINGO_API_KEY"),
        start_date=args.start_date,
        host=args.ibkr_host,
        port=args.ibkr_port,
        client_id=args.ibkr_client_id,
        duration=args.ibkr_duration,
        bar_size=args.ibkr_bar_size,
        tqsdk_user=args.tqsdk_user or _os.environ.get("QOUNT_TQSDK_USER"),
        tqsdk_password=args.tqsdk_pass or _os.environ.get("QOUNT_TQSDK_PASS"),
        tqsdk_bars=args.tqsdk_bars,
        binance_timeframe=args.binance_timeframe,
        binance_limit=args.binance_limit,
        binance_market=args.binance_market,
        openquant_db=args.openquant_db or _os.environ.get("QOUNT_OPENQUANT_DB"),
        openquant_table=args.openquant_table,
        akshare_zip=args.akshare_zip or _os.environ.get("QOUNT_ETF_ZIP"),
        akshare_cache_dir=args.akshare_cache_dir,
        akshare_online=args.akshare_online,
    )

    # Resolve the risk mode: a preset overrides the individual knobs and drops asset classes.
    if args.mode:
        preset = MODE_PRESETS[args.mode]
        eff_target_vol = preset["target_vol"]
        eff_max_weight = preset["max_weight"]
        eff_max_leverage = preset["max_leverage"]
        eff_long_only = preset["long_only"]
        if preset["exclude_classes"]:
            from .cta_data import exclude_asset_classes

            prices = exclude_asset_classes(prices, preset["exclude_classes"])
        data_source = f"{data_source}|mode={args.mode}"
    else:
        eff_target_vol = args.target_vol
        eff_max_weight = args.max_weight
        eff_max_leverage = args.max_leverage
        eff_long_only = args.long_only

    if args.walk_forward:
        from .cta_eval import render_walkforward_summary, run_walkforward_eval

        result = run_walkforward_eval(
            prices,
            long_only=eff_long_only,
            max_leverage=eff_max_leverage,
            max_weight=eff_max_weight,
        )
        result["data_source"] = data_source
        summary = render_walkforward_summary(result)
        artifact_kind = "cta-walk-forward"
        default_filename = "cta_walk_forward.json"
    elif args.gate_scan:
        from .cta_eval import render_gate_summary, run_gate_scan

        result = run_gate_scan(
            prices,
            long_only=eff_long_only,
            max_leverage=eff_max_leverage,
            max_weight=eff_max_weight,
        )
        result["data_source"] = data_source
        summary = render_gate_summary(result)
        artifact_kind = "cta-gate-scan"
        default_filename = "cta_gate_scan.json"
    else:
        config = SimConfig(
            lookback_days=tuple(args.lookback_days) if args.lookback_days else (63, 126, 252),
            vol_lookback_days=args.vol_lookback_days,
            rebalance_days=args.rebalance_days,
            target_vol=eff_target_vol,
            max_leverage=eff_max_leverage,
            cost_per_side_pct=args.cost_per_side_pct,
            dd_threshold=args.dd_threshold,
            dd_factor=args.dd_factor,
            long_only=eff_long_only,
            max_weight=eff_max_weight,
        )
        result = run_paper_sim(prices, config)
        result.pop("net_daily_returns", None)  # keep the single-run artifact lean
        result["data_source"] = data_source
        summary = render_summary(result)
        artifact_kind = "cta-paper-sim"
        default_filename = "cta_paper_sim.json"

    if not args.no_artifact:
        if args.output_path:
            out = Path(args.output_path).expanduser()
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            repo_root = Path(__file__).resolve().parents[2]
            out = repo_root / "state" / "research_runs" / f"{stamp}-{artifact_kind}" / default_filename
        out.parent.mkdir(parents=True, exist_ok=True)
        result["output_path"] = str(out)
        out.write_text(_json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(summary, file=_sys.stderr)
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
