import sys
from collections import defaultdict
import statistics
from qount.research.universal_regime_expectancy import (
    DailyBar, load_etf_bars, compute_ema, compute_atr, compute_kaufman_er, compute_profile_state,
    ALL_10_MACRO_SYMBOLS, NON_EQUITY_SYMBOLS
)

def run_experiment_engine(
    symbols=ALL_10_MACRO_SYMBOLS,
    start_date="2020-01-01",
    end_date="2026-07-30",
    initial_capital=1000.0,
    min_atr_pct=0.0085,
    orthogonal_tier_limit=True,
    # Architectural switches:
    equity_min_rs_vs_spy=False,      # Experiment 1A: Equity candidate must have RS60 >= SPY RS60
    allow_leader_swap=False,         # Experiment 1B: High-conviction leader can swap stagnant equity
    edge_decay_exit=False,           # Experiment 2: Exit when ER < 0.20 and Close < EMA20 (no waiting 30d)
    stagnant_exit_days=30,           # Baseline stagnant exit
    gap_stress_pct=0.015,
):
    spy_bars = load_etf_bars("SPY")
    spy_closes = [b.c for b in spy_bars]
    spy_ema50 = compute_ema(spy_closes, 50)
    spy_ema200 = compute_ema(spy_closes, 200)
    spy_rs60 = []
    for i in range(len(spy_bars)):
        if i >= 60:
            spy_rs60.append((spy_closes[i] / spy_closes[i - 60]) - 1.0)
        else:
            spy_rs60.append(0.0)
    spy_dict = {b.d: (i, b, spy_ema50[i], spy_ema200[i], spy_rs60[i]) for i, b in enumerate(spy_bars)}

    all_data = {}
    all_dates = set()
    for sym in symbols:
        try:
            bars = load_etf_bars(sym)
        except Exception:
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

    fee_pct = 0.0003
    entry_slip_pct = 0.0005
    exit_slip_pct = 0.0005
    stop_slip_pct = 0.0005

    for d_str in sorted_dates:
        # Day T+1 Morning Open
        open_is_macro_bear = False
        open_is_macro_bull = True
        if d_str in spy_dict:
            s_idx, s_bar, s_ema50, s_ema200, _ = spy_dict[d_str]
            if s_idx > 0:
                prev_bar = spy_bars[s_idx - 1]
                prev_ema50 = spy_ema50[s_idx - 1]
                prev_ema200 = spy_ema200[s_idx - 1]
                if prev_bar.c < prev_ema200 or prev_ema50 < prev_ema200:
                    open_is_macro_bear = True
                    open_is_macro_bull = False

        cur_max_pos = 2 if open_is_macro_bull else 1

        # STEP 1: Execute Pending Entry Orders at Open T+1
        if pending_orders:
            for cand in pending_orders:
                sym = cand["symbol"]
                ind = all_data[sym]
                if d_str not in ind["bar_dict"]:
                    continue
                idx, cur_bar = ind["bar_dict"][d_str]
                is_equity = sym not in NON_EQUITY_SYMBOLS

                if open_is_macro_bear and is_equity:
                    continue

                # Leader Swap Logic: If swap was requested, execute close of weaker asset first
                if cand.get("swap_out"):
                    swap_sym = cand["swap_out"]
                    if swap_sym in active_positions:
                        old_pos = active_positions[swap_sym]
                        old_bar = all_data[swap_sym]["bar_dict"][d_str][1]
                        exit_p = old_bar.o * (1.0 - exit_slip_pct)
                        exit_fee = old_pos["qty"] * exit_p * fee_pct
                        net_pnl = old_pos["qty"] * (exit_p - old_pos["entry_price"]) - exit_fee
                        equity += net_pnl
                        trades.append({
                            "date": d_str, "symbol": swap_sym, "type": old_pos["trade_type"],
                            "entry_date": old_pos["entry_date"], "exit_date": d_str,
                            "holding_days": idx - old_pos["entry_idx"],
                            "net_pnl_usd": net_pnl, "exit_reason": "leader_swap_exit",
                            "equity_after": equity
                        })
                        del active_positions[swap_sym]

                if sym in active_positions or len(active_positions) >= cur_max_pos:
                    continue

                if orthogonal_tier_limit and is_equity:
                    active_equities = [s for s in active_positions if s not in NON_EQUITY_SYMBOLS]
                    if len(active_equities) >= 1:
                        continue

                open_p = cur_bar.o
                init_stop = cand["init_stop"]
                raw_stop_dist = open_p - init_stop
                cur_atr = ind["atr14"][idx - 1] if idx > 0 else open_p * 0.02
                eff_stop_dist = max(raw_stop_dist, 1.5 * cur_atr)

                if eff_stop_dist > 0:
                    risk_pct = 0.03 if cur_max_pos >= 2 else 0.04
                    risk_usd = equity * risk_pct
                    qty = risk_usd / eff_stop_dist
                    max_qty = (equity * 0.98 / cur_max_pos) / open_p
                    qty = min(qty, max_qty)

                    if qty * open_p >= 5.0:
                        entry_p = open_p * (1.0 + entry_slip_pct)
                        entry_fee = qty * entry_p * fee_pct
                        equity -= entry_fee
                        active_positions[sym] = {
                            "trade_type": cand["trade_type"],
                            "entry_date": d_str,
                            "entry_price": entry_p,
                            "qty": qty,
                            "risk_usd": risk_usd,
                            "initial_stop": init_stop,
                            "active_stop": init_stop,
                            "highest_close": open_p,
                            "trailing_active": False,
                            "target_p": cand["target_p"],
                            "entry_idx": idx,
                            "took_partial_profit": False,
                        }
            pending_orders = []

        # STEP 3: Exit Checks during Day T
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

            if pos["trade_type"] == "MEAN_REVERSION":
                is_tp = cur_bar.h >= pos["target_p"]
                is_sl = cur_bar.l <= stop_price_today
                is_max_hold = (idx - pos["entry_idx"]) >= 15
                if is_sl and is_tp:
                    is_tp = False
                if is_sl or is_tp or is_max_hold:
                    if is_sl:
                        raw_exit = min(cur_bar.o, stop_price_today) * (1.0 - gap_stress_pct)
                        reason = "mr_stop"
                        slip = stop_slip_pct
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
                        "date": d_str, "symbol": sym, "type": pos["trade_type"],
                        "entry_date": pos["entry_date"], "exit_date": d_str,
                        "holding_days": idx - pos["entry_idx"], "net_pnl_usd": net_pnl,
                        "exit_reason": reason, "equity_after": equity
                    })
                    cooldowns[sym] = idx + (5 if "stop" in reason else 2)
                    del active_positions[sym]
                    continue
            else:
                # Trend Trade Exits
                is_sl = cur_bar.l <= stop_price_today
                hold_days = idx - pos["entry_idx"]
                is_max_hold = hold_days >= 45

                # Stagnant Exit
                is_stagnant = False
                if stagnant_exit_days is not None and hold_days >= stagnant_exit_days:
                    unrealized_r = (c_now - pos["entry_price"]) / (r_dist + 1e-9)
                    if unrealized_r < 0.8:
                        is_stagnant = True

                # Edge-Decay Exit (Architectural Experiment 2)
                is_decay = False
                if edge_decay_exit and hold_days >= 7:
                    er_val = ind["ers"][idx]
                    ema20_val = ind["ema20"][idx]
                    unrealized_r = (c_now - pos["entry_price"]) / (r_dist + 1e-9)
                    if er_val < 0.18 and c_now < ema20_val and unrealized_r < 0.5:
                        is_decay = True

                can_tp = (not pos["took_partial_profit"]) and (r_dist > 0)
                is_tp3r = can_tp and ((cur_bar.h - pos["entry_price"]) >= 3.0 * r_dist)
                if is_sl and is_tp3r:
                    is_tp3r = False

                if is_tp3r:
                    half_qty = pos["qty"] * 0.5
                    tp_price = pos["entry_price"] + 3.0 * r_dist
                    realized_pnl = half_qty * (tp_price - pos["entry_price"]) - (half_qty * tp_price * fee_pct)
                    equity += realized_pnl
                    pos["qty"] -= half_qty
                    pos["took_partial_profit"] = True
                    trades.append({
                        "date": d_str, "symbol": sym, "type": pos["trade_type"] + "_TP50",
                        "entry_date": pos["entry_date"], "exit_date": d_str,
                        "holding_days": idx - pos["entry_idx"], "net_pnl_usd": realized_pnl,
                        "exit_reason": "partial_tp3r", "equity_after": equity
                    })
                    is_sl = cur_bar.l <= stop_price_today

                if is_sl or is_max_hold or is_stagnant or is_decay:
                    if is_sl:
                        raw_exit = min(cur_bar.o, stop_price_today) * (1.0 - gap_stress_pct)
                        reason = "trailing_stop" if pos["trailing_active"] else "initial_stop"
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
                        "date": d_str, "symbol": sym, "type": pos["trade_type"],
                        "entry_date": pos["entry_date"], "exit_date": d_str,
                        "holding_days": idx - pos["entry_idx"], "net_pnl_usd": net_pnl,
                        "exit_reason": reason, "equity_after": equity
                    })
                    cooldowns[sym] = idx + (5 if reason == "initial_stop" else 2)
                    del active_positions[sym]
                    continue

        # STEP 4: End of Day T Close Trailing Stop
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
            pos["active_stop"] = next_st

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

        # STEP 6: Candidate Evaluation at Day T Close
        close_is_macro_bear = False
        close_is_macro_bull = True
        spy_rs_now = 0.0
        if d_str in spy_dict:
            s_idx, s_bar, s_ema50, s_ema200, spy_rs_now = spy_dict[d_str]
            if s_bar.c < s_ema200 or s_ema50 < s_ema200:
                close_is_macro_bear = True
                close_is_macro_bull = False

        eval_max_pos = 2 if close_is_macro_bull else 1

        candidates = []
        for sym, ind in all_data.items():
            if sym in active_positions or d_str not in ind["bar_dict"]:
                continue
            idx, cur_bar = ind["bar_dict"][d_str]
            if idx < 60 or idx < cooldowns.get(sym, 0):
                continue

            is_equity = sym not in NON_EQUITY_SYMBOLS
            if close_is_macro_bear and is_equity:
                continue

            c_now = cur_bar.c
            cur_atr = ind["atr14"][idx]
            if min_atr_pct > 0 and (cur_atr / c_now) < min_atr_pct:
                continue

            er_val = ind["ers"][idx]
            ema20_now = ind["ema20"][idx]
            ema50_now = ind["ema50"][idx]
            ema200_now = ind["ema200"][idx]
            rs_val = ind["rs60"][idx]

            if rs_val < -0.03:
                continue

            # Experiment 1A: Relative Strength Benchmark Gate
            # Equities must outperform or tie SPY over 60 days
            if equity_min_rs_vs_spy and is_equity and rs_val < spy_rs_now:
                continue

            if c_now < ema200_now or ema50_now <= ema200_now:
                continue

            w_bars = ind["bars"][max(0, idx - 30) : idx + 1]
            s_code, s_name, poc_p, vah, val, profit_ratio, concentration = compute_profile_state(w_bars, c_now, cur_atr)
            if s_code == 3:
                continue

            mean_v = sum(b.v for b in ind["bars"][max(0, idx - 20) : idx]) / 20.0
            vol_surge = cur_bar.v / (mean_v + 1e-9)
            chan_high = max(b.h for b in ind["bars"][idx - 20 : idx])
            trend_aligned = (c_now > ema20_now) and (ema20_now > ema50_now)
            rs_bonus = max(0.0, rs_val * 4.0)

            # Breakout
            if s_code in [1, 2] and c_now > chan_high and trend_aligned and er_val >= 0.28:
                bar_range = cur_bar.h - cur_bar.l
                if bar_range > 0 and (cur_bar.c - cur_bar.l) / bar_range >= 0.65:
                    score = 2.5 + 3.0 * (er_val - 0.28) + rs_bonus
                    if s_code == 1: score += 1.0
                    if vol_surge >= 1.15: score += 0.8
                    candidates.append({
                        "symbol": sym, "score": score, "trade_type": "TREND_BREAKOUT",
                        "init_stop": c_now - 1.8 * cur_atr, "target_p": 0.0, "rs": rs_val
                    })

            # Pullback
            is_pullback = (cur_bar.l <= ema20_now * 1.02) and (cur_bar.c > ema20_now) and (cur_bar.c > cur_bar.o)
            if s_code == 2 and trend_aligned and is_pullback and er_val >= 0.28:
                score = 2.3 + 2.5 * (er_val - 0.28) + rs_bonus
                candidates.append({
                    "symbol": sym, "score": score, "trade_type": "TREND_PULLBACK",
                    "init_stop": min(cur_bar.l, ema20_now) - 1.5 * cur_atr, "target_p": 0.0, "rs": rs_val
                })

            # Mean Reversion
            bb_low = ind["bb_lower"][idx]
            if s_code == 4 and cur_bar.l < bb_low and cur_bar.c > bb_low and cur_bar.c > cur_bar.o:
                spr_stop = cur_bar.l - 1.0 * cur_atr
                candidates.append({
                    "symbol": sym, "score": 2.2 + rs_bonus, "trade_type": "MEAN_REVERSION",
                    "init_stop": spr_stop, "target_p": cur_bar.c + 1.5 * abs(cur_bar.c - spr_stop), "rs": rs_val
                })

        if candidates:
            candidates.sort(key=lambda x: x["score"], reverse=True)

            # Experiment 1B: Leader Swap
            # If active equity is stagnant (held >= 10 days, unrealized R < 0.5) and top candidate is a roaring leader (score >= 4.0 and rs >= 0.15)
            if allow_leader_swap and orthogonal_tier_limit:
                active_eq_syms = [s for s in active_positions if s not in NON_EQUITY_SYMBOLS]
                if active_eq_syms:
                    curr_eq = active_eq_syms[0]
                    curr_pos = active_positions[curr_eq]
                    curr_ind = all_data[curr_eq]
                    c_idx = curr_ind["bar_dict"][d_str][0]
                    h_days = c_idx - curr_pos["entry_idx"]
                    r_dist = abs(curr_pos["entry_price"] - curr_pos["initial_stop"])
                    curr_c = curr_ind["bar_dict"][d_str][1].c
                    curr_unr = (curr_c - curr_pos["entry_price"]) / (r_dist + 1e-9)

                    # Top candidate is an equity with overwhelming strength
                    top_eq_cand = next((c for c in candidates if c["symbol"] not in NON_EQUITY_SYMBOLS), None)
                    if top_eq_cand and top_eq_cand["score"] >= 3.8 and top_eq_cand["rs"] >= 0.12:
                        if h_days >= 10 and curr_unr < 0.4:
                            top_eq_cand["swap_out"] = curr_eq

            # Selection
            needed = eval_max_pos - len(active_positions)
            if orthogonal_tier_limit:
                active_eq = sum(1 for s in active_positions if s not in NON_EQUITY_SYMBOLS)
                pending_orders = []
                p_eq = active_eq
                for cand in candidates:
                    is_eq = cand["symbol"] not in NON_EQUITY_SYMBOLS
                    if cand.get("swap_out"):
                        # Swap replaces equity slot
                        is_eq = True
                        p_eq = 0
                    if is_eq and p_eq >= 1:
                        continue
                    pending_orders.append(cand)
                    if is_eq:
                        p_eq += 1
                    if len(pending_orders) >= max(needed, 1):
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

    return {
        "return_pct": ret_pct, "mdd_pct": max_drawdown * 100.0,
        "win_rate": win_rate, "profit_factor": pf, "trade_count": len(trades),
        "calmar": calmar, "curve": curve, "trades": trades
    }

print("Running Architectural Experiments...")

exp_configs = [
    ("1. v1.5 Baseline", {}),
    ("2. Exp 1A: Equity RS >= SPY RS Gate (Filter Laggards)", {"equity_min_rs_vs_spy": True}),
    ("3. Exp 1B: Leader Swap (Upgrade Stagnant Equity)", {"allow_leader_swap": True}),
    ("4. Exp 2:  Edge-Decay Exit (ER<0.18 & Close<EMA20)", {"edge_decay_exit": True}),
    ("5. Exp 1+2 Combined: Leader Swap + Edge Decay", {"allow_leader_swap": True, "edge_decay_exit": True}),
    ("6. Exp 1+2 + 0.95% Vol Floor", {"allow_leader_swap": True, "edge_decay_exit": True, "min_atr_pct": 0.0095}),
]

print("\n" + "=" * 90)
print(f"{'Experiment Configuration':<45} | {'Ret %':<8} | {'MDD %':<7} | {'Calmar':<6} | {'Win %':<6} | {'PF':<5} | {'Trades'}")
print("-" * 90)

results = {}
for name, kwargs in exp_configs:
    res = run_experiment_engine(**kwargs)
    results[name] = res
    ret = res['return_pct']
    mdd = res['mdd_pct']
    cal = res['calmar']
    wr = res['win_rate']
    pf = res['profit_factor']
    tc = res['trade_count']
    print(f"{name:<45} | {ret:+6.2f}%  | {mdd:5.2f}% | {cal:5.2f}  | {wr:5.1f}% | {pf:4.2f} | {tc}")

# Annual breakdown for Baseline vs Combined
print("\n" + "=" * 90)
print("ANNUAL RETURN EVOLUTION: Baseline vs Architectural Upgrades (Exp 5 & 6)")
print("-" * 90)
print(f"{'Year':<6} | {'v1.5 Baseline':<15} | {'Exp 5 (Swap+Decay)':<20} | {'Exp 6 (+0.95% Vol Floor)'}")
print("-" * 90)

years = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
for y in years:
    cb = [p[1] for p in results["1. v1.5 Baseline"]["curve"] if p[0].startswith(y)]
    rb = ((cb[-1] - cb[0]) / cb[0] * 100) if cb else 0.0

    c5 = [p[1] for p in results["5. Exp 1+2 Combined: Leader Swap + Edge Decay"]["curve"] if p[0].startswith(y)]
    r5 = ((c5[-1] - c5[0]) / c5[0] * 100) if c5 else 0.0

    c6 = [p[1] for p in results["6. Exp 1+2 + 0.95% Vol Floor"]["curve"] if p[0].startswith(y)]
    r6 = ((c6[-1] - c6[0]) / c6[0] * 100) if c6 else 0.0

    print(f"{y:<6} | {rb:+6.2f}%          | {r5:+6.2f}%              | {r6:+6.2f}%")

