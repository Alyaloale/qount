"""Pure regime features preserved from the historical reference implementation."""
from __future__ import annotations
from typing import Any, List, Tuple
DailyBar = Any

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
