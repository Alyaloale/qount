"""Revised G20 paper cash book: integer shares, dividend rights, then payment.

The frozen four-account program remains a reference. This account consumes the
same public ETF cache and monthly selection rule, without any order client.
"""
from __future__ import annotations

import copy
import datetime as dt
import fcntl
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from qount.contracts import canonical_hash
from qount.dual_engine.contracts import G20_EXECUTION_SYMBOLS, G20_PROXY_SYMBOLS, DualEnginePaperContract
from qount.dual_engine.strategy import build_g20_decision
from qount.dual_engine.paper import _atomic_json, _rebalance_layer

NY = ZoneInfo("America/New_York")
SYMBOLS = (*G20_EXECUTION_SYMBOLS, "BIL")
KIND = "g20_cash_distributions_v2"


def validate(data):
    if (data.get("kind") != KIND or data.get("research_only") is not True
            or data.get("orders_authorized") is not False):
        raise ValueError("g20_cash_identity_invalid")
    expected = canonical_hash({k:v for k,v in data.items() if k != "state_hash"})
    if data.get("state_hash") != expected:
        raise ValueError("g20_cash_state_hash_invalid")
    cash = data["layer"]["sleeves"]["g20"]["cash"]
    if not math.isfinite(cash) or cash < -1e-7:
        raise ValueError("g20_cash_negative_cash")
    previous = ""
    for row in data["observations"]:
        if row["date"] <= previous or not math.isfinite(row["equity"]) or row["equity"] <= 0:
            raise ValueError("g20_cash_history_invalid")
        previous = row["date"]
        if not math.isclose(row["cash"] + sum(p["market_value"] for p in row["positions"]),
                            row["equity"],abs_tol=1e-6):
            raise ValueError("g20_cash_equity_does_not_reconcile")
    for amount in data["layer"]["sleeves"]["g20"]["positions"].values():
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("g20_cash_position_invalid")
    for event in data["income"]:
        if (event["side"] not in {"DIVIDEND_ACCRUAL","DIVIDEND_PAYMENT"} or
            any(not math.isfinite(event[k]) or event[k]<0 for k in ("quantity","amount","value")) or
            not math.isclose(event["quantity"]*event["amount"],event["value"],abs_tol=1e-7)):
            raise ValueError("g20_cash_income_invalid")


def new_account(observed_at):
    return dict(kind=KIND, research_only=True, orders_authorized=False,
        created_at=observed_at, observed_at=observed_at, initial_equity=10000.0,
        layer=dict(cumulative_cost=0., cumulative_stress_cost=0.,
                   sleeves={"g20":dict(cash=10000., positions={})}),
        receivables=[], income=[], trades=[], observations=[], pending=None,
        last_date=None, distributions_received=0., last_error=None,
        rules=dict(momentum_sessions=63, risk_target=.2, cost_bps=20., lot_size=1,
                   cash_apr=0., dividend_policy="ex_date_receivable_pay_date_close_cash",
                   taxes="gross_before_tax_not_broker_net", unknown_pay_date="unspendable_receivable"))


def normalize_cache(cache, policy):
    """Undo Yahoo's historical split adjustment for physical cash/share accounting."""
    panels, actions = {}, {}
    verified = {(a["symbol"], a["ex_date"]):a for a in policy["verified_actions"]}
    for symbol, payload in cache.items():
        splits = []
        for e in payload.get("events", {}).get("splits", {}).values():
            day = dt.datetime.fromtimestamp(e["date"], NY).date().isoformat()
            ratio = float(e["numerator"]) / float(e["denominator"])
            if not math.isfinite(ratio) or ratio <= 0:
                raise ValueError("g20_cash_split_invalid")
            splits.append((day, ratio))
            if symbol in SYMBOLS:
                actions.setdefault(day, []).append(dict(kind="split", symbol=symbol, ratio=ratio))
        rows = {}
        previous = ""
        for r in payload["rows"]:
            day = r["date"]
            if day <= previous:
                raise ValueError("g20_cash_dates_invalid")
            previous = day
            factor = math.prod(ratio for ex,ratio in splits if day < ex)
            row = dict(r)
            for k in ("open", "high", "low", "close"):
                row[k] = float(r[k]) * factor
            if not all(math.isfinite(row[k]) and row[k] > 0 for k in ("open","high","low","close","adjClose")):
                raise ValueError("g20_cash_price_invalid")
            if not row["low"] <= min(row["open"],row["close"]) <= max(row["open"],row["close"]) <= row["high"]:
                raise ValueError("g20_cash_ohlc_invalid")
            rows[day] = row
        panels[symbol] = rows
        if symbol not in SYMBOLS:
            continue
        group = "proshares" if symbol in ("TQQQ", "URTY") else "BIL" if symbol == "BIL" else "direxion"
        for e in payload.get("events", {}).get("dividends", {}).values():
            day = dt.datetime.fromtimestamp(e["date"], NY).date().isoformat()
            declared = verified.get((symbol, day))
            amount = declared["amount"] if declared else float(e["amount"]) * math.prod(r for ex,r in splits if day < ex)
            if not math.isfinite(amount) or amount < 0:
                raise ValueError("g20_cash_dividend_invalid")
            pay = declared["pay_date"] if declared else policy["pay_dates"].get(group, {}).get(day)
            if pay and pay < day:
                raise ValueError("g20_cash_pay_date_precedes_ex_date")
            actions.setdefault(day, []).append(dict(kind="dividend", symbol=symbol, amount=amount,
                pay_date=pay, amount_source="issuer" if declared else "yahoo_public_rounded",
                source=declared["source"] if declared else policy["sources"][group]))
        for (ticker,day),declared in verified.items():
            if ticker == symbol and day in rows and not any(a["kind"]=="dividend" and a["symbol"]==symbol
                                                           for a in actions.get(day,[])):
                actions.setdefault(day,[]).append(dict(kind="dividend",symbol=symbol,
                    amount=declared["amount"],pay_date=declared["pay_date"],amount_source="issuer",source=declared["source"]))
    dates = sorted(panels["BIL"])
    common_start = max(min(v) for v in panels.values())
    dates = [d for d in dates if d >= common_start]
    for symbol, rows in panels.items():
        if {d for d in rows if d >= common_start} != set(dates):
            raise ValueError(f"g20_cash_calendar_gap:{symbol}")
    return panels, actions, dates


def step(data, *, day, bar, actions, decision, opening, observed_at, reconstructed=False,
         historical_replay=False):
    """One completed session; paid income becomes spendable the following session."""
    data = copy.deepcopy(data)
    sleeve = data["layer"]["sleeves"]["g20"]
    positions = sleeve["positions"]
    for a in sorted(actions, key=lambda x:x["kind"] != "split"):
        symbol = a["symbol"]
        quantity = positions.get(symbol, 0.)
        if a["kind"] == "split":
            new_quantity=quantity*a["ratio"]
            if not math.isclose(new_quantity,round(new_quantity),abs_tol=1e-9):
                raise ValueError("g20_cash_fractional_split_requires_reconciliation")
            positions[symbol] = new_quantity
            if quantity:
                data["trades"].append(dict(date=day,symbol=symbol,side="CORPORATE_ACTION_SPLIT",
                    quantity=0.,price=None,cost=None,split_ratio=a["ratio"],recorded_at=observed_at,
                    sample_kind="reconstructed" if reconstructed else "forward",note=f"split_ratio={a['ratio']}"))
        elif quantity and a["amount"]:
            event = dict(a, date=day, ex_date=day, quantity=quantity, value=quantity*a["amount"],
                         side="DIVIDEND_ACCRUAL", sample_kind="reconstructed" if reconstructed else "forward",
                         recorded_at=observed_at)
            data["receivables"].append(event)
            data["income"].append(event)
    pending = data["pending"]
    if pending and (historical_replay or dt.datetime.fromisoformat(pending["available_at"]) <= opening):
        marks = {s:bar[s]["open"] for s in SYMBOLS}
        _, fills = _rebalance_layer(data["layer"], sleeve_budgets={"g20":1.},
            sleeve_targets={"g20":pending["target"]}, marks=marks, fills=marks,
            rules={s:dict(step_size=1.,minimum_notional=0.) for s in SYMBOLS},
            contract=DualEnginePaperContract.frozen_v1(), signal=False)
        for f in fills:
            data["trades"].append(dict(date=day,symbol=f["symbol"],side=f["side"].upper(),
                quantity=f["quantity"],price=f["reference_price"],cost=f["cost"],
                decision_date=pending["decision_date"], recorded_at=observed_at,
                sample_kind="reconstructed" if reconstructed else "forward",
                note="前一收盘计划、下一可用开盘价模拟；非真实成交"))
        data["pending"] = None
    # Payment is credited after open trades; no spending before the payable date.
    remaining = []
    for a in data["receivables"]:
        if a["pay_date"] and a["pay_date"] <= day:
            sleeve["cash"] += a["value"]
            data["distributions_received"] += a["value"]
            data["income"].append(dict(a,date=day,side="DIVIDEND_PAYMENT",recorded_at=observed_at))
        else:
            remaining.append(a)
    data["receivables"] = remaining
    receivable = sum(a["value"] for a in remaining)
    market = sum(q*bar[s]["close"] for s,q in positions.items())
    equity = sleeve["cash"] + market + receivable
    holdings = [dict(symbol=s,quantity=q,price=bar[s]["close"],market_value=q*bar[s]["close"],
                     weight=q*bar[s]["close"]/equity) for s,q in positions.items() if q]
    if receivable:
        holdings.append(dict(symbol="DIVIDEND_RECEIVABLE",quantity=None,price=None,
                             market_value=receivable,weight=receivable/equity))
    if decision is not None:
        close = dt.datetime.combine(dt.date.fromisoformat(day),dt.time(16),NY)
        data["pending"] = dict(target=decision,decision_date=day,
            available_at=close.isoformat() if historical_replay else observed_at)
    data["observations"].append(dict(date=day,equity=equity,cash=sleeve["cash"],
        receivable=receivable,positions=holdings,recorded_at=observed_at,
        sample_kind="reconstructed" if reconstructed else "forward"))
    data.update(last_date=day,observed_at=observed_at,last_error=None)
    data["state_hash"] = canonical_hash({k:v for k,v in data.items() if k != "state_hash"})
    validate(data)
    return data


def refresh(root, *, policy_path, observed_at, bootstrap=False):
    root, observed = Path(root), dt.datetime.fromisoformat(observed_at)
    account_path = root/"g20-cash"/"forward.json"
    if not account_path.exists() and not bootstrap:
        return None
    account_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (account_path.parent/"account.lock").open("a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        existing = json.loads(account_path.read_text()) if account_path.exists() else None
        if existing:
            validate(existing)
        policy = json.loads(Path(policy_path).read_text())
        cache = {s:json.loads((root/"market-cache/yahoo-public"/(s+"-1d.json")).read_text())
                 for s in (*SYMBOLS,*G20_PROXY_SYMBOLS)}
        panels, actions, dates = normalize_cache(cache,policy)
        dates = [d for d in dates if dt.datetime.combine(dt.date.fromisoformat(d),dt.time(16,15),NY) <= observed]
        if not dates or dates[-1] < (observed.astimezone(NY).date()-dt.timedelta(days=4)).isoformat():
            raise ValueError("g20_cash_stale_inputs")
        if existing:
            if existing["last_date"] < dates[0]:
                raise ValueError("g20_cash_missing_continuation_anchor")
            first = next((i for i,d in enumerate(dates) if d > existing["last_date"]),len(dates))
        else:
            first = next(i for i,d in enumerate(dates) if d >= "2026-01-02")
        if first < 63:
            raise ValueError("g20_cash_warmup_short")
        data = existing or new_account(observed_at)
        if not existing:
            prior = first-1
            choice=build_g20_decision({s:[panels[s][d]["adjClose"] for d in dates[prior-63:prior+1]]
                                       for s in G20_PROXY_SYMBOLS})
            data["pending"]=dict(target=dict(choice.target_weights),decision_date=dates[prior],
                                 available_at=dt.datetime.combine(dt.date.fromisoformat(dates[prior]),dt.time(16),NY).isoformat())
        for i in range(first,len(dates)):
            day=dates[i]
            if data["last_date"] and day <= data["last_date"]:
                continue
            # Only known exchange calendars determine a month-end signal; no price peek.
            from qount.research_data.bars import session
            next_day=dt.date.fromisoformat(day)+dt.timedelta(days=1)
            for _ in range(10):
                if session(int(dt.datetime.combine(next_day,dt.time(12),NY).timestamp())):
                    break
                next_day+=dt.timedelta(days=1)
            else:
                raise ValueError("g20_cash_next_session_unknown")
            decision=None
            if next_day.month != dt.date.fromisoformat(day).month:
                choice=build_g20_decision({s:[panels[s][d]["adjClose"] for d in dates[i-63:i+1]]
                                           for s in G20_PROXY_SYMBOLS})
                decision=dict(choice.target_weights)
            reconstructed = existing is None or day < observed.astimezone(NY).date().isoformat()
            data=step(data,day=day,bar={s:panels[s][day] for s in SYMBOLS},actions=actions.get(day,[]),
                decision=decision,opening=dt.datetime.combine(dt.date.fromisoformat(day),dt.time(9,30),NY),
                observed_at=observed_at,reconstructed=reconstructed,historical_replay=existing is None)
        if existing and data["last_date"] == existing["last_date"]:
            return existing
        data["policy_hash"] = canonical_hash(policy)
        data["source_hashes"] = {s:canonical_hash(cache[s]) for s in cache}
        data["state_hash"] = canonical_hash({k:v for k,v in data.items() if k != "state_hash"})
        validate(data)
        _atomic_json(account_path,data)
        return data
