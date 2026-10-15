"""Causal, public-input paper/replay engine. No exchange execution client."""
from __future__ import annotations

import math
import statistics
from collections import Counter, deque
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from qount.research.small_account_breakout import Bar, aggregate, atr, funding_budget, iso


@dataclass
class UnitLedger:
    equity: float
    units: float
    peak_nav: float = 1.0
    deposits: float = 0.0
    withdrawals: float = 0.0

    @property
    def nav(self):
        return self.equity / self.units

    def transfer(self, amount: float):
        if not math.isfinite(amount) or self.nav <= 0 or self.equity + amount <= 0:
            raise ValueError("invalid_transfer")
        self.units += amount / self.nav
        self.equity += amount
        self.deposits += max(amount, 0)
        self.withdrawals += max(-amount, 0)
        # NAV, its peak, downshift and HALT are not reset by cash flows.


def grid(value, tick, up=False):
    d, step = Decimal(str(value)), Decimal(str(tick))
    return float((d / step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * step)


def common_step(filters):
    values = [Decimal(f["stepSize"]) for f in filters if Decimal(f["stepSize"]) > 0]
    places = max(-v.as_tuple().exponent for v in values)
    scale = 10 ** places
    return Decimal(math.lcm(*(int(v * scale) for v in values))) / scale


def size(config, rule, reference, price, volatility, equity, budget, reserve, fee, slip, liquidity):
    filters = rule["filters"]
    if isinstance(filters, list):
        filters = {f["filterType"]: f for f in filters}
    tick = filters["PRICE_FILTER"]["tickSize"]
    stop = grid(reference - config["signal"]["initial_stop_atr"] * volatility, tick, True)
    if not 0 < stop < price:
        return None, "invalid_stop"
    distance = (price-stop)/price
    friction = 2*(fee+slip)+reserve
    if friction > config["cost_model"]["ordinary_friction_limit_fraction_of_stop"]*distance:
        return None, "friction_budget"
    gap = config["cost_model"]["stop_gap_reserve"]
    buffer = 0.01 + float(rule.get("liquidationFee", rule.get("liquidation_fee", 0.015)))
    leverage = config["sizing"]["exchange_leverage"]["maximum"]
    while leverage and (1/leverage-buffer)/(1-buffer) < 3*(distance+gap):
        leverage -= 1
    if not leverage:
        return None, "liquidation_distance"
    worst = stop*(1-gap)
    # Conservative reference Pe already includes ordinary entry slippage;
    # stress allowance deliberately also reserves it per the frozen exact formula.
    loss_per_unit = price-worst+price*(fee+slip+reserve)+worst*(fee+slip)
    caps = config["sizing"]["notional_caps"]
    lots = [filters["LOT_SIZE"], filters.get("MARKET_LOT_SIZE", filters["LOT_SIZE"])]
    quantity = grid(min(budget/loss_per_unit, caps["effective_gross"]*equity/price,
        caps["maximum_isolated_margin_fraction"]*equity*leverage/price,
        equity/(price*(1/leverage+fee+reserve)), liquidity,
        *(float(f["maxQty"]) for f in lots)), common_step(lots))
    minimum = float(filters["MIN_NOTIONAL"]["notional"])
    if quantity < max(float(f["minQty"]) for f in lots) or quantity*price < minimum:
        return None, "minimum_order"
    result = dict(quantity=quantity, entry_price=price, initial_stop=stop, stop=stop,
        notional_usdt=quantity*price, margin_usdt=quantity*price/leverage,
        leverage=leverage, buffer=buffer, stress_risk_usdt=quantity*loss_per_unit,
        structural_risk_usdt=quantity*(price-stop), risk_budget_usdt=budget)
    assert result["stress_risk_usdt"] <= budget+1e-9
    return result, "accepted"


def features(hours, daily, period):
    updates = {}
    for symbol, rows in hours.items():
        bars = rows if period == 3600 else aggregate(rows, period, 3600)
        volatility = atr(bars)
        for i in range(99, len(bars)):
            if bars[i].t-bars[i-99].t != 99*period:
                continue
            high = max(b.h for b in bars[i-20:i])
            updates.setdefault(bars[i].t+period, {})[symbol] = {
                "close": bars[i].c, "atr": volatility[i], "breakout": bars[i].c > high}
    gates = {}
    for i in range(199, len(daily)):
        if daily[i].t-daily[i-199].t != 199*86400:
            continue
        gates[daily[i].t+86400] = daily[i].c > statistics.mean(b.c for b in daily[i-199:i+1])
    return updates, gates


class PaperEngine:
    """One minute step shared by historical replay and offline paper input streams.

    Only completed feature bars and previously settled funding can affect decisions.
    Snapshot state is JSON serializable for deterministic checkpoint/restart.
    """
    def __init__(self, config, rules, funding, capital=10.0, gated=True, scenario="base"):
        if config.get("research_only") is not True or config.get("orders_authorized") is not False:
            raise ValueError("research_only_contract_required")
        self.config, self.rules, self.funding = config, rules, funding
        self.gated, self.scenario = gated, scenario
        mult = 2 if scenario == "double_cost" else 1
        self.fee = config["cost_model"]["paper_fee_per_side"]*mult
        self.slip = config["cost_model"]["paper_slippage_per_side"]*mult
        self.funding_mult = mult
        self.fill_gap = 0.02 if scenario == "gap_2pct" else 0.01 if scenario == "gap_1pct" else 0
        self.ledger = UnitLedger(capital, capital)
        self.initial = capital
        self.pos = None
        self.gate = None
        self.pending = []
        self.exit_pending = None
        self.halt = None
        self.downshift = False
        self.cooldown = 0
        self.daily_entries = Counter()
        self.history = deque()
        self.history_basis = "unit_nav"
        self.trades, self.decisions, self.journal, self.curve = [], [], [], []
        self.rejections = Counter()
        self.mdd = self.intraminute_mdd_bound = 0.0
        self.held_minutes = 0
        self.last_t = None

    def snapshot(self):
        result = dict(self.__dict__)
        for key in ("config", "rules", "funding"):
            result.pop(key)
        result["ledger"] = asdict(self.ledger)
        result["history"] = list(self.history)
        result["daily_entries"] = dict(self.daily_entries)
        result["rejections"] = dict(self.rejections)
        return result

    def restore(self, state):
        state = dict(state)
        if state.get("history_basis", "equity_usdt") == "equity_usdt":
            ledger = state["ledger"]
            if ledger["deposits"] or ledger["withdrawals"]:
                raise ValueError("legacy_cashflow_history_requires_replay")
            state["history"] = [(t, equity/ledger["units"]) for t, equity in state["history"]]
            state["history_basis"] = "unit_nav"
        elif state["history_basis"] != "unit_nav":
            raise ValueError("unknown_checkpoint_history_basis")
        self.__dict__.update(state)
        self.ledger = UnitLedger(**state["ledger"])
        self.history = deque(tuple(row) for row in state["history"])
        self.daily_entries = Counter({int(k): v for k,v in state["daily_entries"].items()})
        self.rejections = Counter(state["rejections"])

    def transfer(self, amount, t=None):
        """Explicit reconciled research cash flow; never detect account deposits.

        Transfers are accepted only when flat and without pending intents. They
        preserve rolling NAV history, the drawdown high-water mark and latches.
        """
        if self.pos or self.pending or self.exit_pending:
            raise ValueError("cashflow_requires_flat_reconciled_state")
        self.ledger.transfer(amount)
        self.journal.append({"time": self.last_t if t is None else t,
            "type": "CASHFLOW", "amount": amount, "nav": self.ledger.nav,
            "units": self.ledger.units, "equity_usdt": self.ledger.equity})

    def reserve(self, symbol, t, hours):
        return funding_budget(self.funding[symbol], [], t, hours,
            {"funding_interval_mode": "known_or_observed", "funding_interval_fallback_hours": 8})["fraction"]*self.funding_mult

    def close(self, t, raw, reason):
        p = self.pos
        price = raw*(1-self.slip)
        exit_fee = p["quantity"]*price*self.fee
        if reason == "liquidation":
            exit_fee += p["quantity"]*price*(p["buffer"]-0.01)
        self.ledger.equity += p["quantity"]*(price-p["entry_price"])-exit_fee
        net = self.ledger.equity-p["equity_before"]
        trade = {**p, "exit_time": t, "exit_price": price, "exit_reason": reason,
            "net_pnl_usdt": net, "fees_usdt": p["entry_fee"]+exit_fee,
            "slippage_usdt": p["entry_slippage"]+p["quantity"]*raw*self.slip,
            "net_structural_r": net/p["structural_risk_usdt"],
            "net_stress_r": net/p["stress_risk_usdt"],
            "stress_budget_exceeded": -net > p["stress_risk_usdt"]+1e-9}
        self.trades.append(trade)
        self.journal.append({"time": t, "type": "EXIT", "reason": reason, "pnl": net})
        self.cooldown = t+self.config["signal"]["reentry_cooldown_after_exit_hours"]*3600
        self.pos = self.exit_pending = None

    def step(self, t, minutes, marks, previous, completed=None, gate=None, settlements=(), cashflow_usdt=0.0):
        if self.last_t is not None and t != self.last_t+60:
            raise ValueError("noncontinuous_paper_clock")
        for symbol in self.config["universe"]:
            if symbol not in minutes or symbol not in marks:
                raise ValueError("missing_minute_or_mark")
        if cashflow_usdt:
            self.transfer(cashflow_usdt, t)
        self.last_t = t
        had_position = self.pos is not None
        if self.pos:
            p = self.pos
            for symbol, row in settlements:
                if symbol == p["symbol"]:
                    payment = -p["quantity"]*float(row["markPrice"])*float(row["fundingRate"])*self.funding_mult
                    self.ledger.equity += payment
                    p["funding_net_usdt"] += payment
                    p["funding_adverse"] += max(-payment, 0)
                    self.journal.append({"time": t, "type": "FUNDING", "amount": payment})
            bar, mark = minutes[p["symbol"]], marks[p["symbol"]]
            liquidation = (p["entry_price"]-(p["margin_usdt"]+p["funding_net_usdt"])/p["quantity"])/(1-p["buffer"])
            # Opening protection remains effective before scheduled ordinary exits.
            if mark.o <= liquidation:
                self.close(t, bar.o, "liquidation")
            elif bar.o <= p["stop"]:
                self.close(t, bar.o*(1-self.fill_gap), "stop")
            elif self.exit_pending and t >= self.exit_pending[0]:
                self.close(t, bar.o, self.exit_pending[1])
            elif t >= p["deadline"]:
                self.close(t, bar.o, "max_hold")
        if gate is not None:
            self.gate = gate
            if self.gated and not gate:
                self.pending = []
                if self.pos:
                    self.exit_pending = (t+60, "regime_off")
        for symbol, update in (completed or {}).items():
            if self.pos and symbol == self.pos["symbol"]:
                p = self.pos
                try:
                    reserve = self.reserve(symbol, t, max(0, (p["deadline"]-t)/3600))
                except ValueError:
                    reserve = math.inf
                distance = (p["entry_price"]-p["initial_stop"])/p["entry_price"]
                if 2*(self.fee+self.slip)+reserve+p["funding_adverse"]/p["notional_usdt"] > 0.2*distance:
                    self.exit_pending = (t+60, "funding_budget")
                p["highest_close"] = max(p["highest_close"], update["close"])
                if update["close"] >= p["entry_price"]+2*(p["entry_price"]-p["initial_stop"]):
                    p["trailing"] = True
                if p["trailing"]:
                    rule = self.rules[symbol]["filters"]
                    if isinstance(rule, list):
                        rule = {f["filterType"]: f for f in rule}
                    proposed = grid(p["highest_close"]-2*update["atr"], rule["PRICE_FILTER"]["tickSize"], True)
                    if proposed >= update["close"]:
                        self.exit_pending = (t+60, "crossed_trailing_stop")
                    else:
                        p["stop"] = max(p["stop"], proposed)
        due, self.pending = self.pending, []
        for signal in sorted(due, key=lambda s: self.config["selection"]["priority"].index(s["symbol"])):
            symbol = signal["symbol"]
            reason = None
            if self.halt: reason = "halted"
            elif self.pos or had_position: reason = "holding_or_exit_minute"
            elif self.gated and self.gate is not True: reason = "regime_off_or_unknown"
            elif t < self.cooldown: reason = "cooldown"
            elif self.daily_entries[t//86400] >= 1: reason = "daily_entry_limit"
            price = minutes[symbol].o*(1+self.slip)
            if not reason and price > signal["close"]+0.3*signal["atr"]: reason = "entry_drift"
            reserve = 0
            if not reason:
                try: reserve = self.reserve(symbol, signal["time"], 72)
                except ValueError: reason = "missing_funding"
            contract = None
            if not reason:
                e = self.ledger.equity
                risk = min(0.015 if self.downshift else 0.03, 0.02 if e >= 100 else 0.03)
                # Cash flows change USDT equity but must not change the unit-NAV
                # loss budget. Convert the rolling reference back to dollars
                # only after comparing it on the same unit basis.
                ref = self.history[0][1] * self.ledger.units if self.history else e
                budget = min(risk*e, 0.03*e, max(0, e-0.94*ref),
                             max(0, e-0.8*self.ledger.peak_nav*self.ledger.units))
                contract, reason = size(self.config, self.rules[symbol], signal["close"]*(1+self.slip),
                    price, signal["atr"], e, budget, reserve, self.fee, self.slip,
                    previous[symbol].v*0.01 if symbol in previous else 0)
            self.decisions.append({"time":t,"decision_time":signal["time"],"symbol":symbol,"reason":reason})
            if contract:
                assert t > signal["time"]
                self.pos = {**contract,"symbol":symbol,"decision_time":signal["time"],
                    "entry_time":t,"equity_before":self.ledger.equity,"entry_fee":contract["notional_usdt"]*self.fee,
                    "entry_slippage":contract["quantity"]*(price-minutes[symbol].o),
                    "funding_net_usdt":0.0,"funding_adverse":0.0,"highest_close":price,
                    "trailing":False,"deadline":t+72*3600}
                self.ledger.equity -= self.pos["entry_fee"]
                self.daily_entries[t//86400] += 1
                self.journal.append({"time":t,"type":"ENTRY","symbol":symbol,"quantity":contract["quantity"]})
            else:
                self.rejections[reason] += 1
        # Signals known only at this completed close fill at t+60, never t.
        self.pending = [{**u,"symbol":s,"time":t} for s,u in (completed or {}).items() if u["breakout"]]
        equity = self.ledger.equity
        if self.pos:
            p = self.pos
            bar,mark = minutes[p["symbol"]],marks[p["symbol"]]
            self.held_minutes += 1
            liquidation = (p["entry_price"]-(p["margin_usdt"]+p["funding_net_usdt"])/p["quantity"])/(1-p["buffer"])
            if mark.l <= liquidation:
                self.close(t, min(bar.o,liquidation), "liquidation")
            elif bar.l <= p["stop"]:
                self.close(t, min(bar.o,p["stop"])*(1-self.fill_gap), "stop")
            else:
                worst = equity+p["quantity"]*(mark.l*(1-self.slip)-p["entry_price"])-p["quantity"]*mark.l*self.fee
                self.intraminute_mdd_bound = max(self.intraminute_mdd_bound, 1-worst/(self.ledger.peak_nav*self.ledger.units))
                equity += p["quantity"]*(mark.c*(1-self.slip)-p["entry_price"])-p["quantity"]*mark.c*self.fee
        if not self.pos:
            equity = self.ledger.equity
        nav = equity/self.ledger.units
        self.ledger.peak_nav = max(self.ledger.peak_nav, nav)
        dd = 1-nav/self.ledger.peak_nav
        self.mdd = max(self.mdd, dd)
        self.downshift |= dd >= 0.1
        # Store unit NAV rather than absolute equity so deposits and withdrawals
        # cannot manufacture or erase a rolling-loss breach.
        self.history.append((t, nav))
        while self.history and self.history[0][0] < t-86400:
            self.history.popleft()
        if dd >= 0.2 or nav <= 0.94*self.history[0][1]:
            self.halt = self.halt or ("nav_drawdown" if dd >= 0.2 else "rolling_loss")
            self.pending = []
            if self.pos: self.exit_pending = (t+60, self.halt)
        self.curve.append({"time":t+60,"equity_usdt":equity,"nav":nav,"drawdown":dd,
                           "gross":self.pos["quantity"]*marks[self.pos["symbol"]].c/equity if self.pos else 0})


def replay(data, config, updates, gates, start, end, capital=10, gated=True, scenario="base"):
    engine = PaperEngine(config, data.rules, data.funding, capital, gated, scenario)
    # As-of at the first minute includes only already completed days.
    known = [t for t in gates if t <= start]
    engine.gate = gates[max(known)] if known else None
    if gated and engine.gate is None:
        raise ValueError("missing_daily_warmup")
    events = {}
    for symbol, rows in data.funding.items():
        for row in rows:
            t = int(row["fundingTime"])//60000*60
            events.setdefault(t, []).append((symbol,row))
    for t in range(start,end,60):
        engine.step(t, {s: rows[t] for s,rows in data.minutes.items()},
            {s: rows[t] for s,rows in data.marks.items()},
            {s: rows[t-60] for s,rows in data.minutes.items() if t-60 in rows},
            updates.get(t), gates.get(t), events.get(t, []))
    if engine.pos:
        engine.close(end-60, data.minutes[engine.pos["symbol"]][end-60].c, "sample_end")
        equity = engine.ledger.equity
        engine.curve[-1].update(equity_usdt=equity, nav=equity/engine.ledger.units)
        engine.mdd = max(engine.mdd,1-equity/(engine.ledger.units*engine.ledger.peak_nav))
    trades = engine.trades
    monthly = {}
    prev = capital
    for row in engine.curve:
        month = iso(row["time"]-1)[:7]
        monthly.setdefault(month, {"start":prev})["end"] = row["equity_usdt"]
        prev = row["equity_usdt"]
    summary = {"initial_equity_usdt":capital,"final_equity_usdt":engine.ledger.equity,
        "net_return":engine.ledger.equity/capital-1,"max_drawdown":engine.mdd,
        "intraminute_mdd_bound":max(engine.mdd,engine.intraminute_mdd_bound),
        "trade_count":len(trades),"mean_net_structural_r":statistics.mean(t["net_structural_r"] for t in trades) if trades else None,
        "mean_net_stress_r":statistics.mean(t["net_stress_r"] for t in trades) if trades else None,
        "worst_trade_usdt":min((t["net_pnl_usdt"] for t in trades),default=None),
        "fees_usdt":sum(t["fees_usdt"] for t in trades),"slippage_usdt":sum(t["slippage_usdt"] for t in trades),
        "funding_net_usdt":sum(t["funding_net_usdt"] for t in trades),
        "stress_overruns":sum(t["stress_budget_exceeded"] for t in trades),
        "symbol_trades":dict(Counter(t["symbol"] for t in trades)),"rejections":dict(engine.rejections),
        "time_in_cash":1-engine.held_minutes/((end-start)/60),"halt":engine.halt,"downshift":engine.downshift,
        "monthly_returns":{m:r["end"]/r["start"]-1 for m,r in monthly.items()},
        "mean_gross_exposure":statistics.mean(r["gross"] for r in engine.curve),
        "minimum_rejection_rate":engine.rejections["minimum_order"]/len(engine.decisions) if engine.decisions else 0}
    assert math.isclose(engine.ledger.equity, capital+sum(t["net_pnl_usdt"] for t in trades),abs_tol=1e-8)
    return engine, summary


def fixed_fill_double_cost(trades, capital):
    """Accounting counterfactual only: same fills/quantities, no risk/gate rerun."""
    return capital+sum(t["net_pnl_usdt"]-t["fees_usdt"]-t["slippage_usdt"]+t["funding_net_usdt"] for t in trades)
