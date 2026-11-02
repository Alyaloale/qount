"""Feasibility of MR top-ups inside an unchanged lifetime risk budget; no orders."""
import math

from qount.strategies.macro_lease import review_lease
from qount.strategies.perpetual import common_step, grid, normalize_brackets


def review_topup_lease(position, **kwargs):
    """Original financial review plus per-lot loss floors after an addition."""
    result = review_lease(position, **kwargs)
    if not position.get("entry_lots") or kwargs["reserve"] is None:
        return result
    worst = position["stop"]*(1-kwargs["gap"])
    price_cost = sum(lot["quantity"]*max(0., lot["entry_price"]-worst)
        +lot["quantity"]*lot["entry_price"]*(kwargs["fee"]+kwargs["slip"])
        for lot in position["entry_lots"])
    stress = (price_cost+position["quantity"]*worst*(kwargs["fee"]+kwargs["slip"])
        +position["funding_adverse_paid"]+position["quantity"]*kwargs["price"]*kwargs["reserve"])
    result["stress_risk"] = stress
    if result["allowed"] and stress > result["risk_budget"]+1e-9:
        result.update(allowed=False, reason="lease_risk_budget")
    return result


def topup_quote(position, rule, *, now, reserve_hours, reference, equity, cash, reserve, gate_reserve,
                liquidity, fee=.0005, slip=.0025, risk_fraction=.25, gap=.03,
                gross_cap=20., liquidation_multiple=1.25, mark_price=None):
    """Long-only incremental order; do not loosen stop, reset deadlines or budget.

    Loss at the stressed stop is floored per leg. A profitable old lot therefore
    cannot offset a new lot's loss. Paid adverse funding and the original total
    funding allowance remain binding; unrealized profit is never free cash.
    """
    values = (reference, equity, cash, liquidity, fee, slip, risk_fraction, gap, gross_cap)
    if any(not math.isfinite(v) for v in values) or min(reference, equity, liquidity) <= 0:
        raise ValueError("invalid_topup_inputs")
    if position.get("side", 1) != 1 or position.get("partial_exits") or position.get("topups"):
        raise ValueError("single_existing_long_lot_required")
    mark_price = reference if mark_price is None else mark_price
    if not math.isfinite(mark_price) or mark_price <= 0:
        raise ValueError("invalid_topup_mark")
    if reserve is None or gate_reserve is None:
        return dict(allowed=False, reason="funding_unknown")
    if min(reserve, gate_reserve) < 0 or not 0 < risk_fraction <= 1 or not 0 <= gap < 1:
        raise ValueError("invalid_topup_risk_inputs")
    filters = rule["filters"]
    if isinstance(filters, list):
        filters = {f["filterType"]: f for f in filters}
    lots = [filters["LOT_SIZE"], filters.get("MARKET_LOT_SIZE", filters["LOT_SIZE"])]
    step = float(common_step(lots))
    price, stop = reference*(1+slip), position["stop"]
    if stop >= reference or stop <= 0:
        return dict(allowed=False, reason="crossed_or_invalid_stop")
    minimum = grid(max(float(f["minQty"]) for f in lots), step, True)
    minimum = max(minimum, grid(float(filters["MIN_NOTIONAL"]["notional"])/price, step, True))
    old = review_lease(position, now=now, price=reference, equity=equity, cash=cash,
        reserve=reserve, hours=reserve_hours, eligible=True, fee=fee, slip=slip, risk_fraction=risk_fraction, gap=gap)
    result = dict(allowed=False, research_only=True, orders_authorized=False,
        old_quantity=position["quantity"], stop=stop, leverage=position["leverage"],
        entry_price=price, minimum_increment=minimum, step=step,
        original_risk_budget=position["risk_budget_usdt"], effective_risk_budget=old["risk_budget"],
        pre_order_effective_risk_budget=old["risk_budget"],
        existing_stress_risk=old["stress_risk"], risk_headroom=old["risk_budget"]-old["stress_risk"],
        funding_cost_cap=position["funding_cost_cap_usdt"], old_lease_check=old)
    if not old["allowed"]:
        return dict(result, reason="existing_"+old["reason"])
    friction = 2*(fee+slip)+gate_reserve
    if friction > .2*(price-stop)/price:
        return dict(result, reason="increment_friction_budget")
    q0, leverage = position["quantity"], position["leverage"]
    worst = stop*(1-gap)
    loss_per_unit = max(0., price-worst)+price*(fee+slip)+worst*(fee+slip)+reference*reserve
    max_risk_quantity = max(0., result["risk_headroom"])/loss_per_unit
    result.update(increment_stress_per_unit=loss_per_unit, risk_only_quantity=max_risk_quantity,
                  risk_only_grid_quantity=grid(max_risk_quantity, step),
                  minimum_increment_stress=minimum*loss_per_unit)
    upper = grid(min(max_risk_quantity, liquidity, *(float(f["maxQty"])-q0 for f in lots)), step)
    brackets = normalize_brackets(rule["leverage_brackets"]) if "leverage_brackets" in rule else None

    def check(q):
        entry_fee = q*price*fee
        marked_after = equity+q*(mark_price-price)-entry_fee-q*mark_price*fee
        budget = min(position["risk_budget_usdt"], risk_fraction*marked_after)
        total_q = q0+q
        margin = position["margin_usdt"]+q*price/leverage
        future = total_q*reference*reserve
        stress = old["stress_risk"]+q*loss_per_unit
        if stress > budget+1e-9:
            return False, "lifetime_risk_budget"
        if position["funding_adverse_paid"]+future > position["funding_cost_cap_usdt"]+1e-9:
            return False, "lifetime_funding_budget"
        if margin+future > cash-entry_fee+1e-9:
            return False, "cash_margin_funding"
        if margin > .8*marked_after+1e-9 or total_q*reference > gross_cap*marked_after+1e-9:
            return False, "margin_or_gross_cap"
        tier = next((b for b in brackets if b["notionalFloor"] <= total_q*price < b["notionalCap"]), None) if brackets else None
        if brackets and (tier is None or leverage > tier["initialLeverage"]):
            return False, "existing_leverage_tier"
        maintenance = tier["maintMarginRatio"] if tier else float(rule.get("maintenance_margin_ratio", .01))
        buffer = maintenance+float(rule.get("liquidationFee", rule.get("liquidation_fee", .015)))
        average = (q0*position["entry_price"]+q*price)/total_q
        distance = max(0., (average-stop)/average)
        if (1/leverage-buffer)/(1-buffer) < liquidation_multiple*(distance+gap):
            return False, "joint_liquidation_distance"
        return True, dict(quantity=q, total_quantity=total_q, weighted_entry=average,
            incremental_entry_fee=entry_fee, joint_margin=margin, future_funding_reserve=future,
            joint_stress_risk=stress, effective_risk_budget=budget,
            additional_notional=q*price, original_deadline_unchanged=True,
            maintenance_margin_ratio=maintenance, buffer=buffer, leverage_bracket=tier)

    result["minimum_order_financial_check"] = dict(zip(("allowed", "detail"), check(minimum)))
    result["one_step_financial_check"] = dict(zip(("allowed", "detail"), check(step)))
    if upper+1e-10 < minimum:
        return dict(result, reason="risk_headroom_below_minimum_increment" if max_risk_quantity < minimum
                    else "capacity_below_minimum_increment")
    # Constraints can be discontinuous at a tier boundary; search each constant tier.
    feasible = []
    tiers = brackets or [dict(notionalFloor=0., notionalCap=math.inf)]
    for tier in tiers:
        lower = max(minimum, grid(max(0., tier["notionalFloor"]/price-q0), step, True))
        cap = upper if math.isinf(tier["notionalCap"]) else min(upper, grid(
            max(0., math.nextafter(tier["notionalCap"], 0.)/price-q0), step))
        low, high = round(lower/step), round(cap/step)
        if low > high or not check(low*step)[0]:
            continue
        best = low
        while low <= high:
            middle = (low+high)//2
            if check(middle*step)[0]:
                best, low = middle, middle+1
            else:
                high = middle-1
        feasible.append(grid(best*step, step))
    if not feasible:
        return dict(result, reason=result["minimum_order_financial_check"]["detail"] if not result["minimum_order_financial_check"]["allowed"] else "joint_constraints")
    q = max(feasible)
    allowed, details = check(q)
    assert allowed and q+1e-9 >= minimum
    return dict(result, allowed=True, reason="feasible_quote_only", **details)


class MRTopupPolicy:
    """One addition per MR episode; compare new MR with a scheduled refill."""
    def __init__(self, data, features, capacities, *, fee=.0005, slip=.0025,
                 risk_fraction=.25, gap=.03, gross_cap=20., funding_policy="debit_stress", trigger="new_mr"):
        if trigger not in ("new_mr", "first_review"):
            raise ValueError("unknown_topup_trigger")
        self.trigger = trigger
        self.data, self.features, self.capacities = data, features, capacities
        self.fee, self.slip, self.risk_fraction = fee, slip, risk_fraction
        self.gap, self.gross_cap, self.funding_policy = gap, gross_cap, funding_policy
        self.previous_volume = {s: {b.t+3600: b.v for b in d["trade"]} for s, d in data.items()}
        self.marks = {s: {b.t: b.o for b in d["mark"]} for s, d in data.items()}

    def __call__(self, position, feature, now, equity, cash, reference):
        from qount.strategies.macro_1atr import RISK_FRACTION, entry_candidates
        from qount.strategies.macro_funding import funding_reserve
        if self.risk_fraction != RISK_FRACTION:
            raise ValueError("topup_requires_selected_risk_fraction")
        if position.get("topups"):
            return None
        symbol = position["symbol"]
        target = None
        if self.trigger == "new_mr":
            if (not feature["entry_tactical"] or feature["tactical_setup"] != "mean_reversion"
                    or feature["available"] <= position["feature_available"]):
                return None
            orders, rejections = entry_candidates(self.data, self.features, self.capacities,
                now, equity, fee=self.fee, slip=self.slip)
            target = next((o for o in orders if o["symbol"] == symbol), None)
            if target is None:
                return dict(allowed=False, reason="original_full_entry_gate_rejected", rejections=rejections)
        elif now != position["entry_time"]+position["funding_lease_hours"]*3600 or not feature["hold_structural"]:
            return None
        capacity = self.capacities[symbol, now]
        if not now-120 <= capacity["asof"] <= now-60:
            raise ValueError("noncausal_or_stale_topup_capacity")
        deadline = min(position["funding_lease_deadline"],
                       position["entry_time"]+position["max_hold_hours"]*3600)
        hours = max(0., (deadline-now)/3600)
        reserve = funding_reserve(self.data[symbol]["funding"], now, hours, self.funding_policy)
        gate_reserve = funding_reserve(self.data[symbol]["funding"], now, 168, self.funding_policy)
        liquidity = min(self.previous_volume[symbol][now]*.01, capacity["quantity_cap"])
        plan = topup_quote(position, self.data[symbol]["rule"], now=now, reserve_hours=hours,
            reference=reference, equity=equity, cash=cash, reserve=reserve, gate_reserve=gate_reserve,
            liquidity=liquidity, fee=self.fee, slip=self.slip, risk_fraction=self.risk_fraction,
            gap=self.gap, gross_cap=min(self.gross_cap, feature["gross_target"]),
            mark_price=self.marks[symbol][now])
        return dict(plan, full_entry_order=target, trigger=self.trigger)


def verify_topup_replay(result, data, parameters):
    """Reconcile each lot's fees and funding from its own actual model entry time."""
    fee = parameters["fee"]
    for trade in result["trades"]:
        lots = trade.get("entry_lots", [dict(quantity=trade["quantity"], entry_price=trade["entry_price"],
            entry_time=trade["entry_time"], entry_fee=trade["entry_fee"])])
        paid = 0.
        for row in data[trade["symbol"]]["funding"]:
            stamp = int(row["fundingTime"])
            if stamp >= trade["exit_time"]*1000:
                continue
            quantity = sum(lot["quantity"] for lot in lots if lot["entry_time"]*1000 <= stamp)
            payment = -quantity*float(row["markPrice"])*float(row["fundingRate"])
            if trade["exit_reason"] in ("stop", "liquidation_proxy") and stamp >= (trade["exit_time"]-3600)*1000 and payment > 0:
                continue
            paid += payment
        assert math.isclose(paid, trade["funding"], abs_tol=1e-8)
        assert math.isclose(sum(lot["quantity"] for lot in lots), trade["quantity"], abs_tol=1e-8)
        net = sum(lot["quantity"]*(trade["exit_price"]-lot["entry_price"])-lot["entry_fee"]
                  for lot in lots)-trade["quantity"]*trade["exit_price"]*fee+paid
        assert math.isclose(net, trade["net_pnl"], abs_tol=1e-8)
        for add in trade.get("topups", []):
            assert trade["feature_available"] < add["feature_available"] < add["time"]
            assert add["original_hold_deadline"] == trade["entry_time"]+trade["max_hold_hours"]*3600
            assert add["quote"]["original_risk_budget"] == trade["risk_budget_usdt"]
            assert add["post_review"]["allowed"]
            assert add["post_review"]["stress_risk"] <= add["post_review"]["risk_budget"]+1e-8
            assert add["post_review"]["risk_budget"] <= trade["risk_budget_usdt"]+1e-8
        for review in trade.get("funding_lease_reviews", []):
            if review["allowed"]:
                assert review["stress_risk"] <= review["risk_budget"]+1e-8
            assert review["funding_cost_cap"] == trade["funding_cost_cap_usdt"]
    assert math.isclose(parameters["capital"]+sum(t["net_pnl"] for t in result["trades"]),
                        result["summary"]["final_equity"], abs_tol=1e-8)
