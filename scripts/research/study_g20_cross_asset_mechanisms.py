"""Compare economic G20 mechanisms on retained ETF and native public data."""
from __future__ import annotations

import argparse
import bisect
from dataclasses import asdict
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np

from qount.research.binance_macro_history import adjusted_bars
from qount.research.g20_cross_asset import Mechanism, YEAR, causal_features, replay
from qount.research_data.archives import timestamp
from qount.research_data.bars import Bar, NY, aggregate, session
from qount.research_data.binance_history import load_cached_history
from qount.strategies.macro_1atr import SIGNAL_MAPPING

ROOT = Path("state/research_cache")
CRYPTO = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
MECHANISMS = {
    "crypto_control": Mechanism(universe="crypto", regime="btc", eligible_first=False, normalize=False),
    "expanded_raw_btc": Mechanism(regime="btc", eligible_first=False, normalize=False),
    "expanded_local_gate": Mechanism(eligible_first=False, normalize=False),
    "eligible_first": Mechanism(normalize=False),
    "risk_normalized": Mechanism(),
    "retain_trend": Mechanism(retain=True),
    "net_carry": Mechanism(net_carry=True),
    "combined": Mechanism(retain=True, net_carry=True),
    # Follow-up controls isolate retention from ranking and universe changes.
    "retain_raw": Mechanism(normalize=False, retain=True),
    "crypto_retain": Mechanism(universe="crypto", retain=True),
    "macro_retain": Mechanism(universe="macro", retain=True),
    "retain_tradable": Mechanism(retain=True, tradable_first=True),
    "retain_carrier_risk": Mechanism(retain=True, carrier_risk=True),
}


def source(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def groups(symbols):
    return {s: "crypto" if s in CRYPTO else "commodity" if s in
            ("XAUUSDT", "COPPERUSDT", "CLUSDT") else "equity" for s in symbols}


def feature_at(series, now):
    i = bisect.bisect_right([r["available"] for r in series], now - 60) - 1
    return dict(series[i]) if i >= 0 and now - series[i]["available"] <= 4 * 86400 else None


def etf_sources():
    paths, bars = [], {}
    for s, ticker in SIGNAL_MAPPING.items():
        path = ROOT / "binance_macro_etf_history_20261015" / f"yahoo-{ticker}-20160101-2026-01-01.json"
        bars[s] = adjusted_bars(json.loads(path.read_text()))
        paths.append(source(path))
    return bars, paths


def proxy_panel(bars, start, end):
    names = tuple(SIGNAL_MAPPING)
    own = {s: {dt.datetime.fromtimestamp(b.t, NY).date().isoformat(): b for b in bars[s]} for s in names}
    days = sorted(day for day in own[names[0]] if start <= day <= end)
    assert all([d for d in own[s] if start <= d <= end] == days for s in names)
    times = np.array([int(dt.datetime.combine(dt.date.fromisoformat(day), dt.time(9, 30), NY).timestamp()) for day in days])
    opening = np.array([[own[s][day].o for s in names] for day in days])
    lows = np.array([[min(own[s][day].l, opening[i + 1, j]) for j, s in enumerate(names)] for i, day in enumerate(days[:-1])])
    fs = {s: causal_features(bars[s]) for s in names}
    snapshots = [{s: f for s in names if (f := feature_at(fs[s], t)) is not None} for t in times[:-1]]
    return dict(symbols=names, times=times, decision_times=times, open=opening, mark_low=lows,
                funding_value=np.zeros_like(lows), funding_debit=np.zeros_like(lows),
                groups=groups(names), features=snapshots)


def native_inputs():
    roots = [ROOT / d for d in ("binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730", "binance_macro_attack_20261015",
                                "macro_native_tail_20261022", "macro_native_tail_20261026")]
    book, sources, excluded = load_cached_history(roots, tuple(SIGNAL_MAPPING), timestamp("2026-04-07"),
        timestamp("2026-10-26"), ROOT / "binance_macro_attack_20261015/exchange-info.json")
    assert not excluded, excluded
    hour_path = ROOT / "position_flow_20261027/hourly.json"
    mark_path = ROOT / "crypto_g20_rotation_20261102/mark_hourly_windows.json"
    day_path = ROOT / "independent_crypto_factors_20261027/panel_seven.json"
    filter_path = ROOT / "crypto_g20_rotation_20261102/exchange_filters.json"
    daily_mark_path = ROOT / "crypto_g20_rotation_20261102/mark_daily.json"
    raw = json.loads(hour_path.read_text())["data"]
    marks = json.loads(mark_path.read_text())["data"]["2026tail"]
    daily = json.loads(day_path.read_text())["data"]
    daily_marks = json.loads(daily_mark_path.read_text())["data"]
    filters = {r["symbol"]: r for r in json.loads(filter_path.read_text())["symbols"]}
    for s in CRYPTO:
        book[s] = dict(rule=filters[s], funding=daily[s + "_funding"])
        for kind, values in (("trade", raw[s + "_futures"]), ("mark", marks[s])):
            book[s][kind] = [Bar(int(r[0]) // 1000, *(float(r[i]) for i in (1, 2, 3, 4)), float(r[5])) for r in values]
            assert np.all(np.diff([b.t for b in book[s][kind]]) == 3600)
        assert [b.t for b in book[s]["trade"]] == [b.t for b in book[s]["mark"]]
        book[s]['risk_closes'] = [(int(r[0]) // 1000 + 86400, float(r[4])) for r in daily_marks[s]]
    for s in SIGNAL_MAPPING:
        book[s]['risk_closes'] = [(b.t + 86400, b.c) for b in aggregate(book[s]['mark'], 86400, 3600)]
    signal_bars = {s: [Bar(int(r[0]) // 1000 + 86400, *(float(r[i]) for i in (1, 2, 3, 4)))
                       for r in daily[s + "_klines"]] for s in CRYPTO}
    for s, ticker in SIGNAL_MAPPING.items():
        path = ROOT / "macro_native_tail_20261026" / f"yahoo-{ticker}-20250101-2026-10-26.json"
        signal_bars[s] = adjusted_bars(json.loads(path.read_text()))
        sources.append(source(path))
    sources += [source(p) for p in (hour_path, mark_path, day_path, filter_path, daily_mark_path)]
    return book, signal_bars, sources


def native_panel(book, signal_bars, *, delay_hours=0, start="2026-08-03", end="2026-10-23", allow_unlisted=False):
    names = (*CRYPTO, *SIGNAL_MAPPING)
    days = np.arange(np.datetime64(start), np.datetime64(end) + np.timedelta64(1, "D")).astype(str)
    decisions = []
    for day in days:
        t = int(dt.datetime.combine(dt.date.fromisoformat(day), dt.time(10), NY).timestamp())
        if session(t) is not None:
            decisions.append(t)
    times = np.asarray(decisions) + delay_hours * 3600
    n, m = len(times), len(names)
    opening, caps = np.zeros((n, m)), np.zeros((n - 1, m))
    low, fund, debit = (np.zeros((n - 1, m)) for _ in range(3))
    snapshots = [{} for _ in range(n - 1)]
    for j, s in enumerate(names):
        trade = {b.t: b for b in book[s]["trade"]}
        mark = {b.t: b for b in book[s]["mark"]}
        fs = causal_features(signal_bars[s])
        settlements = book[s]["funding"]
        for i, t in enumerate(times):
            if t not in trade:
                if not allow_unlisted:
                    raise ValueError('execution_price_unavailable:'+s+':'+str(t))
                # No prices or eligibility before the actual native listing.
                opening[i,j]=np.nan
                continue
            opening[i, j] = trade[t].o
            if i == n - 1:
                continue
            caps[i, j] = trade[t - 3600].v * .01
            interval = range(int(t), int(times[i + 1]), 3600)
            assert all(k in mark and k in trade for k in interval)
            low[i, j] = min(mark[k].l for k in interval)
            for r in settlements:
                stamp = int(r["fundingTime"]) / 1000
                if t < stamp <= times[i + 1]:
                    assert r.get("markPrice"), (s, stamp)
                    value = float(r["fundingRate"]) * float(r["markPrice"])
                    fund[i, j] += value
                    debit[i, j] += max(0., value)
            f = feature_at(fs, decisions[i])
            if f is None:
                continue
            known_risk = [v for stamp, v in book[s]['risk_closes'] if stamp <= decisions[i] - 60]
            f['carrier_sigma'] = float(np.std(np.diff(np.log(known_risk[-31:])), ddof=1) * np.sqrt(365.25)) if len(known_risk) >= 31 else None
            known = [r for r in settlements if decisions[i] - 7 * 86400 <= int(r["fundingTime"]) / 1000 < decisions[i]]
            if not known or int(known[0]["fundingTime"]) / 1000 > decisions[i] - 7 * 86400 + 8 * 3600:
                f["annual_carry"] = float("inf")  # insufficient carry warmup rejects the net-carry policy
            else:
                f["annual_carry"] = sum(float(r["fundingRate"]) for r in known) * 365.25 / 7
            snapshots[i][s] = f
    return dict(symbols=names, groups=groups(names), times=times, decision_times=np.asarray(decisions),
                open=opening, mark_low=low, funding_value=fund, funding_debit=debit,
                features=snapshots, capacity=caps,
                terminal_capacity=np.array([next((b.v for b in book[s]['trade'] if b.t==times[-1]-3600),0.)*.01 for s in names]))


def failure_diagnostics():
    """Frozen ledger attribution: does not pretend removing trades is a replay."""
    path = Path("state/research_runs/crypto_g20_daily_low_leverage_20261102/curves.json")
    run = json.loads(path.read_text())["daily_vol60_cap2_btc:small21"]
    prices, funding, costs = (sum(r[k] for r in run["curve"]) for k in ("price_pnl", "funding_pnl", "costs"))
    episodes, active = [], None
    for fill in run["trades"]:
        if fill["reason"] == "scheduled":
            if active is None:
                active = dict(symbol=fill["symbol"], entry=fill["date"], signed_cash=0., quantity=0., costs=0.)
            direction = 1 if fill["side"] == "BUY" else -1
            active["quantity"] += direction * fill["quantity"]
            active["signed_cash"] -= direction * fill["quantity"] * fill["price"]
            active["costs"] += fill["quantity"] * fill["price"] * .001
        else:
            assert active is not None and active["symbol"] == fill["symbol"]
            active["signed_cash"] += fill["quantity"] * fill["price"]
            active["costs"] += fill["quantity"] * fill["price"] * .001
            active.update(exit=fill["date"], reason=fill["reason"], holding_bars=fill["holding_bars"],
                          price_pnl=active["signed_cash"])
            episodes.append(active)
            active = None
    terminal = dict(active, price_pnl=prices-sum(r['price_pnl'] for r in episodes),
                    total_costs=costs-sum(r['costs'] for r in episodes)) if active else None
    return dict(source=str(path), total_price_pnl=prices, funding_pnl=funding, costs=costs,
                completed_episodes=len(episodes), terminal_episode_missing_exit_fill=terminal,
                largest_completed_price_episode=max(episodes,key=lambda r:r['price_pnl']),
                completed_by_reason={reason: dict(count=len(rows := [r for r in episodes if r["reason"] == reason]),
                    price_pnl=sum(r["price_pnl"] for r in rows), costs=sum(r["costs"] for r in rows),
                    median_holding_days=float(np.median([r["holding_bars"] for r in rows])))
                    for reason in sorted({r["reason"] for r in episodes})},
                note="Funding is account-level. Original terminal exit is charged in NAV but omitted from its fills array; residual terminal episode reconciles to the total ledger. No counterfactual deletion claim.")


def paired_interval(left, right, blocks=(5, 15), annual=False):
    assert [r['time'] for r in left['curve']] == [r['time'] for r in right['curve']]
    x = np.log1p([r['returns'] for r in left['curve']]) - np.log1p([r['returns'] for r in right['curve']])
    if not np.isfinite(x).all():
        return dict(unavailable="account_exhaustion")
    # Callers provide full evaluation years; do not infer elapsed window from
    # the first actual trade when a strategy starts in cash.
    factor = 1 / annual if annual else 1.
    rng, ci = np.random.default_rng(20), {}
    for block in blocks:
        starts = rng.integers(0,len(x),(4000,(len(x)+block-1)//block))
        ix=((starts[...,None]+np.arange(block))%len(x)).reshape(4000,-1)[:,:len(x)]
        ci[str(block)] = (np.quantile(x[ix].sum(axis=1)*factor*100,[.025,.975])).tolist()
    return dict(log_growth_difference_pct=float(x.sum()*factor*100), block95_pct=ci,
                units="annual log growth percentage points" if annual else "full-window log growth percentage points",
                samples=4000,seed=20,note="Paired consumed-account results; timing, exposure, selection, quantities and costs all included; unadjusted for selection and multiple trials.")


def buy_hold(panel, symbols, capital=10000., cost_bp=30):
    fee = cost_bp / 10000
    ix = [panel['symbols'].index(s) for s in symbols]
    opening = panel['open'][:, ix]
    q = capital / len(ix) / (opening[0] * (1 + fee))
    cash = capital - float(np.sum(q * opening[0] * (1 + fee)))
    nav = cash + opening @ q
    nav[-1] -= float(np.sum(q * opening[-1] * fee))
    path = np.r_[capital, nav]
    mdd = float(np.max(1-path/np.maximum.accumulate(path)))
    years = (panel['times'][-1]-panel['times'][0])/YEAR
    return dict(final=float(nav[-1]), return_pct=float((nav[-1]/capital-1)*100),
                cagr_pct=float(((nav[-1]/capital)**(1/years)-1)*100), mdd_pct=mdd*100,
                note="Fractional, cap1, equal initial capital, no rebalancing; only entry/exit costs. Adjusted ETF units, pretax.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/g20_cross_asset_mechanisms_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    bars, sources = etf_sources()
    book, signal_bars, native_sources = native_inputs()
    panels = {"native": native_panel(book, signal_bars), "native_delay1h": native_panel(book, signal_bars, delay_hours=1)}
    native, saved = {}, {}
    filters = {s: d["rule"] for s, d in book.items()}
    for name, mechanism in MECHANISMS.items():
        native[name] = {}
        for label, capital, units, cost, capacity, panel_name in (
            ("small21", 21.25, filters, 30, True, "native"),
            ("small21_cost60", 21.25, filters, 60, True, "native"),
            ("small21_delay1h", 21.25, filters, 30, True, "native_delay1h"),
            ("filtered1000", 1000., filters, 30, True, "native"),
            ("continuous21", 21.25, None, 30, False, "native")):
            run = replay(panels[panel_name], mechanism, capital=capital, cost_bp=cost,
                         filters=units, capacity=capacity)
            native[name][label] = run["summary"]
            saved["native:" + name + ":" + label] = run
        print('native', name, native[name]['small21']['return_pct'], native[name]['small21']['mdd_pct'], flush=True)
    proxy, proxy_controls, full_proxy_years = {}, {}, None
    windows = {"2017_2025": ("2017-01-03", "2025-12-31"),
               "2017_2020": ("2017-01-03", "2020-12-31"),
               "2021_2023": ("2021-01-04", "2023-12-29"),
               "2024_2025": ("2024-01-02", "2025-12-31")}
    for window, (start, end) in windows.items():
        panel = proxy_panel(bars, start, end)
        if window == '2017_2025':
            full_proxy_years = (panel['times'][-1] - panel['times'][0]) / YEAR
        proxy_controls[window] = dict(SPY_buy_hold=buy_hold(panel, ['SPYUSDT']),
            equal_initial_eight=buy_hold(panel, list(SIGNAL_MAPPING)))
        proxy[window] = {}
        for name in ("expanded_local_gate", "eligible_first", "risk_normalized", "retain_trend", "net_carry", "combined", "retain_raw"):
            proxy[window][name] = {}
            for cost in (30, 60):
                run = replay(panel, MECHANISMS[name], capital=10000, cap=1, cost_bp=cost)
                proxy[window][name][str(cost)] = run["summary"]
                if window == "2017_2025":
                    saved["proxy:" + name + ":" + str(cost)] = run
        print('proxy', window, {n: round(r['30']['cagr_pct'], 2) for n,r in proxy[window].items()}, flush=True)
    paired = {key: paired_interval(saved[a],saved[b],blocks=(20,60) if key.startswith('proxy') else (5,15),
                                  annual=full_proxy_years if key.startswith('proxy') else False)
              for key,a,b in (
                ('native_retention','native:retain_trend:small21','native:risk_normalized:small21'),
                ('native_carrier_vs_proxy_risk','native:retain_carrier_risk:small21','native:retain_trend:small21'),
                ('native_expand_same_retention','native:retain_trend:small21','native:crypto_retain:small21'),
                ('proxy_retention','proxy:retain_trend:30','proxy:risk_normalized:30'))}
    payload = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Broader economic opportunity set, local market regimes, eligibility before ranking, risk-normalized strength, retain valid trends, and causal net-carry hurdle.",
        rules={k: asdict(v) for k,v in MECHANISMS.items()}, native_start="2026-08-03 NY10:00", native_end="2026-10-23 NY10:00",
        native_symbols=list(panels['native']['symbols']), native_decision_periods=len(panels['native']['times'])-1,
        proxy_windows=windows, signal_horizons="63 elapsed calendar day momentum /120 calendar day mean; 30 observed returns annualized by elapsed time",
        costs="Native single-side 30bp, stress60bp; proxies same cost, cap1/no funding; native cap2/60% volatility target, observed funding, hourly previous-volume 1% entry capacity.",
        carrier_risk="For retain_carrier_risk both ranking and sizing use 30 complete UTC daily mark returns of the actual contract, annualized sqrt365.25; insufficient 31-close history rejects that asset. Other native policies use the signal proxy volatility.",
        followup_controls="After observing retention, compare raw-rank retention, crypto-only/macro-only retention, executable-first selection and actual-carrier risk; these are post-result ablations, not independent tests.",
        source_hashes=sources+native_sources, previous_candidate_diagnostics=failure_diagnostics(),
        native=native, proxy=proxy, proxy_controls=proxy_controls, paired_comparisons=paired,
        limitations=["Consumed histories, ex-post universes and fixed mechanism ablations, no parameter search or independent OOS.",
            "Native common history is only Aug3-Oct23 2026, three cryptos plus eight native macro assets; not comparable to the seven-crypto 2024-2026 return.",
            "ETF proxies use contemporaneously adjusted OHLC, fractional units, pretax, cap1. Not a dated dividend/cash ledger or perpetual funding/carry reconstruction.",
            "Native proxy clocks use last complete ETF close before NY10; crypto uses complete UTC daily bars. All use same elapsed momentum/trend horizons.",
            "Native current filters and prior-hour 1% volume are retrospective approximations, not minute quotes or actual executable capacity. Full exits assume reduce-only and are stress-priced, not capacity-certified.",
            "Daily execution-endpoint MDD and adverse hourly mark extreme vs prior endpoint highwater are not complete hourly/ intraday peak-to-trough MDD.",
            "Full-wallet fixed 0.5% maintenance and liquidation fee exceeding maintenance approximate exhaustion; historical venue tiers and matching not reconstructed.",
            "No fresh market downloads, account reads, production changes, timers, or trading authority."])
    (args.output/'results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'curves.json').write_text(json.dumps(saved,ensure_ascii=False,allow_nan=False)+'\n')


if __name__ == "__main__":
    main()
