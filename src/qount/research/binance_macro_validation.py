"""Focused minute execution and isolated-margin stress for frozen orders."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qount.research.binance_etf_leverage import funding_reserve, public_get
from qount.research.engine.perpetual import grid
from qount.research_data.bars import Bar, aggregate, atr


def minute_windows(trades, cache: Path, sample_end, download=False):
    """Public endpoints only; each window includes up to five exit-delay minutes."""
    cache.mkdir(parents=True, exist_ok=True)
    windows = {(t["symbol"], t["entry_time"], min(sample_end, t["exit_time"]+360)) for t in trades}

    def fetch(task):
        (symbol, start, end), kind = task
        path = cache/f"{symbol}-{kind}-1m-{start}-{end}.json"
        cached_end = end
        if not path.exists():
            # A shorter exit experiment can reuse an immutable longer window.
            supersets = [(int(p.stem.rsplit("-", 1)[1]), p)
                         for p in cache.glob(f"{symbol}-{kind}-1m-{start}-*.json")]
            supersets = [(e, p) for e, p in supersets if e >= end]
            if supersets:
                cached_end, path = min(supersets)
        if not path.exists():
            if not download:
                raise FileNotFoundError(path)
            endpoint = "/fapi/v1/klines" if kind == "trade" else "/fapi/v1/markPriceKlines"
            rows, cursor = [], start*1000
            while cursor < end*1000:
                page = public_get(endpoint, dict(symbol=symbol, interval="1m", startTime=cursor,
                                                endTime=end*1000-1, limit=1000))
                if not isinstance(page, list) or not page:
                    raise ValueError(f"missing_minute_page:{symbol}:{kind}:{cursor}")
                rows.extend(page)
                nxt = int(page[-1][0])+60000
                if nxt <= cursor:
                    raise ValueError("minute_pagination_not_advancing")
                cursor = nxt
            # Never replace earlier cache bytes; validate the fetched grid below.
            with path.open("x") as f:
                f.write(json.dumps(rows, separators=(",", ":"))+"\n")
        raw = path.read_bytes()
        rows = json.loads(raw)
        bars = [Bar(int(r[0])//1000, *(float(r[j]) for j in (1, 2, 3, 4)), float(r[5]), float(r[7])) for r in rows]
        if [b.t for b in bars] != list(range(start, cached_end, 60)):
            raise ValueError(f"minute_gap_or_duplicate:{symbol}:{kind}")
        if any(not 0 < b.l <= min(b.o, b.c) <= max(b.o, b.c) <= b.h for b in bars):
            raise ValueError("invalid_minute_ohlc")
        return (symbol, start), kind, [b for b in bars if b.t < end], dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())

    result, sources = {}, []
    tasks = [(w, k) for w in sorted(windows) for k in ("trade", "mark")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for key, kind, bars, source in pool.map(fetch, tasks):
            result.setdefault(key, {})[kind] = bars
            sources.append(source)
    return result, sources


from qount.strategies.macro_gates import available_atr


def frozen_trade(order, minutes, marks, funding, atr_rows, rule, *, fee=.0005, slip=.0005,
                 entry_delay=0, exit_delay=0, trigger="trade", maintenance=.01,
                 funding_collateral="wallet_first", stop_overshoot=None):
    """Hold signals/quantity fixed; intraminute stop-vs-liquidation is pessimistic.

    Funding can drain isolated collateral after free cash, or all debits can be
    charged to isolated collateral as a stress bound. Current rates/fee filters
    remain proxies. Liquidation fills/insurance protection are model bounds.
    """
    if trigger not in ("trade", "mark") or funding_collateral not in ("wallet_first", "isolated_debit"):
        raise ValueError("invalid_execution_scenario")
    if not 0 <= maintenance < 1 or entry_delay < 0 or exit_delay < 0:
        raise ValueError("invalid_execution_parameters")
    side, q = order.get("side", 1), order["quantity"]
    initial_q = q
    reductions = {r["time"]: r for r in order.get("partial_exits", [])}
    if len(reductions) != len(order.get("partial_exits", [])) or any(
            not order["entry_time"] < r["time"] < order["exit_time"] or r["quantity"] <= 0
            for r in reductions.values()) or sum(r["quantity"] for r in reductions.values()) >= q:
        raise ValueError("invalid_frozen_reductions")
    start = order["entry_time"]+entry_delay*60
    end_of_sample = order["exit_reason"] == "end_of_sample"
    planned_end = order["exit_time"]+(0 if end_of_sample else exit_delay*60)
    by_time, mark_by_time = {b.t: b for b in minutes}, {b.t: b for b in marks}
    if start not in by_time or (not end_of_sample and planned_end not in by_time):
        raise ValueError("minute_execution_boundary_missing")
    raw_entry = by_time[start].o
    entry = raw_entry*(1+side*slip)
    stop = order["initial_stop"]
    if side*(entry-stop) <= 0:
        return dict(status="cancelled_entry_beyond_stop", net_pnl=0, entry_time=start,
                    exit_time=start, exit_reason="cancelled_entry_beyond_stop", curve=[])
    margin = q*entry/order["leverage"]
    entry_fee = q*entry*fee
    free = order["equity_before_entry"]-margin-entry_fee
    isolated = margin
    if free < 0:
        return dict(status="unaffordable_entry", net_pnl=0, entry_time=start,
                    exit_time=start, exit_reason="unaffordable_entry", curve=[])
    funded = 0.0
    total_paid = 0.0
    favourable = entry
    structural_r = side*(entry-stop)
    atr_times = [r[0] for r in atr_rows]
    fs = {}
    for r in funding:
        fs.setdefault(int(r["fundingTime"])//60000*60, []).append(r)
    curve = []
    min_margin_buffer = math.inf
    ambiguous = 0
    realized_reductions = reduction_fees = 0.0
    executed_reductions = []
    max_entry_liquidity_fraction = q/by_time[start].v if by_time[start].v > 0 else None
    liquidation_fee_rate = float(rule.get("liquidationFee", 0.015))
    reserve = funding_reserve(funding, start, order.get("funding_reserve_hours", order.get("max_hold_hours", 168)), "debit_stress", side)
    worst_stop = stop*(1-side*order.get("sizing_gap_reserve", .01))
    estimated_risk = (q*(side*(entry-worst_stop)+entry*(fee+slip+reserve)+worst_stop*(fee+slip))
                      if reserve is not None else order["stress_risk_usdt"])
    budget = order.get("risk_budget_usdt", order["stress_risk_usdt"])
    tick = next(f["tickSize"] for f in rule["filters"] if f["filterType"] == "PRICE_FILTER")
    exit_data = None

    def exit_at(now, raw, reason, liquidation=False):
        price = raw*(1-side*slip)
        exit_fee = q*price*fee
        pnl = side*q*(price-entry)
        residual = isolated+pnl-exit_fee
        clearance = min(max(0, residual), liquidation_fee_rate*q*price) if liquidation else 0
        bankruptcy = max(0, -residual) if liquidation else 0
        net = realized_reductions+pnl-entry_fee-exit_fee+funded-clearance+bankruptcy
        result = dict(status="executed", entry_time=start, exit_time=now, exit_reason=reason,
                    entry_price=entry, exit_price=price, quantity=initial_q, net_pnl=net, funding=funded,
                    funding_paid=total_paid, entry_fee=entry_fee, exit_fee=exit_fee,
                    liquidation_fee=clearance, bankruptcy_adjustment=bankruptcy,
                    risk_fraction_loss=max(0, -net)/order["equity_before_entry"],
                    entry_stress_risk_usdt=estimated_risk, risk_budget_usdt=budget,
                    stress_estimate_exceeded=-net > estimated_risk+1e-9,
                    risk_budget_exceeded=-net > budget+1e-9,
                    entry_margin_fraction=margin/order["equity_before_entry"],
                    entry_minute_volume=by_time[start].v,
                    entry_quantity_fraction_of_minute_volume=max_entry_liquidity_fraction,
                    ambiguous_stop_liquidation_minutes=ambiguous,
                    min_margin_buffer_usdt=min_margin_buffer if math.isfinite(min_margin_buffer) else None,
                    curve=curve)
        if reductions:
            result.update(partial_exits=list(executed_reductions), remaining_quantity=q,
                          partial_exit_fees=reduction_fees)
        return result

    for now in range(start, planned_end+60, 60):
        if now >= planned_end:
            if end_of_sample:
                raw = by_time[now-60].c
            else:
                raw = by_time[now].o
            exit_data = exit_at(now, raw, order["exit_reason"])
            break
        if now not in by_time or now not in mark_by_time:
            raise ValueError("minute_path_missing")
        b, m = by_time[now], mark_by_time[now]
        if now in reductions:
            if entry_delay or exit_delay or stop_overshoot is not None:
                raise ValueError("reduction_schedule_requires_undelayed_historical_path")
            # Reduction at the known minute open precedes this minute's funding
            # and range. An already liquidated open cannot be rescued by it.
            opening_liq = (entry-side*isolated/q)/(1-side*maintenance)
            if side*(m.o-opening_liq) <= 0:
                exit_data = exit_at(now, b.o, "liquidation_proxy", True)
                break
            dq = reductions[now]["quantity"]
            if dq >= q:
                raise ValueError("frozen_reduction_exhausts_position")
            fill = b.o*(1-side*slip)
            charged = dq*fill*fee
            realized = side*dq*(fill-entry)-charged
            released = isolated*dq/q
            free += released+realized
            isolated -= released
            q -= dq
            realized_reductions += realized
            reduction_fees += charged
            executed_reductions.append(dict(time=now, quantity=dq, price=fill,
                fee=charged, realized_pnl=realized, remaining_quantity=q))
        # Synthetic persistent jump through the pre-existing stop after one
        # minute, never used to tune a signal. It is not historical market data.
        if stop_overshoot is not None and now >= start+60:
            shock = order["initial_stop"]*(1-side*stop_overshoot)
            b = m = Bar(now, shock, shock, shock, shock, b.v, b.q)
        stop_bar = b if trigger == "trade" else m
        stop_hit = stop_bar.l <= stop if side == 1 else stop_bar.h >= stop
        before_liq = (entry-side*isolated/q)/(1-side*maintenance)
        liq_hit_before = m.l <= before_liq if side == 1 else m.h >= before_liq
        for r in fs.get(now, []):
            if int(r["fundingTime"]) < start*1000:
                continue
            payment = -side*q*float(r["markPrice"])*float(r["fundingRate"])
            if payment > 0 and (stop_hit or liq_hit_before):
                continue
            funded += payment
            if payment >= 0:
                free += payment
            else:
                debit = -payment
                total_paid += debit
                from_free = min(max(0, free), debit) if funding_collateral == "wallet_first" else 0
                free -= from_free
                isolated -= debit-from_free
        liq = (entry-side*isolated/q)/(1-side*maintenance)
        adverse = m.l if side == 1 else m.h
        residual = isolated+side*q*(adverse-entry)-maintenance*q*adverse
        min_margin_buffer = min(min_margin_buffer, residual)
        liq_hit = m.l <= liq if side == 1 else m.h >= liq
        if liq_hit and stop_hit:
            ambiguous += 1
        if liq_hit:
            raw = min(b.o, liq) if side == 1 else max(b.o, liq)
            exit_data = exit_at(now+60, raw, "liquidation_proxy", True)
            break
        if stop_hit:
            # A mark-price trigger executes against the contract market, whose
            # price can differ. Use its adverse minute extreme as a fill bound.
            raw = ((b.l if side == 1 else b.h) if trigger == "mark" else
                   min(b.o, stop) if side == 1 else max(b.o, stop))
            exit_data = exit_at(now+60, raw, "stop")
            break
        mark_equity = free+isolated+side*q*(m.c-entry)-q*m.c*fee
        worst_equity = free+isolated+side*q*(adverse-entry)-q*adverse*fee
        curve.append(dict(time=now+60, equity=mark_equity, adverse_equity=worst_equity))
        # Preserve the original hourly-close trailing schedule and causal ATR.
        if (now+60) % 3600 == 0:
            favourable = max(favourable, b.c) if side == 1 else min(favourable, b.c)
            vi = bisect.bisect_right(atr_times, now+60)-1
            if vi >= 0 and side*(b.c-entry) >= 2*structural_r:
                proposed = grid(favourable-side*2*atr_rows[vi][1], tick, True)
                if side*(proposed-b.c) >= 0:
                    exit_data = exit_at(now+60, b.c, "crossed_trailing_stop")
                    break
                stop = max(stop, proposed) if side == 1 else min(stop, proposed)
    if exit_data is None:
        raise AssertionError("frozen_trade_did_not_close")
    final_equity = order["equity_before_entry"]+exit_data["net_pnl"]
    reconciled = free+max(0, isolated+side*q*(exit_data["exit_price"]-entry)-exit_data["exit_fee"]-exit_data["liquidation_fee"]) if exit_data["exit_reason"] == "liquidation_proxy" else free+isolated+side*q*(exit_data["exit_price"]-entry)-exit_data["exit_fee"]
    if not math.isclose(final_equity, reconciled, abs_tol=1e-8):
        raise AssertionError("minute_cash_reconciliation")
    curve.append(dict(time=exit_data["exit_time"], equity=final_equity, adverse_equity=final_equity))
    return exit_data
