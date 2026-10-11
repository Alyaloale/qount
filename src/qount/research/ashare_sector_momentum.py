"""A-share Sector and Track ETF Momentum Breakout Strategy Module.

Designed for retail quantitative trading:
1. High-elasticity core sector universe (Chips, NEV, Solar, Liquor, Defense, Tech, Brokers, etc.)
2. Donchian 20-day high breakout entry with moving average trend confirmation.
3. Trailing peak stop-loss / profit-lock to let winners run while cutting losers quickly.
4. Macro-adaptive regime filter (reduces exposure during macro bear markets).
5. 100% causal execution (Signal at T close -> Order filled at T+1 open with commission & slippage).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SectorBar:
    """Daily OHLCV bar for an asset."""
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    vol: float = 0.0
    amount: float = 0.0


@dataclass
class TradeRecord:
    """Record of an executed trade."""
    trade_date: str
    symbol: str
    action: str  # 'BUY' or 'SELL'
    shares: float
    price: float
    fee: float
    cash_flow: float  # Negative for buy, positive for sell
    pnl: Optional[float] = None
    reason: str = ""


@dataclass
class DailySnapshot:
    """Daily portfolio status snapshot."""
    trade_date: str
    cash: float
    equity: float
    drawdown: float
    positions: Dict[str, float]  # symbol -> shares


@dataclass
class SectorMetrics:
    """Comprehensive performance metrics."""
    initial_capital: float
    final_equity: float
    total_return: float
    cagr: float
    max_drawdown: float
    annualized_volatility: float
    sharpe_ratio: float
    calmar_ratio: float
    annual_turnover: float
    total_trades: int
    win_rate: float
    profit_loss_ratio: float
    year_returns: Dict[str, float] = field(default_factory=dict)
    regime_returns: Dict[str, float] = field(default_factory=dict)


@dataclass
class SectorSimulationResult:
    """Full backtest simulation result."""
    name: str
    metrics: SectorMetrics
    snapshots: List[DailySnapshot]
    trades: List[TradeRecord]
    equity_curve: List[float]
    dates: List[str]


def compute_drawdowns(navs: List[float]) -> Tuple[List[float], float]:
    """Compute drawdown series and max drawdown."""
    if not navs:
        return [], 0.0
    dds = []
    peak = navs[0]
    max_dd = 0.0
    for val in navs:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        dds.append(dd)
        if dd > max_dd:
            max_dd = dd
    return dds, max_dd


def evaluate_sector_performance(
    dates: List[str],
    equity_curve: List[float],
    trades: List[TradeRecord],
    total_turnover_value: float,
    initial_capital: float = 1_000_000.0,
    annual_cash_yield: float = 0.02,
) -> SectorMetrics:
    """Calculate standard performance metrics from equity curve and trades."""
    if not equity_curve:
        return SectorMetrics(
            initial_capital=initial_capital,
            final_equity=initial_capital,
            total_return=0.0,
            cagr=0.0,
            max_drawdown=0.0,
            annualized_volatility=0.0,
            sharpe_ratio=0.0,
            calmar_ratio=0.0,
            annual_turnover=0.0,
            total_trades=0,
            win_rate=0.0,
            profit_loss_ratio=0.0,
        )

    final_equity = equity_curve[-1]
    total_return = (final_equity / initial_capital) - 1.0
    years = max(len(equity_curve) / 252.0, 1.0 / 252.0)
    cagr = (final_equity / initial_capital) ** (1.0 / years) - 1.0

    _, max_dd = compute_drawdowns(equity_curve)

    # Volatility and Sharpe
    rets = [
        (equity_curve[i] / equity_curve[i - 1]) - 1.0
        for i in range(1, len(equity_curve))
    ]
    if rets:
        mean_r = sum(rets) / len(rets)
        var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)
        ann_vol = math.sqrt(var_r) * math.sqrt(252.0)
        sharpe = (cagr - annual_cash_yield) / ann_vol if ann_vol > 1e-6 else 0.0
    else:
        ann_vol = 0.0
        sharpe = 0.0

    calmar = cagr / max_dd if max_dd > 1e-6 else 0.0

    # Turnover: one-way turnover = (total traded gross value / 2) / (mean portfolio equity * years)
    mean_equity = sum(equity_curve) / len(equity_curve)
    ann_turnover = (total_turnover_value / 2.0) / (mean_equity * years) if mean_equity > 0 else 0.0

    # Trade stats
    sell_trades = [t for t in trades if t.action == "SELL" and t.pnl is not None]
    if sell_trades:
        wins = [t.pnl for t in sell_trades if t.pnl > 0]
        losses = [t.pnl for t in sell_trades if t.pnl <= 0]
        win_rate = len(wins) / len(sell_trades)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        plr = avg_win / avg_loss if avg_loss > 1e-6 else 0.0
    else:
        win_rate = 0.0
        plr = 0.0

    # Calendar year returns
    year_map: Dict[str, List[float]] = {}
    for d, eq in zip(dates, equity_curve):
        y = d[:4]
        year_map.setdefault(y, []).append(eq)

    year_returns: Dict[str, float] = {}
    prev_eq = initial_capital
    for y, eq_list in sorted(year_map.items()):
        year_returns[y] = (eq_list[-1] / prev_eq) - 1.0
        prev_eq = eq_list[-1]

    # Standard historical regimes
    regime_bounds = {
        "2015_crash": ("20150615", "20150826"),
        "2016_circuit": ("20160101", "20160129"),
        "2018_trade_war": ("20180129", "20181228"),
        "2019_recovery": ("20190102", "20190419"),
        "2020_covid_shock": ("20200120", "20200323"),
        "2020_2021_bull": ("20200324", "20210218"),
        "2022_downtrend": ("20220104", "20221031"),
        "2024_rebound": ("20240918", "20241009"),
    }
    date_to_eq = {d: eq for d, eq in zip(dates, equity_curve)}
    regime_returns: Dict[str, float] = {}
    for r_key, (d0, d1) in regime_bounds.items():
        sub = [d for d in dates if d0 <= d <= d1]
        if sub and len(sub) >= 2:
            eq0 = date_to_eq[sub[0]]
            eq1 = date_to_eq[sub[-1]]
            regime_returns[r_key] = (eq1 / eq0) - 1.0 if eq0 > 0 else 0.0

    return SectorMetrics(
        initial_capital=initial_capital,
        final_equity=final_equity,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_dd,
        annualized_volatility=ann_vol,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        annual_turnover=ann_turnover,
        total_trades=len(trades),
        win_rate=win_rate,
        profit_loss_ratio=plr,
        year_returns=year_returns,
        regime_returns=regime_returns,
    )


class SectorMomentumSimulator:
    """Simulator for Sector and Track Momentum Breakout Strategy."""

    def __init__(
        self,
        commission_bps: float = 6.0,
        slippage_bps: float = 5.0,
        annual_cash_yield: float = 0.02,
        initial_capital: float = 1_000_000.0,
        extra_execution_delay: int = 0,
    ):
        self.commission_rate = commission_bps / 10000.0
        self.slippage_rate = slippage_bps / 10000.0
        self.annual_cash_yield = annual_cash_yield
        self.daily_cash_yield = (1.0 + annual_cash_yield) ** (1.0 / 252.0) - 1.0
        self.initial_capital = initial_capital
        self.extra_execution_delay = extra_execution_delay

    def run(
        self,
        bars_dict: Dict[str, List[SectorBar]],
        universe: List[str],
        benchmark_symbol: str = "000300.SH",
        top_n: int = 2,
        ma_period: int = 30,
        breakout_window: int = 20,
        trailing_stop_pct: float = 0.10,
        momentum_window: int = 20,
        macro_filter: bool = True,
        macro_ma_period: int = 120,
        macro_tighten_factor: float = 0.80,
    ) -> SectorSimulationResult:
        """Run backtest simulation.
        
        Args:
            bars_dict: Dict mapping symbol -> list of SectorBar.
            universe: List of candidate symbols.
            benchmark_symbol: Benchmark symbol for macro filter.
            top_n: Max positions held concurrently.
            ma_period: Moving average period for sector trend filter.
            breakout_window: Donchian high lookback window.
            trailing_stop_pct: Max drawdown allowed from peak price.
            momentum_window: Return window used to rank candidates.
            macro_filter: Whether to use benchmark macro regime overlay.
            macro_ma_period: Moving average period for benchmark macro filter.
            macro_tighten_factor: Multiplier to tighten stop during bear market.
        """
        # Determine global dates based on benchmark
        if benchmark_symbol not in bars_dict:
            raise ValueError(f"Benchmark symbol {benchmark_symbol} missing from data")
        
        bench_bars = bars_dict[benchmark_symbol]
        dates = [b.trade_date for b in bench_bars]

        # Map symbol -> trade_date -> SectorBar
        by_date: Dict[str, Dict[str, SectorBar]] = {}
        for sym in universe + [benchmark_symbol]:
            if sym in bars_dict:
                by_date[sym] = {b.trade_date: b for b in bars_dict[sym]}
            else:
                by_date[sym] = {}

        # Precalculate benchmark macro MA if macro_filter is True
        bench_closes = [by_date[benchmark_symbol][d].close for d in dates]
        bench_ma: List[Optional[float]] = [None] * len(bench_closes)
        for i in range(macro_ma_period - 1, len(bench_closes)):
            bench_ma[i] = sum(bench_closes[i - macro_ma_period + 1 : i + 1]) / float(macro_ma_period)

        # Pre-allocate history structures
        history_closes: Dict[str, List[float]] = {s: [] for s in universe}

        # Simulation state
        cash = self.initial_capital
        # Position: symbol -> {'shares': float, 'entry_px': float, 'highest_px': float}
        positions: Dict[str, Dict[str, float]] = {}
        # Pending orders: list of (action, symbol, delay_remaining, reason)
        pending_orders: List[Tuple[str, str, int, str]] = []
        
        equity_curve: List[float] = []
        snapshots: List[DailySnapshot] = []
        trades: List[TradeRecord] = []
        total_turnover_value = 0.0

        for t, d in enumerate(dates):
            # -------------------------------------------------------------
            # STEP 1: Morning Open Execution for Pending Orders
            # -------------------------------------------------------------
            next_pending: List[Tuple[str, str, int, str]] = []

            # 1a. Process SELLs first to free up liquidity
            for action, sym, delay, reason in pending_orders:
                if delay == 0:
                    if action == "SELL" and sym in positions:
                        bar = by_date[sym].get(d)
                        if bar is not None:
                            pos = positions[sym]
                            fill_px = bar.open * (1.0 - self.slippage_rate)
                            gross = pos["shares"] * fill_px
                            fee = gross * self.commission_rate
                            net_proceeds = gross - fee
                            cash += net_proceeds
                            total_turnover_value += gross
                            pnl = net_proceeds - (pos["shares"] * pos["entry_px"])
                            trades.append(
                                TradeRecord(
                                    trade_date=d,
                                    symbol=sym,
                                    action="SELL",
                                    shares=pos["shares"],
                                    price=fill_px,
                                    fee=fee,
                                    cash_flow=net_proceeds,
                                    pnl=pnl,
                                    reason=reason,
                                )
                            )
                            del positions[sym]
                else:
                    next_pending.append((action, sym, delay - 1, reason))

            # 1b. Process BUYs
            for action, sym, delay, reason in pending_orders:
                if delay == 0 and action == "BUY" and sym not in positions:
                    bar = by_date[sym].get(d)
                    if bar is not None:
                        # Estimate current portfolio value at open
                        cur_eq = cash
                        for s, pos in positions.items():
                            s_bar = by_date[s].get(d)
                            px = s_bar.open if s_bar is not None else pos["entry_px"]
                            cur_eq += pos["shares"] * px
                        
                        target_alloc = cur_eq / float(top_n)
                        alloc = min(cash * 0.98, target_alloc)
                        if alloc > 1000.0:
                            fill_px = bar.open * (1.0 + self.slippage_rate)
                            shares = alloc / (fill_px * (1.0 + self.commission_rate))
                            gross_cost = shares * fill_px
                            fee = gross_cost * self.commission_rate
                            total_cost = gross_cost + fee
                            cash -= total_cost
                            total_turnover_value += gross_cost
                            positions[sym] = {
                                "shares": shares,
                                "entry_px": fill_px,
                                "highest_px": fill_px,
                            }
                            trades.append(
                                TradeRecord(
                                    trade_date=d,
                                    symbol=sym,
                                    action="BUY",
                                    shares=shares,
                                    price=fill_px,
                                    fee=fee,
                                    cash_flow=-total_cost,
                                    pnl=None,
                                    reason=reason,
                                )
                            )
            pending_orders = next_pending

            # -------------------------------------------------------------
            # STEP 2: Daily Cash Yield Accrual
            # -------------------------------------------------------------
            cash *= (1.0 + self.daily_cash_yield)

            # -------------------------------------------------------------
            # STEP 3: Mark to Market at Close & Trailing High Update
            # -------------------------------------------------------------
            for sym in universe:
                bar = by_date[sym].get(d)
                if bar is not None:
                    history_closes[sym].append(bar.close)

            day_equity = cash
            for s, pos in positions.items():
                bar = by_date[s].get(d)
                px = bar.close if bar is not None else pos["entry_px"]
                day_equity += pos["shares"] * px
                if bar is not None and bar.close > pos["highest_px"]:
                    pos["highest_px"] = bar.close

            equity_curve.append(day_equity)
            snapshots.append(
                DailySnapshot(
                    trade_date=d,
                    cash=cash,
                    equity=day_equity,
                    drawdown=0.0,
                    positions={s: pos["shares"] for s, pos in positions.items()},
                )
            )

            # -------------------------------------------------------------
            # STEP 4: Causal Signal Generation on Day T Close
            # -------------------------------------------------------------
            # Check macro regime
            is_macro_bear = False
            if macro_filter and bench_ma[t] is not None:
                if bench_closes[t] < bench_ma[t]:
                    is_macro_bear = True

            effective_top_n = max(1, top_n // 2) if is_macro_bear else top_n
            effective_trailing_stop = (
                trailing_stop_pct * macro_tighten_factor if is_macro_bear else trailing_stop_pct
            )

            # Check sell signals on held positions
            to_sell: set[str] = set()
            for s, pos in positions.items():
                bar = by_date[s].get(d)
                if bar is None:
                    continue
                c = bar.close
                h_c = history_closes[s]
                if len(h_c) >= ma_period:
                    ma = sum(h_c[-ma_period:]) / float(ma_period)
                    # 1. Trailing peak stop
                    if c <= pos["highest_px"] * (1.0 - effective_trailing_stop):
                        to_sell.add(s)
                        if not any(a == "SELL" and sym == s for a, sym, _, _ in pending_orders):
                            pending_orders.append(("SELL", s, self.extra_execution_delay, "TRAILING_STOP"))
                    # 2. Moving average breakdown
                    elif c < ma:
                        to_sell.add(s)
                        if not any(a == "SELL" and sym == s for a, sym, _, _ in pending_orders):
                            pending_orders.append(("SELL", s, self.extra_execution_delay, "MA_BREAKDOWN"))

            # Check buy signals for available slots
            active_after_sells = len(positions) - len(to_sell)
            slots_open = effective_top_n - active_after_sells
            if slots_open > 0:
                candidates_ranked: List[Tuple[float, str]] = []
                for s in universe:
                    if s in positions and s not in to_sell:
                        continue
                    bar = by_date[s].get(d)
                    if bar is None:
                        continue
                    c = bar.close
                    h_c = history_closes[s]
                    min_req = max(ma_period, breakout_window, momentum_window)
                    if len(h_c) < min_req + 1:
                        continue
                    ma = sum(h_c[-ma_period:]) / float(ma_period)
                    if c < ma:
                        continue
                    # Donchian breakout (must strictly exceed peak of past breakout_window days before today)
                    past_closes = h_c[-breakout_window - 1 : -1]
                    if c > max(past_closes):
                        mom = (c / h_c[-momentum_window - 1]) - 1.0
                        candidates_ranked.append((mom, s))

                candidates_ranked.sort(reverse=True)
                for _, s in candidates_ranked[:slots_open]:
                    if not any(a == "BUY" and sym == s for a, sym, _, _ in pending_orders):
                        pending_orders.append(("BUY", s, self.extra_execution_delay, "DONCHIAN_BREAKOUT"))

        # Compute drawdowns for snapshots
        dds, _ = compute_drawdowns(equity_curve)
        for snap, dd in zip(snapshots, dds):
            snap.drawdown = dd

        metrics = evaluate_sector_performance(
            dates=dates,
            equity_curve=equity_curve,
            trades=trades,
            total_turnover_value=total_turnover_value,
            initial_capital=self.initial_capital,
            annual_cash_yield=self.annual_cash_yield,
        )

        return SectorSimulationResult(
            name="SectorMomentumBreakout",
            metrics=metrics,
            snapshots=snapshots,
            trades=trades,
            equity_curve=equity_curve,
            dates=dates,
        )
