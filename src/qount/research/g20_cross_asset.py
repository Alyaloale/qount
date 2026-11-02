"""Causal cross-asset opportunity comparison, with a single funded account.

Adapters own market clocks and observed funding. No execution interface.
"""
from __future__ import annotations

import bisect
from collections import Counter
from dataclasses import dataclass

import numpy as np

from qount.research.crypto_g20_rotation import rounded_quantity

YEAR = 365.25 * 86400


@dataclass(frozen=True)
class Mechanism:
    universe: str = "all"
    regime: str = "local"
    eligible_first: bool = True
    normalize: bool = True
    retain: bool = False
    net_carry: bool = False
    tradable_first: bool = False
    carrier_risk: bool = False
    allocation_score: bool = False
    replacement: str = "never"
    hold_condition: str = "entry"
    entry_condition: str = "trend"
    core_symbol: str | None = None
    core_defensive: bool = True
    capacity_mode: str = "skip"
    excluded_symbols: tuple[str, ...] = ()

    def __post_init__(self):
        if self.universe not in ("all", "crypto", "macro") or self.regime not in ("local", "btc", "own"):
            raise ValueError("invalid_opportunity_scope")
        if self.replacement not in ("never", "cost") or self.hold_condition not in ("entry", "price", "dual_failure"):
            raise ValueError("invalid_holding_policy")
        if self.entry_condition not in ("trend", "price"):
            raise ValueError("invalid_entry_policy")
        if self.capacity_mode not in ("skip", "clip"):
            raise ValueError("invalid_capacity_policy")


def causal_features(bars):
    """Same elapsed 63/120 day horizons across 24/7 and session calendars.

    Volatility uses 30 observed log returns and annualizes by their elapsed
    calendar time. It never treats missing ETF sessions as zero-return bars.
    """
    times = np.array([b.t for b in bars], dtype=np.int64)
    close = np.array([b.c for b in bars])
    result = []
    for i, b in enumerate(bars):
        anchor = bisect.bisect_right(times, b.t - 63 * 86400) - 1
        first = bisect.bisect_right(times, b.t - 120 * 86400)
        if anchor < 0 or b.t - times[0] < 120 * 86400 or i < 30:
            continue
        days = (b.t - times[anchor]) / 86400
        annual_momentum = float(np.log(close[i] / close[anchor]) * 365.25 / days)
        annualization = YEAR * 30 / (b.t - times[i - 30])
        sigma = float(np.std(np.diff(np.log(close[i - 30:i + 1])), ddof=1) * np.sqrt(annualization))
        result.append(dict(available=b.t, close=b.c, annual_momentum=annual_momentum,
                           sigma=max(sigma, 1e-8), above_mean=bool(b.c > close[first:i + 1].mean()),
                           trend=bool(annual_momentum > 0 and b.c > close[first:i + 1].mean())))
    return result


def choose(features, groups, mechanism, *, held=None, cost=0.003, tradable=None, cap=2., vol_target=.6):
    names = sorted(s for s in features if s not in mechanism.excluded_symbols and (mechanism.universe == "all" or
                   (groups[s] == "crypto" if mechanism.universe == "crypto" else groups[s] != "crypto")))
    allowed, scores, drifts, exposure = {}, {}, {}, {}
    def on(symbol):
        return bool(features.get(symbol, {}).get("trend", False))
    for s in names:
        f = features[s]
        gate = True if mechanism.regime == "own" else on("BTCUSDT") if mechanism.regime == "btc" else (
            on("BTCUSDT") if groups[s] == "crypto" else on("SPYUSDT") if groups[s] == "equity" else True)
        price_condition = mechanism.entry_condition == "price" or (
            mechanism.retain and s == held and mechanism.hold_condition == "price")
        trend = f.get("above_mean", f["trend"]) if price_condition else f["trend"]
        if mechanism.retain and s == held and mechanism.hold_condition == "dual_failure":
            # Entry can require both signals; a held trend is invalidated only
            # when both existing indicators fail, with no new numeric buffer.
            trend = f.get("above_mean", f["trend"]) or f["annual_momentum"] > 0
        allowed[s] = bool(trend and gate)
        if mechanism.carrier_risk:
            allowed[s] = allowed[s] and f.get("risk_available", False)
        if mechanism.tradable_first:
            allowed[s] = allowed[s] and bool(tradable and tradable.get(s, False))
        drift = f["annual_momentum"]
        if mechanism.net_carry:
            # Causal realized carry is an explicit forecast proxy, not a
            # known future rate. Amortize two sides over the signal horizon.
            drift -= max(0., f.get("annual_carry", 0.)) + 2 * cost * 365.25 / 63
            allowed[s] = allowed[s] and drift > 0
        exposure[s] = min(cap, vol_target / f["sigma"])
        drifts[s] = exposure[s] * drift
        scores[s] = drifts[s] if mechanism.allocation_score else drift / f["sigma"] if mechanism.normalize else drift
    if mechanism.core_symbol is not None:
        if allowed.get(mechanism.core_symbol, False):
            return mechanism.core_symbol
        if not mechanism.core_defensive:
            return None
        # The equity core has failed its own trend. Alternative sleeves must
        # have a different economic driver, rather than substitute a sector
        # equity for a broken broad-equity signal.
        for s in names:
            if groups[s] == "equity":
                allowed[s] = False
    candidates = [s for s in names if allowed[s]] if mechanism.eligible_first else names
    if not candidates:
        return None
    best = min(candidates, key=lambda s: (-scores[s], s))
    if mechanism.retain and held in allowed and allowed[held]:
        if mechanism.replacement == "never":
            return held
        # The signal's 63-calendar-day horizon, with no optimized buffer.
        # Past drift is only a forecast proxy. A rank change alone cannot
        # justify paying the estimated full close-and-open cost.
        advantage = (drifts[best] - drifts[held]) * 63 / 365.25
        switch_cost = cost * (exposure[best] + exposure[held])
        if advantage <= switch_cost:
            return held
    return best if allowed[best] else None


def replay(panel, mechanism, *, capital=21.25, cost_bp=30, cap=2, vol_target=.6,
           filters=None, capacity=False, keep_records=True):
    """One open-to-open self-financing account, no averaging child NAVs.

    Panel rows are actual execution endpoints. Funding owns (entry, exit],
    signals have their own availability timestamps. Full exits assume a
    reduce-only close; entry/resize capacity uses only already closed volume.
    Mark extremes give a conservative full-interval debit liquidation proxy.
    """
    if capital <= 0 or not 0 <= cost_bp or not 0 < cap <= 2:
        raise ValueError("invalid_account")
    names, times = panel["symbols"], panel["times"]
    assert np.all(np.diff(times) > 0)
    equity, held, q = float(capital), None, 0.
    fee, peak, adverse = cost_bp / 10000, float(capital), 0.
    counts, curve, fills, picks = Counter(), [], [], []
    terminal_position = None
    attribution = {s: dict(price=0., funding=0., costs=0.) for s in names}
    for i in range(len(times) - 1):
        before = equity
        price_pnl = funding_pnl = costs = gross = 0.
        fs = panel["features"][i]
        if mechanism.carrier_risk:
            fs = {s: dict(f, sigma=f.get("carrier_sigma") or f["sigma"],
                          risk_available=f.get("carrier_sigma") is not None) for s, f in fs.items()}
        assert all(f["available"] <= panel["decision_times"][i] - 60 for f in fs.values()), "future_feature"
        tradable = {}
        if mechanism.tradable_first:
            for s, f in fs.items():
                j = names.index(s)
                price = panel["open"][i, j]
                desired = min(cap, vol_target / f["sigma"])
                wanted = rounded_quantity(equity * desired / (1 + desired * fee), price, s, filters)
                tradable[s] = bool(s == held or wanted > 0 and
                                   (not capacity or wanted <= panel["capacity"][i, j]))
        target = choose(fs, panel["groups"], mechanism, held=held, cost=fee, tradable=tradable,
                        cap=cap, vol_target=vol_target) if equity > 0 else None
        picks.append(dict(time=int(times[i]), target=target, held=held,
                          signal_available=fs[target]["available"] if target else None))

        def charge(symbol, quantity, reason):
            nonlocal equity, costs
            j = names.index(symbol)
            charge_ = abs(quantity) * panel["open"][i, j] * fee
            equity -= charge_
            costs += charge_
            attribution[symbol]["costs"] += charge_
            counts[reason] += 1
            fills.append(dict(time=int(times[i]), symbol=symbol, quantity=float(quantity),
                              price=float(panel["open"][i, j]), costs=float(charge_), reason=reason))

        pending_exit = False
        if held is not None and target != held:
            to_close = q
            j = names.index(held)
            if capacity and mechanism.capacity_mode == "clip" and to_close > panel["capacity"][i, j]:
                to_close = rounded_quantity(panel["capacity"][i, j] * panel["open"][i, j],
                    panel["open"][i, j], held, filters)
            if to_close > 1e-12:
                charge(held, -to_close, "switch_exit" if target else "qualification_exit")
                q -= to_close
            if q > 1e-12:
                pending_exit = True
                counts["exit_capacity_deferred"] += 1
            else:
                held, q = None, 0.
        if target is not None and not pending_exit:
            j = names.index(target)
            desired = min(cap, vol_target / fs[target]["sigma"])
            price = panel["open"][i, j]
            wanted = rounded_quantity(equity * desired / (1 + desired * fee), price, target, filters)
            delta = wanted - q
            if wanted == 0:
                counts["minimum_target_skip"] += 1
                # Failure to resize does not invalidate an existing position.
                # A full close still occurs on trend or opportunity change.
                wanted, delta = q, 0.
            if filters is not None and abs(delta) > 1e-12:
                if rounded_quantity(abs(delta) * price, price, target, filters) == 0:
                    counts["minimum_delta_skip"] += 1
                    wanted, delta = q, 0.
            if capacity and abs(delta) > panel["capacity"][i, j]:
                if mechanism.capacity_mode == "clip":
                    bounded = rounded_quantity(panel["capacity"][i, j] * price, price, target, filters)
                    delta = np.sign(delta) * bounded
                    wanted = q + delta
                    counts["capacity_clipped"] += 1
                else:
                    counts["capacity_skip"] += 1
                    wanted, delta = q, 0.
            if abs(delta) > 1e-12:
                charge(target, delta, "entry" if held is None else "resize")
            q, held = wanted, target if wanted > 0 else None
        if held is not None:
            j = names.index(held)
            price = panel["open"][i, j]
            gross = q * price / max(equity, 1e-30)
            pnl = q * (panel["open"][i + 1, j] - price)
            funding = -q * panel["funding_value"][i, j]
            worst = equity + q * (panel["mark_low"][i, j] - price) - q * panel["funding_debit"][i, j]
            liquidated = worst <= q * panel["mark_low"][i, j] * .005
            adverse = max(adverse, 1 - max(0., worst) / peak)
            if liquidated or equity + pnl + funding < 0:
                # Existing research convention: liquidation fee > maintenance
                # leaves zero under this simplified full-wallet model.
                funding = -q * panel["funding_debit"][i, j]
                pnl = -equity - funding
                counts["liquidations"] += 1
                adverse = 1.
            price_pnl, funding_pnl = pnl, funding
            attribution[held]["price"] += pnl
            attribution[held]["funding"] += funding
            equity += pnl + funding
            if liquidated or equity <= 0:
                equity, held, q = 0., None, 0.
            elif i == len(times) - 2:
                to_close = q
                if capacity and mechanism.capacity_mode == "clip":
                    terminal_cap = panel["terminal_capacity"][j]
                    if to_close > terminal_cap:
                        to_close = rounded_quantity(terminal_cap * panel["open"][i + 1, j],
                            panel["open"][i + 1, j], held, filters)
                final_cost = to_close * panel["open"][i + 1, j] * fee
                equity -= final_cost
                costs += final_cost
                attribution[held]["costs"] += final_cost
                if to_close > 1e-12:
                    fills.append(dict(time=int(times[i + 1]), symbol=held, quantity=-to_close,
                                      price=float(panel["open"][i + 1, j]), costs=float(final_cost), reason="terminal_exit"))
                    counts["terminal_exit"] += 1
                if q - to_close > 1e-12:
                    terminal_position = dict(symbol=held,quantity=float(q-to_close),
                                             price=float(panel["open"][i+1,j]))
                    counts["terminal_capacity_unclosed"] += 1
        assert np.isfinite(equity) and equity >= -1e-10
        assert abs(equity - before - (price_pnl + funding_pnl - costs)) < 1e-8 * max(1., before)
        peak = max(peak, equity)
        curve.append(dict(time=int(times[i + 1]), equity=float(equity), returns=float(equity / before - 1) if before else 0.,
                          price_pnl=float(price_pnl), funding_pnl=float(funding_pnl), costs=float(costs), gross=float(gross)))
    nav = np.array([capital, *[r["equity"] for r in curve]])
    years = (times[-1] - times[0]) / YEAR
    mdd = float(np.max(1 - nav / np.maximum.accumulate(nav)))
    cagr = float((equity / capital) ** (1 / years) - 1) if equity > 0 else -1.
    weights = np.diff(times)
    summary = dict(initial=capital, final=float(equity), return_pct=float((equity / capital - 1) * 100),
        cagr_pct=cagr * 100, mdd_pct=mdd * 100, calmar=cagr / mdd if mdd else None,
        adverse_mark_bound_pct=adverse * 100, mean_gross=float(np.average([r["gross"] for r in curve], weights=weights)),
        funding_pnl=sum(r["funding_pnl"] for r in curve), costs=sum(r["costs"] for r in curve),
        counts=dict(counts), attribution=attribution)
    assert np.isclose(equity - capital, sum(v["price"] + v["funding"] - v["costs"] for v in attribution.values()))
    if capacity and mechanism.capacity_mode == "clip":
        summary['terminal_position'] = terminal_position
    return dict(summary=summary, **(dict(curve=curve, fills=fills, picks=picks) if keep_records else {}))
