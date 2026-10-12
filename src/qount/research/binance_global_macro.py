"""Binance Global Long/Short Macro Strategy: Futures, Leverage, and Cross-Market Hedging.

Core Capabilities:
1. Bidirectional Futures Execution (LONG and SHORT on Binance USD-M):
   - Bull Wave (BTC > MA120 or MA60 upward): LONG high-momentum Crypto (SOL/BTC/ETH) with 1.35x leverage.
   - Bear Wave (BTC < MA120 & MA60 down-sloping): SHORT breakdown Crypto with 1.10x leverage, capitalizing on
     the rapid, cascading nature of crypto selloffs (liquidation cascades).
2. Asymmetric Risk Defense:
   - LONG Defense: 14-day ATR-adaptive trailing stop (2.2x ATR, ~12-18% breath) + 7.5% hard stop.
   - SHORT Defense: Tight 5.0% squeeze stop + 9.0% profit-lock trailing from trough (guards against V-reversals).
3. Global Macro Real Asset Pairing:
   - Long Real Assets / Short Crypto Bubble: During crypto bear markets, pairs short crypto with long energy (XLE)
     and gold (PAXG) for a true global macro market-neutral hedge.
4. Realistic Margin Accounting & Fees:
   - 100% causal, T-day close signal, T+1 day open execution.
   - Realistic leverage, margin allocation, trading fees (7 bps crypto, 15 bps US ETF), cash earns 5.0% APR.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AssetBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class PositionState:
    symbol: str
    entry_date: str
    entry_price: float
    shares: float
    margin: float
    extrema: float  # highest price for LONG, lowest price for SHORT
    side: str  # "LONG" | "SHORT"
    asset_class: str  # "crypto" | "us_etf"
    profit_locked: bool = False


@dataclass(frozen=True)
class StrategyConfig:
    # Leverage settings
    crypto_long_leverage: float = 1.35
    crypto_short_leverage: float = 1.10
    crypto_long_margin_pct: float = 0.35  # 35% margin per long slot
    crypto_short_margin_pct: float = 0.25  # 25% margin per short slot
    us_slot_margin_pct: float = 0.20  # 20% margin per US ETF slot

    # Risk parameters for LONG
    crypto_long_hard_stop: float = 0.075  # -7.5% stop loss
    crypto_long_profit_lock: float = 0.15  # +15% gain triggers lock
    crypto_long_lock_buffer: float = 0.02  # lock at cost + 2%
    crypto_long_atr_mult: float = 2.2  # 2.2x ATR trailing

    # Risk parameters for SHORT (tighter protection against short squeeze)
    crypto_short_hard_stop: float = 0.050  # +5.0% stop loss
    crypto_short_profit_lock: float = 0.12  # +12% gain triggers lock
    crypto_short_lock_buffer: float = 0.015  # lock at cost - 1.5%
    crypto_short_trailing_pct: float = 0.090  # 9.0% trailing from trough

    # US ETF parameters
    us_hard_stop: float = 0.055
    us_profit_lock: float = 0.10
    us_lock_buffer: float = 0.015
    us_trailing_pct: float = 0.10

    # General
    cooldown_bars: int = 7
    cash_apr: float = 0.05  # 5% Binance Flexible Earn APR
    crypto_fee_bps: float = 7.0  # 5 bps comm + 2 bps slip
    stock_fee_bps: float = 15.0  # 10 bps comm + 5 bps slip

    # Audit & Ablation controls
    annual_funding_rate: float = 0.0  # Annual funding rate (e.g. 0.1095 = 10.95%)
    exact_stop_execution: bool = False  # If True, execute stop at trigger price, not close
    allow_short: bool = True  # If False, disables shorting (long-only)
    single_asset_btc: bool = False  # If True, restricts crypto to BTC only


def compute_sma(prices: Sequence[float], window: int) -> list[float]:
    res = [float("nan")] * len(prices)
    if window <= 0 or len(prices) < window:
        return res
    curr_sum = sum(prices[:window])
    res[window - 1] = curr_sum / window
    for i in range(window, len(prices)):
        curr_sum += prices[i] - prices[i - window]
        res[i] = curr_sum / window
    return res


def compute_atr(bars: Sequence[AssetBar], end_idx: int, window: int = 14) -> float:
    if end_idx < window:
        return bars[end_idx].close * 0.05
    trs: list[float] = []
    for k in range(end_idx - window + 1, end_idx + 1):
        h, l = bars[k].high, bars[k].low
        c_prev = bars[k - 1].close
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else bars[end_idx].close * 0.05


def compute_kaufman_efficiency_ratio(bars: Sequence[AssetBar], end_idx: int, window: int = 20) -> float:
    if end_idx < window:
        return 0.0
    net_change = abs(bars[end_idx].close - bars[end_idx - window].close)
    total_change = sum(abs(bars[k].close - bars[k - 1].close) for k in range(end_idx - window + 1, end_idx + 1))
    return net_change / total_change if total_change > 1e-6 else 0.0


def evaluate_macro_regimes(
    crypto_bars: Sequence[AssetBar],
    us_bars: Sequence[AssetBar],
    idx_crypto: int,
    idx_us: int,
) -> tuple[bool, bool, bool]:
    """Evaluate if Crypto is in Bull, Crypto is in Bear, and US is in Bull.
    
    Returns: (crypto_bull, crypto_bear, us_bull)
    """
    crypto_bull = False
    crypto_bear = False
    if idx_crypto >= 130:
        c_closes = [b.close for b in crypto_bars[: idx_crypto + 1]]
        ma120 = sum(c_closes[-120:]) / 120.0
        ma120_prev10 = sum(c_closes[-130:-10]) / 120.0
        slope120 = (ma120 - ma120_prev10) / ma120_prev10
        ma60 = sum(c_closes[-60:]) / 60.0
        ma20 = sum(c_closes[-20:]) / 20.0

        crypto_bull = (c_closes[-1] > ma120) or (c_closes[-1] > ma60 and c_closes[-1] > ma20)
        # Bear requires price below both MAs AND downward sloping long-term trend
        crypto_bear = (c_closes[-1] < ma120) and (c_closes[-1] < ma60) and (slope120 < -0.005)

    us_bull = False
    if idx_us >= 120:
        u_closes = [b.close for b in us_bars[: idx_us + 1]]
        ma120 = sum(u_closes[-120:]) / 120.0
        us_bull = u_closes[-1] > ma120

    return crypto_bull, crypto_bear, us_bull


@dataclass
class BacktestResult:
    cagr: float
    max_drawdown: float
    sharpe: float
    calmar: float
    trades_count: int
    win_rate: float
    profit_factor: float
    final_equity: float
    nav_series: list[tuple[str, float]]
    trade_logs: list[dict[str, Any]] = field(default_factory=list)


def run_binance_global_macro_backtest(
    market_data: Mapping[str, Sequence[AssetBar]],
    calendar: Sequence[str],
    config: StrategyConfig | None = None,
    initial_capital: float = 100_000.0,
    cost_multiplier: float = 1.0,
    execution_delay: int = 1,
) -> BacktestResult:
    """Run bidirectional long/short futures backtest across Binance Global Assets."""
    if config is None:
        config = StrategyConfig()

    crypto_fee = (config.crypto_fee_bps * cost_multiplier) / 10000.0
    stock_fee = (config.stock_fee_bps * cost_multiplier) / 10000.0
    daily_cash_rate = config.cash_apr / 365.0

    date_to_idx: dict[str, dict[str, int]] = {}
    for sym, bars in market_data.items():
        date_to_idx[sym] = {b.date: i for i, b in enumerate(bars)}

    MACRO_SYMBOLS = {"XLKBUSDT", "XLEBUSDT", "XLFBUSDT", "XLIBUSDT", "XLVBUSDT", "PAXGUSDT"}

    def is_macro_asset(sym: str) -> bool:
        return sym in MACRO_SYMBOLS or sym.startswith("XL") or sym.startswith("PAXG") or sym.startswith("SPY")

    def is_crypto_asset(sym: str) -> bool:
        return sym.endswith("USDT") and not is_macro_asset(sym)

    cash = initial_capital
    positions: dict[str, PositionState] = {}
    cooldowns: dict[str, int] = {}
    nav_series: list[tuple[str, float]] = []
    trade_records: list[dict[str, Any]] = []
    last_known_close: dict[str, float] = {}
    morning_eq = initial_capital

    btc_sym = "BTCUSDT" if "BTCUSDT" in market_data else next((s for s in market_data if "BTC" in s), None)
    us_benchmark_sym = "XLKBUSDT" if "XLKBUSDT" in market_data else "SPYBUSDT"
    if us_benchmark_sym not in market_data:
        us_benchmark_sym = next((s for s in market_data if "XL" in s or "QQQ" in s or "SPY" in s), None)

    pending_actions: list[tuple[str, list[dict[str, Any]]]] = []

    for step_i, dt in enumerate(calendar):
        cash *= (1.0 + daily_cash_rate)
        morning_eq *= (1.0 + daily_cash_rate)

        # Funding rate deduction on active crypto long positions
        if config.annual_funding_rate > 0.0:
            daily_fr = config.annual_funding_rate / 365.0
            for sym, pos in positions.items():
                if pos.side == "LONG" and pos.asset_class == "crypto":
                    notional = pos.shares * pos.entry_price
                    cash -= notional * daily_fr

        # 1. Process Pending Buy/Short Actions at Morning Open (sized using morning_eq, independent of dt close)
        if len(pending_actions) >= execution_delay:
            _, actions = pending_actions.pop(0)
            for act in actions:
                sym = act["symbol"]
                if sym in positions or sym in cooldowns:
                    continue
                if dt not in date_to_idx.get(sym, {}):
                    continue
                p_bar = market_data[sym][date_to_idx[sym][dt]]
                target_margin = morning_eq * act["margin_pct"]
                side = act["side"]
                leverage = act["leverage"]
                asset_kind = act["asset_class"]
                fee_rate = crypto_fee if asset_kind == "crypto" else stock_fee
                notional = target_margin * leverage
                entry_fee = notional * fee_rate
                total_entry_cost = target_margin + entry_fee

                if cash >= total_entry_cost * 0.95 and target_margin > 100.0:
                    buy_shares = notional / p_bar.open
                    cash -= total_entry_cost
                    positions[sym] = PositionState(
                        symbol=sym,
                        entry_date=dt,
                        entry_price=p_bar.open,
                        shares=buy_shares,
                        margin=target_margin,
                        extrema=p_bar.open,
                        side=side,
                        asset_class=asset_kind,
                    )

        # 2. Macro Regimes
        btc_bull = False
        btc_bear = False
        if btc_sym and dt in date_to_idx.get(btc_sym, {}):
            b_idx = date_to_idx[btc_sym][dt]
            if b_idx >= 130:
                c_slice = [b.close for b in market_data[btc_sym][: b_idx + 1]]
                ma120 = sum(c_slice[-120:]) / 120.0
                ma120_prev10 = sum(c_slice[-130:-10]) / 120.0
                slope120 = (ma120 - ma120_prev10) / ma120_prev10
                ma60 = sum(c_slice[-60:]) / 60.0
                ma20 = sum(c_slice[-20:]) / 20.0
                btc_bull = (c_slice[-1] > ma120) or (c_slice[-1] > ma60 and c_slice[-1] > ma20)
                btc_bear = (c_slice[-1] < ma120) and (c_slice[-1] < ma60) and (slope120 < -0.005)

        us_bull = False
        if us_benchmark_sym and dt in date_to_idx.get(us_benchmark_sym, {}):
            u_idx = date_to_idx[us_benchmark_sym][dt]
            if u_idx >= 120:
                u_slice = [b.close for b in market_data[us_benchmark_sym][: u_idx + 1]]
                us_bull = u_slice[-1] > (sum(u_slice[-120:]) / 120.0)

        # 3. Exits on Active Positions (including entry-day positions for hard stops)
        exits_to_execute = []
        for sym, pos in list(positions.items()):
            if dt not in date_to_idx.get(sym, {}):
                continue
            bar_idx = date_to_idx[sym][dt]
            bar = market_data[sym][bar_idx]
            exit_reason = None
            exec_px = bar.close

            # Compute prior ATR for trailing stop if needed
            prior_atr_idx = max(0, bar_idx - 1)
            prior_atr = compute_atr(market_data[sym], prior_atr_idx, 14)
            prev_px = market_data[sym][prior_atr_idx].close if prior_atr_idx < bar_idx else pos.entry_price
            atr_trailing_pct = min(0.18, max(0.12, (config.crypto_long_atr_mult * prior_atr) / prev_px)) if prev_px > 0 else 0.15

            if pos.side == "LONG":
                if pos.asset_class == "crypto":
                    hard_stop_px = pos.entry_price * (1.0 - config.crypto_long_hard_stop)
                    trail_stop_px = pos.extrema * (1.0 - atr_trailing_pct)
                    lock_stop_px = pos.entry_price * (1.0 + config.crypto_long_lock_buffer)

                    # 3a. Open gap checks (for positions held prior to today)
                    if pos.entry_date != dt and bar.open <= hard_stop_px:
                        exit_reason = "crypto_long_hard_stop"
                        exec_px = bar.open
                    elif pos.entry_date != dt and pos.profit_locked and bar.open <= lock_stop_px:
                        exit_reason = "crypto_long_profit_lock"
                        exec_px = bar.open
                    elif pos.entry_date != dt and bar.open <= trail_stop_px:
                        exit_reason = "crypto_long_atr_trailing"
                        exec_px = bar.open
                    # 3b. Intraday checks
                    elif bar.low <= hard_stop_px:
                        exit_reason = "crypto_long_hard_stop"
                        exec_px = bar.open if (pos.entry_date != dt and bar.open <= hard_stop_px) else (hard_stop_px if config.exact_stop_execution else bar.close)
                    elif pos.entry_date != dt and pos.profit_locked and bar.low <= lock_stop_px:
                        exit_reason = "crypto_long_profit_lock"
                        exec_px = lock_stop_px if config.exact_stop_execution else bar.close
                    elif pos.entry_date != dt and bar.low <= trail_stop_px:
                        exit_reason = "crypto_long_atr_trailing"
                        exec_px = trail_stop_px if config.exact_stop_execution else bar.close
                    # 3c. End-of-day macro exit
                    elif not btc_bull and pos.entry_date != dt:
                        exit_reason = "macro_btc_exit_long"
                        exec_px = bar.close
                else:
                    hard_stop_px = pos.entry_price * (1.0 - config.us_hard_stop)
                    trail_stop_px = pos.extrema * (1.0 - config.us_trailing_pct)
                    lock_stop_px = pos.entry_price * (1.0 + config.us_lock_buffer)

                    if pos.entry_date != dt and bar.open <= hard_stop_px:
                        exit_reason = "us_tight_stop"
                        exec_px = bar.open
                    elif pos.entry_date != dt and pos.profit_locked and bar.open <= lock_stop_px:
                        exit_reason = "us_profit_lock"
                        exec_px = bar.open
                    elif pos.entry_date != dt and bar.open <= trail_stop_px:
                        exit_reason = "us_trailing_stop"
                        exec_px = bar.open
                    elif bar.low <= hard_stop_px:
                        exit_reason = "us_tight_stop"
                        exec_px = bar.open if (pos.entry_date != dt and bar.open <= hard_stop_px) else (hard_stop_px if config.exact_stop_execution else bar.close)
                    elif pos.entry_date != dt and pos.profit_locked and bar.low <= lock_stop_px:
                        exit_reason = "us_profit_lock"
                        exec_px = lock_stop_px if config.exact_stop_execution else bar.close
                    elif pos.entry_date != dt and bar.low <= trail_stop_px:
                        exit_reason = "us_trailing_stop"
                        exec_px = trail_stop_px if config.exact_stop_execution else bar.close
                    elif not us_bull and sym not in ("XLEBUSDT", "PAXGUSDT") and pos.entry_date != dt:
                        exit_reason = "macro_us_exit_long"
                        exec_px = bar.close

            elif pos.side == "SHORT":
                hard_stop_px = pos.entry_price * (1.0 + config.crypto_short_hard_stop)
                trail_stop_px = pos.extrema * (1.0 + config.crypto_short_trailing_pct)
                lock_stop_px = pos.entry_price * (1.0 - config.crypto_short_lock_buffer)

                if pos.entry_date != dt and bar.open >= hard_stop_px:
                    exit_reason = "short_hard_stop"
                    exec_px = bar.open
                elif pos.entry_date != dt and pos.profit_locked and bar.open >= lock_stop_px:
                    exit_reason = "short_profit_lock"
                    exec_px = bar.open
                elif pos.entry_date != dt and bar.open >= trail_stop_px:
                    exit_reason = "short_trailing_stop"
                    exec_px = bar.open
                elif bar.high >= hard_stop_px:
                    exit_reason = "short_hard_stop"
                    exec_px = bar.open if (pos.entry_date != dt and bar.open >= hard_stop_px) else (hard_stop_px if config.exact_stop_execution else bar.close)
                elif pos.entry_date != dt and pos.profit_locked and bar.high >= lock_stop_px:
                    exit_reason = "short_profit_lock"
                    exec_px = lock_stop_px if config.exact_stop_execution else bar.close
                elif pos.entry_date != dt and bar.high >= trail_stop_px:
                    exit_reason = "short_trailing_stop"
                    exec_px = trail_stop_px if config.exact_stop_execution else bar.close
                elif not btc_bear and pos.entry_date != dt:
                    exit_reason = "macro_btc_exit_short"
                    exec_px = bar.close

            if exit_reason:
                exec_px = max(bar.low, min(bar.high, exec_px))
                exits_to_execute.append((sym, exit_reason, exec_px))

        # Decrement cooldowns
        for s in list(cooldowns.keys()):
            cooldowns[s] -= 1
            if cooldowns[s] <= 0:
                del cooldowns[s]

        # Execute Exits
        for sym, reason, exit_price in exits_to_execute:
            pos = positions.pop(sym)
            fee_rate = crypto_fee if pos.asset_class == "crypto" else stock_fee
            exit_fee = pos.shares * exit_price * fee_rate
            if pos.side == "LONG":
                pnl = pos.shares * (exit_price - pos.entry_price) - exit_fee
            else:
                pnl = pos.shares * (pos.entry_price - exit_price) - exit_fee

            proceeds = pos.margin + pnl
            cash += proceeds
            pnl_pct = (pnl / pos.margin) if pos.margin > 0 else 0.0
            if "hard_stop" in reason:
                cooldowns[sym] = config.cooldown_bars

            trade_records.append({
                "symbol": sym,
                "side": pos.side,
                "entry_date": pos.entry_date,
                "exit_date": dt,
                "entry_price": pos.entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "reason": reason,
            })

        # Update surviving positions at Close(T)
        for sym, pos in positions.items():
            if dt not in date_to_idx.get(sym, {}):
                continue
            bar_idx = date_to_idx[sym][dt]
            bar = market_data[sym][bar_idx]
            if pos.side == "LONG":
                if bar.high > pos.extrema:
                    pos.extrema = bar.high
                gain = (bar.close - pos.entry_price) / pos.entry_price
                if pos.asset_class == "crypto":
                    if gain >= config.crypto_long_profit_lock:
                        pos.profit_locked = True
                else:
                    if gain >= config.us_profit_lock:
                        pos.profit_locked = True
            elif pos.side == "SHORT":
                if bar.low < pos.extrema:
                    pos.extrema = bar.low
                gain = (pos.entry_price - bar.close) / pos.entry_price
                if gain >= config.crypto_short_profit_lock:
                    pos.profit_locked = True

        # 4. Generate New Entry Actions at Close (LONG or SHORT)
        crypto_held = [s for s, p in positions.items() if p.asset_class == "crypto"]
        us_held = [s for s, p in positions.items() if p.asset_class == "us_etf"]

        new_actions: list[dict[str, Any]] = []

        # A. Crypto LONG (when btc_bull) with leverage
        if btc_bull and len(crypto_held) < 2:
            needed = 2 - len(crypto_held)
            c_cands = []
            for s in market_data:
                if not is_crypto_asset(s):
                    continue
                if config.single_asset_btc and s != "BTCUSDT":
                    continue
                if s in positions or s in cooldowns:
                    continue
                if dt not in date_to_idx.get(s, {}):
                    continue
                s_idx = date_to_idx[s][dt]
                if s_idx < 60:
                    continue
                c_slice = [b.close for b in market_data[s][: s_idx + 1]]
                ma30 = sum(c_slice[-30:]) / 30.0
                ma60 = sum(c_slice[-60:]) / 60.0
                if c_slice[-1] <= ma30 or c_slice[-1] <= ma60:
                    continue
                p_high = max(b.high for b in market_data[s][s_idx - 20 : s_idx])
                if c_slice[-1] >= p_high:
                    ret20 = (c_slice[-1] - c_slice[-20]) / c_slice[-20]
                    c_cands.append((s, ret20))

            c_cands.sort(key=lambda x: x[1], reverse=True)
            for s, _ in c_cands[:needed]:
                new_actions.append({
                    "symbol": s,
                    "side": "LONG",
                    "margin_pct": config.crypto_long_margin_pct,
                    "leverage": config.crypto_long_leverage,
                    "asset_class": "crypto",
                })

        # B. Crypto SHORT (when btc_bear) with leverage on breakdowns
        elif config.allow_short and btc_bear and len(crypto_held) < 2:
            needed = 2 - len(crypto_held)
            c_short_cands = []
            for s in market_data:
                if not is_crypto_asset(s):
                    continue
                if config.single_asset_btc and s != "BTCUSDT":
                    continue
                if s in positions or s in cooldowns:
                    continue
                if dt not in date_to_idx.get(s, {}):
                    continue
                s_idx = date_to_idx[s][dt]
                if s_idx < 60:
                    continue
                c_slice = [b.close for b in market_data[s][: s_idx + 1]]
                ma30 = sum(c_slice[-30:]) / 30.0
                ma60 = sum(c_slice[-60:]) / 60.0
                if c_slice[-1] >= ma30 or c_slice[-1] >= ma60:
                    continue
                p_low = min(b.low for b in market_data[s][s_idx - 20 : s_idx])
                if c_slice[-1] <= p_low:
                    ret20 = (c_slice[-1] - c_slice[-20]) / c_slice[-20]
                    c_short_cands.append((s, ret20))

            c_short_cands.sort(key=lambda x: x[1])  # Lowest return first
            for s, _ in c_short_cands[:needed]:
                new_actions.append({
                    "symbol": s,
                    "side": "SHORT",
                    "margin_pct": config.crypto_short_margin_pct,
                    "leverage": config.crypto_short_leverage,
                    "asset_class": "crypto",
                })

        # C. US ETF LONG (Macro Sector Rotation: XLK, XLE, XLV, XLF, PAXG)
        max_us_slots = 2
        if len(us_held) < max_us_slots:
            needed = max_us_slots - len(us_held)
            u_cands = []
            for s in market_data:
                if not is_macro_asset(s):
                    continue
                if s in positions or s in cooldowns:
                    continue
                if dt not in date_to_idx.get(s, {}):
                    continue
                s_idx = date_to_idx[s][dt]
                if s_idx < 60:
                    continue
                c_slice = [b.close for b in market_data[s][: s_idx + 1]]
                ma30 = sum(c_slice[-30:]) / 30.0
                ma60 = sum(c_slice[-60:]) / 60.0
                if c_slice[-1] <= ma30 or c_slice[-1] <= ma60:
                    continue
                p_high = max(b.high for b in market_data[s][s_idx - 20 : s_idx])
                if c_slice[-1] >= p_high:
                    ret20 = (c_slice[-1] - c_slice[-20]) / c_slice[-20]
                    u_cands.append((s, ret20))

            u_cands.sort(key=lambda x: x[1], reverse=True)
            for s, _ in u_cands[:needed]:
                new_actions.append({
                    "symbol": s,
                    "side": "LONG",
                    "margin_pct": config.us_slot_margin_pct,
                    "leverage": 1.0,
                    "asset_class": "us_etf",
                })

        pending_actions.append((dt, new_actions))

        # 5. Record daily Mark-to-Market Equity at Close
        end_day_equity = cash
        for s, pos in positions.items():
            if dt in date_to_idx.get(s, {}):
                bar = market_data[s][date_to_idx[s][dt]]
                last_known_close[s] = bar.close
                close_px = bar.close
            else:
                close_px = last_known_close.get(s, pos.entry_price)
            fee_rate = crypto_fee if pos.asset_class == "crypto" else stock_fee
            exit_fee = pos.shares * close_px * fee_rate
            if pos.side == "LONG":
                pnl = pos.shares * (close_px - pos.entry_price) - exit_fee
            else:
                pnl = pos.shares * (pos.entry_price - close_px) - exit_fee
            end_day_equity += pos.margin + pnl
        nav_series.append((dt, end_day_equity))
        morning_eq = end_day_equity

    if not nav_series:
        return BacktestResult(0, 0, 0, 0, 0, 0, 0, initial_capital, [])

    start_eq = initial_capital
    end_eq = nav_series[-1][1]
    years = max(len(nav_series) / 365.25, 0.1)
    cagr = (end_eq / start_eq) ** (1.0 / years) - 1.0

    peak = start_eq
    max_dd = 0.0
    daily_rets = []
    for i in range(len(nav_series)):
        eq = nav_series[i][1]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd
        if i > 0:
            daily_rets.append((eq - nav_series[i - 1][1]) / nav_series[i - 1][1])

    mean_ret = sum(daily_rets) / len(daily_rets) if daily_rets else 0.0
    vol = (sum((r - mean_ret) ** 2 for r in daily_rets) / len(daily_rets)) ** 0.5 if daily_rets else 0.0
    ann_vol = vol * math.sqrt(365.25)
    sharpe = ((cagr - config.cash_apr) / ann_vol) if ann_vol > 1e-6 else 0.0
    calmar = cagr / max_dd if max_dd > 1e-4 else 0.0

    wins = [t for t in trade_records if t["pnl"] > 0]
    losses = [t for t in trade_records if t["pnl"] <= 0]
    win_rate = len(wins) / len(trade_records) if trade_records else 0.0
    tot_win = sum(t["pnl"] for t in wins)
    tot_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = (tot_win / tot_loss) if tot_loss > 1e-4 else (99.0 if tot_win > 0 else 1.0)

    return BacktestResult(
        cagr=cagr,
        max_drawdown=max_dd,
        sharpe=sharpe,
        calmar=calmar,
        trades_count=len(trade_records),
        win_rate=win_rate,
        profit_factor=profit_factor,
        final_equity=end_eq,
        nav_series=nav_series,
        trade_logs=trade_records,
    )
