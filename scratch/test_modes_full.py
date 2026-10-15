import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scratch.test_causal_architecture import (
    load_etf_bars, compute_ema, compute_atr, compute_kaufman_er,
    compute_profile_state, ALL_10_MACRO_SYMBOLS, NON_EQUITY_SYMBOLS
)
import statistics
from collections import defaultdict

def run_full_modes(er_min=0.28):
    for period_name, s_d, e_d in [('2025-2026 Recent', '2025-01-01', '2026-07-30'), ('2020-2026 Full', '2020-01-01', '2026-07-30')]:
        print(f"\n>>> PERIOD: {period_name}")
        for mode in ['1X_SPOT', 'TRADIFI_MARGIN_2X', 'BINANCE_PERP_2X']:
            symbols = ALL_10_MACRO_SYMBOLS
            data_dir = 'data/raw'
            spy_bars = load_etf_bars('SPY', data_dir=data_dir)
            spy_closes = [b.c for b in spy_bars]
            spy_ema50 = compute_ema(spy_closes, 50)
            spy_ema200 = compute_ema(spy_closes, 200)
            spy_dict = {b.d: (i, b, spy_ema50[i], spy_ema200[i]) for i, b in enumerate(spy_bars)}

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
                        win_p = closes[i-19:i+1]
                        m_p = sum(win_p) / 20.0
                        s_p = (sum((x - m_p)**2 for x in win_p) / 20.0)**0.5
                        bb_lower.append(m_p - 2.0 * s_p)

                    if i >= 60:
                        rs60.append((closes[i] / closes[i-60]) - 1.0)
                    else:
                        rs60.append(0.0)

                bar_dict = {b.d: (i, b) for i, b in enumerate(bars)}
                for b in bars:
                    if s_d <= b.d <= e_d:
                        all_dates.add(b.d)

                all_data[sym] = {
                    'bars': bars,
                    'bar_dict': bar_dict,
                    'atr14': atr14,
                    'ema20': ema20,
                    'ema50': ema50,
                    'ema200': ema200,
                    'bb_lower': bb_lower,
                    'ers': ers,
                    'rs60': rs60,
                }

            sorted_dates = sorted(list(all_dates))
            trades = []
            equity = 1000.0
            peak_equity = 1000.0
            max_drawdown = 0.0
            curve = []
            active_positions = {}
            cooldowns = {}
            pending_orders = []

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
                margin_borrow_apr = 0.060
                daily_funding_rate = 0.0
            elif mode == "BINANCE_PERP_2X":
                leverage = 2.0
                fee_pct = 0.0004
                entry_slip_pct = 0.0010
                exit_slip_pct = 0.0010
                stop_slip_pct = 0.0040
                margin_borrow_apr = 0.0
                daily_funding_rate = 0.0001

            total_borrow_interest_paid = 0.0
            total_funding_fees_paid = 0.0
            gap_stress_pct = 0.015

            for d_str in sorted_dates:
                open_is_macro_bear = False
                open_is_macro_bull = True
                if d_str in spy_dict:
                    s_idx, s_bar, s_ema50, s_ema200 = spy_dict[d_str]
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
                        sym = cand['symbol']
                        if sym in active_positions or len(active_positions) >= cur_max_pos:
                            continue
                        ind = all_data[sym]
                        if d_str not in ind['bar_dict']:
                            continue
                        idx, cur_bar = ind['bar_dict'][d_str]

                        is_equity = sym not in NON_EQUITY_SYMBOLS
                        if open_is_macro_bear and is_equity:
                            continue

                        if is_equity:
                            active_equities = [s for s in active_positions if s not in NON_EQUITY_SYMBOLS]
                            if len(active_equities) >= 1:
                                continue

                        open_p = cur_bar.o
                        init_stop = cand['init_stop']
                        raw_stop_dist = open_p - init_stop
                        cur_atr = ind['atr14'][idx - 1] if idx > 0 else open_p * 0.02
                        eff_stop_dist = max(raw_stop_dist, 1.5 * cur_atr)

                        if eff_stop_dist > 0:
                            risk_pct = 0.03 if cur_max_pos >= 2 else 0.04
                            risk_usd = equity * risk_pct
                            qty = risk_usd / eff_stop_dist

                            if leverage > 1.0:
                                max_qty = (equity * leverage * 0.95 / cur_max_pos) / open_p
                            else:
                                max_qty = (equity * 0.98 / cur_max_pos) / open_p
                            qty = min(qty, max_qty)

                            if qty * open_p >= 5.0:
                                entry_p = open_p * (1.0 + entry_slip_pct)
                                entry_fee = qty * entry_p * fee_pct
                                equity -= entry_fee
                                notional = qty * entry_p
                                borrowed_usd = notional * 0.5 if mode == "TRADIFI_MARGIN_2X" else 0.0
                                active_positions[sym] = {
                                    'trade_type': cand['trade_type'],
                                    'entry_date': d_str,
                                    'entry_price': entry_p,
                                    'qty': qty,
                                    'orig_qty': qty,
                                    'risk_usd': risk_usd,
                                    'initial_stop': init_stop,
                                    'active_stop': init_stop,
                                    'next_stop': init_stop,
                                    'highest_close': open_p,
                                    'trailing_active': False,
                                    'target_p': cand['target_p'],
                                    'entry_idx': idx,
                                    'took_partial_profit': False,
                                    'borrowed_usd': borrowed_usd,
                                }
                    pending_orders = []

                # STEP 2: Accrue Daily Financing & Borrow Interest
                for sym, pos in active_positions.items():
                    if mode == "TRADIFI_MARGIN_2X":
                        daily_interest = pos["borrowed_usd"] * (margin_borrow_apr / 365.0)
                        equity -= daily_interest
                        total_borrow_interest_paid += daily_interest
                    elif mode == "BINANCE_PERP_2X":
                        c_now = all_data[sym]["bar_dict"][d_str][1].c if d_str in all_data[sym]["bar_dict"] else pos["entry_price"]
                        funding = pos["qty"] * c_now * daily_funding_rate
                        equity -= funding
                        total_funding_fees_paid += funding

                # STEP 3: Exit Checks during Day T
                for sym in list(active_positions.keys()):
                    pos = active_positions[sym]
                    ind = all_data[sym]
                    if d_str not in ind['bar_dict']:
                        continue
                    idx, cur_bar = ind['bar_dict'][d_str]
                    stop_price_today = pos['active_stop']

                    if pos['trade_type'] == 'MEAN_REVERSION':
                        is_tp = cur_bar.h >= pos['target_p']
                        is_sl = cur_bar.l <= stop_price_today
                        is_max_hold = (idx - pos['entry_idx']) >= 15

                        if is_tp or is_sl or is_max_hold:
                            if is_sl and is_tp:
                                is_tp = False

                            if is_sl:
                                raw_exit = min(cur_bar.o, stop_price_today) * (1.0 - gap_stress_pct)
                                reason = 'mr_stop'
                                slip = stop_slip_pct
                            elif is_tp:
                                raw_exit = pos['target_p']
                                reason = 'mr_tp'
                                slip = exit_slip_pct
                            else:
                                raw_exit = cur_bar.o
                                reason = 'mr_max_hold'
                                slip = exit_slip_pct

                            exit_p = raw_exit * (1.0 - slip)
                            exit_fee = pos['qty'] * exit_p * fee_pct
                            net_pnl = pos['qty'] * (exit_p - pos['entry_price']) - exit_fee
                            equity += net_pnl
                            trades.append({
                                'date': d_str,
                                'symbol': sym,
                                'type': pos['trade_type'],
                                'entry_date': pos['entry_date'],
                                'exit_date': d_str,
                                'holding_days': idx - pos['entry_idx'],
                                'entry_price': pos['entry_price'],
                                'exit_price': exit_p,
                                'quantity': pos['qty'],
                                'net_pnl_usd': net_pnl,
                                'net_R': net_pnl / (pos['risk_usd'] + 1e-9),
                                'exit_reason': reason,
                                'equity_after': equity,
                            })
                            cooldowns[sym] = idx + (5 if 'stop' in reason else 2)
                            del active_positions[sym]
                            continue
                    else:
                        is_sl = cur_bar.l <= stop_price_today
                        is_max_hold = (idx - pos['entry_idx']) >= 45
                        r_dist = abs(pos['entry_price'] - pos['initial_stop'])

                        can_tp = (not pos['took_partial_profit']) and (r_dist > 0)
                        is_tp3r = can_tp and ((cur_bar.h - pos['entry_price']) >= 3.0 * r_dist)

                        if is_sl and is_tp3r:
                            is_tp3r = False

                        if is_tp3r:
                            half_qty = pos['qty'] * 0.5
                            tp_price = pos['entry_price'] + 3.0 * r_dist
                            realized_pnl = half_qty * (tp_price - pos['entry_price']) - (half_qty * tp_price * fee_pct)
                            equity += realized_pnl
                            pos['qty'] -= half_qty
                            pos['took_partial_profit'] = True
                            trades.append({
                                'date': d_str,
                                'symbol': sym,
                                'type': pos['trade_type'] + '_TP50',
                                'entry_date': pos['entry_date'],
                                'exit_date': d_str,
                                'holding_days': idx - pos['entry_idx'],
                                'entry_price': pos['entry_price'],
                                'exit_price': tp_price,
                                'quantity': half_qty,
                                'net_pnl_usd': realized_pnl,
                                'net_R': 1.5,
                                'exit_reason': 'partial_tp3r',
                                'equity_after': equity,
                            })
                            is_sl = cur_bar.l <= stop_price_today

                        if is_sl or is_max_hold:
                            if is_sl:
                                raw_exit = min(cur_bar.o, stop_price_today) * (1.0 - gap_stress_pct)
                                reason = 'trailing_stop' if pos['trailing_active'] else 'initial_stop'
                                slip = stop_slip_pct
                            else:
                                raw_exit = cur_bar.o
                                reason = 'max_hold'
                                slip = exit_slip_pct

                            exit_p = raw_exit * (1.0 - slip)
                            exit_fee = pos['qty'] * exit_p * fee_pct
                            net_pnl = pos['qty'] * (exit_p - pos['entry_price']) - exit_fee
                            equity += net_pnl
                            trades.append({
                                'date': d_str,
                                'symbol': sym,
                                'type': pos['trade_type'],
                                'entry_date': pos['entry_date'],
                                'exit_date': d_str,
                                'holding_days': idx - pos['entry_idx'],
                                'entry_price': pos['entry_price'],
                                'exit_price': exit_p,
                                'quantity': pos['qty'],
                                'net_pnl_usd': net_pnl,
                                'net_R': net_pnl / (pos['risk_usd'] + 1e-9),
                                'exit_reason': reason,
                                'equity_after': equity,
                            })
                            cooldowns[sym] = idx + (5 if reason == 'initial_stop' else 2)
                            del active_positions[sym]
                            continue

                # STEP 4: Trailing Stop update at Day T Close
                for sym, pos in active_positions.items():
                    ind = all_data[sym]
                    if d_str not in ind['bar_dict']:
                        continue
                    idx, cur_bar = ind['bar_dict'][d_str]
                    cur_atr = ind['atr14'][idx]
                    c_now = cur_bar.c
                    r_dist = abs(pos['entry_price'] - pos['initial_stop'])
                    pos['highest_close'] = max(pos['highest_close'], c_now)

                    next_st = pos['active_stop']
                    if pos['took_partial_profit']:
                        next_st = max(next_st, pos['entry_price'])
                    if c_now >= pos['entry_price'] + 1.5 * r_dist:
                        next_st = max(next_st, pos['entry_price'] + 0.15 * r_dist)
                    if c_now >= pos['entry_price'] + 2.5 * r_dist:
                        pos['trailing_active'] = True
                    if pos['trailing_active']:
                        next_st = max(next_st, pos['highest_close'] - 1.8 * cur_atr)

                    pos['next_stop'] = next_st
                    pos['active_stop'] = pos['next_stop']

                # STEP 5: Mark to Market
                total_nav = equity
                for sym, pos in active_positions.items():
                    ind = all_data[sym]
                    if d_str in ind['bar_dict']:
                        _, cur_bar = ind['bar_dict'][d_str]
                        total_nav += pos['qty'] * (cur_bar.c - pos['entry_price'])
                if total_nav > peak_equity:
                    peak_equity = total_nav
                dd = (peak_equity - total_nav) / peak_equity
                if dd > max_drawdown:
                    max_drawdown = dd
                curve.append((d_str, total_nav))

                # STEP 6: Candidate Evaluation at Day T Close for Day T+1 Entry
                close_is_macro_bear = False
                close_is_macro_bull = True
                if d_str in spy_dict:
                    s_idx, s_bar, s_ema50, s_ema200 = spy_dict[d_str]
                    if s_bar.c < s_ema200 or s_ema50 < s_ema200:
                        close_is_macro_bear = True
                        close_is_macro_bull = False

                eval_max_pos = 2 if close_is_macro_bull else 1

                if len(active_positions) < eval_max_pos:
                    candidates = []
                    for sym, ind in all_data.items():
                        if sym in active_positions:
                            continue
                        if d_str not in ind['bar_dict']:
                            continue
                        idx, cur_bar = ind['bar_dict'][d_str]
                        if idx < 60 or idx < cooldowns.get(sym, 0):
                            continue

                        is_equity = sym not in NON_EQUITY_SYMBOLS
                        if close_is_macro_bear and is_equity:
                            continue

                        c_now = cur_bar.c
                        cur_atr = ind['atr14'][idx]

                        if (cur_atr / c_now) < 0.0085:
                            continue

                        er_val = ind['ers'][idx]
                        ema20_now = ind['ema20'][idx]
                        ema50_now = ind['ema50'][idx]
                        ema200_now = ind['ema200'][idx]
                        rs_val = ind['rs60'][idx]

                        if c_now < ema200_now:
                            continue
                        if ema50_now <= ema200_now:
                            continue

                        w_bars = ind['bars'][max(0, idx - 30):idx + 1]
                        s_code, s_name, poc_p, vah, val, profit_ratio, concentration = compute_profile_state(w_bars, c_now, cur_atr)
                        if s_code == 3:
                            continue

                        mean_v = statistics.mean([b.v for b in ind['bars'][max(0, idx - 20):idx]])
                        vol_surge = cur_bar.v / (mean_v + 1e-9)
                        chan_high = max(b.h for b in ind['bars'][idx - 20:idx])
                        trend_aligned = (c_now > ema20_now) and (ema20_now > ema50_now)
                        rs_bonus = max(0.0, rs_val * 4.0)

                        # Trigger 1: Trend Breakout
                        if s_code in [1, 2] and c_now > chan_high and trend_aligned and er_val >= er_min:
                            bar_range = cur_bar.h - cur_bar.l
                            if bar_range > 0 and (cur_bar.c - cur_bar.l) / bar_range < 0.65:
                                continue
                            score = 2.5 + 3.0 * (er_val - er_min) + rs_bonus
                            if s_code == 1:
                                score += 1.0
                            if vol_surge >= 1.15:
                                score += 0.8
                            candidates.append({
                                'symbol': sym,
                                'score': score,
                                'trade_type': 'TREND_BREAKOUT',
                                'init_stop': c_now - 1.8 * cur_atr,
                                'target_p': 0.0,
                            })

                        # Trigger 2: Trend Pullback
                        is_pullback = (cur_bar.l <= ema20_now * 1.02) and (cur_bar.c > ema20_now) and (cur_bar.c > cur_bar.o)
                        if s_code == 2 and trend_aligned and is_pullback and er_val >= er_min:
                            score = 2.3 + 2.5 * (er_val - er_min) + rs_bonus
                            pb_stop = min(cur_bar.l, ema20_now) - 1.5 * cur_atr
                            candidates.append({
                                'symbol': sym,
                                'score': score,
                                'trade_type': 'TREND_PULLBACK',
                                'init_stop': pb_stop,
                                'target_p': 0.0,
                            })

                        # Trigger 3: Mean Reversion
                        bb_low = ind['bb_lower'][idx]
                        if s_code == 4 and cur_bar.l < bb_low and cur_bar.c > bb_low:
                            spr_stop = cur_bar.l - 1.0 * cur_atr
                            spr_tp = cur_bar.c + 1.5 * abs(cur_bar.c - spr_stop)
                            candidates.append({
                                'symbol': sym,
                                'score': 2.2 + rs_bonus,
                                'trade_type': 'MEAN_REVERSION',
                                'init_stop': spr_stop,
                                'target_p': spr_tp,
                            })

                    if candidates:
                        candidates.sort(key=lambda x: x['score'], reverse=True)
                        needed = eval_max_pos - len(active_positions)
                        active_eq = sum(1 for s in active_positions if s not in NON_EQUITY_SYMBOLS)
                        pending_orders = []
                        p_eq = active_eq
                        for cand in candidates:
                            is_eq = cand['symbol'] not in NON_EQUITY_SYMBOLS
                            if is_eq and p_eq >= 1:
                                continue
                            pending_orders.append(cand)
                            if is_eq:
                                p_eq += 1
                            if len(pending_orders) >= needed:
                                break

            final_eq = curve[-1][1] if curve else equity
            ret_pct = ((final_eq - 1000.0) / 1000.0) * 100.0
            wins = [t for t in trades if t['net_pnl_usd'] > 0]
            win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
            tot_gain = sum(t['net_pnl_usd'] for t in wins)
            losses = [t for t in trades if t['net_pnl_usd'] <= 0]
            tot_loss = abs(sum(t['net_pnl_usd'] for t in losses))
            pf = (tot_gain / tot_loss) if tot_loss > 0 else 999.0
            calmar = (ret_pct / (max_drawdown * 100.0)) if max_drawdown > 0 else 0.0
            print(f"  {mode:<20}: Ret={ret_pct:>+6.2f}%, MDD={max_drawdown*100:>5.2f}%, WinRate={win_rate:>5.1f}%, Trades={len(trades):>3}, Calmar={calmar:>5.2f}")
            if "MARGIN" in mode:
                print(f"      ↳ Borrow Interest Paid: ${total_borrow_interest_paid:.2f}")
            if "BINANCE" in mode:
                print(f"      ↳ Funding Fees Paid: ${total_funding_fees_paid:.2f}")

run_full_modes(er_min=0.28)
