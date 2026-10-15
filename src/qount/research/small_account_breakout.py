"""Single-position linear-perpetual breakout research; no execution integration.

The independent contract deliberately does not relax StrategyIntent/portfolio
gross limits. Minute OHLC fills and maintenance margin are declared approximations.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from zoneinfo import ZoneInfo

from qount.research.small_account_breakout_data import archive_rows, timestamp

NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
HOLIDAYS_2026 = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
                 "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
                 "2026-11-26", "2026-12-25"}
EARLY_CLOSE_2026 = {"2026-11-27", "2026-12-24"}


def iso(t: int) -> str:
    return dt.datetime.fromtimestamp(t, UTC).isoformat()


@dataclass(frozen=True)
class Bar:
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0
    q: float = 0.0


@dataclass(frozen=True)
class Signal:
    symbol: str
    market: str
    side: int
    decision_time: int
    close: float
    atr: float
    breakout_high: float | None = None
    breakout_low: float | None = None
    direction_pass: bool = True
    volume_pass: bool = True
    original_decision_time: int | None = None
    event_id: str | None = None
    structural_stop: float | None = None


@dataclass(frozen=True)
class FuturesRiskContract:
    symbol: str
    side: int
    quantity: float
    entry_price: float
    notional_usdt: float
    isolated_margin_usdt: float
    leverage_setting: int
    actual_gross: float
    initial_stop: float
    planned_stop_risk_usdt: float
    risk_budget_usdt: float
    estimated_friction_fraction: float
    liquidation_distance_fraction: float
    maintenance_margin_assumption: float
    margin_mode: str = "isolated"
    position_mode: str = "one_way"
    auto_add_margin: bool = False
    research_only: bool = True
    orders_authorized: bool = False


@dataclass
class MarketData:
    minutes: dict[str, dict[int, Bar]]
    marks: dict[str, dict[int, Bar]]
    hours: dict[str, list[Bar]]
    funding: dict[str, list[dict]]
    rules: dict[str, dict]
    quality: dict
    funding_intervals: dict[str, list[dict]] = field(default_factory=dict)


def parse_bars(path: Path) -> list[Bar]:
    result = []
    for row in archive_rows(path):
        t = int(row[0])
        if t >= 10**14:  # Explicitly support microsecond files.
            t //= 1000
        result.append(Bar(t // 1000, *(float(row[i]) for i in (1, 2, 3, 4)),
                          float(row[5]), float(row[7])))
    return result


def aggregate(bars: list[Bar], period: int, source_period: int) -> list[Bar]:
    groups: dict[int, list[Bar]] = defaultdict(list)
    for bar in bars:
        groups[bar.t // period * period].append(bar)
    result = []
    for t, rows in sorted(groups.items()):
        rows.sort(key=lambda row: row.t)
        if [row.t for row in rows] != list(range(t, t + period, source_period)):
            continue  # Incomplete feature bar is never used.
        result.append(Bar(t, rows[0].o, max(row.h for row in rows),
                          min(row.l for row in rows), rows[-1].c,
                          sum(row.v for row in rows), sum(row.q for row in rows)))
    return result


def ema(values: list[float], span: int) -> list[float]:
    result = []
    for value in values:
        result.append(value if not result else result[-1] + 2 / (span + 1) * (value-result[-1]))
    return result


def atr(bars: list[Bar], span: int = 14) -> list[float | None]:
    ranges = [max(bar.h-bar.l, abs(bar.h-bars[i-1].c), abs(bar.l-bars[i-1].c))
              if i else bar.h-bar.l for i, bar in enumerate(bars)]
    result: list[float | None] = [None] * len(bars)
    if len(bars) >= span:
        result[span-1] = statistics.mean(ranges[:span])
        for i in range(span, len(bars)):
            result[i] = (result[i-1] * (span-1) + ranges[i]) / span
    return result


def load_data(cache: Path, config: dict, week: str) -> MarketData:
    start, end = timestamp(week), timestamp(week) + 7*86400
    symbols = config["crypto_symbols"] + config["stock_symbols"]
    minutes, marks, hours, funding, quality = {}, {}, {}, {}, {}
    exchange = json.loads((cache / "exchange-info.json").read_text())
    rules = {row["symbol"]: row for row in exchange["symbols"] if row["symbol"] in symbols}
    for symbol in symbols:
        for kind, destination in (("klines", minutes), ("markPriceKlines", marks)):
            all_rows = {}
            for day in range(-2 if symbol in config["stock_symbols"] else 0, 7):
                date = dt.datetime.fromtimestamp(start+day*86400, UTC).date().isoformat()
                path = cache / f"{kind}-{symbol}-1m-{date}.zip"
                for bar in parse_bars(path):
                    if bar.t in all_rows:
                        raise ValueError("duplicate_minute")
                    if not (0 < bar.l <= min(bar.o, bar.c) <= max(bar.o, bar.c) <= bar.h):
                        raise ValueError(f"invalid_ohlc:{symbol}:{bar.t}")
                    all_rows[bar.t] = bar
            if sorted(t for t in all_rows if start <= t < end) != list(range(start,end,60)):
                raise ValueError(f"missing_week_minutes:{symbol}:{kind}")
            destination[symbol] = all_rows
        funding[symbol] = json.loads((cache / f"funding-{symbol}-{week}.json").read_text())
        if symbol in config["crypto_symbols"]:
            rows = {}
            for path in sorted(cache.glob(f"klines-{symbol}-1h-*.zip")):
                for bar in parse_bars(path):
                    if start-35*86400 <= bar.t < end:
                        if bar.t in rows and rows[bar.t] != bar:
                            raise ValueError("conflicting_hour_sources")
                        rows[bar.t] = bar
            hours[symbol] = [rows[t] for t in sorted(rows)]
            if sorted(rows) != list(range(start-35*86400,end,3600)):
                raise ValueError(f"hourly_warmup_gap:{symbol}:{week}")
            minute_hours = aggregate([minutes[symbol][t] for t in range(start,end,60)],3600,60)
            for bar in minute_hours:
                other = rows[bar.t]
                if any(not math.isclose(getattr(bar,k),getattr(other,k),rel_tol=1e-7,abs_tol=1e-5)
                       for k in ("o","h","l","c","v","q")):
                    raise ValueError(f"minute_hour_mismatch:{symbol}:{bar.t}")
        quality[symbol] = {"week_trade_minutes": 10080, "week_mark_minutes": 10080,
                           "warmup_hours": 35*24 if symbol in hours else 48,
                           "funding_records": len(funding[symbol]),
                           "minute_hour_consistent": symbol in hours}
    return MarketData(minutes, marks, hours, funding, rules, quality)


def session(t: int) -> tuple[str, int, int] | None:
    local = dt.datetime.fromtimestamp(t, NY)
    date = local.date().isoformat()
    if local.year != 2026:
        raise ValueError("calendar_only_certified_for_2026")
    if local.weekday() >= 5 or date in HOLIDAYS_2026:
        return None
    return date, local.hour*60+local.minute, 13*60 if date in EARLY_CLOSE_2026 else 16*60


def generate_signals(data: MarketData, config: dict, start: int, end: int,
                     simple: bool = False, *, direction_filter: bool | None = None,
                     volume_filter: bool | None = None) -> tuple[list[Signal], dict[str, dict[int, tuple[Bar, float]]]]:
    signals, updates, trends = [], {}, {}
    use_direction = not simple if direction_filter is None else direction_filter
    use_volume = not simple if volume_filter is None else volume_filter
    for symbol, bars in data.hours.items():
        four = aggregate(bars, 14400, 3600)
        fast, slow = ema([bar.c for bar in four],20), ema([bar.c for bar in four],60)
        trends[symbol] = {bar.t+14400: (1 if bar.c > slow[i] and fast[i] > slow[i]
                                      else -1 if bar.c < slow[i] and fast[i] < slow[i] else 0)
                          for i,bar in enumerate(four) if i >= 59}
    for symbol, bars in data.hours.items():
        volatility = atr(bars)
        updates[symbol] = {bar.t+3600:(bar,volatility[i]) for i,bar in enumerate(bars)
                           if volatility[i] is not None and start <= bar.t+3600 < end}
        for i, bar in enumerate(bars):
            close_time = bar.t+3600
            if not start <= close_time < end or i < 20 or not volatility[i]:
                continue
            trend_time = close_time // 14400 * 14400
            own, btc = trends[symbol].get(trend_time,0), trends["BTCUSDT"].get(trend_time,0)
            high,low = max(row.h for row in bars[i-20:i]),min(row.l for row in bars[i-20:i])
            direction = 1 if bar.c > high else (-1 if bar.c < low else 0)
            active = bar.q > 1.5 * statistics.median(row.q for row in bars[i-20:i])
            if direction and (not use_direction or direction == own == btc) and (not use_volume or active):
                signals.append(Signal(symbol,"crypto",direction,close_time,bar.c,volatility[i],
                                      high,low,direction == own == btc,active))
    for symbol in config["stock_symbols"]:
        bars = sorted(data.minutes[symbol].values(), key=lambda bar:bar.t)
        quarters = aggregate(bars,900,60)
        volatility = atr(quarters)
        updates[symbol] = {bar.t+900:(bar,volatility[i]) for i,bar in enumerate(quarters)
                           if volatility[i] is not None and start <= bar.t+900 < end}
        rth: dict[str,list[Bar]] = defaultdict(list)
        for bar in bars:
            hours = session(bar.t)
            if hours and 570 <= hours[1] < hours[2]:
                rth[hours[0]].append(bar)
        for i,bar in enumerate(quarters):
            close_time = bar.t+900
            hours = session(close_time)
            if (not start <= close_time < end or not hours or not volatility[i]
                    or not 600 < hours[1] < min(870,hours[2]-90)):
                continue
            known = [row for row in rth[hours[0]] if row.t+60 <= close_time]
            opening = [row for row in known if session(row.t)[1] < 600]
            if len(opening) != 30 or sum(row.v for row in known) <= 0:
                continue
            vwap = sum(row.q for row in known)/sum(row.v for row in known)
            side = 1 if bar.c > max(row.h for row in opening) and bar.c > vwap else (
                -1 if bar.c < min(row.l for row in opening) and bar.c < vwap else 0)
            if side:
                signals.append(Signal(symbol,"stock",side,close_time,bar.c,volatility[i]))
    priority = {symbol:i for i,symbol in enumerate(config["priority"])}
    return sorted(signals,key=lambda sig:(sig.decision_time,priority[sig.symbol])), updates


def funding_estimate(rows: list[dict], now: int, remaining_hours: float) -> float:
    known = [abs(float(row["fundingRate"])) for row in rows
             if (now-72*3600)*1000 <= int(row["fundingTime"]) < now*1000]
    if not known:
        raise ValueError("no_causal_funding_history")
    return max(known) * math.ceil(max(remaining_hours,0)/8)


def funding_budget(rows: list[dict], snapshots: list[dict], now: int,
                   remaining_hours: float, config: dict) -> dict:
    """Only information available strictly before decision/fill can set the budget."""
    known = [r for r in rows if (now-72*3600)*1000 <= int(r["fundingTime"]) < now*1000]
    if not known:
        raise ValueError("no_causal_funding_history")
    hours,source = 8.0,"v01_fixed_8h_assumption"
    if config.get("funding_interval_mode") == "known_or_observed":
        available = [r for r in snapshots if r["known_at"] <= now and r["effective_from"] <= now
                     and now < r.get("effective_until",float("inf"))]
        if available:
            record = max(available,key=lambda r:(r["known_at"],r["effective_from"]))
            hours,source = float(record["fundingIntervalHours"]),"point_in_time_snapshot"
        else:
            times = sorted({int(r["fundingTime"])//60000*60 for r in known
                            if r.get("rateType","Regular")=="Regular"})
            hours = (times[-1]-times[-2])/3600 if len(times)>=2 else config["funding_interval_fallback_hours"]
            source = "last_settlement_gap_assumption" if len(times)>=2 else "fallback_interval_assumption"
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError("invalid_funding_interval")
    count = math.ceil(max(remaining_hours,0)/hours)
    return {"fraction":max(abs(float(r["fundingRate"])) for r in known)*count,
            "interval_hours":hours,"interval_source":source,"settlement_count_budget":count}


def floor_step(value: float, step: float) -> float:
    return float((Decimal(str(value))/Decimal(str(step))).to_integral_value(
        rounding=ROUND_DOWN)*Decimal(str(step)))


def size_contract(signal: Signal, price: float, equity: float, risk: float,
                  friction: float, rule: dict, config: dict, *,
                  liquidity_quantity: float | None = None) -> tuple[FuturesRiskContract | None,str]:
    market = signal.market
    filters = {row["filterType"]:row for row in rule["filters"]}
    raw_stop = (signal.structural_stop if signal.structural_stop is not None
                else price-signal.side*config["initial_stop_atr"]*signal.atr)
    distance = abs(price-raw_stop)/price
    if distance <= 0 or signal.side*(price-raw_stop) <= 0:
        return None,"invalid_structural_stop"
    if friction > config["max_friction_to_stop"]*distance:
        return None,"friction_budget"
    maintenance = config[f"{market}_maintenance_margin_assumption"]
    buffer = maintenance + float(rule["liquidationFee"])
    leverage = config[f"{market}_max_leverage"]
    while leverage > 0 and (1/leverage-buffer)/(1+buffer) < config["liquidation_stop_multiple"]*distance:
        leverage -= 1
    if leverage == 0:
        return None,"liquidation_distance"
    # Research-only tail-slippage reserve: include an extra adverse move in the
    # sizing denominator while leaving the structural stop and ordinary cost
    # checks unchanged.
    stress_slippage = float(config.get("stress_slippage_budget_fraction", 0.0))
    if stress_slippage < 0 or not math.isfinite(stress_slippage):
        raise ValueError("invalid_stress_slippage_budget")
    desired = min(risk*equity/(distance+friction+stress_slippage), config[f"{market}_max_gross"]*equity,
                  config["max_margin_fraction"]*equity*leverage)
    lot = filters["LOT_SIZE"]
    market_lot = filters.get("MARKET_LOT_SIZE",lot)
    step = max(float(lot["stepSize"]),float(market_lot["stepSize"]))
    q_max = min(desired/price,float(lot["maxQty"]),float(market_lot["maxQty"]),
                liquidity_quantity if liquidity_quantity is not None else math.inf)
    quantity = floor_step(q_max,step)
    notional = quantity*price
    minimum = float(filters["MIN_NOTIONAL"]["notional"])
    if signal.symbol == "BTCUSDT" and signal.decision_time < timestamp("2026-04-14T06:30:00"):
        minimum = 100.0
    if quantity < max(float(lot["minQty"]),float(market_lot["minQty"])) or notional < minimum:
        return None,"minimum_order"
    stop = raw_stop
    # Round towards the entry so price-tick rounding never increases planned loss.
    tick = float(filters["PRICE_FILTER"]["tickSize"])
    stop = (math.ceil(stop/tick) if signal.side == 1 else math.floor(stop/tick))*tick
    actual_distance = abs(stop-price)/price
    if actual_distance <= 0 or signal.side*(price-stop) <= 0:
        return None,"invalid_stop_after_rounding"
    contract = FuturesRiskContract(signal.symbol,signal.side,quantity,price,notional,
        notional/leverage,leverage,notional/equity,stop,notional*(actual_distance+friction),
        risk*equity,friction,(1/leverage-buffer)/(1-signal.side*buffer),maintenance)
    if contract.planned_stop_risk_usdt > contract.risk_budget_usdt+1e-9:
        raise AssertionError("risk_budget_exceeded")
    return contract,"allowed"


@dataclass
class Position:
    contract: FuturesRiskContract
    signal: Signal
    entered: int
    equity_before: float
    entry_fee: float
    entry_slippage: float
    stop: float
    deadline: int
    funding_net: float = 0.0
    funding_adverse: float = 0.0
    extreme: float = 0.0
    trailing: bool = False
    failure_exit_at: int | None = None
    entry_funding_budget: dict = field(default_factory=dict)


def simulate(data: MarketData, config: dict, week: str, signals: list[Signal],
             updates: dict, *, variant: str = "combined", risk: float = 0.10,
             scenario: str = "base", end_time: int | None = None) -> dict:
    start,end = timestamp(week),end_time or timestamp(week)+7*86400
    cost_mult = 2 if scenario == "double_cost" else 1
    funding_mult = 2 if scenario == "funding_2x" else 1
    delay = 5 if scenario == "delay_5m" else config["entry_delay_minutes"]
    scheduled: dict[int,list[Signal]] = defaultdict(list)
    for sig in signals:
        if variant in {"crypto","simple"} and sig.market != "crypto":
            continue
        scheduled[sig.decision_time+delay*60].append(sig)
    funding_events: dict[int,list[tuple[str,dict]]] = defaultdict(list)
    for symbol,rows in data.funding.items():
        for row in rows:
            # Funding happens within a minute, often a few milliseconds after :00.
            t = int(row["fundingTime"])//60000*60
            if start <= t < end:
                funding_events[t].append((symbol,row))
    equity = peak = config["initial_equity_usdt"]
    pos = None
    trades,curve,rejections,decisions = [],[],Counter(),[]
    daily_entries = Counter()
    consecutive_stops,cooldown_until,halt,downshift = 0,0,None,False
    max_drawdown = 0.0
    max_intra_minute_drawdown = 0.0
    max_gross = max_margin = 0.0
    pending_account_stop = False

    def close(t: int, raw_price: float, reason: str) -> None:
        nonlocal pos,equity,consecutive_stops,cooldown_until
        contract = pos.contract
        fee_rate = config[f"{pos.signal.market}_fee_per_side"]*cost_mult
        slip_rate = config[f"{pos.signal.market}_slippage_per_side"]*cost_mult
        price = raw_price*(1-contract.side*slip_rate)
        gross = contract.quantity*contract.side*(price-contract.entry_price)
        exit_fee = contract.quantity*price*fee_rate
        if reason == "liquidation":
            exit_fee += contract.quantity*price*float(data.rules[contract.symbol]["liquidationFee"])
        equity += gross-exit_fee
        net = equity-pos.equity_before
        trades.append({"symbol":contract.symbol,"market":pos.signal.market,
            "side":"long" if contract.side == 1 else "short",
            "decision_time":iso(pos.signal.decision_time),"entry_time":iso(pos.entered),
            "exit_time":iso(t),"exit_reason":reason,"entry_price":contract.entry_price,
            "exit_price":price,"quantity":contract.quantity,"notional_usdt":contract.notional_usdt,
            "leverage_setting":contract.leverage_setting,"actual_gross":contract.actual_gross,
            "margin_usdt":contract.isolated_margin_usdt,"initial_stop":contract.initial_stop,
            "planned_risk_usdt":contract.planned_stop_risk_usdt,"risk_budget_usdt":contract.risk_budget_usdt,
            "liquidation_distance":contract.liquidation_distance_fraction,
            "fees_usdt":pos.entry_fee+exit_fee,"funding_net_usdt":pos.funding_net,
            "slippage_usdt":pos.entry_slippage+contract.quantity*abs(price-raw_price),
            "net_pnl_usdt":net,"equity_before":pos.equity_before,"equity_after":equity,
            "risk_contract":asdict(contract),
            "signal":asdict(pos.signal),"entry_funding_budget":pos.entry_funding_budget,
            "exit_timing":"intraminute_unknown" if reason in {"initial_stop","trailing_stop","liquidation"}
                          else "end_close" if reason == "sample_end" else "minute_open",
            "research_only":True,"orders_authorized":False})
        if reason == "initial_stop":
            consecutive_stops += 1
        else:
            consecutive_stops = 0
        if consecutive_stops >= config["cooldown_after_initial_stops"]:
            cooldown_until = t+config["cooldown_hours"]*3600
            consecutive_stops = 0
        pos = None

    for t in range(start,end,60):
        closed_this_minute = False
        if pos:
            # Settlements are booked before any fill in the same minute, conservatively.
            for symbol,row in funding_events.get(t,[]):
                if symbol != pos.contract.symbol:
                    continue
                payment = (-pos.contract.side*pos.contract.quantity*float(row["markPrice"])
                           *float(row["fundingRate"])*funding_mult)
                pos.funding_net += payment
                pos.funding_adverse += max(-payment,0)
                equity += payment
        if pos:
            sym = pos.contract.symbol
            bar,mark = data.minutes[sym][t],data.marks[sym][t]
            if pending_account_stop:
                close(t,bar.o,"account_stop")
                pending_account_stop = False
            elif pos.failure_exit_at is not None and t >= pos.failure_exit_at:
                # Protection stays live during the decision delay, including an opening gap.
                side = pos.contract.side
                buffer = pos.contract.maintenance_margin_assumption + float(data.rules[sym]["liquidationFee"])
                margin_per_unit = (pos.contract.isolated_margin_usdt+pos.funding_net)/pos.contract.quantity
                liquidation = (pos.contract.entry_price-side*margin_per_unit)/(1-side*buffer)
                if side*(mark.o-liquidation) <= 0:
                    close(t,bar.o,"liquidation")
                elif side*(bar.o-pos.stop) <= 0:
                    raw = bar.o*(1-side*0.01) if scenario == "stop_gap_1pct" else bar.o
                    close(t,raw,"trailing_stop" if pos.trailing else "initial_stop")
                else:
                    close(t,bar.o,"breakout_failure")
            elif t >= pos.deadline:
                close(t,bar.o,"session_close" if pos.signal.market == "stock" else "max_hold")
            elif t in updates[sym]:
                completed,volatility = updates[sym][t]
                remaining = max((pos.deadline-t)/3600,0)
                forecast = funding_budget(data.funding[sym],data.funding_intervals.get(sym,[]),
                                          t,remaining,config)["fraction"]*funding_mult
                execution_friction = 2*(config[f"{pos.signal.market}_fee_per_side"]
                                         +config[f"{pos.signal.market}_slippage_per_side"])*cost_mult
                initial_distance = abs(pos.contract.initial_stop-pos.contract.entry_price)/pos.contract.entry_price
                if (execution_friction+forecast+pos.funding_adverse/pos.contract.notional_usdt
                        > config["max_friction_to_stop"]*initial_distance):
                    close(t,bar.o,"funding_budget")
                elif pos.signal.market == "crypto" and completed.t+3600 > pos.entered:
                    direction = pos.contract.side
                    boundary = pos.signal.breakout_high if direction == 1 else pos.signal.breakout_low
                    if (config.get("breakout_failure_exit",False) and boundary is not None
                            and direction*(completed.c-boundary) <= 0):
                        pos.failure_exit_at = t+delay*60
                    if completed.t < pos.entered:
                        # The first hour contains pre-entry prices: keep only known
                        # minutes after the fill, while still checking its completed close.
                        held_minutes = [data.minutes[sym][minute]
                                        for minute in range(pos.entered,completed.t+3600,60)]
                        high,low = max(b.h for b in held_minutes),min(b.l for b in held_minutes)
                    else:
                        high,low = completed.h,completed.l
                    pos.extreme = max(pos.extreme,high) if direction == 1 else min(pos.extreme,low)
                    initial_r = abs(pos.contract.entry_price-pos.contract.initial_stop)
                    if direction*(completed.c-pos.contract.entry_price) >= config["trailing_activation_r"]*initial_r:
                        pos.trailing = True
                    if pos.trailing:
                        proposed = pos.extreme-direction*config["trailing_atr"]*volatility
                        tick = float(next(row["tickSize"] for row in data.rules[sym]["filters"]
                                          if row["filterType"] == "PRICE_FILTER"))
                        proposed = (math.ceil(proposed/tick) if direction == 1 else math.floor(proposed/tick))*tick
                        pos.stop = max(pos.stop,proposed) if direction == 1 else min(pos.stop,proposed)
        if pos:
            sym = pos.contract.symbol
            bar,mark = data.minutes[sym][t],data.marks[sym][t]
            contract,side = pos.contract,pos.contract.side
            buffer = contract.maintenance_margin_assumption + float(data.rules[sym]["liquidationFee"])
            margin_per_unit = (contract.isolated_margin_usdt+pos.funding_net)/contract.quantity
            liquidation = (contract.entry_price-side*margin_per_unit)/(1-side*buffer)
            touched_liquidation = mark.l <= liquidation if side == 1 else mark.h >= liquidation
            touched_stop = bar.l <= pos.stop if side == 1 else bar.h >= pos.stop
            adverse = mark.l if side == 1 else mark.h
            worst_equity = equity+side*contract.quantity*(adverse-contract.entry_price)
            max_intra_minute_drawdown = max(max_intra_minute_drawdown,1-worst_equity/peak)
            # If both are reached in one minute, OHLC cannot order the events: liquidation first.
            if touched_liquidation:
                close(t,bar.o if side*(bar.o-liquidation)<0 else liquidation,"liquidation")
            elif touched_stop:
                raw = min(bar.o,pos.stop) if side == 1 else max(bar.o,pos.stop)
                if scenario == "stop_gap_1pct":
                    raw *= 1-side*0.01
                close(t,raw,"trailing_stop" if pos.trailing else "initial_stop")
        closed_this_minute = bool(trades and trades[-1]["exit_time"] == iso(t))
        for sig in scheduled.get(t,[]):
            reason = None
            if halt: reason = "account_halted"
            elif pos: reason = "already_holding"
            elif closed_this_minute: reason = "exit_same_minute"
            elif t < cooldown_until: reason = "cooldown"
            elif daily_entries[t//86400] >= config["max_entries_per_utc_day"]: reason = "daily_entry_limit"
            bar = data.minutes[sig.symbol][t]
            fee_rate = config[f"{sig.market}_fee_per_side"]*cost_mult
            slip_rate = config[f"{sig.market}_slippage_per_side"]*cost_mult
            price = bar.o*(1+sig.side*slip_rate)
            if not reason and abs(price-sig.close)>config["max_entry_drift_atr"]*sig.atr:
                reason = "entry_drift"
            max_hours = config["crypto_max_hold_hours"] if sig.market == "crypto" else 6
            budget = funding_budget(data.funding[sig.symbol],data.funding_intervals.get(sig.symbol,[]),
                                    sig.decision_time if config.get("funding_interval_mode") else t,
                                    max_hours,config)
            forecast = budget["fraction"]*funding_mult
            friction = 2*(fee_rate+slip_rate)+forecast
            contract = None
            if not reason:
                previous = data.minutes[sig.symbol].get(t-60)
                liquidity = previous.v*config["max_minute_volume_participation"] if previous else 0.0
                contract,reason = size_contract(sig,price,equity,
                    min(risk,config["risk_after_downshift"]) if downshift else risk,
                    friction,data.rules[sig.symbol],config,
                    liquidity_quantity=liquidity if config.get("size_to_liquidity",False) else None)
                if contract:
                    # Use the previous full minute's volume, never future fill-minute volume.
                    previous = data.minutes[sig.symbol].get(t-60)
                    if not previous or previous.v*config["max_minute_volume_participation"] < contract.quantity:
                        reason,contract = "liquidity",None
            decisions.append({"decision_time":iso(sig.decision_time),"attempt_time":iso(t),
                              "symbol":sig.symbol,"side":sig.side,"reason":reason,
                              "event_id":sig.event_id,"funding_budget":budget})
            if contract:
                before = equity
                entry_fee = contract.notional_usdt*fee_rate
                equity -= entry_fee
                deadline = t+config["crypto_max_hold_hours"]*3600
                if sig.market == "stock":
                    local = dt.datetime.fromtimestamp(t,NY)
                    close_hour = session(t)[2]
                    deadline = int(local.replace(hour=close_hour//60-1,minute=45,second=0).timestamp())
                pos = Position(contract,sig,t,before,entry_fee,
                    contract.quantity*abs(price-bar.o),contract.initial_stop,deadline,extreme=price,
                    entry_funding_budget=budget)
                daily_entries[t//86400] += 1
                max_gross,max_margin = max(max_gross,contract.actual_gross),max(max_margin,contract.isolated_margin_usdt/before)
                # The protection exists on entry; handle a touch inside this very minute.
                touched = bar.l <= pos.stop if contract.side == 1 else bar.h >= pos.stop
                mark = data.marks[sig.symbol][t]
                adverse = mark.l if contract.side == 1 else mark.h
                worst_equity = equity+contract.side*contract.quantity*(adverse-contract.entry_price)
                max_intra_minute_drawdown = max(max_intra_minute_drawdown,1-worst_equity/peak)
                liq = contract.entry_price*(1-contract.side*contract.liquidation_distance_fraction)
                if (mark.l <= liq if contract.side == 1 else mark.h >= liq):
                    close(t,liq,"liquidation")
                elif touched:
                    raw = pos.stop*(1-contract.side*0.01) if scenario == "stop_gap_1pct" else pos.stop
                    close(t,raw,"initial_stop")
                    closed_this_minute = True
            else:
                rejections[reason] += 1
        if t == end-60 and pos:
            close(end,data.minutes[pos.contract.symbol][t].c,"sample_end")
        nav = equity
        if pos:
            nav += pos.contract.side*pos.contract.quantity*(data.marks[pos.contract.symbol][t].c-pos.contract.entry_price)
        peak = max(peak,nav)
        max_drawdown = max(max_drawdown,1-nav/peak)
        if peak >= config["risk_downshift_equity_usdt"]:
            downshift = True
        if not halt and (nav <= config["equity_floor_usdt"] or max_drawdown >= config["max_drawdown"]):
            halt = "equity_floor" if nav <= config["equity_floor_usdt"] else "drawdown"
            if pos:
                # Observe at this minute close; execute next minute open.
                pending_account_stop = True
        curve.append({"time":iso(t+60),"equity_usdt":nav,
                      "position":pos.contract.symbol if pos else None})
    pnl_sum = sum(row["net_pnl_usdt"] for row in trades)
    if not math.isclose(equity,config["initial_equity_usdt"]+pnl_sum,abs_tol=1e-8):
        raise AssertionError("ledger_does_not_reconcile")
    benchmark = {}
    for symbol in config["crypto_symbols"]:
        rows = data.minutes[symbol]
        benchmark[symbol] = rows[end-60].c/rows[start].o-1
    result = {"week_start":week,"end_exclusive":iso(end),"variant":variant,
        "risk_fraction":risk,"scenario":scenario,"initial_equity_usdt":config["initial_equity_usdt"],
        "final_equity_usdt":equity,"net_return":equity/config["initial_equity_usdt"]-1,
        "log_growth":math.log(equity/config["initial_equity_usdt"]) if equity>0 else None,
        "max_drawdown":max_drawdown,"intra_minute_adverse_drawdown_bound":max_intra_minute_drawdown,
        "trade_count":len(trades),"winning_trades":sum(row["net_pnl_usdt"]>0 for row in trades),
        "crypto_trades":sum(row["market"]=="crypto" for row in trades),
        "stock_trades":sum(row["market"]=="stock" for row in trades),
        "fees_usdt":sum(row["fees_usdt"] for row in trades),
        "funding_net_usdt":sum(row["funding_net_usdt"] for row in trades),
        "slippage_usdt":sum(row["slippage_usdt"] for row in trades),
        "gross_pnl_before_all_costs_usdt":pnl_sum+sum(row["fees_usdt"]+row["slippage_usdt"]-row["funding_net_usdt"] for row in trades),
        "max_entry_gross":max_gross,"max_entry_margin_fraction":max_margin,
        "halt_reason":halt,"downshift_reached":downshift,"rejections":dict(rejections),
        "raw_signal_counts":dict(Counter(sig.symbol for sig in signals if variant=="combined" or sig.market=="crypto")),
        "benchmark_unlevered_price_return":benchmark,"cash_return":0.0,
        "CAGR":None,"Calmar":None,"annualization_reason":"development research; report unannualized path",
        "continuous_account":end_time is not None,
        "research_only":True,"orders_authorized":False,"sample_type":"discovery_not_independent_oos"}
    return {"summary":result,"trades":trades,"curve":curve,"decisions":decisions}
