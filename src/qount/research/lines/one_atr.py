"""Replay current 1ATR signal/nominal-allocation rules on native hourly data.

Daily decisions at 03:40 UTC are approximated by fills at 04:00 UTC because
existing inputs are hourly. This is consumed-history exploration, not a live
fill reconstruction or the older macro-tactical strategy.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from qount.strategies.one_atr import DailyBar, build_signal, select_signal, allocation_quantity
from qount.research_data.bars import aggregate
from qount.research.engine.perpetual import common_step, grid
from qount.research.engine.linear_account import LinearAccount
from qount.research.engine.evaluation import nav_metrics


def signals_by_day(data):
    updates = {}
    for symbol, book in data.items():
        days = aggregate(book["trade"], 86400, 3600)
        for index in range(120,len(days)):
            rows = days[max(0,index-158):index+1]  # live limit=160 includes one forming bar
            if any(b.t-a.t != 86400 for a,b in zip(rows,rows[1:])):
                continue
            bars = [DailyBar(b.t,b.o,b.h,b.l,b.c,b.v) for b in rows]
            signal = build_signal(symbol,bars)
            updates.setdefault(days[index].t+86400+4*3600,[]).append(signal)
    return updates


def replay(data, *, start, end, capital=100, fraction=1.0, fee=.0005, slip=.0005, hold_symbol=None):
    account = LinearAccount(capital,fee,slip)
    updates = signals_by_day(data)
    if not updates:
        raise ValueError("no_symbol_has_121_complete_native_days")
    clocks = [t for t in updates if start <= t < end]
    if not clocks:
        raise ValueError("no_evaluation_window_after_warmup")
    begin = min(clocks)
    hours = {s:{b.t:b for b in book["trade"]} for s,book in data.items()}
    marks = {s:{b.t:b for b in book["mark"]} for s,book in data.items()}
    funding = {}
    for symbol, book in data.items():
        for row in book["funding"]:
            t = int(row["fundingTime"])//1000
            funding.setdefault((symbol,t//3600*3600),[]).append(row)
    points = [{"t":begin,"nav":1.0,"equity":capital}]
    rejections = Counter()
    candidates = accepted = 0
    entered_today = False
    for now in range(begin,end,3600):
        exited = False
        if account.position:
            p = account.position
            symbol = p["symbol"]
            bar, mark = hours[symbol][now], marks[symbol][now]
            stopped = hold_symbol is None and mark.l <= p["stop"]
            for row in funding.get((symbol,now),[]):
                rate = float(row["fundingRate"])
                # Charge all positive funding in a stopped hour; do not credit
                # negative funding whose ordering relative to the stop is unknown.
                if rate >= 0 or not stopped:
                    account.funding(rate,float(row.get("markPrice") or mark.o))
            if stopped:
                # Stop-market reference and mark/trade divergence are conservative
                # OHLC approximations. No intrahour capacity claim is made.
                account.close(min(p["stop"],bar.o,bar.l),now+3600,"stop_ohlc_bound")
                exited = True
        if now in updates:
            entered_today = False
        if not account.position and not exited and not entered_today:
            if hold_symbol:
                selected = next((s for s in updates.get(begin,[]) if s.symbol==hold_symbol),None) if now==begin else None
            else:
                selected = select_signal(updates.get(now,[]))
            if selected:
                candidates += 1
                book = data[selected.symbol]
                filters = {f["filterType"]:f for f in book["rule"]["filters"]}
                lots = [filters["LOT_SIZE"],filters.get("MARKET_LOT_SIZE",filters["LOT_SIZE"])]
                price = hours[selected.symbol][now].o
                stop = grid(selected.stop_price if not hold_symbol else price*.01,filters["PRICE_FILTER"]["tickSize"])
                try:
                    quantity = allocation_quantity(account.cash,selected.close,fraction=fraction,
                        step=float(common_step(lots)),minimum=max(float(f["minQty"]) for f in lots),
                        maximum=min(float(f["maxQty"]) for f in lots),min_notional=float(filters["MIN_NOTIONAL"]["notional"]))
                    account.open(selected.symbol,quantity,price,stop,now,now-20*60)
                except ValueError as exc:
                    rejections[str(exc)] += 1
                else:
                    accepted += 1
                    entered_today = True
                    # Evaluate the entry hour too, after an open-price fill.
                    bar, mark = hours[selected.symbol][now], marks[selected.symbol][now]
                    stopped = not hold_symbol and mark.l <= stop
                    for row in funding.get((selected.symbol,now),[]):
                        rate = float(row["fundingRate"])
                        if rate >= 0 or (not stopped and int(row["fundingTime"]) > now*1000):
                            account.funding(rate,float(row.get("markPrice") or mark.o))
                    if stopped:
                        account.close(min(stop,bar.o,bar.l),now+3600,"entry_hour_stop_ohlc_bound")
        if account.position:
            symbol = account.position["symbol"]
            equity = account.equity(marks[symbol][now].c)
        else:
            equity = account.cash
        if equity <= 0:
            raise ValueError("nonpositive_equity_requires_liquidation_model")
        points.append(dict(t=now+3600,nav=equity/capital,equity=equity))
    open_position = account.position
    terminal = 0.0
    if open_position:
        symbol = open_position["symbol"]
        terminal = points[-1]["equity"]-account.cash-open_position["entry_fee"]+open_position["funding"]
    net = sum(t["net_pnl"] for t in account.trades)+terminal
    if abs(capital+net-points[-1]["equity"]) > 1e-7:
        raise ValueError("replay_cash_identity_failed")
    coverage = {}
    for symbol, book in data.items():
        clocks = [t for t,signals in updates.items() if begin <= t < end and any(s.symbol == symbol for s in signals)]
        coverage[symbol] = dict(native_history_start=book["trade"][0].t,
                                decision_count=len(clocks),first_decision=min(clocks) if clocks else None)
    return dict(nav=points,trades=account.trades,summary=dict(
        **nav_metrics(points),initial_capital=capital,final_equity=points[-1]["equity"],
        trade_count=len(account.trades),entry_count=accepted,candidate_count=candidates,
        rejections=dict(rejections),open_position=open_position,
        realized_net_pnl=sum(t["net_pnl"] for t in account.trades),terminal_open_net_pnl=terminal,
        start=begin,end_exclusive=end,sample_kind="consumed_historical_exploration",signal_coverage=coverage,
        execution_assumptions={"decision":"03:40 UTC, previous complete UTC daily bars", "fill":"04:00 UTC hourly open + slippage", "exit":"2ATR fixed mark-trigger stop; pessimistic trade-OHLC bound; no discretionary/7-day exit", "allocation":"current live nominal fraction, no invented 50% risk budget", "fee_per_side":fee,"slippage_per_side":slip},
        limitations=["20-minute execution delay proxy, not exact live fill replication", "Current filters applied historically; leverage/margin brackets and liquidation not certified", "Positive funding charged in ambiguous entry/stop hours, ambiguous negative credits omitted", "Hourly-close MDD does not bound intrahour loss", "Active configured asset subset, no point-in-time universe claim", "Consumed historical data, not independent OOS"]
    ))
