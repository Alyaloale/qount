"""Selected macro rules. Pure functions; no venue or research-run imports."""
from __future__ import annotations

import bisect
import copy

from qount.research_data.bars import session
from qount.strategies.macro_episodes import episode_confirmations
from qount.strategies.macro_funding import feature_at, funding_reserve
from qount.strategies.macro_gates import available_atr, mean_reversion_gap_confirmations
from qount.strategies.perpetual import grid, size

STRATEGY_ID = "rolling7_risk_no_chase_mr_signal_gap_1atr"
SIGNAL_MAPPING = dict(SPYUSDT="SPY", QQQUSDT="QQQ", SMHUSDT="SMH", IWMUSDT="IWM",
                      XLEUSDT="XLE", XAUUSDT="GLD", COPPERUSDT="CPER", CLUSDT="USO")
SETUPS = {"breakout": (168, "hold_tactical"), "pullback": (168, "hold_tactical"),
          "mean_reversion": (504, "hold_structural")}
FEE, SLIP, GAP, RISK_FRACTION = .0005, .0025, .03, .5


def sizing_config(gross=20):
    return {"signal": {"initial_stop_atr": 2},
            "cost_model": {"ordinary_friction_limit_fraction_of_stop": .2, "stop_gap_reserve": GAP},
            "sizing": {"exchange_leverage": {"maximum": 50}, "notional_caps": {
                "effective_gross": gross, "maximum_isolated_margin_fraction": .8}}}


def scaled_features(features):
    return {s: [dict(f, gross_target=f["gross_target"]*(20/3)) for f in rows]
            for s, rows in features.items()}


def is_decision(now):
    clock = session(now)
    return clock is not None and clock[1] == 600 and now % 3600 == 0


def known_atr(bars, now):
    rows = available_atr(bars)
    i = bisect.bisect_right([t for t, _ in rows], now)-1
    return rows[i][1] if i >= 0 and now-rows[i][0] <= 86400 else None


def entry_candidates(data, features, capacities, now, equity, *, fee=FEE, slip=SLIP):
    """Reconstruct episode anchors and rank the same eligible replay entries.

    Only the current hourly open is read; its high/low/close/volume are ignored.
    Missing causal inputs reject a candidate, never substitute a different rule.
    """
    if not is_decision(now):
        return [], {"outside_decision_time": 1}
    if set(features) != set(SIGNAL_MAPPING) or set(data) != set(SIGNAL_MAPPING):
        raise ValueError("macro_universe_mismatch")
    fs = {s: feature_at(rows, now) for s, rows in features.items()}
    if any(f is None or not 0 < now-f["available"] <= 4*86400 for f in fs.values()):
        return [], {"stale_equity_features": 1}
    anchors = episode_confirmations(data, features, "no_chase")
    gaps = mean_reversion_gap_confirmations(data, features, [(s, now) for s in data])
    accepted, rejected = [], {}
    def reject(reason):
        rejected[reason] = rejected.get(reason, 0)+1
    ranked = sorted((s for s in fs if fs[s]["entry_tactical"]),
                    key=lambda s: (-fs[s]["rank_tactical"], s))
    if not ranked:
        reject("regime_off")
    for s in ranked:
        rows = data[s]["trade"]
        index = {b.t: i for i, b in enumerate(rows)}.get(now)
        if index is None or index < 1 or rows[index-1].t != now-3600:
            reject("contract_unavailable")
            continue
        anchor, gap = anchors.get((s, now)), gaps.get((s, now))
        if not anchor or not gap:
            reject("native_confirmation_unknown")
            continue
        if not anchor["eligible"] or not gap["eligible"]:
            reject(anchor["reason"] if not anchor["eligible"] else gap["reason"])
            continue
        volatility = known_atr(rows, now)
        if volatility is None:
            reject("atr_warmup")
            continue
        horizon, hold = SETUPS[fs[s]["tactical_setup"]]
        reserve = funding_reserve(data[s]["funding"], now, min(horizon, 168), "debit_stress")
        if reserve is None:
            reject("funding_unknown")
            continue
        cap = capacities.get((s, now))
        if cap is None or cap["asof"] < now-120:
            reject("liquidity_unknown")
            continue
        if cap["asof"] > now-60:
            raise ValueError("future_liquidity_context")
        reference = rows[index].o
        config = sizing_config(min(20, fs[s]["gross_target"]))
        order, reason = size(config, data[s]["rule"], reference, reference*(1+slip),
                             volatility, equity, RISK_FRACTION*equity, reserve, fee, slip,
                             min(rows[index-1].v*.01, cap["quantity_cap"]),
                             liquidation_stop_multiple=1.25)
        if order is None:
            reject(reason)
            continue
        order.update(symbol=s, strategy_id=STRATEGY_ID, entry_time=now,
                     feature_available=fs[s]["available"], feature_date=fs[s]["date"],
                     tactical_setup=fs[s]["tactical_setup"], hold_feature=hold,
                     max_hold_hours=horizon, engine="tactical", state=fs[s]["state"],
                     gross_target=config["sizing"]["notional_caps"]["effective_gross"],
                     structural_r=order["entry_price"]-order["stop"], highest_close=order["entry_price"],
                     reference_open=reference, atr=volatility, entry_liquidity=dict(cap),
                     episode=dict(anchor), signal_gap=dict(gap), funding=0.0)
        if horizon > 168:
            order.update(funding_reserve_hours=168, funding_lease_hours=168,
                         funding_reserve_fraction=reserve, funding_lease_budget="risk",
                         funding_lease_deadline=now+168*3600, funding_adverse_paid=0.0,
                         funding_cost_cap_usdt=max(0, order["risk_budget_usdt"]-
                             (order["stress_risk_usdt"]-order["notional_usdt"]*reserve)),
                         funding_lease_reviews=[])
        accepted.append(order)
    return accepted, rejected


def trailing_update(position, close, volatility, tick):
    """Completed-hour update, effective for subsequent trading only."""
    pos = copy.deepcopy(position)
    side = pos.get("side", 1)
    pos["highest_close"] = (max if side == 1 else min)(pos["highest_close"], close)
    if volatility is not None and side*(close-pos["entry_price"]) >= 2*pos["structural_r"]:
        proposed = grid(pos["highest_close"]-side*2*volatility, tick, True)
        if side*(proposed-close) >= 0:
            return pos, "crossed_trailing_stop"
        pos["stop"] = (max if side == 1 else min)(pos["stop"], proposed)
    return pos, None
