"""Original macro ETF feature rules, shared by historical and live decisions."""
from __future__ import annotations
import math
import statistics
from qount.research_data.bars import Bar
from qount.research_data.regime import compute_ema, compute_kaufman_er, compute_profile_state
MACRO_TEN = ("SPY", "SMH", "IWM", "XLI", "XLB", "GLD", "CPER", "XLU", "TLT", "UUP")


def build_macro_features(fetched, contract_signals):
    indicators, sources = {}, []
    for ticker, bars, dates, source in fetched:
        sources.append(source)
        closes = [b.c for b in bars]
        ema20, ema50, ema200 = (compute_ema(closes, span) for span in (20, 50, 200))
        ers = compute_kaufman_er(closes, 20)
        rows = {}
        for i in range(200, len(bars)):
            b = bars[i]
            ret63 = b.c/closes[i-63]-1
            returns = [math.log(closes[j]/closes[j-1]) for j in range(i-19, i+1)]
            sigma = statistics.stdev(returns)*math.sqrt(252)
            tr = [max(bars[j].h-bars[j].l, abs(bars[j].h-bars[j-1].c), abs(bars[j].l-bars[j-1].c))
                  for j in range(i-13, i+1)]
            vol = statistics.mean(tr)
            state, label, *_ = compute_profile_state(bars[i-30:i+1], b.c, vol)
            structural = b.c > ema200[i] and ema50[i] > ema200[i] and ret63 > 0
            aligned = b.c > ema20[i] > ema50[i]
            green = b.c > b.o
            breakout = b.c > max(x.h for x in bars[i-20:i])
            pullback = b.l <= 1.02*ema20[i] and b.c > ema20[i] and green
            lower = statistics.mean(closes[i-19:i+1])-2*statistics.pstdev(closes[i-19:i+1])
            mr = state == 4 and b.l < lower < b.c and green
            trend_setup = state in (1, 2) and aligned and ers[i] >= 0.28 and (breakout or (state == 2 and pullback))
            score = (2.5+3*max(ers[i]-0.28, 0) if trend_setup else 2.2 if mr else 0)+max(0, ret63*4)
            state_gross = 3.0 if aligned and ers[i] >= 0.28 and state in (1, 2) else 1.0 if mr else 1.5
            # Reflect only the already available31-bar window to classify the
            # bearish counterpart with the same pure state function. These
            # artificial bars never enter execution prices or PnL.
            window = bars[i-30:i+1]
            pivot = 2*max(x.h for x in window)
            mirrored = [Bar(x.t, pivot-x.o, pivot-x.l, pivot-x.h, pivot-x.c, x.v) for x in window]
            short_state, short_label, *_ = compute_profile_state(mirrored, pivot-b.c, vol)
            bear = b.c < ema200[i] and ema50[i] < ema200[i] and ret63 < 0
            ret20 = b.c/closes[i-20]-1
            bear_fast = b.c < ema20[i] < ema50[i] and ret20 < 0
            down = b.c < ema20[i] < ema50[i]
            breakdown = b.c < min(x.l for x in bars[i-20:i])
            bounce = b.h >= 0.98*ema20[i] and b.c < ema20[i] and b.c < b.o
            upper = statistics.mean(closes[i-19:i+1])+2*statistics.pstdev(closes[i-19:i+1])
            short_mr = short_state == 4 and b.h > upper > b.c and b.c < b.o
            short_trend = short_state in (1, 2) and down and ers[i] >= 0.28 and (breakdown or (short_state == 2 and bounce))
            short_score = (2.5+3*max(ers[i]-0.28, 0) if short_trend else 2.2 if short_mr else 0)+max(0, -ret63*4)
            short_gross = 3.0 if down and ers[i] >= 0.28 and short_state in (1, 2) else 1.0 if short_mr else 1.5
            rows[dates[i]] = {"available": b.t, "date": dates[i], "state": label,
                             "entry_core": structural and b.c > ema20[i] and state != 3,
                             "entry_tactical": structural and (trend_setup or mr),
                             "tactical_setup": ("breakout" if trend_setup and breakout else
                                                "pullback" if trend_setup else "mean_reversion" if mr else None),
                             "hold_core": structural and b.c > ema20[i] and state != 3,
                             "hold_tactical": structural and state != 3,
                             "hold_price_trend": structural and b.c > ema20[i],
                             "hold_structural": structural,
                             "rank_core": ret63, "rank_tactical": score,
                             "gross_target": min(state_gross, 0.60/max(sigma, 1e-6)),
                             "realized_vol20": sigma, "er20": ers[i], "structural": structural,
                             "above_ema50": b.c > ema50[i],
                             "bear_structural": bear, "state_short": short_label,
                             "entry_short": bear and (short_trend or short_mr),
                             "hold_short": bear and short_state != 3,
                             "bear_fast": b.c < ema20[i] and ret20 < 0,
                             "entry_short_tactical": bear_fast and (short_trend or short_mr),
                             "hold_short_tactical": bear_fast and short_state != 3,
                             "rank_short": short_score,
                             "gross_short": min(short_gross, 0.60/max(sigma, 1e-6))}
        indicators[ticker] = rows
    features = {}
    for contract, ticker in contract_signals.items():
        values = []
        for date, row in sorted(indicators[ticker].items()):
            spy = indicators["SPY"].get(date)
            if spy is None:
                raise ValueError("macro_calendar_mismatch")
            row = dict(row)
            # Equity systemic gate follows the C60 systemic/own-gate separation.
            # Commodities retain their own structural gate, not an equity veto.
            if contract not in ("XAUUSDT", "COPPERUSDT", "CLUSDT") and not spy["structural"]:
                for key in ("entry_core", "entry_tactical", "hold_core", "hold_tactical", "hold_price_trend", "hold_structural"):
                    row[key] = False
            if contract not in ("XAUUSDT", "COPPERUSDT", "CLUSDT") and not spy["bear_structural"]:
                row["entry_short"] = row["hold_short"] = False
            if contract not in ("XAUUSDT", "COPPERUSDT", "CLUSDT") and not spy["bear_fast"]:
                row["entry_short_tactical"] = row["hold_short_tactical"] = False
            row["macro_ten_above_ema50"] = sum(indicators[t].get(date, {}).get("above_ema50", False) for t in MACRO_TEN)
            values.append(row)
        features[contract] = values
    return features, sources

