"""
QOUNT Universal Regime & Dynamic Expectancy Strategy Engine (Audited & Rigorous)

Key Tenets:
1. Objective Universe: ALL 10 Macro Orthogonal Assets (SPY, SMH, IWM, XLI, XLB, GLD, CPER, XLU, TLT, UUP).
   No post-hoc cherry-picking or manual dropping of underperforming assets.
2. First-Principles Volatility Floor:
   Instruments must exhibit normalized daily volatility (ATR_14 / Close >= 0.85%) to qualify
   for momentum/breakout sizing, naturally disqualifying tight low-volatility FX noise without ticker bias.
3. Rigorous Causality & Conflict Resolution:
   - Next-Day Open execution (Open_{t+1}) with slippage.
   - Conservative Intraday Exit Precedence: If Low <= Stop AND High >= Target in the same bar,
     STOP-OUT FIRST (avoids optimistic execution bias).
   - Trailing Stop Lag: Trailing stops raised at Day T close take effect strictly on Day T+1
     (eliminates retroactive lookahead against morning lows).
4. Realistic Cost & Financing Regimes:
   - 1X Cash Spot: Baseline, 0% borrow fee, 0.05% slippage, 0.03% fee.
   - TradFi Broker Margin 2X: Annualized 6.0% borrow interest on borrowed capital.
   - Binance TradFi Perp 2X: 3.65% annualized base funding rate, 0.04% taker fee,
     0.40% punitive slippage on stop-out/off-hours to reflect liquidity vacuum.
"""

from collections import defaultdict
import csv
import datetime as dt
from pathlib import Path
import statistics
from typing import Any, Dict, List, Optional, Tuple

ALL_10_MACRO_SYMBOLS: List[str] = [
    "SPY",
    "SMH",
    "IWM",
    "XLI",
    "XLB",
    "GLD",
    "CPER",
    "XLU",
    "TLT",
    "UUP",
]

NON_EQUITY_SYMBOLS: List[str] = ["GLD", "CPER", "TLT", "UUP"]
EQUITY_SYMBOLS: List[str] = ["SPY", "SMH", "IWM", "XLI", "XLB", "XLU"]



class DailyBar:
  """Represents a standardized daily OHLCV bar."""

  def __init__(
      self, date_str: str, o: float, h: float, l: float, c: float, v: float
  ):
    self.d = date_str
    self.o = float(o)
    self.h = float(h)
    self.l = float(l)
    self.c = float(c)
    self.v = float(v)
    self.dt = dt.datetime.strptime(date_str, "%Y-%m-%d").replace(
        tzinfo=dt.timezone.utc
    )
    self.t = int(self.dt.timestamp())


def load_etf_bars(
    sym: str, data_dir: str = "data/raw"
) -> List[DailyBar]:
  """Loads and sorts daily bars from CSV for a given symbol."""
  fn = Path(data_dir) / f"{sym}_daily.csv"
  if not fn.exists():
    raise FileNotFoundError(f"Bar data file not found: {fn}")
  bars = []
  with fn.open("r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for r in reader:
      bars.append(
          DailyBar(
              r["Date"],
              float(r["Open"]),
              float(r["High"]),
              float(r["Low"]),
              float(r["Close"]),
              float(r["Volume"]),
          )
      )
  bars.sort(key=lambda b: b.t)
  return bars


def compute_ema(series: List[float], span: int) -> List[float]:
  """Computes Exponential Moving Average with standard alpha = 2 / (span + 1)."""
  if not series:
    return []
  alpha = 2.0 / (span + 1.0)
  res = [series[0]]
  for x in series[1:]:
    res.append(alpha * x + (1.0 - alpha) * res[-1])
  return res


def compute_atr(bars: List[DailyBar], span: int = 14) -> List[float]:
  """Computes Average True Range using Wilder's smoothing."""
  if not bars:
    return []
  res = [bars[0].h - bars[0].l]
  alpha = 1.0 / span
  for i in range(1, len(bars)):
    tr = max(
        bars[i].h - bars[i].l,
        abs(bars[i].h - bars[i - 1].c),
        abs(bars[i].l - bars[i - 1].c),
    )
    res.append(alpha * tr + (1.0 - alpha) * res[-1])
  return res


def compute_kaufman_er(closes: List[float], period: int = 20) -> List[float]:
  """Computes Kaufman Efficiency Ratio (ER = Direction / Volatility)."""
  ers = []
  for i in range(len(closes)):
    if i < period:
      ers.append(0.3)
    else:
      net_chg = abs(closes[i] - closes[i - period])
      gross_chg = sum(
          abs(closes[i - k] - closes[i - k - 1]) for k in range(period)
      )
      ers.append(net_chg / (gross_chg + 1e-9))
  return ers


def compute_profile_state(
    bars: List[DailyBar], c_now: float, cur_atr: float
) -> Tuple[int, str, float, float, float, float, float]:
  """Computes 4D market microstructure state:

  State 1: ACCUMULATION / SQUEEZE
  State 2: DIRECTIONAL TREND EXPANSION
  State 3: EXHAUSTION / CLIMAX
  State 4: VALUE AREA OSCILLATION / CHOP
  """
  if len(bars) < 15 or cur_atr <= 0:
    return 4, "CHOP", c_now, c_now + cur_atr, c_now - cur_atr, 0.5, 0.0
  min_p = min(b.l for b in bars)
  max_p = max(b.h for b in bars)
  if max_p <= min_p:
    return 4, "CHOP", c_now, c_now + cur_atr, c_now - cur_atr, 0.5, 0.0

  num_bins = 40
  bin_w = (max_p - min_p) / num_bins
  bin_v = [0.0] * num_bins
  tot_v = 0.0
  for b in bars:
    v = b.v
    if v <= 0:
      continue
    tot_v += v
    i_l = max(0, min(num_bins - 1, int((b.l - min_p) / bin_w)))
    i_h = max(0, min(num_bins - 1, int((b.h - min_p) / bin_w)))
    n_sp = max(1, i_h - i_l + 1)
    for idx in range(i_l, i_h + 1):
      bin_v[idx] += v / n_sp

  if tot_v <= 0:
    return 4, "CHOP", c_now, c_now + cur_atr, c_now - cur_atr, 0.5, 0.0

  max_idx = max(range(num_bins), key=lambda k: bin_v[k])
  poc_p = min_p + (max_idx + 0.5) * bin_w

  below_v = sum(
      bin_v[k] for k in range(num_bins) if min_p + (k + 0.5) * bin_w < c_now
  )
  profit_ratio = below_v / tot_v

  tgt_70 = tot_v * 0.70
  acc_v = bin_v[max_idx]
  l_idx = r_idx = max_idx
  while acc_v < tgt_70 and (l_idx > 0 or r_idx < num_bins - 1):
    v_l = bin_v[l_idx - 1] if l_idx > 0 else -1
    v_r = bin_v[r_idx + 1] if r_idx < num_bins - 1 else -1
    if v_l >= v_r and l_idx > 0:
      l_idx -= 1
      acc_v += bin_v[l_idx]
    elif r_idx < num_bins - 1:
      r_idx += 1
      acc_v += bin_v[r_idx]
    else:
      break

  val = min_p + l_idx * bin_w
  vah = min_p + (r_idx + 1) * bin_w
  concentration = (
      1.0 - (vah - val) / (max_p - min_p) if (max_p - min_p) > 0 else 0
  )
  dist_poc_atr = (c_now - poc_p) / cur_atr

  if dist_poc_atr > 3.8 and profit_ratio > 0.90:
    return 3, "EXHAUSTION", poc_p, vah, val, profit_ratio, concentration
  if c_now > vah and dist_poc_atr > 0.6 and profit_ratio > 0.65:
    return 2, "TREND_UP", poc_p, vah, val, profit_ratio, concentration
  if (
      concentration > 0.40
      and abs(dist_poc_atr) < 1.2
      and 0.30 <= profit_ratio <= 0.70
  ):
    return 1, "ACCUMULATION", poc_p, vah, val, profit_ratio, concentration
  return 4, "CHOP", poc_p, vah, val, profit_ratio, concentration


def run_regime_backtest(
    symbols: Optional[List[str]] = None,
    mode: str = "1X_SPOT",  # "1X_SPOT", "TRADIFI_MARGIN_2X", "BINANCE_PERP_2X", "DYNAMIC_BULL_2_5X"
    causality_mode: str = "RIGOROUS",  # "RIGOROUS" vs "ORIGINAL_OPTIMISTIC"
    start_date: str = "2020-01-01",
    end_date: str = "2026-07-30",
    initial_capital: float = 1000.0,
    max_positions: int = 2,
    risk_budget_pct: Optional[float] = None,
    min_atr_pct: float = 0.0085,  # 0.85% normalized daily volatility floor
    strict_golden_cross: bool = True,
    breakout_quality_filter: bool = True,
    dynamic_max_pos: bool = True,
    orthogonal_tier_limit: bool = True,
    gap_stress_pct: float = 0.015,
    er_min: float = 0.28,
    mr_require_green: bool = True,
    mr_max_hold_days: int = 10,
    mr_edge_decay: bool = True,
    stagnant_exit_days: Optional[int] = 30,
    min_rs60: Optional[float] = -0.03,
    edge_decay_exit: bool = True,
    enable_cash_overlay: bool = True,
    cash_rate_mode: str = "historical",  # "historical", "flat_4pct", "none"
    data_dir: str = "data/raw",
) -> Dict[str, Any]:
  """Executes the universal regime expectancy strategy backtest with audited causality."""
  if symbols is None:
    symbols = ALL_10_MACRO_SYMBOLS

  # Preload SPY benchmark
  spy_bars = load_etf_bars("SPY", data_dir=data_dir)
  spy_closes = [b.c for b in spy_bars]
  spy_ema50 = compute_ema(spy_closes, 50)
  spy_ema200 = compute_ema(spy_closes, 200)
  spy_dict = {
      b.d: (i, b, spy_ema50[i], spy_ema200[i]) for i, b in enumerate(spy_bars)
  }

  all_data = {}
  all_dates = set()
  for sym in symbols:
    try:
      bars = load_etf_bars(sym, data_dir=data_dir)
    except FileNotFoundError:
      continue
    closes = [b.c for b in bars]
    atr14 = compute_atr(bars, 14)
    ema20 = compute_ema(closes, 20)
    ema50 = compute_ema(closes, 50)
    ema200 = compute_ema(closes, 200)
    ers = compute_kaufman_er(closes, 20)

    bb_lower = []
    rs60 = []
    for i in range(len(bars)):
      if i < 20:
        bb_lower.append(bars[i].c)
      else:
        win_p = closes[i - 19 : i + 1]
        m_p = sum(win_p) / 20.0
        s_p = (sum((x - m_p) ** 2 for x in win_p) / 20.0) ** 0.5
        bb_lower.append(m_p - 2.0 * s_p)

      if i >= 60:
        rs60.append((closes[i] / closes[i - 60]) - 1.0)
      else:
        rs60.append(0.0)

    bar_dict = {b.d: (i, b) for i, b in enumerate(bars)}
    for b in bars:
      if start_date <= b.d <= end_date:
        all_dates.add(b.d)

    all_data[sym] = {
        "bars": bars,
        "bar_dict": bar_dict,
        "atr14": atr14,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "bb_lower": bb_lower,
        "ers": ers,
        "rs60": rs60,
    }

  sorted_dates = sorted(list(all_dates))
  trades = []
  equity = initial_capital
  peak_equity = initial_capital
  max_drawdown = 0.0
  curve = []
  active_positions = {}
  cooldowns = {}
  pending_orders = []

  # Cost configurations
  if mode == "1X_SPOT":
    leverage = 1.0
    fee_pct = 0.0003
    entry_slip_pct = 0.0005
    exit_slip_pct = 0.0005
    stop_slip_pct = 0.0005
    margin_borrow_apr = 0.0
    daily_funding_rate = 0.0
  elif mode == "TRADIFI_MARGIN_2X":
    leverage = 2.0
    fee_pct = 0.0003
    entry_slip_pct = 0.0005
    exit_slip_pct = 0.0005
    stop_slip_pct = 0.0005
    margin_borrow_apr = 0.060  # 6.0% annual borrow interest on borrowed margin
    daily_funding_rate = 0.0
  elif mode == "DYNAMIC_BULL_2_5X":
    leverage = 2.5
    fee_pct = 0.0003
    entry_slip_pct = 0.0005
    exit_slip_pct = 0.0005
    stop_slip_pct = 0.0005
    margin_borrow_apr = 0.060  # 6.0% annual borrow interest on borrowed margin
    daily_funding_rate = 0.0
  elif mode == "BINANCE_PERP_2X":
    leverage = 2.0
    fee_pct = 0.0004  # 0.04% taker fee
    entry_slip_pct = 0.0010  # crypto tradfi wider spread
    exit_slip_pct = 0.0010
    stop_slip_pct = (
        0.0040  # 0.40% punitive slippage on stop-out (liquidity vacuum)
    )
    margin_borrow_apr = 0.0
    daily_funding_rate = 0.0001  # ~3.65% annualized funding rate
  else:
    raise ValueError(f"Unknown mode: {mode}")

  total_borrow_interest_paid = 0.0
  total_funding_fees_paid = 0.0
  total_cash_interest = 0.0

  fed_funds_rate = {
      "2020": 0.0035,
      "2021": 0.0010,
      "2022": 0.0200,
      "2023": 0.0500,
      "2024": 0.0525,
      "2025": 0.0450,
      "2026": 0.0430,
  }

  for d_str in sorted_dates:
    # Day T+1 Morning Open: Determine macro state strictly from Day T close (yesterday)
    open_is_macro_bear = False
    open_is_macro_bull = True
    open_is_strong_bull = False
    if d_str in spy_dict:
      s_idx, s_bar, s_ema50, s_ema200 = spy_dict[d_str]
      if s_idx > 0:
        prev_bar = spy_bars[s_idx - 1]
        prev_ema50 = spy_ema50[s_idx - 1]
        prev_ema200 = spy_ema200[s_idx - 1]
        if prev_bar.c < prev_ema200 or prev_ema50 < prev_ema200:
          open_is_macro_bear = True
          open_is_macro_bull = False
        elif prev_bar.c > prev_ema50 and prev_ema50 > prev_ema200:
          open_is_strong_bull = True

    effective_lev = leverage
    if mode == "DYNAMIC_BULL_2_5X":
      effective_lev = leverage if open_is_strong_bull else min(leverage, 1.0)

    cur_max_pos = max_positions
    if dynamic_max_pos:
      cur_max_pos = max_positions if open_is_macro_bull else 1

    # STEP 1: Execute Pending Entry Orders at Open T+1
    if pending_orders:
      for cand in pending_orders:
        sym = cand["symbol"]
        if sym in active_positions or len(active_positions) >= cur_max_pos:
          continue
        ind = all_data[sym]
        if d_str not in ind["bar_dict"]:
          continue
        idx, cur_bar = ind["bar_dict"][d_str]

        is_equity = sym not in NON_EQUITY_SYMBOLS
        if open_is_macro_bear and is_equity:
          continue

        if orthogonal_tier_limit and is_equity:
          active_equities = [
              s for s in active_positions if s not in NON_EQUITY_SYMBOLS
          ]
          if len(active_equities) >= 1:
            continue

        open_p = cur_bar.o
        init_stop = cand["init_stop"]
        raw_stop_dist = open_p - init_stop
        cur_atr = ind["atr14"][idx - 1] if idx > 0 else open_p * 0.02
        eff_stop_dist = max(raw_stop_dist, 1.5 * cur_atr)

        if eff_stop_dist > 0:
          if risk_budget_pct is not None:
            risk_pct = risk_budget_pct
          else:
            risk_pct = (
                0.08
                if mode == "DYNAMIC_BULL_2_5X"
                else (0.03 if cur_max_pos >= 2 else 0.04)
            )
          risk_usd = equity * risk_pct
          qty = risk_usd / eff_stop_dist

          if effective_lev > 1.0:
            max_qty = (equity * effective_lev * 0.95 / cur_max_pos) / open_p
          else:
            max_qty = (equity * 0.98 / cur_max_pos) / open_p
          qty = min(qty, max_qty)

          if qty * open_p >= 5.0:
            entry_p = open_p * (1.0 + entry_slip_pct)
            entry_fee = qty * entry_p * fee_pct
            equity -= entry_fee
            notional = qty * entry_p
            if mode == "TRADIFI_MARGIN_2X":
              borrowed_usd = notional * 0.5
            elif mode == "DYNAMIC_BULL_2_5X":
              borrowed_usd = max(0.0, notional - (equity / cur_max_pos))
            else:
              borrowed_usd = 0.0

            active_positions[sym] = {
                "trade_type": cand["trade_type"],
                "entry_date": d_str,
                "entry_price": entry_p,
                "qty": qty,
                "orig_qty": qty,
                "risk_usd": risk_usd,
                "initial_stop": init_stop,
                "active_stop": init_stop,
                "next_stop": init_stop,
                "highest_close": open_p,
                "trailing_active": False,
                "target_p": cand["target_p"],
                "entry_idx": idx,
                "took_partial_profit": False,
                "borrowed_usd": borrowed_usd,
            }
      pending_orders = []

    # STEP 2: Accrue Daily Financing, Borrow Interest & Cash Yield
    allocated_capital = sum(
        pos["qty"] * pos["entry_price"] for pos in active_positions.values()
    )
    idle_cash = max(0.0, equity - allocated_capital)
    if enable_cash_overlay and idle_cash > 0 and cash_rate_mode != "none":
      if cash_rate_mode == "flat_4pct":
        rate = 0.04
      else:
        rate = fed_funds_rate.get(d_str[:4], 0.035)
      day_interest = idle_cash * (rate / 365.0)
      equity += day_interest
      total_cash_interest += day_interest

    for sym, pos in active_positions.items():
      if mode in ("TRADIFI_MARGIN_2X", "DYNAMIC_BULL_2_5X"):
        daily_interest = pos["borrowed_usd"] * (margin_borrow_apr / 365.0)
        equity -= daily_interest
        total_borrow_interest_paid += daily_interest
      elif mode == "BINANCE_PERP_2X":
        c_now = (
            all_data[sym]["bar_dict"][d_str][1].c
            if d_str in all_data[sym]["bar_dict"]
            else pos["entry_price"]
        )
        funding = pos["qty"] * c_now * daily_funding_rate
        equity -= funding
        total_funding_fees_paid += funding

    # STEP 3: Exit Checks during Day T (Using ACTIVE STOP)
    for sym in list(active_positions.keys()):
      pos = active_positions[sym]
      ind = all_data[sym]
      if d_str not in ind["bar_dict"]:
        continue
      idx, cur_bar = ind["bar_dict"][d_str]
      cur_atr = ind["atr14"][idx]
      c_now = cur_bar.c
      r_dist = abs(pos["entry_price"] - pos["initial_stop"])
      stop_price_today = pos["active_stop"]
      hold_days = idx - pos["entry_idx"]

      if pos["trade_type"] == "MEAN_REVERSION":
        is_tp = cur_bar.h >= pos["target_p"]
        is_sl = cur_bar.l <= stop_price_today
        is_max_hold = hold_days >= mr_max_hold_days

        is_decay = False
        if mr_edge_decay and hold_days >= 5:
          er_val = ind["ers"][idx]
          if er_val < 0.20 and c_now < pos["entry_price"]:
            is_decay = True

        if is_tp or is_sl or is_max_hold or is_decay:
          if is_sl and is_tp and causality_mode == "RIGOROUS":
            is_tp = False  # STOP LOSS PRECEDENCE

          if is_sl:
            raw_exit = min(cur_bar.o, stop_price_today) * (
                1.0 - gap_stress_pct
            )
            reason = "mr_stop"
            slip = stop_slip_pct
          elif is_decay:
            raw_exit = cur_bar.o
            reason = "mr_edge_decay"
            slip = exit_slip_pct
          elif is_tp:
            raw_exit = pos["target_p"]
            reason = "mr_tp"
            slip = exit_slip_pct
          else:
            raw_exit = cur_bar.o
            reason = "mr_max_hold"
            slip = exit_slip_pct

          exit_p = raw_exit * (1.0 - slip)
          exit_fee = pos["qty"] * exit_p * fee_pct
          net_pnl = pos["qty"] * (exit_p - pos["entry_price"]) - exit_fee
          equity += net_pnl
          trades.append({
              "date": d_str,
              "symbol": sym,
              "type": pos["trade_type"],
              "entry_date": pos["entry_date"],
              "exit_date": d_str,
              "holding_days": idx - pos["entry_idx"],
              "entry_price": pos["entry_price"],
              "exit_price": exit_p,
              "quantity": pos["qty"],
              "net_pnl_usd": net_pnl,
              "net_R": net_pnl / (pos["risk_usd"] + 1e-9),
              "exit_reason": reason,
              "equity_after": equity,
          })
          cooldowns[sym] = idx + (5 if "stop" in reason else 2)
          del active_positions[sym]
          continue
      else:
        # Trend Trade Exits
        is_sl = cur_bar.l <= stop_price_today
        hold_days = idx - pos["entry_idx"]
        is_max_hold = hold_days >= 45

        # Stagnant exit check: release capital if held >= stagnant_exit_days without reaching +0.8R
        is_stagnant = False
        if stagnant_exit_days is not None and hold_days >= stagnant_exit_days:
          unrealized_r = (c_now - pos["entry_price"]) / (r_dist + 1e-9)
          if unrealized_r < 0.8:
            is_stagnant = True

        # Edge-decay exit check: release capital early if held >= 7 days, Kaufman ER collapses (< 0.18), price drops below EMA20, and unrealized R < 0.5
        is_decay = False
        if edge_decay_exit and hold_days >= 7:
          er_val = ind["ers"][idx]
          ema20_val = ind["ema20"][idx]
          unrealized_r = (c_now - pos["entry_price"]) / (r_dist + 1e-9)
          if er_val < 0.18 and c_now < ema20_val and unrealized_r < 0.5:
            is_decay = True

        can_tp = (not pos["took_partial_profit"]) and (r_dist > 0)
        is_tp3r = can_tp and ((cur_bar.h - pos["entry_price"]) >= 3.0 * r_dist)

        if is_sl and is_tp3r and causality_mode == "RIGOROUS":
          is_tp3r = False  # Conservative: SL first

        if is_tp3r:
          half_qty = pos["qty"] * 0.5
          tp_price = pos["entry_price"] + 3.0 * r_dist
          realized_pnl = half_qty * (tp_price - pos["entry_price"]) - (
              half_qty * tp_price * fee_pct
          )
          equity += realized_pnl
          pos["qty"] -= half_qty
          pos["took_partial_profit"] = True
          if causality_mode == "ORIGINAL_OPTIMISTIC":
            stop_price_today = max(stop_price_today, pos["entry_price"])
          trades.append({
              "date": d_str,
              "symbol": sym,
              "type": pos["trade_type"] + "_TP50",
              "entry_date": pos["entry_date"],
              "exit_date": d_str,
              "holding_days": idx - pos["entry_idx"],
              "entry_price": pos["entry_price"],
              "exit_price": tp_price,
              "quantity": half_qty,
              "net_pnl_usd": realized_pnl,
              "net_R": 1.5,
              "exit_reason": "partial_tp3r",
              "equity_after": equity,
          })
          is_sl = cur_bar.l <= stop_price_today

        if is_sl or is_max_hold or is_stagnant or is_decay:
          if is_sl:
            raw_exit = min(cur_bar.o, stop_price_today) * (
                1.0 - gap_stress_pct
            )
            reason = (
                "trailing_stop" if pos["trailing_active"] else "initial_stop"
            )
            slip = stop_slip_pct
          elif is_decay:
            raw_exit = cur_bar.o
            reason = "edge_decay_exit"
            slip = exit_slip_pct
          elif is_stagnant:
            raw_exit = cur_bar.o
            reason = "stagnant_release"
            slip = exit_slip_pct
          else:
            raw_exit = cur_bar.o
            reason = "max_hold"
            slip = exit_slip_pct

          exit_p = raw_exit * (1.0 - slip)
          exit_fee = pos["qty"] * exit_p * fee_pct
          net_pnl = pos["qty"] * (exit_p - pos["entry_price"]) - exit_fee
          equity += net_pnl
          trades.append({
              "date": d_str,
              "symbol": sym,
              "type": pos["trade_type"],
              "entry_date": pos["entry_date"],
              "exit_date": d_str,
              "holding_days": idx - pos["entry_idx"],
              "entry_price": pos["entry_price"],
              "exit_price": exit_p,
              "quantity": pos["qty"],
              "net_pnl_usd": net_pnl,
              "net_R": net_pnl / (pos["risk_usd"] + 1e-9),
              "exit_reason": reason,
              "equity_after": equity,
          })
          cooldowns[sym] = idx + (5 if reason == "initial_stop" else 2)
          del active_positions[sym]
          continue

    # STEP 4: End of Day T Close — Update Trailing Stop for Day T+1
    for sym, pos in active_positions.items():
      ind = all_data[sym]
      if d_str not in ind["bar_dict"]:
        continue
      idx, cur_bar = ind["bar_dict"][d_str]
      cur_atr = ind["atr14"][idx]
      c_now = cur_bar.c
      r_dist = abs(pos["entry_price"] - pos["initial_stop"])
      pos["highest_close"] = max(pos["highest_close"], c_now)

      next_st = pos["active_stop"]
      if pos["took_partial_profit"]:
        next_st = max(next_st, pos["entry_price"])
      if c_now >= pos["entry_price"] + 1.5 * r_dist:
        next_st = max(next_st, pos["entry_price"] + 0.15 * r_dist)
      if c_now >= pos["entry_price"] + 2.5 * r_dist:
        pos["trailing_active"] = True
      if pos["trailing_active"]:
        next_st = max(next_st, pos["highest_close"] - 1.8 * cur_atr)

      pos["next_stop"] = next_st
      pos["active_stop"] = pos["next_stop"]

    # STEP 5: Mark to Market
    total_nav = equity
    for sym, pos in active_positions.items():
      ind = all_data[sym]
      if d_str in ind["bar_dict"]:
        _, cur_bar = ind["bar_dict"][d_str]
        total_nav += pos["qty"] * (cur_bar.c - pos["entry_price"])
    if total_nav > peak_equity:
      peak_equity = total_nav
    dd = (peak_equity - total_nav) / peak_equity
    if dd > max_drawdown:
      max_drawdown = dd
    curve.append((d_str, total_nav))

    # STEP 6: Candidate Evaluation at Day T Close for T+1 Entry
    close_is_macro_bear = False
    close_is_macro_bull = True
    if d_str in spy_dict:
      s_idx, s_bar, s_ema50, s_ema200 = spy_dict[d_str]
      if s_bar.c < s_ema200 or s_ema50 < s_ema200:
        close_is_macro_bear = True
        close_is_macro_bull = False

    eval_max_pos = max_positions
    if dynamic_max_pos:
      eval_max_pos = max_positions if close_is_macro_bull else 1

    if len(active_positions) < eval_max_pos:
      candidates = []
      for sym, ind in all_data.items():
        if sym in active_positions:
          continue
        if d_str not in ind["bar_dict"]:
          continue
        idx, cur_bar = ind["bar_dict"][d_str]
        if idx < 60 or idx < cooldowns.get(sym, 0):
          continue

        is_equity = sym not in NON_EQUITY_SYMBOLS
        if close_is_macro_bear and is_equity:
          continue

        c_now = cur_bar.c
        cur_atr = ind["atr14"][idx]

        # First-Principles Volatility Floor
        if min_atr_pct > 0 and (cur_atr / c_now) < min_atr_pct:
          continue

        er_val = ind["ers"][idx]
        ema20_now = ind["ema20"][idx]
        ema50_now = ind["ema50"][idx]
        ema200_now = ind["ema200"][idx]
        rs_val = ind["rs60"][idx]

        # Medium-term momentum gate: filter out assets in 3-month downtrend (< -3%)
        if min_rs60 is not None and rs_val < min_rs60:
          continue

        # Structural Trend Gate & Golden Cross
        if c_now < ema200_now:
          continue
        if strict_golden_cross and ema50_now <= ema200_now:
          continue

        w_bars = ind["bars"][max(0, idx - 30) : idx + 1]
        s_code, s_name, poc_p, vah, val, profit_ratio, concentration = (
            compute_profile_state(w_bars, c_now, cur_atr)
        )
        if s_code == 3:
          continue

        mean_v = statistics.mean(
            [b.v for b in ind["bars"][max(0, idx - 20) : idx]]
        )
        vol_surge = cur_bar.v / (mean_v + 1e-9)
        chan_high = max(b.h for b in ind["bars"][idx - 20 : idx])
        trend_aligned = (c_now > ema20_now) and (ema20_now > ema50_now)
        rs_bonus = max(0.0, rs_val * 4.0)

        # Trigger 1: Trend Breakout
        if (
            s_code in [1, 2]
            and c_now > chan_high
            and trend_aligned
            and er_val >= er_min
        ):
          if breakout_quality_filter:
            bar_range = cur_bar.h - cur_bar.l
            if bar_range > 0 and (cur_bar.c - cur_bar.l) / bar_range < 0.65:
              continue
          score = 2.5 + 3.0 * (er_val - er_min) + rs_bonus
          if s_code == 1:
            score += 1.0
          if vol_surge >= 1.15:
            score += 0.8
          candidates.append({
              "symbol": sym,
              "score": score,
              "trade_type": "TREND_BREAKOUT",
              "init_stop": c_now - 1.8 * cur_atr,
              "target_p": 0.0,
          })

        # Trigger 2: Trend Pullback
        is_pullback = (
            (cur_bar.l <= ema20_now * 1.02)
            and (cur_bar.c > ema20_now)
            and (cur_bar.c > cur_bar.o)
        )
        if s_code == 2 and trend_aligned and is_pullback and er_val >= er_min:
          score = 2.3 + 2.5 * (er_val - er_min) + rs_bonus
          pb_stop = min(cur_bar.l, ema20_now) - 1.5 * cur_atr
          candidates.append({
              "symbol": sym,
              "score": score,
              "trade_type": "TREND_PULLBACK",
              "init_stop": pb_stop,
              "target_p": 0.0,
          })

        # Trigger 3: Mean Reversion (Right-side green candle reclaim confirmation)
        bb_low = ind["bb_lower"][idx]
        is_mr = (
            s_code == 4
            and cur_bar.l < bb_low
            and cur_bar.c > bb_low
            and (not mr_require_green or cur_bar.c > cur_bar.o)
        )
        if is_mr:
          spr_stop = cur_bar.l - 1.0 * cur_atr
          spr_tp = cur_bar.c + 1.5 * abs(cur_bar.c - spr_stop)
          candidates.append({
              "symbol": sym,
              "score": 2.2 + rs_bonus,
              "trade_type": "MEAN_REVERSION",
              "init_stop": spr_stop,
              "target_p": spr_tp,
          })

      if candidates:
        candidates.sort(key=lambda x: x["score"], reverse=True)
        needed = eval_max_pos - len(active_positions)
        if orthogonal_tier_limit:
          active_eq = sum(
              1 for s in active_positions if s not in NON_EQUITY_SYMBOLS
          )
          pending_orders = []
          p_eq = active_eq
          for cand in candidates:
            is_eq = cand["symbol"] not in NON_EQUITY_SYMBOLS
            if is_eq and p_eq >= 1:
              continue
            pending_orders.append(cand)
            if is_eq:
              p_eq += 1
            if len(pending_orders) >= needed:
              break
        else:
          pending_orders = candidates[:needed]

  final_eq = curve[-1][1] if curve else equity
  ret_pct = ((final_eq - initial_capital) / initial_capital) * 100.0
  wins = [t for t in trades if t["net_pnl_usd"] > 0]
  win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
  tot_gain = sum(t["net_pnl_usd"] for t in wins)
  losses = [t for t in trades if t["net_pnl_usd"] <= 0]
  tot_loss = abs(sum(t["net_pnl_usd"] for t in losses))
  pf = (tot_gain / tot_loss) if tot_loss > 0 else 999.0
  calmar = (ret_pct / (max_drawdown * 100.0)) if max_drawdown > 0 else 0.0

  sym_pnl = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
  for t in trades:
    s = t["symbol"]
    sym_pnl[s]["count"] += 1
    sym_pnl[s]["pnl"] += t["net_pnl_usd"]
    if t["net_pnl_usd"] > 0:
      sym_pnl[s]["wins"] += 1

  return {
      "return_pct": ret_pct,
      "mdd_pct": max_drawdown * 100.0,
      "win_rate": win_rate,
      "profit_factor": pf,
      "trade_count": len(trades),
      "final_equity": final_eq,
      "calmar": calmar,
      "sym_pnl": dict(sym_pnl),
      "total_borrow_interest_paid": total_borrow_interest_paid,
      "total_funding_fees_paid": total_funding_fees_paid,
      "total_cash_interest": total_cash_interest,
      "orthogonal_tier_limit": orthogonal_tier_limit,
      "trades": trades,
      "curve": curve,
  }
