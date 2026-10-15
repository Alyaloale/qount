import sys
import copy
from collections import defaultdict
from pathlib import Path
import statistics

from qount.research.universal_regime_expectancy import (
    DailyBar, load_etf_bars, compute_ema, compute_atr, compute_kaufman_er,
    compute_profile_state, ALL_10_MACRO_SYMBOLS, NON_EQUITY_SYMBOLS, EQUITY_SYMBOLS,
    run_regime_backtest
)

def run_causal_regime_backtest(
    symbols=None,
    mode='1X_SPOT',
    start_date='2020-01-01',
    end_date='2026-07-30',
    initial_capital=1000.0,
    min_atr_pct=0.0085,
    strict_golden_cross=True,
    breakout_quality_filter=True,
    dynamic_max_pos=True,
    orthogonal_tier_limit=True,
    gap_stress_pct=0.015,
    spy_lookahead_fixed=True,
    trailing_atr_mult=1.8,
    er_min=0.25,
    max_hold_days=45,
    data_dir='data/raw',
):
    if symbols is None:
        symbols = ALL_10_MACRO_SYMBOLS

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
            if start_date <= b.d <= end_date:
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
        # Macro state for Day T+1 morning
        if d_str in spy_dict:
            s_idx, s_bar, s_ema50, s_ema200 = spy_dict[d_str]
            if spy_lookahead_fixed:
                # Strictly use yesterday's close (Day T) to judge macro state at Day T+1 morning
                if s_idx > 0:
                    prev_b = spy_bars[s_idx - 1]
                    prev_ema50 = spy_ema50[s_idx - 1]
                    prev_ema200 = spy_ema200[s_idx - 1]
                    is_macro_bear = prev_b.c < prev_ema200 or prev_ema50 < prev_ema200
                    is_macro_bull = not is_macro_bear
                else:
                    is_macro_bear = False
                    is_macro_bull = True
            else:
                # Original: uses Day T+1 close (Lookahead!)
                is_macro_bear = s_bar.c < s_ema200 or s_ema50 < s_ema200
                is_macro_bull = not is_macro_bear
        else:
            is_macro_bear = False
            is_macro_bull = True

        cur_max_pos = 2
        if dynamic_max_pos:
            cur_max_pos = 2 if is_macro_bull else 1

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
                if is_macro_bear and is_equity:
                    continue

                if orthogonal_tier_limit and is_equity:
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
                    max_qty = (equity * 0.98 / cur_max_pos) / open_p
                    qty = min(qty, max_qty)

                    if qty * open_p >= 5.0:
                        entry_p = open_p * (1.0 + entry_slip_pct)
                        entry_fee = qty * entry_p * fee_pct
                        equity -= entry_fee
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
                        }
            pending_orders = []

        # STEP 3: Exit Checks during Day T (Using ACTIVE STOP)
        for sym in list(active_positions.keys()):
            pos = active_positions[sym]
            ind = all_data[sym]
            if d_str not in ind['bar_dict']:
                continue
            idx, cur_bar = ind['bar_dict'][d_str]
            cur_atr = ind['atr14'][idx]
            stop_price_today = pos['active_stop']

            if pos['trade_type'] == 'MEAN_REVERSION':
                is_tp = cur_bar.h >= pos['target_p']
                is_sl = cur_bar.l <= stop_price_today
                is_max_hold = (idx - pos['entry_idx']) >= 15

                if is_tp or is_sl or is_max_hold:
                    if is_sl and is_tp:
                        is_tp = False  # STOP LOSS PRECEDENCE

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
                is_max_hold = (idx - pos['entry_idx']) >= max_hold_days
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

        # STEP 4: End of Day T Close — Update Trailing Stop for Day T+1
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
                next_st = max(next_st, pos['highest_close'] - trailing_atr_mult * cur_atr)

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

        # STEP 6: Candidate Evaluation at Day T Close for T+1 Entry
        if d_str in spy_dict:
            s_idx, s_bar, s_ema50, s_ema200 = spy_dict[d_str]
            close_is_macro_bull = not (s_bar.c < s_ema200 or s_ema50 < s_ema200)
            eval_max_pos = 2 if close_is_macro_bull else 1
        else:
            eval_max_pos = 2

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

                c_now = cur_bar.c
                cur_atr = ind['atr14'][idx]

                if min_atr_pct > 0 and (cur_atr / c_now) < min_atr_pct:
                    continue

                er_val = ind['ers'][idx]
                ema20_now = ind['ema20'][idx]
                ema50_now = ind['ema50'][idx]
                ema200_now = ind['ema200'][idx]
                rs_val = ind['rs60'][idx]

                if c_now < ema200_now:
                    continue
                if strict_golden_cross and ema50_now <= ema200_now:
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
                if orthogonal_tier_limit:
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
                else:
                    pending_orders = candidates[:needed]

    final_eq = curve[-1][1] if curve else equity
    ret_pct = ((final_eq - initial_capital) / initial_capital) * 100.0
    wins = [t for t in trades if t['net_pnl_usd'] > 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    tot_gain = sum(t['net_pnl_usd'] for t in wins)
    losses = [t for t in trades if t['net_pnl_usd'] <= 0]
    tot_loss = abs(sum(t['net_pnl_usd'] for t in losses))
    pf = (tot_gain / tot_loss) if tot_loss > 0 else 999.0
    calmar = (ret_pct / (max_drawdown * 100.0)) if max_drawdown > 0 else 0.0

    sym_pnl = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0})
    for t in trades:
        s = t['symbol']
        sym_pnl[s]['count'] += 1
        sym_pnl[s]['pnl'] += t['net_pnl_usd']
        if t['net_pnl_usd'] > 0:
            sym_pnl[s]['wins'] += 1

    return {
        'return_pct': ret_pct,
        'mdd_pct': max_drawdown * 100.0,
        'win_rate': win_rate,
        'profit_factor': pf,
        'trade_count': len(trades),
        'final_equity': final_eq,
        'calmar': calmar,
        'sym_pnl': dict(sym_pnl),
        'trades': trades,
        'curve': curve,
    }

if __name__ == '__main__':
    print('=== 1. AUDIT: SPY MACRO LOOKAHEAD IMPACT ===')
    r_original = run_causal_regime_backtest(spy_lookahead_fixed=False)
    r_causal = run_causal_regime_backtest(spy_lookahead_fixed=True)
    print(f'Original (with T+1 SPY close at T+1 open): Ret={r_original["return_pct"]:+.2f}%, MDD={r_original["mdd_pct"]:.2f}%, WinRate={r_original["win_rate"]:.1f}%, Trades={r_original["trade_count"]}, Calmar={r_original["calmar"]:.2f}')
    print(f'Causal (Fixed with T SPY close at T+1 open): Ret={r_causal["return_pct"]:+.2f}%, MDD={r_causal["mdd_pct"]:.2f}%, WinRate={r_causal["win_rate"]:.1f}%, Trades={r_causal["trade_count"]}, Calmar={r_causal["calmar"]:.2f}')

    print('\n=== 2. AUDIT: ASSET ABLATION & CONCENTRATION RISK (Full 2020-2026) ===')
    print(f'Full universe (10 assets): Ret={r_causal["return_pct"]:+.2f}%, MDD={r_causal["mdd_pct"]:.2f}%')
    for s, stats in sorted(r_causal['sym_pnl'].items(), key=lambda x: x[1]['pnl'], reverse=True):
        wr = stats['wins']/stats['count']*100 if stats['count']>0 else 0
        print(f'  {s:<5}: PnL=${stats["pnl"]:>+7.2f} | Trades={stats["count"]:>3} | WinRate={wr:>5.1f}%')

    # Ablate top winner CPER
    syms_no_cper = [s for s in ALL_10_MACRO_SYMBOLS if s != 'CPER']
    r_no_cper = run_causal_regime_backtest(symbols=syms_no_cper, spy_lookahead_fixed=True)
    print(f'Without CPER (Copper): Ret={r_no_cper["return_pct"]:+.2f}%, MDD={r_no_cper["mdd_pct"]:.2f}%, Calmar={r_no_cper["calmar"]:.2f}')

    # Ablate SMH
    syms_no_smh = [s for s in ALL_10_MACRO_SYMBOLS if s != 'SMH']
    r_no_smh = run_causal_regime_backtest(symbols=syms_no_smh, spy_lookahead_fixed=True)
    print(f'Without SMH (Semiconductor): Ret={r_no_smh["return_pct"]:+.2f}%, MDD={r_no_smh["mdd_pct"]:.2f}%, Calmar={r_no_smh["calmar"]:.2f}')

    # Ablate both top winners
    syms_no_top2 = [s for s in ALL_10_MACRO_SYMBOLS if s not in ['CPER', 'SMH']]
    r_no_top2 = run_causal_regime_backtest(symbols=syms_no_top2, spy_lookahead_fixed=True)
    print(f'Without CPER & SMH: Ret={r_no_top2["return_pct"]:+.2f}%, MDD={r_no_top2["mdd_pct"]:.2f}%, Calmar={r_no_top2["calmar"]:.2f}')

    print('\n=== 3. AUDIT: PARAMETER SENSITIVITY ===')
    print('--- Volatility Floor (min_atr_pct) ---')
    for min_atr in [0.006, 0.0075, 0.0085, 0.0095, 0.0110]:
        r = run_causal_regime_backtest(min_atr_pct=min_atr, spy_lookahead_fixed=True)
        print(f'  min_atr_pct={min_atr:.4f}: Ret={r["return_pct"]:+.2f}%, MDD={r["mdd_pct"]:.2f}%, Trades={r["trade_count"]}, Calmar={r["calmar"]:.2f}')

    print('--- Kaufman ER Threshold ---')
    for er in [0.20, 0.22, 0.25, 0.28, 0.30]:
        r = run_causal_regime_backtest(er_min=er, spy_lookahead_fixed=True)
        print(f'  er_min={er:.2f}: Ret={r["return_pct"]:+.2f}%, MDD={r["mdd_pct"]:.2f}%, Trades={r["trade_count"]}, Calmar={r["calmar"]:.2f}')

    print('--- Trailing Stop ATR Multiplier ---')
    for mult in [1.5, 1.8, 2.0, 2.2]:
        r = run_causal_regime_backtest(trailing_atr_mult=mult, spy_lookahead_fixed=True)
        print(f'  trailing_atr={mult:.1f}: Ret={r["return_pct"]:+.2f}%, MDD={r["mdd_pct"]:.2f}%, Trades={r["trade_count"]}, Calmar={r["calmar"]:.2f}')

    print('--- Gap Stress % ---')
    for gap in [0.0, 0.010, 0.015, 0.020, 0.030]:
        r = run_causal_regime_backtest(gap_stress_pct=gap, spy_lookahead_fixed=True)
        print(f'  gap_stress={gap*100:.1f}%: Ret={r["return_pct"]:+.2f}%, MDD={r["mdd_pct"]:.2f}%, Trades={r["trade_count"]}, Calmar={r["calmar"]:.2f}')

    print('\n=== 4. AUDIT: MULTI-REGIME SUB-PERIOD STABILITY ===')
    subperiods = [
        ('2020 Crash & Recovery', '2020-01-01', '2020-12-31'),
        ('2021 Expansion Bull', '2021-01-01', '2021-12-31'),
        ('2022 Fed Rate Hike Bear', '2022-01-01', '2022-12-31'),
        ('2023 Recovery Chop', '2023-01-01', '2023-12-31'),
        ('2024 AI Expansion Bull', '2024-01-01', '2024-12-31'),
        ('2025-2026 Recent Window', '2025-01-01', '2026-07-30'),
    ]
    for name, s_d, e_d in subperiods:
        r = run_causal_regime_backtest(start_date=s_d, end_date=e_d, spy_lookahead_fixed=True)
        print(f'  {name:<24} ({s_d[:4]}-{e_d[:4]}): Ret={r["return_pct"]:>+6.2f}%, MDD={r["mdd_pct"]:>5.2f}%, WinRate={r["win_rate"]:>5.1f}%, Trades={r["trade_count"]:>3}')
