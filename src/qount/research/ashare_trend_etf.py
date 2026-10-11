"""A-share ETF Trend Timing and Regime Rotation Research Kernel.

Research-only quantitative study for personal trading. Evaluates large-cycle trend
timing, whipsaw buffer filters, dual-asset regime rotation (CSI 300 vs CSI 500 vs Cash),
and cash-yield compounding on daily price bars (2013-2026).

STRICT RULES:
- research_only = True, orders_authorized = False
- Zero future leakage: signals decided at Close(T), executed at Open(T+1)
- Realistic friction: commission + slippage per side (ETFs have 0 stamp duty)
- Cash management: optional risk-free cash yield (money market fund proxy)
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclasses.dataclass(frozen=True)
class DailyBar:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    vol: float = 0.0
    amount: float = 0.0


@dataclasses.dataclass
class TradeRecord:
    trade_date: str
    symbol: str
    action: str  # 'BUY' or 'SELL'
    price: float
    units: float
    fee: float
    slippage: float
    cash_after: float
    nav_after: float
    reason: str


@dataclasses.dataclass
class DailySnapshot:
    trade_date: str
    cash: float
    units: Dict[str, float]
    prices: Dict[str, float]
    nav: float
    signal: Dict[str, float]  # target allocation fraction
    drawdown: float
    benchmark_nav: float


@dataclasses.dataclass
class PerformanceMetrics:
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe_ratio: float
    calmar_ratio: float
    volatility: float
    annual_turnover: float
    trade_count: int
    win_rate: float
    profit_loss_ratio: float
    year_returns: Dict[str, float]
    regime_returns: Dict[str, float]


@dataclasses.dataclass
class BacktestResult:
    model_name: str
    params: Dict[str, Any]
    snapshots: List[DailySnapshot]
    trades: List[TradeRecord]
    metrics: PerformanceMetrics


class MovingAverageEngine:
    """Computes moving averages strictly causally on historical series."""

    @staticmethod
    def sma(closes: List[float], period: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * len(closes)
        if period <= 0 or len(closes) < period:
            return out
        s = sum(closes[:period])
        out[period - 1] = s / period
        for i in range(period, len(closes)):
            s += closes[i] - closes[i - period]
            out[i] = s / period
        return out

    @staticmethod
    def ema(closes: List[float], period: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * len(closes)
        if period <= 0 or len(closes) < period:
            return out
        multiplier = 2.0 / (period + 1.0)
        # Seed with initial SMA
        init_val = sum(closes[:period]) / period
        out[period - 1] = init_val
        val = init_val
        for i in range(period, len(closes)):
            val = (closes[i] - val) * multiplier + val
            out[i] = val
        return out

    @staticmethod
    def donchian_high(highs: List[float], window: int) -> List[Optional[float]]:
        """Past window-day high strictly prior to t (i.e. highs[t-window : t])."""
        out: List[Optional[float]] = [None] * len(highs)
        if window <= 0 or len(highs) <= window:
            return out
        for t in range(window, len(highs)):
            out[t] = max(highs[t - window : t])
        return out

    @staticmethod
    def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[Optional[float]]:
        """Average True Range strictly causal with Wilder smoothing."""
        n = len(closes)
        out: List[Optional[float]] = [None] * n
        if period <= 0 or n <= period:
            return out
        tr: List[float] = [highs[0] - lows[0]]
        for t in range(1, n):
            h = highs[t]
            l = lows[t]
            c_prev = closes[t - 1]
            tr_val = max(h - l, abs(h - c_prev), abs(l - c_prev))
            tr.append(tr_val)

        init_atr = sum(tr[:period]) / period
        out[period - 1] = init_atr
        val = init_atr
        for t in range(period, n):
            val = (val * (period - 1) + tr[t]) / period
            out[t] = val
        return out


def compute_drawdowns(navs: List[float]) -> Tuple[List[float], float]:
    """Computes drawdown series and maximum drawdown."""
    dd: List[float] = []
    peak = navs[0] if navs else 1.0
    max_dd = 0.0
    for v in navs:
        if v > peak:
            peak = v
        d = (peak - v) / peak if peak > 0 else 0.0
        dd.append(d)
        if d > max_dd:
            max_dd = d
    return dd, max_dd


def evaluate_performance(
    snapshots: List[DailySnapshot],
    trades: List[TradeRecord],
    risk_free_rate: float = 0.02,
) -> PerformanceMetrics:
    """Evaluates comprehensive quantitative performance metrics."""
    if not snapshots or len(snapshots) < 2:
        return PerformanceMetrics(
            total_return=0.0,
            cagr=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            calmar_ratio=0.0,
            volatility=0.0,
            annual_turnover=0.0,
            trade_count=0,
            win_rate=0.0,
            profit_loss_ratio=0.0,
            year_returns={},
            regime_returns={},
        )

    navs = [s.nav for s in snapshots]
    init_nav = navs[0]
    final_nav = navs[-1]
    total_ret = (final_nav / init_nav) - 1.0
    num_days = len(snapshots)
    years = max(num_days / 252.0, 1.0 / 252.0)
    cagr = (final_nav / init_nav) ** (1.0 / years) - 1.0 if final_nav > 0 else -1.0

    _, max_dd = compute_drawdowns(navs)

    # Daily returns
    daily_rets = [(navs[i] / navs[i - 1]) - 1.0 for i in range(1, len(navs))]
    if daily_rets:
        mean_daily = sum(daily_rets) / len(daily_rets)
        var_daily = sum((r - mean_daily) ** 2 for r in daily_rets) / max(len(daily_rets) - 1, 1)
        vol_daily = math.sqrt(var_daily)
        ann_vol = vol_daily * math.sqrt(252.0)
        daily_rf = risk_free_rate / 252.0
        excess_mean = mean_daily - daily_rf
        sharpe = (excess_mean / vol_daily) * math.sqrt(252.0) if vol_daily > 1e-8 else 0.0
    else:
        ann_vol = 0.0
        sharpe = 0.0

    calmar = cagr / max_dd if max_dd > 1e-4 else 0.0

    # Turnover calculation
    # Sum of absolute sell trade amounts divided by average NAV per year
    total_sell_volume = sum(t.price * t.units for t in trades if t.action == "SELL")
    avg_nav = sum(navs) / len(navs)
    annual_turnover = (total_sell_volume / avg_nav) / years if avg_nav > 0 else 0.0

    # Win rate and Profit/Loss ratio for closed trades
    # Pair BUY and SELL for each symbol
    closed_pnl: List[float] = []
    symbol_positions: Dict[str, List[Tuple[float, float]]] = {}  # symbol -> [(units, price)]
    for t in trades:
        if t.action == "BUY":
            symbol_positions.setdefault(t.symbol, []).append((t.units, t.price))
        elif t.action == "SELL":
            units_to_sell = t.units
            cost_basis = 0.0
            total_cost_units = 0.0
            while units_to_sell > 1e-6 and symbol_positions.get(t.symbol):
                lot_u, lot_p = symbol_positions[t.symbol][0]
                matched_u = min(units_to_sell, lot_u)
                cost_basis += matched_u * lot_p
                total_cost_units += matched_u
                units_to_sell -= matched_u
                if lot_u - matched_u <= 1e-6:
                    symbol_positions[t.symbol].pop(0)
                else:
                    symbol_positions[t.symbol][0] = (lot_u - matched_u, lot_p)
            if total_cost_units > 0:
                pnl = (t.price * total_cost_units) - cost_basis - (t.fee + t.slippage)
                closed_pnl.append(pnl)

    wins = [p for p in closed_pnl if p > 0]
    losses = [p for p in closed_pnl if p < 0]
    win_rate = len(wins) / len(closed_pnl) if closed_pnl else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    pnl_ratio = avg_win / avg_loss if avg_loss > 1e-4 else (99.0 if avg_win > 0 else 0.0)

    # Annual breakdown
    by_year: Dict[str, List[DailySnapshot]] = {}
    for s in snapshots:
        yr = s.trade_date[:4]
        by_year.setdefault(yr, []).append(s)

    year_returns: Dict[str, float] = {}
    prev_close_nav = snapshots[0].nav
    for yr, y_snaps in sorted(by_year.items()):
        yr_final_nav = y_snaps[-1].nav
        year_returns[yr] = (yr_final_nav / prev_close_nav) - 1.0
        prev_close_nav = yr_final_nav

    # Key stress regime breakdown
    regimes = {
        "2015_crash": ("20150615", "20150826"),
        "2016_circuit": ("20160101", "20160129"),
        "2018_bear": ("20180129", "20181228"),
        "2019_2020_bull": ("20190102", "20201231"),
        "2021_2023_bear": ("20210218", "20231229"),
        "2024_09_surge": ("20240918", "20241008"),
    }
    regime_returns: Dict[str, float] = {}
    snap_by_date = {s.trade_date: s for s in snapshots}
    for r_name, (d_start, d_end) in regimes.items():
        avail_dates = [s.trade_date for s in snapshots if d_start <= s.trade_date <= d_end]
        if avail_dates:
            s_first = snap_by_date[avail_dates[0]]
            s_last = snap_by_date[avail_dates[-1]]
            regime_returns[r_name] = (s_last.nav / s_first.nav) - 1.0

    return PerformanceMetrics(
        total_return=total_ret,
        cagr=cagr,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        volatility=ann_vol,
        annual_turnover=annual_turnover,
        trade_count=len(trades),
        win_rate=win_rate,
        profit_loss_ratio=pnl_ratio,
        year_returns=year_returns,
        regime_returns=regime_returns,
    )


class TrendETFAssistantSimulator:
    """Rigorous causal backtest engine for A-share ETF trend timing strategies."""

    def __init__(
        self,
        commission_bps: float = 6.0,  # 0.06% broker commission (ETF no stamp duty)
        slippage_bps: float = 5.0,    # 0.05% slippage per side
        annual_cash_yield: float = 0.02, # 2.0% cash yield (money market fund/reverse repo)
        initial_capital: float = 1_000_000.0,
        extra_execution_delay: int = 0, # 0 means signal on T close, fill on T+1 open; 1 means fill on T+2 open
    ):
        self.commission_bps = commission_bps
        self.slippage_bps = slippage_bps
        self.annual_cash_yield = annual_cash_yield
        self.initial_capital = initial_capital
        self.extra_delay = extra_execution_delay

    def simulate_single_asset_trend(
        self,
        bars: List[DailyBar],
        symbol: str = "000300.SH",
        ma_period: int = 200,
        ma_type: str = "SMA",  # 'SMA' or 'EMA'
        band_pct: float = 0.015,  # 1.5% hysteresis buffer band
        confirm_days: int = 2,    # consecutive days required to confirm signal shift
    ) -> BacktestResult:
        """Simulates single-asset large-cycle trend timing with hysteresis buffer."""
        closes = [b.close for b in bars]
        if ma_type.upper() == "EMA":
            mas = MovingAverageEngine.ema(closes, ma_period)
        else:
            mas = MovingAverageEngine.sma(closes, ma_period)

        n = len(bars)
        # Compute target allocation signal on Close(t) strictly
        # state: 1.0 (Full), 0.0 (Cash)
        signals: List[float] = [0.0] * n
        current_state = 0.0
        pending_state = 0.0
        pending_count = 0

        for t in range(n):
            ma_val = mas[t]
            if ma_val is None:
                signals[t] = 0.0
                continue

            c = closes[t]
            upper_bound = ma_val * (1.0 + band_pct)
            lower_bound = ma_val * (1.0 - band_pct)

            # Determine candidate target state
            if c > upper_bound:
                cand_state = 1.0
            elif c < lower_bound:
                cand_state = 0.0
            else:
                # Inside buffer band: maintain current state
                cand_state = current_state

            # Confirmation filter
            if cand_state != current_state:
                if cand_state == pending_state:
                    pending_count += 1
                else:
                    pending_state = cand_state
                    pending_count = 1

                if pending_count >= confirm_days:
                    current_state = cand_state
                    pending_count = 0
            else:
                pending_count = 0
                pending_state = current_state

            signals[t] = current_state

        # Now simulate order execution on Open(t + 1 + extra_delay)
        cash = self.initial_capital
        units = 0.0
        trades: List[TradeRecord] = []
        snapshots: List[DailySnapshot] = []

        daily_cash_yield = (1.0 + self.annual_cash_yield) ** (1.0 / 252.0) - 1.0
        init_benchmark_price = bars[0].close

        for t in range(n):
            date_t = bars[t].trade_date
            open_t = bars[t].open
            close_t = bars[t].close

            # Check if there's a signal to execute on today's Open
            # The signal that governs today's open is decided on day: t - 1 - extra_delay
            signal_day = t - 1 - self.extra_delay
            if signal_day >= 0:
                target_alloc = signals[signal_day]
                # Current pre-trade portfolio equity at Open(t)
                est_nav = cash + units * open_t
                target_asset_value = est_nav * target_alloc
                curr_asset_value = units * open_t
                diff_value = target_asset_value - curr_asset_value

                # Rebalance if there is a significant shift (> 1% of NAV)
                if abs(diff_value) > est_nav * 0.01:
                    if diff_value > 0:  # BUY
                        # Cost: price * (1 + slip), fee = val * comm
                        buy_price = open_t * (1.0 + self.slippage_bps / 10000.0)
                        effective_price = buy_price * (1.0 + self.commission_bps / 10000.0)
                        units_to_buy = min(diff_value, cash) / effective_price
                        # In real execution, round to lots of 100 (for ETF)
                        # We use 100-lot rounding for fidelity
                        units_to_buy = math.floor(units_to_buy / 100.0) * 100.0
                        if units_to_buy > 0:
                            trade_val = units_to_buy * buy_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = units_to_buy * (buy_price - open_t)
                            cash -= (trade_val + fee)
                            units += units_to_buy
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=symbol,
                                    action="BUY",
                                    price=open_t,
                                    units=units_to_buy,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + units * open_t,
                                    reason=f"Trend breakout to {target_alloc:.1%}",
                                )
                            )
                    else:  # SELL
                        sell_price = open_t * (1.0 - self.slippage_bps / 10000.0)
                        units_to_sell = min(abs(diff_value) / open_t, units)
                        # Round to 100 shares
                        units_to_sell = math.ceil(units_to_sell / 100.0) * 100.0
                        units_to_sell = min(units_to_sell, units)
                        if units_to_sell > 0:
                            trade_val = units_to_sell * sell_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = units_to_sell * (open_t - sell_price)
                            cash += (trade_val - fee)
                            units -= units_to_sell
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=symbol,
                                    action="SELL",
                                    price=open_t,
                                    units=units_to_sell,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + units * open_t,
                                    reason=f"Trend breakdown to {target_alloc:.1%}",
                                )
                            )

            # End of day: cash earns daily interest (money market fund overnight)
            if cash > 0 and self.annual_cash_yield > 0:
                cash += cash * daily_cash_yield

            # Daily Close valuation
            eod_nav = cash + units * close_t
            bench_nav = self.initial_capital * (close_t / init_benchmark_price)
            snapshots.append(
                DailySnapshot(
                    trade_date=date_t,
                    cash=cash,
                    units={symbol: units},
                    prices={symbol: close_t},
                    nav=eod_nav,
                    signal={symbol: signals[t]},
                    drawdown=0.0,
                    benchmark_nav=bench_nav,
                )
            )

        # Post-process drawdowns
        navs = [s.nav for s in snapshots]
        dds, _ = compute_drawdowns(navs)
        for s, d in zip(snapshots, dds):
            s.drawdown = d

        metrics = evaluate_performance(snapshots, trades, risk_free_rate=self.annual_cash_yield)
        return BacktestResult(
            model_name=f"SingleTrend_{symbol}_{ma_type}{ma_period}_band{int(band_pct*1000)}bp",
            params={
                "symbol": symbol,
                "ma_period": ma_period,
                "ma_type": ma_type,
                "band_pct": band_pct,
                "confirm_days": confirm_days,
                "commission_bps": self.commission_bps,
                "slippage_bps": self.slippage_bps,
                "annual_cash_yield": self.annual_cash_yield,
                "extra_delay": self.extra_delay,
            },
            snapshots=snapshots,
            trades=trades,
            metrics=metrics,
        )

    def simulate_dual_asset_rotation(
        self,
        bars_a: List[DailyBar],
        bars_b: List[DailyBar],
        symbol_a: str = "000300.SH",  # CSI 300 (Large-cap Beta)
        symbol_b: str = "000905.SH",  # CSI 500 (Mid/Small-cap Beta)
        ma_period: int = 120,
        momentum_window: int = 20,    # Momentum lookback window to pick the stronger asset
        band_pct: float = 0.015,
        confirm_days: int = 2,
    ) -> BacktestResult:
        """Dual-asset trend + relative momentum rotation (A vs B vs Cash)."""
        # Align bars by date
        map_a = {b.trade_date: b for b in bars_a}
        map_b = {b.trade_date: b for b in bars_b}
        common_dates = sorted(set(map_a.keys()) & set(map_b.keys()))

        aligned_a = [map_a[d] for d in common_dates]
        aligned_b = [map_b[d] for d in common_dates]
        n = len(common_dates)

        closes_a = [b.close for b in aligned_a]
        closes_b = [b.close for b in aligned_b]

        mas_a = MovingAverageEngine.sma(closes_a, ma_period)
        mas_b = MovingAverageEngine.sma(closes_b, ma_period)

        # Calculate momentum: close(t) / close(t - momentum_window) - 1
        moms_a: List[Optional[float]] = [None] * n
        moms_b: List[Optional[float]] = [None] * n
        for t in range(momentum_window, n):
            moms_a[t] = closes_a[t] / closes_a[t - momentum_window] - 1.0
            moms_b[t] = closes_b[t] / closes_b[t - momentum_window] - 1.0

        # Signals: dict mapping symbol -> target fraction
        signals: List[Dict[str, float]] = []
        current_alloc: Dict[str, float] = {symbol_a: 0.0, symbol_b: 0.0}

        for t in range(n):
            ma_a = mas_a[t]
            ma_b = mas_b[t]
            mom_a = moms_a[t]
            mom_b = moms_b[t]

            if ma_a is None or ma_b is None or mom_a is None or mom_b is None:
                signals.append({symbol_a: 0.0, symbol_b: 0.0})
                continue

            # Trend conditions
            up_a = closes_a[t] > ma_a * (1.0 + band_pct)
            down_a = closes_a[t] < ma_a * (1.0 - band_pct)
            up_b = closes_b[t] > ma_b * (1.0 + band_pct)
            down_b = closes_b[t] < ma_b * (1.0 - band_pct)

            # Trend eligibility
            eligible_a = up_a or (not down_a and current_alloc[symbol_a] > 0)
            eligible_b = up_b or (not down_b and current_alloc[symbol_b] > 0)

            # Allocation decision
            if not eligible_a and not eligible_b:
                # Bear market: 100% Cash
                target = {symbol_a: 0.0, symbol_b: 0.0}
            elif eligible_a and not eligible_b:
                target = {symbol_a: 1.0, symbol_b: 0.0}
            elif not eligible_a and eligible_b:
                target = {symbol_a: 0.0, symbol_b: 1.0}
            else:
                # Both eligible: pick the one with higher momentum
                if mom_a >= mom_b:
                    target = {symbol_a: 1.0, symbol_b: 0.0}
                else:
                    target = {symbol_a: 0.0, symbol_b: 1.0}

            current_alloc = target
            signals.append(dict(target))

        # Execution simulation
        cash = self.initial_capital
        units: Dict[str, float] = {symbol_a: 0.0, symbol_b: 0.0}
        trades: List[TradeRecord] = []
        snapshots: List[DailySnapshot] = []

        daily_cash_yield = (1.0 + self.annual_cash_yield) ** (1.0 / 252.0) - 1.0
        init_benchmark_price = closes_a[0]

        for t in range(n):
            date_t = common_dates[t]
            bar_a = aligned_a[t]
            bar_b = aligned_b[t]
            opens = {symbol_a: bar_a.open, symbol_b: bar_b.open}
            closes = {symbol_a: bar_a.close, symbol_b: bar_b.close}

            signal_day = t - 1 - self.extra_delay
            if signal_day >= 0:
                target_allocs = signals[signal_day]
                # Pre-trade NAV at Open
                est_nav = cash + sum(units[s] * opens[s] for s in units)

                # Execute sells first to free cash
                for sym in [symbol_a, symbol_b]:
                    target_val = est_nav * target_allocs.get(sym, 0.0)
                    curr_val = units[sym] * opens[sym]
                    if curr_val > target_val + est_nav * 0.01:
                        sell_price = opens[sym] * (1.0 - self.slippage_bps / 10000.0)
                        u_to_sell = min((curr_val - target_val) / opens[sym], units[sym])
                        u_to_sell = math.ceil(u_to_sell / 100.0) * 100.0
                        u_to_sell = min(u_to_sell, units[sym])
                        if u_to_sell > 0:
                            trade_val = u_to_sell * sell_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = u_to_sell * (opens[sym] - sell_price)
                            cash += (trade_val - fee)
                            units[sym] -= u_to_sell
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=sym,
                                    action="SELL",
                                    price=opens[sym],
                                    units=u_to_sell,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + sum(units[s] * opens[s] for s in units),
                                    reason=f"Rotation sell to target {target_allocs.get(sym, 0.0):.1%}",
                                )
                            )

                # Execute buys
                for sym in [symbol_a, symbol_b]:
                    target_val = est_nav * target_allocs.get(sym, 0.0)
                    curr_val = units[sym] * opens[sym]
                    if target_val > curr_val + est_nav * 0.01:
                        buy_price = opens[sym] * (1.0 + self.slippage_bps / 10000.0)
                        effective_price = buy_price * (1.0 + self.commission_bps / 10000.0)
                        needed_val = target_val - curr_val
                        u_to_buy = min(needed_val, cash) / effective_price
                        u_to_buy = math.floor(u_to_buy / 100.0) * 100.0
                        if u_to_buy > 0:
                            trade_val = u_to_buy * buy_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = u_to_buy * (buy_price - opens[sym])
                            cash -= (trade_val + fee)
                            units[sym] += u_to_buy
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=sym,
                                    action="BUY",
                                    price=opens[sym],
                                    units=u_to_buy,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + sum(units[s] * opens[s] for s in units),
                                    reason=f"Rotation buy to target {target_allocs.get(sym, 0.0):.1%}",
                                )
                            )

            # Cash interest
            if cash > 0 and self.annual_cash_yield > 0:
                cash += cash * daily_cash_yield

            # EOD valuation
            eod_nav = cash + sum(units[s] * closes[s] for s in units)
            bench_nav = self.initial_capital * (closes[symbol_a] / init_benchmark_price)
            snapshots.append(
                DailySnapshot(
                    trade_date=date_t,
                    cash=cash,
                    units=dict(units),
                    prices=dict(closes),
                    nav=eod_nav,
                    signal=dict(signals[t]),
                    drawdown=0.0,
                    benchmark_nav=bench_nav,
                )
            )

        navs = [s.nav for s in snapshots]
        dds, _ = compute_drawdowns(navs)
        for s, d in zip(snapshots, dds):
            s.drawdown = d

        metrics = evaluate_performance(snapshots, trades, risk_free_rate=self.annual_cash_yield)
        return BacktestResult(
            model_name=f"DualRotation_{symbol_a}_{symbol_b}_MA{ma_period}_MOM{momentum_window}",
            params={
                "symbol_a": symbol_a,
                "symbol_b": symbol_b,
                "ma_period": ma_period,
                "momentum_window": momentum_window,
                "band_pct": band_pct,
                "confirm_days": confirm_days,
                "commission_bps": self.commission_bps,
                "slippage_bps": self.slippage_bps,
                "annual_cash_yield": self.annual_cash_yield,
                "extra_delay": self.extra_delay,
            },
            snapshots=snapshots,
            trades=trades,
            metrics=metrics,
        )

    def simulate_trend_dividend_shield(
        self,
        bars_trend: List[DailyBar],
        bars_shield: List[DailyBar],
        symbol_trend: str = "000300.SH",
        symbol_shield: str = "H00922.CSI",
        ma_period: int = 200,
        band_pct: float = 0.015,
        confirm_days: int = 2,
        shield_mode: str = "DIV_50_CASH_50",  # "DIV_100", "DIV_50_CASH_50", "CASH_100"
    ) -> BacktestResult:
        """Trend timing on main beta asset, rotating into dividend shield or cash during bears."""
        map_t = {b.trade_date: b for b in bars_trend}
        map_s = {b.trade_date: b for b in bars_shield}
        common_dates = sorted(set(map_t.keys()) & set(map_s.keys()))

        aligned_t = [map_t[d] for d in common_dates]
        aligned_s = [map_s[d] for d in common_dates]
        n = len(common_dates)

        closes_t = [b.close for b in aligned_t]
        mas_t = MovingAverageEngine.sma(closes_t, ma_period)

        signals: List[Dict[str, float]] = []
        current_state = 0.0  # 1.0 = Bull, 0.0 = Bear
        pending_state = 0.0
        pending_count = 0

        for t in range(n):
            ma_val = mas_t[t]
            if ma_val is None:
                signals.append({symbol_trend: 0.0, symbol_shield: 0.0})
                continue

            c = closes_t[t]
            upper = ma_val * (1.0 + band_pct)
            lower = ma_val * (1.0 - band_pct)

            if c > upper:
                cand = 1.0
            elif c < lower:
                cand = 0.0
            else:
                cand = current_state

            if cand != current_state:
                if cand == pending_state:
                    pending_count += 1
                else:
                    pending_state = cand
                    pending_count = 1

                if pending_count >= confirm_days:
                    current_state = cand
                    pending_count = 0
            else:
                pending_count = 0
                pending_state = current_state

            if current_state == 1.0:
                sig = {symbol_trend: 1.0, symbol_shield: 0.0}
            else:
                if shield_mode == "DIV_100":
                    sig = {symbol_trend: 0.0, symbol_shield: 1.0}
                elif shield_mode == "DIV_50_CASH_50":
                    sig = {symbol_trend: 0.0, symbol_shield: 0.5}
                else:
                    sig = {symbol_trend: 0.0, symbol_shield: 0.0}
            signals.append(sig)

        # Simulation
        cash = self.initial_capital
        units: Dict[str, float] = {symbol_trend: 0.0, symbol_shield: 0.0}
        trades: List[TradeRecord] = []
        snapshots: List[DailySnapshot] = []

        daily_cash_yield = (1.0 + self.annual_cash_yield) ** (1.0 / 252.0) - 1.0
        init_benchmark_price = closes_t[0]

        for t in range(n):
            date_t = common_dates[t]
            opens = {symbol_trend: aligned_t[t].open, symbol_shield: aligned_s[t].open}
            closes = {symbol_trend: aligned_t[t].close, symbol_shield: aligned_s[t].close}

            signal_day = t - 1 - self.extra_delay
            if signal_day >= 0:
                target_allocs = signals[signal_day]
                est_nav = cash + sum(units[s] * opens[s] for s in units)

                # Execute sells first
                for sym in [symbol_trend, symbol_shield]:
                    tgt_val = est_nav * target_allocs.get(sym, 0.0)
                    cur_val = units[sym] * opens[sym]
                    if cur_val > tgt_val + est_nav * 0.02:
                        sell_price = opens[sym] * (1.0 - self.slippage_bps / 10000.0)
                        u_to_sell = min((cur_val - tgt_val) / opens[sym], units[sym])
                        u_to_sell = math.ceil(u_to_sell / 100.0) * 100.0
                        u_to_sell = min(u_to_sell, units[sym])
                        if u_to_sell > 0:
                            trade_val = u_to_sell * sell_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = u_to_sell * (opens[sym] - sell_price)
                            cash += (trade_val - fee)
                            units[sym] -= u_to_sell
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=sym,
                                    action="SELL",
                                    price=opens[sym],
                                    units=u_to_sell,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + sum(units[s] * opens[s] for s in units),
                                    reason=f"Shield sell to target {target_allocs.get(sym, 0.0):.1%}",
                                )
                            )

                # Execute buys
                for sym in [symbol_trend, symbol_shield]:
                    tgt_val = est_nav * target_allocs.get(sym, 0.0)
                    cur_val = units[sym] * opens[sym]
                    if tgt_val > cur_val + est_nav * 0.02:
                        buy_price = opens[sym] * (1.0 + self.slippage_bps / 10000.0)
                        effective_price = buy_price * (1.0 + self.commission_bps / 10000.0)
                        needed_val = tgt_val - cur_val
                        u_to_buy = min(needed_val, cash) / effective_price
                        u_to_buy = math.floor(u_to_buy / 100.0) * 100.0
                        if u_to_buy > 0:
                            trade_val = u_to_buy * buy_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = u_to_buy * (buy_price - opens[sym])
                            cash -= (trade_val + fee)
                            units[sym] += u_to_buy
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=sym,
                                    action="BUY",
                                    price=opens[sym],
                                    units=u_to_buy,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + sum(units[s] * opens[s] for s in units),
                                    reason=f"Shield buy to target {target_allocs.get(sym, 0.0):.1%}",
                                )
                            )

            if cash > 0 and self.annual_cash_yield > 0:
                cash += cash * daily_cash_yield

            eod_nav = cash + sum(units[s] * closes[s] for s in units)
            bench_nav = self.initial_capital * (closes[symbol_trend] / init_benchmark_price)
            snapshots.append(
                DailySnapshot(
                    trade_date=date_t,
                    cash=cash,
                    units=dict(units),
                    prices=dict(closes),
                    nav=eod_nav,
                    signal=dict(signals[t]),
                    drawdown=0.0,
                    benchmark_nav=bench_nav,
                )
            )

        navs = [s.nav for s in snapshots]
        dds, _ = compute_drawdowns(navs)
        for s, d in zip(snapshots, dds):
            s.drawdown = d

        metrics = evaluate_performance(snapshots, trades, risk_free_rate=self.annual_cash_yield)
        return BacktestResult(
            model_name=f"TrendShield_{symbol_trend}_{symbol_shield}_MA{ma_period}_{shield_mode}",
            params={
                "symbol_trend": symbol_trend,
                "symbol_shield": symbol_shield,
                "ma_period": ma_period,
                "band_pct": band_pct,
                "confirm_days": confirm_days,
                "shield_mode": shield_mode,
                "commission_bps": self.commission_bps,
                "slippage_bps": self.slippage_bps,
                "annual_cash_yield": self.annual_cash_yield,
                "extra_delay": self.extra_delay,
            },
            snapshots=snapshots,
            trades=trades,
            metrics=metrics,
        )

    def simulate_asymmetric_trend(
        self,
        bars_trend: List[DailyBar],
        bars_shield: Optional[List[DailyBar]] = None,
        symbol_trend: str = "000300.SH",
        symbol_shield: str = "H00922.CSI",
        entry_donchian_window: int = 20,
        exit_ma_period: int = 200,
        band_pct: float = 0.015,
        trailing_stop_pct: float = 0.0,  # 0.0 means disabled; e.g. 0.10 means 10% trailing stop
        shield_mode: str = "DIV_50_CASH_50",  # "DIV_100", "DIV_50_CASH_50", "CASH_100"
    ) -> BacktestResult:
        """Asymmetric trend timing: Fast Donchian breakout entry + Slow MA defense exit."""
        if bars_shield is None:
            bars_shield = bars_trend
        map_t = {b.trade_date: b for b in bars_trend}
        map_s = {b.trade_date: b for b in bars_shield}
        common_dates = sorted(set(map_t.keys()) & set(map_s.keys()))

        aligned_t = [map_t[d] for d in common_dates]
        aligned_s = [map_s[d] for d in common_dates]
        n = len(common_dates)

        closes_t = [b.close for b in aligned_t]
        highs_t = [b.high for b in aligned_t]

        mas_exit = MovingAverageEngine.sma(closes_t, exit_ma_period)
        donch_highs = MovingAverageEngine.donchian_high(highs_t, entry_donchian_window)

        signals: List[Dict[str, float]] = []
        current_state = 0.0
        peak_close_since_entry = 0.0

        for t in range(n):
            c = closes_t[t]
            ma_exit = mas_exit[t]
            d_high = donch_highs[t]

            if ma_exit is None or d_high is None:
                signals.append({symbol_trend: 0.0, symbol_shield: 0.0})
                continue

            if current_state == 0.0:
                # Fast Entry: Price breaks above Donchian past high OR above exit MA
                if c >= d_high or c > ma_exit * (1.0 + band_pct):
                    current_state = 1.0
                    peak_close_since_entry = c
            else:
                if c > peak_close_since_entry:
                    peak_close_since_entry = c

                # Slow Exit: Price falls below exit MA band OR triggers trailing stop
                below_ma = c < ma_exit * (1.0 - band_pct)
                hit_trail = False
                if trailing_stop_pct > 0.0 and peak_close_since_entry > 0:
                    dd_from_peak = (peak_close_since_entry - c) / peak_close_since_entry
                    if dd_from_peak >= trailing_stop_pct:
                        hit_trail = True

                if below_ma or hit_trail:
                    current_state = 0.0
                    peak_close_since_entry = 0.0

            if current_state == 1.0:
                sig = {symbol_trend: 1.0, symbol_shield: 0.0}
            else:
                if shield_mode == "DIV_100":
                    sig = {symbol_trend: 0.0, symbol_shield: 1.0}
                elif shield_mode == "DIV_50_CASH_50":
                    sig = {symbol_trend: 0.0, symbol_shield: 0.5}
                else:
                    sig = {symbol_trend: 0.0, symbol_shield: 0.0}
            signals.append(sig)

        return self._simulate_portfolio_execution(
            common_dates, aligned_t, aligned_s, symbol_trend, symbol_shield, signals,
            model_name=f"Asymmetric_Donch{entry_donchian_window}_MA{exit_ma_period}_{shield_mode}",
            params={
                "entry_donchian_window": entry_donchian_window,
                "exit_ma_period": exit_ma_period,
                "band_pct": band_pct,
                "trailing_stop_pct": trailing_stop_pct,
                "shield_mode": shield_mode,
            }
        )

    def simulate_atr_dynamic_band_trend(
        self,
        bars_trend: List[DailyBar],
        bars_shield: Optional[List[DailyBar]] = None,
        symbol_trend: str = "000300.SH",
        symbol_shield: str = "H00922.CSI",
        ma_period: int = 200,
        atr_period: int = 14,
        atr_multiplier: float = 1.5,
        confirm_days: int = 2,
        shield_mode: str = "DIV_50_CASH_50",
    ) -> BacktestResult:
        """Trend timing using adaptive ATR volatility buffer band."""
        if bars_shield is None:
            bars_shield = bars_trend
        map_t = {b.trade_date: b for b in bars_trend}
        map_s = {b.trade_date: b for b in bars_shield}
        common_dates = sorted(set(map_t.keys()) & set(map_s.keys()))

        aligned_t = [map_t[d] for d in common_dates]
        aligned_s = [map_s[d] for d in common_dates]
        n = len(common_dates)

        closes_t = [b.close for b in aligned_t]
        highs_t = [b.high for b in aligned_t]
        lows_t = [b.low for b in aligned_t]

        mas = MovingAverageEngine.sma(closes_t, ma_period)
        atrs = MovingAverageEngine.atr(highs_t, lows_t, closes_t, atr_period)

        signals: List[Dict[str, float]] = []
        current_state = 0.0
        pending_state = 0.0
        pending_count = 0

        for t in range(n):
            ma_val = mas[t]
            atr_val = atrs[t]
            if ma_val is None or atr_val is None:
                signals.append({symbol_trend: 0.0, symbol_shield: 0.0})
                continue

            c = closes_t[t]
            band_width = atr_multiplier * atr_val
            upper = ma_val + band_width
            lower = ma_val - band_width

            if c > upper:
                cand = 1.0
            elif c < lower:
                cand = 0.0
            else:
                cand = current_state

            if cand != current_state:
                if cand == pending_state:
                    pending_count += 1
                else:
                    pending_state = cand
                    pending_count = 1
                if pending_count >= confirm_days:
                    current_state = cand
                    pending_count = 0
            else:
                pending_count = 0
                pending_state = current_state

            if current_state == 1.0:
                sig = {symbol_trend: 1.0, symbol_shield: 0.0}
            else:
                if shield_mode == "DIV_100":
                    sig = {symbol_trend: 0.0, symbol_shield: 1.0}
                elif shield_mode == "DIV_50_CASH_50":
                    sig = {symbol_trend: 0.0, symbol_shield: 0.5}
                else:
                    sig = {symbol_trend: 0.0, symbol_shield: 0.0}
            signals.append(sig)

        return self._simulate_portfolio_execution(
            common_dates, aligned_t, aligned_s, symbol_trend, symbol_shield, signals,
            model_name=f"ATRBand_MA{ma_period}_k{atr_multiplier}_{shield_mode}",
            params={
                "ma_period": ma_period,
                "atr_period": atr_period,
                "atr_multiplier": atr_multiplier,
                "confirm_days": confirm_days,
                "shield_mode": shield_mode,
            }
        )

    def simulate_core_satellite_portfolio(
        self,
        bars_core_trend: List[DailyBar],
        bars_core_shield: List[DailyBar],
        bars_satellite: List[DailyBar],
        symbol_core_trend: str = "000300.SH",
        symbol_core_shield: str = "H00922.CSI",
        symbol_satellite: str = "513100.SH",
        core_weight: float = 0.80,
        satellite_weight: float = 0.20,
        core_ma_period: int = 200,
        satellite_ma_period: int = 120,
        core_shield_mode: str = "DIV_50_CASH_50",
    ) -> BacktestResult:
        """Composite Core-Satellite: 80% A-share Core (Trend+Shield) + 20% Overseas/Growth Satellite."""
        map_ct = {b.trade_date: b for b in bars_core_trend}
        map_cs = {b.trade_date: b for b in bars_core_shield}
        map_sat = {b.trade_date: b for b in bars_satellite}
        common_dates = sorted(set(map_ct.keys()) & set(map_cs.keys()) & set(map_sat.keys()))

        aligned_ct = [map_ct[d] for d in common_dates]
        aligned_cs = [map_cs[d] for d in common_dates]
        aligned_sat = [map_sat[d] for d in common_dates]
        n = len(common_dates)

        closes_ct = [b.close for b in aligned_ct]
        closes_sat = [b.close for b in aligned_sat]

        mas_core = MovingAverageEngine.sma(closes_ct, core_ma_period)
        mas_sat = MovingAverageEngine.sma(closes_sat, satellite_ma_period)

        # Generate signals for each sleeve
        signals: List[Dict[str, float]] = []
        state_core = 0.0
        state_sat = 0.0

        for t in range(n):
            ma_c = mas_core[t]
            ma_s = mas_sat[t]
            if ma_c is None or ma_s is None:
                signals.append({symbol_core_trend: 0.0, symbol_core_shield: 0.0, symbol_satellite: 0.0})
                continue

            # Core state
            c_ct = closes_ct[t]
            if c_ct > ma_c * 1.015:
                state_core = 1.0
            elif c_ct < ma_c * 0.985:
                state_core = 0.0

            # Satellite state (trend timing on satellite)
            c_sat = closes_sat[t]
            if c_sat > ma_s * 1.015:
                state_sat = 1.0
            elif c_sat < ma_s * 0.985:
                state_sat = 0.0

            # Combine sleeves
            sig: Dict[str, float] = {}
            if state_core == 1.0:
                sig[symbol_core_trend] = core_weight * 1.0
                sig[symbol_core_shield] = 0.0
            else:
                if core_shield_mode == "DIV_100":
                    sig[symbol_core_trend] = 0.0
                    sig[symbol_core_shield] = core_weight * 1.0
                elif core_shield_mode == "DIV_50_CASH_50":
                    sig[symbol_core_trend] = 0.0
                    sig[symbol_core_shield] = core_weight * 0.5
                else:
                    sig[symbol_core_trend] = 0.0
                    sig[symbol_core_shield] = 0.0

            if state_sat == 1.0:
                sig[symbol_satellite] = satellite_weight * 1.0
            else:
                sig[symbol_satellite] = 0.0

            signals.append(sig)

        # Portfolio simulation across 3 assets
        symbols = [symbol_core_trend, symbol_core_shield, symbol_satellite]
        bars_by_sym = {symbol_core_trend: aligned_ct, symbol_core_shield: aligned_cs, symbol_satellite: aligned_sat}

        cash = self.initial_capital
        units: Dict[str, float] = {s: 0.0 for s in symbols}
        trades: List[TradeRecord] = []
        snapshots: List[DailySnapshot] = []

        daily_cash_yield = (1.0 + self.annual_cash_yield) ** (1.0 / 252.0) - 1.0
        init_benchmark_price = closes_ct[0]

        for t in range(n):
            date_t = common_dates[t]
            opens = {s: bars_by_sym[s][t].open for s in symbols}
            closes = {s: bars_by_sym[s][t].close for s in symbols}

            signal_day = t - 1 - self.extra_delay
            if signal_day >= 0:
                target_allocs = signals[signal_day]
                est_nav = cash + sum(units[s] * opens[s] for s in symbols)

                # Sells first
                for sym in symbols:
                    tgt_val = est_nav * target_allocs.get(sym, 0.0)
                    cur_val = units[sym] * opens[sym]
                    if cur_val > tgt_val + est_nav * 0.015:
                        sell_price = opens[sym] * (1.0 - self.slippage_bps / 10000.0)
                        u_to_sell = min((cur_val - tgt_val) / opens[sym], units[sym])
                        u_to_sell = math.ceil(u_to_sell / 100.0) * 100.0
                        u_to_sell = min(u_to_sell, units[sym])
                        if u_to_sell > 0:
                            trade_val = u_to_sell * sell_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = u_to_sell * (opens[sym] - sell_price)
                            cash += (trade_val - fee)
                            units[sym] -= u_to_sell
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=sym,
                                    action="SELL",
                                    price=opens[sym],
                                    units=u_to_sell,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + sum(units[s] * opens[s] for s in symbols),
                                    reason=f"Core-Sat sell to {target_allocs.get(sym, 0.0):.1%}",
                                )
                            )

                # Buys
                for sym in symbols:
                    tgt_val = est_nav * target_allocs.get(sym, 0.0)
                    cur_val = units[sym] * opens[sym]
                    if tgt_val > cur_val + est_nav * 0.015:
                        buy_price = opens[sym] * (1.0 + self.slippage_bps / 10000.0)
                        effective_price = buy_price * (1.0 + self.commission_bps / 10000.0)
                        needed_val = tgt_val - cur_val
                        u_to_buy = min(needed_val, cash) / effective_price
                        u_to_buy = math.floor(u_to_buy / 100.0) * 100.0
                        if u_to_buy > 0:
                            trade_val = u_to_buy * buy_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = u_to_buy * (buy_price - opens[sym])
                            cash -= (trade_val + fee)
                            units[sym] += u_to_buy
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=sym,
                                    action="BUY",
                                    price=opens[sym],
                                    units=u_to_buy,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + sum(units[s] * opens[s] for s in symbols),
                                    reason=f"Core-Sat buy to {target_allocs.get(sym, 0.0):.1%}",
                                )
                            )

            if cash > 0 and self.annual_cash_yield > 0:
                cash += cash * daily_cash_yield

            eod_nav = cash + sum(units[s] * closes[s] for s in symbols)
            bench_nav = self.initial_capital * (closes[symbol_core_trend] / init_benchmark_price)
            snapshots.append(
                DailySnapshot(
                    trade_date=date_t,
                    cash=cash,
                    units=dict(units),
                    prices=dict(closes),
                    nav=eod_nav,
                    signal=dict(signals[t]),
                    drawdown=0.0,
                    benchmark_nav=bench_nav,
                )
            )

        navs = [s.nav for s in snapshots]
        dds, _ = compute_drawdowns(navs)
        for s, d in zip(snapshots, dds):
            s.drawdown = d

        metrics = evaluate_performance(snapshots, trades, risk_free_rate=self.annual_cash_yield)
        return BacktestResult(
            model_name=f"CoreSat_{int(core_weight*100)}_{int(satellite_weight*100)}_{symbol_satellite}",
            params={
                "core_trend": symbol_core_trend,
                "core_shield": symbol_core_shield,
                "satellite": symbol_satellite,
                "core_weight": core_weight,
                "satellite_weight": satellite_weight,
                "core_ma": core_ma_period,
                "satellite_ma": satellite_ma_period,
                "core_shield_mode": core_shield_mode,
            },
            snapshots=snapshots,
            trades=trades,
            metrics=metrics,
        )

    def _simulate_portfolio_execution(
        self,
        common_dates: List[str],
        aligned_t: List[DailyBar],
        aligned_s: List[DailyBar],
        symbol_trend: str,
        symbol_shield: str,
        signals: List[Dict[str, float]],
        model_name: str,
        params: Dict[str, Any],
    ) -> BacktestResult:
        """Helper to simulate portfolio execution across two assets."""
        n = len(common_dates)
        cash = self.initial_capital
        units: Dict[str, float] = {symbol_trend: 0.0, symbol_shield: 0.0}
        trades: List[TradeRecord] = []
        snapshots: List[DailySnapshot] = []

        daily_cash_yield = (1.0 + self.annual_cash_yield) ** (1.0 / 252.0) - 1.0
        init_benchmark_price = aligned_t[0].close

        for t in range(n):
            date_t = common_dates[t]
            opens = {symbol_trend: aligned_t[t].open, symbol_shield: aligned_s[t].open}
            closes = {symbol_trend: aligned_t[t].close, symbol_shield: aligned_s[t].close}

            signal_day = t - 1 - self.extra_delay
            if signal_day >= 0:
                target_allocs = signals[signal_day]
                est_nav = cash + sum(units[s] * opens[s] for s in units)

                # Sells first
                for sym in [symbol_trend, symbol_shield]:
                    tgt_val = est_nav * target_allocs.get(sym, 0.0)
                    cur_val = units[sym] * opens[sym]
                    if cur_val > tgt_val + est_nav * 0.02:
                        sell_price = opens[sym] * (1.0 - self.slippage_bps / 10000.0)
                        u_to_sell = min((cur_val - tgt_val) / opens[sym], units[sym])
                        u_to_sell = math.ceil(u_to_sell / 100.0) * 100.0
                        u_to_sell = min(u_to_sell, units[sym])
                        if u_to_sell > 0:
                            trade_val = u_to_sell * sell_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = u_to_sell * (opens[sym] - sell_price)
                            cash += (trade_val - fee)
                            units[sym] -= u_to_sell
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=sym,
                                    action="SELL",
                                    price=opens[sym],
                                    units=u_to_sell,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + sum(units[s] * opens[s] for s in units),
                                    reason=f"Sell to target {target_allocs.get(sym, 0.0):.1%}",
                                )
                            )

                # Buys
                for sym in [symbol_trend, symbol_shield]:
                    tgt_val = est_nav * target_allocs.get(sym, 0.0)
                    cur_val = units[sym] * opens[sym]
                    if tgt_val > cur_val + est_nav * 0.02:
                        buy_price = opens[sym] * (1.0 + self.slippage_bps / 10000.0)
                        effective_price = buy_price * (1.0 + self.commission_bps / 10000.0)
                        needed_val = tgt_val - cur_val
                        u_to_buy = min(needed_val, cash) / effective_price
                        u_to_buy = math.floor(u_to_buy / 100.0) * 100.0
                        if u_to_buy > 0:
                            trade_val = u_to_buy * buy_price
                            fee = trade_val * (self.commission_bps / 10000.0)
                            slip = u_to_buy * (buy_price - opens[sym])
                            cash -= (trade_val + fee)
                            units[sym] += u_to_buy
                            trades.append(
                                TradeRecord(
                                    trade_date=date_t,
                                    symbol=sym,
                                    action="BUY",
                                    price=opens[sym],
                                    units=u_to_buy,
                                    fee=fee,
                                    slippage=slip,
                                    cash_after=cash,
                                    nav_after=cash + sum(units[s] * opens[s] for s in units),
                                    reason=f"Buy to target {target_allocs.get(sym, 0.0):.1%}",
                                )
                            )

            if cash > 0 and self.annual_cash_yield > 0:
                cash += cash * daily_cash_yield

            eod_nav = cash + sum(units[s] * closes[s] for s in units)
            bench_nav = self.initial_capital * (closes[symbol_trend] / init_benchmark_price)
            snapshots.append(
                DailySnapshot(
                    trade_date=date_t,
                    cash=cash,
                    units=dict(units),
                    prices=dict(closes),
                    nav=eod_nav,
                    signal=dict(signals[t]),
                    drawdown=0.0,
                    benchmark_nav=bench_nav,
                )
            )

        navs = [s.nav for s in snapshots]
        dds, _ = compute_drawdowns(navs)
        for s, d in zip(snapshots, dds):
            s.drawdown = d

        metrics = evaluate_performance(snapshots, trades, risk_free_rate=self.annual_cash_yield)
        full_params = {
            "symbol_trend": symbol_trend,
            "symbol_shield": symbol_shield,
            "commission_bps": self.commission_bps,
            "slippage_bps": self.slippage_bps,
            "annual_cash_yield": self.annual_cash_yield,
            "extra_delay": self.extra_delay,
            **params,
        }
        return BacktestResult(
            model_name=model_name,
            params=full_params,
            snapshots=snapshots,
            trades=trades,
            metrics=metrics,
        )
