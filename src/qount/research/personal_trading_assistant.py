"""Personal Trading Assistant Minimal Loop & Core ETF Baseline Kernel.

Implements Phase S2 (R04) of docs/research-repair-and-consolidation-plan-2026-10.md.
Provides causal baseline comparisons (Buy&Hold vs Trend vs Cash) on 1-3 core real ETFs
with strictly audited listing dates, zero future leakage, realistic fees, corporate action
split/dividend adjustments, unified confirmation state machine, and daily after-close review.

STRICT BOUNDARIES:
- research_only = True, orders_authorized = False, promotion_evidence = False.
- Zero future leakage: signals decided at Close(T), executed at Open(T+1).
- Real listing constraints: no simulated fills prior to official listing date.
- Corporate action continuity: 1:5 split (2022-01-13) for 513100.SH handled in both
  portfolio share ledger and backward-adjusted indicator prices.
- Unified state machine: backtest and daily evaluation share identical hysteresis & confirmation rules.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclasses.dataclass(frozen=True)
class CorporateAction:
    ex_date: str                 # YYYYMMDD (e.g. 20220113)
    split_ratio: float = 1.0     # e.g. 5.0 means 1 share becomes 5 shares
    cash_dividend: float = 0.0   # cash dividend per share in CNY
    note: str = ""


@dataclasses.dataclass(frozen=True)
class ETFAssetMeta:
    symbol: str
    name: str
    tracking_target: str
    listing_date: str  # YYYYMMDD
    is_index_proxy: bool
    annual_expense_ratio: float  # management + custodian fee (e.g. 0.006)
    commission_bps: float = 6.0  # 0.06% broker fee (ETF exempt from stamp duty)
    slippage_bps: float = 5.0    # 0.05% slippage per side
    corporate_actions: Tuple[CorporateAction, ...] = dataclasses.field(default_factory=tuple)


# Authoritative metadata for the core 1-3 retail assets
CORE_ETF_UNIVERSE: Dict[str, ETFAssetMeta] = {
    "510300.SH": ETFAssetMeta(
        symbol="510300.SH",
        name="华泰柏瑞沪深300ETF",
        tracking_target="沪深300指数 (000300.SH)",
        listing_date="20120528",
        is_index_proxy=False,
        annual_expense_ratio=0.006,
        commission_bps=6.0,
        slippage_bps=5.0,
    ),
    "513100.SH": ETFAssetMeta(
        symbol="513100.SH",
        name="国泰纳斯达克100ETF(QDII)",
        tracking_target="纳斯达克100指数",
        listing_date="20130515",
        is_index_proxy=False,
        annual_expense_ratio=0.008,
        commission_bps=6.0,
        slippage_bps=5.0,
        corporate_actions=(
            CorporateAction(
                ex_date="20220113",
                split_ratio=5.0,
                note="国泰纳斯达克100ETF 1:5拆分 (2022-01-13除权除息，国泰基金2023年中报第22页披露)",
            ),
        ),
    ),
    "159915.SZ": ETFAssetMeta(
        symbol="159915.SZ",
        name="易方达创业板ETF",
        tracking_target="创业板指数 (399006.SZ)",
        listing_date="20111209",
        is_index_proxy=False,
        annual_expense_ratio=0.002,
        commission_bps=6.0,
        slippage_bps=5.0,
    ),
    # Index proxy baseline for long-term structural reference
    "000300.SH": ETFAssetMeta(
        symbol="000300.SH",
        name="沪深300价格指数(基准代理)",
        tracking_target="沪深300指数",
        listing_date="20050408",
        is_index_proxy=True,
        annual_expense_ratio=0.0,
        commission_bps=6.0,
        slippage_bps=5.0,
    ),
}


@dataclasses.dataclass(frozen=True)
class AssistantBar:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    vol: float = 0.0
    amount: float = 0.0
    is_complete: bool = True


@dataclasses.dataclass
class BaselineMetrics:
    model_name: str
    symbol: str
    start_date: str
    end_date: str
    trading_days: int
    initial_equity: float
    terminal_equity: float
    total_return_pct: float
    cagr_pct: float             # 252 trading days annualized convention (252折年)
    max_drawdown_pct: float
    calmar_ratio: Optional[float]
    exposure_pct: float         # In-market days / total trading days
    trade_count: int
    annual_turnover: float      # Sell-only turnover / average nav / years (preserved alias)
    win_rate_pct: Optional[float]
    calendar_years: float = 0.0
    cagr_252_pct: float = 0.0
    cagr_calendar_pct: float = 0.0
    annual_turnover_two_sided: float = 0.0


@dataclasses.dataclass
class DailyAssistantStatus:
    as_of_date: str
    symbol: str
    name: str
    close_price: float
    ma_trend_val: float
    ma_period: int
    band_pct: float
    distance_to_ma_pct: float
    regime: str  # "BULLISH_HOLD" | "BEARISH_CASH" | "BULLISH_CONFIRMING" | "BEARISH_CONFIRMING" | "TRANSITION_DEADBAND"
    target_weight: float  # strictly 1.0 or 0.0 (never 0.5)
    reason: str
    confirm_count: int = 0
    executed_holding: float = 0.0
    safety_boundary: Dict[str, bool] = dataclasses.field(
        default_factory=lambda: {
            "research_only": True,
            "orders_authorized": False,
            "promotion_evidence": False,
        }
    )
    data_qualification_status: str = "QUALIFIED"  # "QUALIFIED" | "STALE_DATA" | "INCOMPLETE_BAR" | "BENCHMARK_PROXY_ONLY" | "MISSING_INDEPENDENT_SERIES"
    is_actionable: bool = True
    dividend_qualification: str = "QUALIFIED_OR_NOT_APPLICABLE"


@dataclasses.dataclass
class StateMachineState:
    current_target: float = 0.0   # 0.0 (Cash) or 1.0 (Invested) decided by rule
    executed_state: float = 0.0   # 0.0 or 1.0 currently filled in portfolio
    pending_target: float = 0.0   # Candidate target awaiting confirmation
    confirm_count: int = 0        # Number of consecutive bars pending target has persisted


class TrendTimingStateMachine:
    """Unified hysteresis and confirmation state machine shared by backtest and daily evaluation."""

    def __init__(self, ma_period: int = 120, band_pct: float = 0.015, confirm_days: int = 2):
        self.ma_period = ma_period
        self.band_pct = band_pct
        self.confirm_days = confirm_days

    def update_at_close(
        self,
        state: StateMachineState,
        close_price: float,
        ma_val: Optional[float],
    ) -> StateMachineState:
        if ma_val is None:
            return state

        upper = ma_val * (1.0 + self.band_pct)
        lower = ma_val * (1.0 - self.band_pct)

        if close_price > upper:
            cand = 1.0
        elif close_price < lower:
            cand = 0.0
        else:
            cand = state.current_target  # In deadband, maintain current target (0.0 or 1.0)

        current_target = state.current_target
        pending_target = state.pending_target
        confirm_count = state.confirm_count

        if cand != current_target:
            if cand == pending_target:
                confirm_count += 1
            else:
                pending_target = cand
                confirm_count = 1

            if confirm_count >= self.confirm_days:
                current_target = pending_target
                confirm_count = 0
        else:
            pending_target = current_target
            confirm_count = 0

        return StateMachineState(
            current_target=current_target,
            executed_state=state.executed_state,
            pending_target=pending_target,
            confirm_count=confirm_count,
        )


def _date_key(d: str) -> Any:
    cleaned = d.replace("-", "").strip()
    return int(cleaned) if cleaned.isdigit() else d


def validate_bars(bars: List[AssistantBar], meta: Optional[ETFAssetMeta] = None) -> None:
    """Strictly validates input bars to prevent duplicates, inverted prices, and non-chronological order."""
    if not bars:
        raise ValueError("Bars cannot be empty")
    seen_dates = set()
    for i, b in enumerate(bars):
        if b.trade_date in seen_dates:
            raise ValueError(f"Duplicate trade date detected: {b.trade_date}")
        seen_dates.add(b.trade_date)
        if i > 0 and _date_key(b.trade_date) <= _date_key(bars[i - 1].trade_date):
            raise ValueError(
                f"Non-chronological trade dates: {bars[i - 1].trade_date} followed by {b.trade_date}"
            )
        if not (math.isfinite(b.open) and math.isfinite(b.high) and math.isfinite(b.low) and math.isfinite(b.close)):
            raise ValueError(f"Non-finite price in bar {b.trade_date}")
        if b.open <= 0 or b.high <= 0 or b.low <= 0 or b.close <= 0:
            raise ValueError(f"Non-positive price in bar {b.trade_date}")
        if not (b.low <= b.open <= b.high and b.low <= b.close <= b.high):
            raise ValueError(
                f"Inconsistent OHLC prices in bar {b.trade_date}: low={b.low}, open={b.open}, high={b.high}, close={b.close}"
            )


def compute_adjusted_closes(bars: List[AssistantBar], meta: ETFAssetMeta) -> List[float]:
    """Computes backward-adjusted close prices for indicators (前复权) to eliminate corporate action jumps."""
    raw_closes = [b.close for b in bars]
    if not meta.corporate_actions:
        return raw_closes

    adj_closes = list(raw_closes)
    for ca in meta.corporate_actions:
        if ca.split_ratio != 1.0:
            for i, b in enumerate(bars):
                if b.trade_date < ca.ex_date:
                    adj_closes[i] /= ca.split_ratio
    return adj_closes


def _calculate_calendar_years(start_date: str, end_date: str, fallback_years: float) -> float:
    try:
        s = start_date.replace("-", "").strip()[:8]
        e = end_date.replace("-", "").strip()[:8]
        days = (datetime.strptime(e, "%Y%m%d") - datetime.strptime(s, "%Y%m%d")).days
        return days / 365.25 if days > 0 else fallback_years
    except Exception:
        return fallback_years


class PersonalTradingAssistantKernel:
    """Causal, friction-adjusted simulator and daily evaluation engine."""

    def __init__(
        self,
        cash_apr: float = 0.02,
        initial_capital: float = 1_000_000.0,
    ):
        self.cash_apr = cash_apr
        self.initial_capital = initial_capital

    @staticmethod
    def compute_sma(series: List[float], period: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * len(series)
        if period <= 0 or len(series) < period:
            return out
        s = sum(series[:period])
        out[period - 1] = s / period
        for i in range(period, len(series)):
            s += series[i] - series[i - period]
            out[i] = s / period
        return out

    def simulate_buy_and_hold(
        self,
        bars: List[AssistantBar],
        meta: ETFAssetMeta,
        return_trades: bool = False,
    ) -> Tuple[List[float], BaselineMetrics] | Tuple[List[float], BaselineMetrics, List[Dict[str, Any]]]:
        """Strict buy & hold baseline executed on day 1 open with corporate action continuity."""
        validate_bars(bars, meta)

        # Filter by official listing date
        valid_bars = [b for b in bars if b.trade_date >= meta.listing_date]
        if not valid_bars:
            raise ValueError(f"No bars after listing date {meta.listing_date} for {meta.symbol}")

        comm = meta.commission_bps / 10000.0
        slip = meta.slippage_bps / 10000.0
        cash = self.initial_capital
        entry_px = valid_bars[0].open * (1.0 + slip)
        shares = cash / (entry_px * (1.0 + comm))
        cost = shares * entry_px * (1.0 + comm)
        cash -= cost

        trades: List[Dict[str, Any]] = [
            {
                "action": "BUY",
                "date": valid_bars[0].trade_date,
                "price": entry_px,
                "shares": shares,
                "cost": cost,
                "commission": shares * entry_px * comm,
                "cash_rem": cash,
            }
        ]

        nav_series: List[float] = []
        peak = 0.0
        max_dd = 0.0

        for i, b in enumerate(valid_bars):
            # Apply corporate actions (splits and dividends) between previous and current bar
            if i > 0 and meta.corporate_actions:
                prev_date = valid_bars[i - 1].trade_date
                curr_date = b.trade_date
                for ca in meta.corporate_actions:
                    if prev_date < ca.ex_date <= curr_date:
                        if ca.split_ratio != 1.0 and shares > 0.0:
                            old_shares = shares
                            shares *= ca.split_ratio
                            trades.append({
                                "action": "CORPORATE_ACTION_SPLIT",
                                "date": ca.ex_date,
                                "split_ratio": ca.split_ratio,
                                "shares_before": old_shares,
                                "shares_after": shares,
                                "note": ca.note,
                            })
                        if ca.cash_dividend > 0.0 and shares > 0.0:
                            div_amt = shares * ca.cash_dividend
                            cash += div_amt
                            trades.append({
                                "action": "CORPORATE_ACTION_DIVIDEND",
                                "date": ca.ex_date,
                                "cash_dividend": ca.cash_dividend,
                                "dividend_received": div_amt,
                                "cash_rem": cash,
                            })

            eq = cash + shares * b.close
            nav_series.append(eq)
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        n_days = len(valid_bars)
        years_252 = n_days / 252.0
        calendar_years = _calculate_calendar_years(valid_bars[0].trade_date, valid_bars[-1].trade_date, years_252)

        final_eq = nav_series[-1]
        cagr_252 = ((final_eq / self.initial_capital) ** (1.0 / years_252) - 1.0) if years_252 > 0 else 0.0
        cagr_cal = ((final_eq / self.initial_capital) ** (1.0 / calendar_years) - 1.0) if calendar_years > 0 else 0.0
        calmar = cagr_252 / max_dd if max_dd > 1e-4 else 0.0

        metrics = BaselineMetrics(
            model_name="Buy_and_Hold",
            symbol=meta.symbol,
            start_date=valid_bars[0].trade_date,
            end_date=valid_bars[-1].trade_date,
            trading_days=n_days,
            calendar_years=calendar_years,
            initial_equity=self.initial_capital,
            terminal_equity=final_eq,
            total_return_pct=(final_eq / self.initial_capital - 1.0) * 100.0,
            cagr_pct=cagr_252 * 100.0,
            cagr_252_pct=cagr_252 * 100.0,
            cagr_calendar_pct=cagr_cal * 100.0,
            max_drawdown_pct=max_dd * 100.0,
            calmar_ratio=calmar,
            exposure_pct=100.0,
            trade_count=1,
            annual_turnover=0.0,
            annual_turnover_two_sided=0.0,
            win_rate_pct=100.0 if final_eq >= self.initial_capital else 0.0,
        )
        if return_trades:
            return nav_series, metrics, trades
        return nav_series, metrics

    def simulate_trend_timing(
        self,
        bars: List[AssistantBar],
        meta: ETFAssetMeta,
        ma_period: int = 120,
        band_pct: float = 0.015,
        confirm_days: int = 2,
        return_trades: bool = False,
    ) -> Tuple[List[float], BaselineMetrics] | Tuple[List[float], BaselineMetrics, List[Dict[str, Any]]]:
        """Causal trend timing with unified confirmation state machine and corporate action handling."""
        validate_bars(bars, meta)

        valid_bars = [b for b in bars if b.trade_date >= meta.listing_date]
        if len(valid_bars) <= ma_period:
            raise ValueError(f"Insufficient bars ({len(valid_bars)}) for MA {ma_period}")

        # Compute backward-adjusted closes for indicator calculation
        adj_closes = compute_adjusted_closes(valid_bars, meta)
        mas = self.compute_sma(adj_closes, ma_period)

        comm = meta.commission_bps / 10000.0
        slip = meta.slippage_bps / 10000.0
        daily_cash_rate = (1.0 + self.cash_apr) ** (1.0 / 252.0) - 1.0

        cash = self.initial_capital
        shares = 0.0
        nav_series: List[float] = []
        trades: List[Dict[str, Any]] = []
        in_market_days = 0

        sm = TrendTimingStateMachine(ma_period=ma_period, band_pct=band_pct, confirm_days=confirm_days)
        state = StateMachineState(current_target=0.0, executed_state=0.0, pending_target=0.0, confirm_count=0)

        for i, bar in enumerate(valid_bars):
            # 1. Overnight cash yield on uninvested cash balance
            if shares == 0.0 and cash > 0.0:
                cash *= (1.0 + daily_cash_rate)

            # 2. Corporate actions on existing shares
            if i > 0 and meta.corporate_actions:
                prev_date = valid_bars[i - 1].trade_date
                curr_date = bar.trade_date
                for ca in meta.corporate_actions:
                    if prev_date < ca.ex_date <= curr_date:
                        if ca.split_ratio != 1.0 and shares > 0.0:
                            old_shares = shares
                            shares *= ca.split_ratio
                            trades.append({
                                "action": "CORPORATE_ACTION_SPLIT",
                                "date": ca.ex_date,
                                "split_ratio": ca.split_ratio,
                                "shares_before": old_shares,
                                "shares_after": shares,
                                "note": ca.note,
                            })
                        if ca.cash_dividend > 0.0 and shares > 0.0:
                            div_amt = shares * ca.cash_dividend
                            cash += div_amt
                            trades.append({
                                "action": "CORPORATE_ACTION_DIVIDEND",
                                "date": ca.ex_date,
                                "cash_dividend": ca.cash_dividend,
                                "dividend_received": div_amt,
                                "cash_rem": cash,
                            })

            # 3. T+1 Open execution based on previous close signal
            if i > 0 and state.current_target != state.executed_state:
                if state.current_target == 1.0 and state.executed_state == 0.0:
                    # BUY at Open(T+1)
                    px = bar.open * (1.0 + slip)
                    buy_shares = cash / (px * (1.0 + comm))
                    cost = buy_shares * px * (1.0 + comm)
                    fee = buy_shares * px * comm
                    cash -= cost
                    shares = buy_shares
                    state.executed_state = 1.0
                    trades.append({
                        "action": "BUY",
                        "date": bar.trade_date,
                        "price": px,
                        "shares": buy_shares,
                        "cost": cost,
                        "commission": fee,
                        "cash_rem": cash,
                    })
                elif state.current_target == 0.0 and state.executed_state == 1.0:
                    # SELL at Open(T+1)
                    px = bar.open * (1.0 - slip)
                    fee = shares * px * comm
                    proceeds = shares * px * (1.0 - comm)
                    cash += proceeds
                    trades.append({
                        "action": "SELL",
                        "date": bar.trade_date,
                        "price": px,
                        "shares": shares,
                        "proceeds": proceeds,
                        "commission": fee,
                        "cash_rem": cash,
                    })
                    shares = 0.0
                    state.executed_state = 0.0

            if state.executed_state == 1.0:
                in_market_days += 1

            # 4. Mark to market at Close(T)
            eq = cash + shares * bar.close
            nav_series.append(eq)

            # 5. Generate Signal at Close(T) via unified state machine
            state = sm.update_at_close(state, adj_closes[i], mas[i])

        # Performance evaluation
        peak = 0.0
        max_dd = 0.0
        for eq in nav_series:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        n_days = len(valid_bars)
        years_252 = n_days / 252.0
        calendar_years = _calculate_calendar_years(valid_bars[0].trade_date, valid_bars[-1].trade_date, years_252)

        final_eq = nav_series[-1]
        cagr_252 = ((final_eq / self.initial_capital) ** (1.0 / years_252) - 1.0) if years_252 > 0 else 0.0
        cagr_cal = ((final_eq / self.initial_capital) ** (1.0 / calendar_years) - 1.0) if calendar_years > 0 else 0.0
        calmar = cagr_252 / max_dd if max_dd > 1e-4 else 0.0
        exposure = (in_market_days / n_days) * 100.0

        # Turnover metrics
        total_sell_amt = sum(t["shares"] * t["price"] for t in trades if t["action"] == "SELL")
        total_buy_amt = sum(t["shares"] * t["price"] for t in trades if t["action"] == "BUY")
        avg_nav = sum(nav_series) / len(nav_series) if nav_series else 1.0
        annual_turnover_sell = (total_sell_amt / avg_nav) / years_252 if avg_nav > 0 and years_252 > 0 else 0.0
        annual_turnover_two_sided = ((total_buy_amt + total_sell_amt) / avg_nav) / years_252 if avg_nav > 0 and years_252 > 0 else 0.0

        # Trade win rate
        buy_prices = [t["price"] for t in trades if t["action"] == "BUY"]
        sell_prices = [t["price"] for t in trades if t["action"] == "SELL"]
        win_count = sum(1 for b, s in zip(buy_prices, sell_prices) if s > b)
        round_trips = min(len(buy_prices), len(sell_prices))
        win_rate = (win_count / round_trips * 100.0) if round_trips > 0 else 0.0

        metrics = BaselineMetrics(
            model_name=f"MA{ma_period}_Band{band_pct*100:.1f}pct",
            symbol=meta.symbol,
            start_date=valid_bars[0].trade_date,
            end_date=valid_bars[-1].trade_date,
            trading_days=n_days,
            calendar_years=calendar_years,
            initial_equity=self.initial_capital,
            terminal_equity=final_eq,
            total_return_pct=(final_eq / self.initial_capital - 1.0) * 100.0,
            cagr_pct=cagr_252 * 100.0,
            cagr_252_pct=cagr_252 * 100.0,
            cagr_calendar_pct=cagr_cal * 100.0,
            max_drawdown_pct=max_dd * 100.0,
            calmar_ratio=calmar,
            exposure_pct=exposure,
            trade_count=len(trades),
            annual_turnover=annual_turnover_sell,
            annual_turnover_two_sided=annual_turnover_two_sided,
            win_rate_pct=win_rate,
        )
        current_target = state.current_target
        confirm_count = state.confirm_count
        if return_trades:
            return nav_series, metrics, trades
        return nav_series, metrics

    def simulate_pure_cash(
        self,
        bars: List[AssistantBar],
        meta: ETFAssetMeta,
        return_trades: bool = False,
    ) -> Tuple[List[float], BaselineMetrics] | Tuple[List[float], BaselineMetrics, List[Dict[str, Any]]]:
        """Pure cash control compounding at 2.0% annual cash yield."""
        validate_bars(bars, meta)
        valid_bars = [b for b in bars if b.trade_date >= meta.listing_date]
        daily_cash_rate = (1.0 + self.cash_apr) ** (1.0 / 252.0) - 1.0
        nav_series: List[float] = []
        cash = self.initial_capital
        for _ in valid_bars:
            cash *= (1.0 + daily_cash_rate)
            nav_series.append(cash)

        n_days = len(valid_bars)
        years_252 = n_days / 252.0
        calendar_years = _calculate_calendar_years(valid_bars[0].trade_date, valid_bars[-1].trade_date, years_252)

        final_eq = nav_series[-1]
        cagr_252 = ((final_eq / self.initial_capital) ** (1.0 / years_252) - 1.0) if years_252 > 0 else 0.0
        cagr_cal = ((final_eq / self.initial_capital) ** (1.0 / calendar_years) - 1.0) if calendar_years > 0 else 0.0

        metrics = BaselineMetrics(
            model_name="Pure_Cash_2pct_Control",
            symbol=meta.symbol,
            start_date=valid_bars[0].trade_date,
            end_date=valid_bars[-1].trade_date,
            trading_days=n_days,
            calendar_years=calendar_years,
            initial_equity=self.initial_capital,
            terminal_equity=final_eq,
            total_return_pct=(final_eq / self.initial_capital - 1.0) * 100.0,
            cagr_pct=cagr_252 * 100.0,
            cagr_252_pct=cagr_252 * 100.0,
            cagr_calendar_pct=cagr_cal * 100.0,
            max_drawdown_pct=0.0,
            calmar_ratio=None,
            exposure_pct=0.0,
            trade_count=0,
            annual_turnover=0.0,
            annual_turnover_two_sided=0.0,
            win_rate_pct=None,
        )
        if return_trades:
            return nav_series, metrics, []
        return nav_series, metrics

    def evaluate_daily_status(
        self,
        bars: List[AssistantBar],
        meta: ETFAssetMeta,
        ma_period: int = 120,
        band_pct: float = 0.015,
        confirm_days: int = 2,
        expected_as_of_date: Optional[str] = None,
        require_completed_bar: bool = True,
    ) -> DailyAssistantStatus:
        """Evaluates after-market status and produces a daily review report strictly sharing backtest state machine."""
        validate_bars(bars, meta)
        valid_bars = [b for b in bars if b.trade_date >= meta.listing_date]
        if len(valid_bars) < ma_period:
            raise ValueError(f"Insufficient bars ({len(valid_bars)}) for MA {ma_period}")

        adj_closes = compute_adjusted_closes(valid_bars, meta)
        mas = self.compute_sma(adj_closes, ma_period)
        latest_bar = valid_bars[-1]
        latest_adj_close = adj_closes[-1]
        latest_ma = mas[-1]

        if latest_ma is None:
            raise ValueError("Latest MA is None")

        upper = latest_ma * (1.0 + band_pct)
        lower = latest_ma * (1.0 - band_pct)
        dist_pct = (latest_adj_close - latest_ma) / latest_ma * 100.0

        sm = TrendTimingStateMachine(ma_period=ma_period, band_pct=band_pct, confirm_days=confirm_days)
        state = StateMachineState(current_target=0.0, executed_state=0.0, pending_target=0.0, confirm_count=0)

        for i, b in enumerate(valid_bars):
            if i > 0 and state.current_target != state.executed_state:
                state.executed_state = state.current_target
            state = sm.update_at_close(state, adj_closes[i], mas[i])

        if latest_adj_close > upper:
            if state.confirm_count > 0 and state.current_target == 0.0:
                regime = "BULLISH_CONFIRMING"
                reason = (
                    f"收盘价 ({latest_bar.close:.3f}) 突破 MA{ma_period} 上轨 ({upper:.3f})，"
                    f"当前确认进度 {state.confirm_count}/{confirm_days} 日，等待确认完成后次日开盘建仓"
                )
            else:
                regime = "BULLISH_HOLD"
                reason = (
                    f"收盘价 ({latest_bar.close:.3f}) 位于 MA{ma_period} (+{band_pct*100:.1f}% 缓冲带 {upper:.3f}) 之上，"
                    f"处于大周期多头趋势，建议 100% 仓位吃 Beta"
                )
        elif latest_adj_close < lower:
            if state.confirm_count > 0 and state.current_target == 1.0:
                regime = "BEARISH_CONFIRMING"
                reason = (
                    f"收盘价 ({latest_bar.close:.3f}) 跌破 MA{ma_period} 下轨 ({lower:.3f})，"
                    f"当前破位确认进度 {state.confirm_count}/{confirm_days} 日，等待确认完成后次日开盘清仓"
                )
            else:
                regime = "BEARISH_CASH"
                reason = (
                    f"收盘价 ({latest_bar.close:.3f}) 跌破 MA{ma_period} (-{band_pct*100:.1f}% 缓冲带 {lower:.3f})，"
                    f"处于大周期空头破位状态，建议 100% 现金空仓保本"
                )
        else:
            regime = "TRANSITION_DEADBAND"
            reason = (
                f"收盘价 ({latest_bar.close:.3f}) 处于 MA{ma_period} 缓冲震荡带 [{lower:.3f}, {upper:.3f}] 内，"
                f"属于防抖过渡区，维持上一决策 (目标仓位: {state.current_target * 100:.0f}%)"
            )

        # Data qualification, freshness, and benchmark proxy enforcement
        data_qual_status = "QUALIFIED"
        actionable = True
        dividend_qual = "QUALIFIED_OR_NOT_APPLICABLE"

        # Asset-identity disqualification: the instrument cannot back a live position regardless
        # of data freshness. Kept separate from the freshness gates below so both can be reported.
        identity_qual_status = "QUALIFIED"
        identity_reason = ""
        if meta.symbol == "510300.SH":
            identity_qual_status = "MISSING_INDEPENDENT_SERIES"
            identity_reason = (
                "【独立行情缺失】510300.SH 缺失场内独立复权行情序列，仅保留研究比较身份，严禁生成实盘仓位建议。"
            )
        elif meta.is_index_proxy:
            identity_qual_status = "BENCHMARK_PROXY_ONLY"
            dividend_qual = "NOT_AUDITED_PRICE_ONLY"
            identity_reason = (
                f"【基准指数代理】{meta.name} 为指数基准代理，非场内可交易实体；"
                f"拒绝生成有效建仓建议，仅保留大周期趋势宏观比较身份 (模型计算: {state.current_target * 100:.0f}%)。"
            )
        elif meta.symbol == "513100.SH":
            dividend_qual = "AUDITED_SPLIT_ONLY_CASH_DIVIDEND_PENDING"

        # Data disqualification gates are evaluated independently and accumulated, never
        # short-circuited: a bar can be both stale and incomplete, and the daily brief must
        # surface every disqualifying reason rather than an arbitrary first match. The
        # previous if/elif chain reported only INCOMPLETE_BAR while the report's top-level
        # freshness field said STALE, i.e. the brief contradicted itself.
        disqualifications: List[str] = []
        if require_completed_bar and not getattr(latest_bar, "is_complete", True):
            disqualifications.append("INCOMPLETE_BAR")
        if expected_as_of_date is not None and latest_bar.trade_date < expected_as_of_date:
            disqualifications.append("STALE_DATA")

        freshness_reason = ""
        if disqualifications:
            reason_parts = []
            if "INCOMPLETE_BAR" in disqualifications:
                reason_parts.append(
                    f"【未收盘/不完整K线拦截】最新行情 ({latest_bar.trade_date}) 标记为未完整收盘 (is_complete=False)；"
                    f"盘中仅供预览，大周期日线信号必须在完整收盘后生成"
                )
            if "STALE_DATA" in disqualifications:
                reason_parts.append(
                    f"【陈旧数据拦截】最新行情日期 ({latest_bar.trade_date}) 早于预期交易日 ({expected_as_of_date})，"
                    f"数据新鲜度未通过检验"
                )
            freshness_reason = "；".join(reason_parts) + "；拒绝生成有效仓位建议，维持 0% 仓位保本。"

        # Single point of assembly so the reported status string always names every reason the
        # asset is non-actionable, in a stable order: identity first, then freshness.
        all_reasons = ([identity_qual_status] if identity_qual_status != "QUALIFIED" else []) + list(disqualifications)
        if all_reasons:
            data_qual_status = "+".join(all_reasons)
            actionable = False
            # Regime always mirrors the full disqualification set, so a composite status never
            # loses one of its reasons. INCOMPLETE_BAR keeps the documented INCOMPLETE label.
            regime = "DATA_DISQUALIFIED_" + "_AND_".join(
                "INCOMPLETE" if r == "INCOMPLETE_BAR" else r for r in all_reasons
            )

        if not actionable:
            target_weight = 0.0
            # Asset-identity and data-freshness disqualifications can co-occur (an index proxy
            # whose series is also stale). Report both instead of letting either overwrite the other.
            reason = " ".join(p for p in (identity_reason, freshness_reason) if p)
        else:
            target_weight = state.current_target

        return DailyAssistantStatus(
            as_of_date=latest_bar.trade_date,
            symbol=meta.symbol,
            name=meta.name,
            close_price=latest_bar.close,
            ma_trend_val=latest_ma,
            ma_period=ma_period,
            band_pct=band_pct,
            distance_to_ma_pct=dist_pct,
            regime=regime,
            target_weight=target_weight,
            reason=reason,
            confirm_count=state.confirm_count,
            executed_holding=state.executed_state,
            data_qualification_status=data_qual_status,
            is_actionable=actionable,
            dividend_qualification=dividend_qual,
        )


def load_dataset_from_clean_indices(json_path: Path) -> Dict[str, List[AssistantBar]]:
    """Loads cleaned daily bars from clean_indices_daily_2013_2026.json."""
    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: Dict[str, List[AssistantBar]] = {}
    for sym, items in raw.items():
        bars = [
            AssistantBar(
                trade_date=it["trade_date"],
                open=float(it["open"]),
                high=float(it["high"]),
                low=float(it["low"]),
                close=float(it["close"]),
                vol=float(it.get("vol", 0.0)),
                amount=float(it.get("amount", 0.0)),
            )
            for it in items
        ]
        out[sym] = bars
    return out


def generate_deterministic_daily_report(
    daily_statuses: Sequence[DailyAssistantStatus],
    baseline_metrics: Optional[Mapping[str, BaselineMetrics]] = None,
    expected_as_of_date: Optional[str] = None,
    source_data_hash: Optional[str] = None,
    source_data_path: Optional[str] = None,
    execution_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates the four-section deterministic daily review report dictionary according to S3-C specification.

    Sections:
    1. input_status: as_of_date, expected_as_of_date, data freshness, source hash, and qualification per asset.
    2. rule_status: frozen trend parameters, positions, actionable targets, regimes, and reasons.
    3. risk_and_evidence: safety boundaries, fee assumptions, baseline metrics, and known gaps.
    4. tool_status: generation status, evidence qualification, disclaimer.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    as_of = max((s.as_of_date for s in daily_statuses), default="UNKNOWN")

    freshness = "FRESH"
    if expected_as_of_date is not None and as_of < expected_as_of_date:
        freshness = "STALE"

    # Indexed by position, not keyed by symbol: the same symbol can legitimately appear more than
    # once in one replay (e.g. a stale evaluation and an incomplete-bar evaluation of 513100.SH on
    # the same date). Keying by symbol - or by symbol+date - silently dropped all but the last
    # entry, hiding the stale disqualification while the top-level freshness field still said STALE.
    asset_quals = {}
    for idx, s in enumerate(daily_statuses):
        asset_quals[f"{s.symbol}#{idx}"] = {
            "symbol": s.symbol,
            "name": s.name,
            "as_of_date": s.as_of_date,
            "data_qualification_status": s.data_qualification_status,
            "is_actionable": s.is_actionable,
            "dividend_qualification": s.dividend_qualification,
            "reason": s.reason,
        }

    input_status = {
        "as_of_date": as_of,
        "expected_as_of_date": expected_as_of_date,
        "freshness_status": freshness,
        "source_data_path": source_data_path or "data/processed/clean_indices_daily_2013_2026.json",
        "source_data_hash": source_data_hash or "UNKNOWN",
        "assets_qualification": asset_quals,
    }

    rule_assets = {}
    for idx, s in enumerate(daily_statuses):
        rule_assets[f"{s.symbol}#{idx}"] = {
            "symbol": s.symbol,
            "as_of_date": s.as_of_date,
            "name": s.name,
            "close_price": round(s.close_price, 3),
            "ma_trend_val": round(s.ma_trend_val, 3),
            "distance_to_ma_pct": round(s.distance_to_ma_pct, 2),
            "regime": s.regime,
            "target_weight": s.target_weight,
            "executed_holding": s.executed_holding,
            "confirm_count": s.confirm_count,
            "is_actionable": s.is_actionable,
            "reason": s.reason,
        }

    first_st = daily_statuses[0] if daily_statuses else None
    rule_status = {
        "frozen_parameters": {
            "ma_period": first_st.ma_period if first_st else 120,
            "band_pct": first_st.band_pct if first_st else 0.015,
            "confirm_days": 2,
            "decision_timing": "T日收盘后判定，T+1日开盘撮合",
        },
        "assets": rule_assets,
    }

    bm_data = {}
    if baseline_metrics:
        for sym, m in baseline_metrics.items():
            bm_data[sym] = {
                "model_name": m.model_name,
                "cagr_252_pct": round(m.cagr_252_pct, 2),
                "cagr_calendar_pct": round(m.cagr_calendar_pct, 2),
                "max_drawdown_pct": round(m.max_drawdown_pct, 2),
                "annual_turnover_sell": round(m.annual_turnover, 2),
                "annual_turnover_two_sided": round(m.annual_turnover_two_sided, 2),
                "trade_count": m.trade_count,
                "calmar_ratio": round(m.calmar_ratio, 2) if m.calmar_ratio is not None else None,
            }

    risk_and_evidence = {
        "safety_boundary": {
            "research_only": True,
            "orders_authorized": False,
            "promotion_evidence": False,
        },
        "cost_assumptions": {
            "commission_bps": 6.0,
            "slippage_bps": 5.0,
            "cash_apr_pct": 2.0,
            "cash_compounding": "252交易日折算日复利",
        },
        "reconciled_run_link": "state/research_runs/personal_assistant_reconciled_20261012/",
        "baseline_performance": bm_data,
        "known_open_unknowns": [
            "000300.SH 仅为价格指数基准代理，非场内可交易实体，0 仓位",
            "510300.SH 缺少场内独立复权行情，0 仓位",
            "513100.SH 现金分红与到账日资格 pending，已审计 1:5 拆分连续性",
            "个人真实账户存在整手 (100股) 与最低 5 元佣金门槛，未在小数模拟中体现",
        ],
    }

    evidence_qual = "DISQUALIFIED"
    if any(s.is_actionable for s in daily_statuses):
        evidence_qual = "QUALIFIED"
    elif any(s.data_qualification_status in ("BENCHMARK_PROXY_ONLY", "MISSING_INDEPENDENT_SERIES") for s in daily_statuses):
        evidence_qual = "PARTIALLY_QUALIFIED"

    tool_status = {
        "report_generation_status": "SUCCESS",
        "input_freshness_status": freshness,
        "evidence_qualification_status": evidence_qual,
        "execution_run_id": execution_run_id or "local_deterministic_run",
        "llm_disclaimer": "LLM/Agent 仅解释已固化事实，严禁生成生产订单、目标权重或修改风控规则。",
    }

    return {
        "schema_version": "1.0.0",
        "generated_at": now_iso,
        "title": "个人量化交易助手每日收盘复盘报告 (Deterministic Daily Brief)",
        "input_status": input_status,
        "rule_status": rule_status,
        "risk_and_evidence": risk_and_evidence,
        "tool_status": tool_status,
    }


def format_daily_report_markdown(report: Mapping[str, Any]) -> str:
    """Formats the deterministic daily review dictionary into Github-flavored markdown."""
    inp = report.get("input_status", {})
    rules = report.get("rule_status", {})
    risk = report.get("risk_and_evidence", {})
    tool = report.get("tool_status", {})
    params = rules.get("frozen_parameters", {})
    assets = rules.get("assets", {})
    quals = inp.get("assets_qualification", {})
    gen_at = report.get("generated_at", "")

    fresh_badge = "🟢 新鲜" if inp.get("freshness_status") == "FRESH" else "🔴 陈旧"
    lines = [
        f"# {report.get('title', '个人量化交易助手每日收盘复盘报告')}",
        "",
        f"> **生成时间**：`{gen_at}`｜**评估基准日**：`{inp.get('as_of_date')}`｜**数据新鲜度**：{fresh_badge}（预期交易日：`{inp.get('expected_as_of_date')}`）",
        "> **安全底线**：`research_only=true / orders_authorized=false / promotion_evidence=false`（零生产订单、零实盘交互）。",
        "",
        "## 1. 输入与数据资格状态 (Input Status)",
        "",
        f"- **来源文件**：`{inp.get('source_data_path')}`",
        f"- **文件 SHA256**：`{inp.get('source_data_hash')}`",
        "",
        "| 标的代码 | 标的名称 | 数据资格状态 | 是否可行动 | 分红/到账资格 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for q in quals.values():
        act_str = "✅ 是" if q.get("is_actionable") else "❌ 否 (0%仓位)"
        lines.append(
            f"| `{q.get('symbol')}` | {q.get('name')} | `{q.get('data_qualification_status')}` | {act_str} | "
            f"`{q.get('dividend_qualification')}` |"
        )

    lines.extend([
        "",
        "## 2. 规则决策与无订单看板 (Rule Status)",
        "",
        f"冻结参数：MA 周期 `{params.get('ma_period')}`，缓冲带 `±{params.get('band_pct', 0.015)*100:.1f}%`，确认日 `{params.get('confirm_days')}` 日；{params.get('decision_timing')}。",
        "",
        "| 标的代码 | 标的名称 | 收盘价 | MA 趋势值 | 偏离度 | 趋势体制 | 建议仓位 | 决策原因 |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: | --- |",
    ])
    for a in assets.values():
        regime_badge = "🟢 [多头持仓]" if a.get("regime") == "BULLISH_HOLD" else ("🔴 [空头现金]" if a.get("regime") == "BEARISH_CASH" else f"🟡 [{a.get('regime')}]")
        target_str = f"**{a.get('target_weight', 0.0)*100:.0f}%**"
        lines.append(
            f"| `{a.get('symbol')}` | {a.get('name')} | {a.get('close_price'):.3f} | {a.get('ma_trend_val'):.3f} | "
            f"{a.get('distance_to_ma_pct'):+.2f}% | {regime_badge} | {target_str} | {a.get('reason')} |"
        )

    lines.extend([
        "",
        "## 3. 风险基线与证据追踪 (Risk & Evidence)",
        "",
        "- **交易摩擦假设**：双边手续费 6 bps，滑点 5 bps；闲置现金计息 2.0% APR（252 交易日折算日复利）。",
        f"- **不可变调和包指针**：`{risk.get('reconciled_run_link')}`",
    ])
    bm = risk.get("baseline_performance", {})
    if bm:
        lines.extend([
            "",
            "| 标的代码 | 模型 | CAGR(252) | 日历年化 | 最大回撤 | 年化换手(卖出) | 双边换手 | 交易笔数 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for sym, b in bm.items():
            lines.append(
                f"| `{sym}` | {b.get('model_name')} | {b.get('cagr_252_pct'):.2f}% | {b.get('cagr_calendar_pct'):.2f}% | "
                f"{b.get('max_drawdown_pct'):.2f}% | {b.get('annual_turnover_sell'):.2f}x | {b.get('annual_turnover_two_sided'):.2f}x | {b.get('trade_count')} |"
            )

    lines.extend([
        "",
        "### 已知未知项与缺陷说明",
        "",
    ])
    for unk in risk.get("known_open_unknowns", []):
        lines.append(f"- {unk}")

    lines.extend([
        "",
        "## 4. 工具与系统状态 (Tool Status)",
        "",
        f"- **报告生成状态**：`{tool.get('report_generation_status')}`",
        f"- **数据新鲜度判定**：`{tool.get('input_freshness_status')}`",
        f"- **证据资格状态**：`{tool.get('evidence_qualification_status')}`",
        f"- **LLM / 决策说明**：{tool.get('llm_disclaimer')}",
        "",
    ])
    return "\n".join(lines)
