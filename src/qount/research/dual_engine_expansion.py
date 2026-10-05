"""Registered breadth, network fundamentals and macro crisis discovery experiments.

Only historical public data and cash/unit ledgers; no production interface.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import statistics as stats
import sys
import random
from pathlib import Path

from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.research import dual_engine_optimization as old
from qount.research import dual_engine_structural as base
from qount.research.dual_engine_execution_study import (
    load_cache, read_opens, verify_manifest, paired_diagnostics, paired_year_exclusion,
)
from qount.research.dual_engine_expansion_data import MACRO, METRICS, load_macro, load_rates, network_growth
from qount.research.c60_execution_control import acquire_opens

G20_CANDIDATES = ("gold20", "duration20", "macro_static", "macro_trend", "multi3_macro",
                  "macro_fund", "crisis_cash", "crisis_rotation")
G20_CONTROLS = ("g20", "macro_only_static", "macro_only_trend")
C60_CANDIDATES = ("raw2", "raw_positive2", "equal_positive8", "residual4_8", "residual4_20",
                  "equal_positive20", "residual4_robust20", "risk_weighted4_20", "fundamental4",
                  "usage_gate4", "residual2_ex_SOL")
C60_CONTROLS = ("btc_continuous", "core_only", "residual2", "coverage4",
                "random_positive2_s11", "random_positive2_s29", "random_positive2_s47")
MACRO_BASKET = ("GLD", "IEF", "TIP", "DBC", "UUP")


def require_storage(out):
    if (sys.platform != "linux" or not os.path.ismount("/mnt/e") or not out.resolve().is_relative_to(
            Path("/mnt/e/qount_data/qount/artifacts/dual_engine"))):
        raise ValueError("wsl_e_research_storage_required")


def read_contract(path):
    c = json.loads(path.read_text())
    if (c.get("study_id") != "dual_engine_expansion_20261004" or c.get("research_only") is not True
            or c.get("orders_authorized") is not False or c.get("promotion_evidence") is not False
            or c.get("new_candidate_trials") != 19 or c.get("planned_curves") != 116
            or tuple(c["g20"]["candidates"]) != G20_CANDIDATES or tuple(c["g20"]["controls"]) != G20_CONTROLS
            or tuple(c["c60"]["candidates"]) != C60_CANDIDATES or tuple(c["c60"]["controls"]) != C60_CONTROLS):
        raise ValueError("expansion_contract_invalid")
    return c


def percentile(values):
    """Tie-aware ranks, so identical observations cannot acquire artificial alpha."""
    n = len(values)
    return {k: (sum(v < x for v in values.values()) + .5 * sum(v == x for v in values.values())) / n
            for k, x in values.items()} if n else {}


def select_satellites(assets, t, market, day, rule, network):
    pool = [a for a in assets.values() if a.symbol not in ("BTCUSDT", "PAXGUSDT") and a.window(t) is not None]
    robust = rule == "residual4_robust20"
    pool.sort(key=lambda a: (-(stats.median(a.quote[t - a.start - 29:t - a.start + 1])
                               if robust else a.volume(t)), a.asset_id))
    wide = rule in ("residual4_20", "equal_positive20", "residual4_robust20", "risk_weighted4_20",
                    "coverage4", "fundamental4", "usage_gate4")
    universe = [a.asset_id for a in pool[:20 if wide else 8]]
    if rule == "residual2_ex_SOL":
        # Exclude the PREVIOUS round's top contributor; explicitly postselection diagnostic.
        universe = [k for k in universe if assets[k].symbol != "SOLUSDT"]
    relative = {k: base.relative_strength(assets[k].window(t), market)["score"] for k in universe}
    positive = [k for k in universe if relative[k] > 0.0]
    raw = {k: math.log(assets[k].window(t)[-1] / assets[k].window(t)[-91]) for k in universe}
    growth = {k: network_growth(network.get(assets[k].symbol, {}), day) for k in positive}
    covered = [k for k in positive if growth[k] is not None]
    scores, eligible, count = relative, positive, 2
    if rule == "raw2":
        scores, eligible = raw, [k for k in universe if raw[k] > 0.0]
    elif rule == "raw_positive2":
        scores = raw
    elif rule.startswith("random_positive2_"):
        seed = rule.rsplit("s", 1)[1]
        scores = {k: int(hashlib.sha256(f"{day}:{k}:{seed}".encode()).hexdigest(), 16) for k in positive}
    elif rule in ("equal_positive8", "equal_positive20"):
        count = len(positive)
    elif rule in ("residual4_8", "residual4_20", "residual4_robust20", "risk_weighted4_20"):
        count = 4
    elif rule in ("coverage4", "fundamental4", "usage_gate4"):
        eligible, count = covered, 4
        if rule == "usage_gate4":
            eligible = [k for k in covered if all(growth[k][m] > 0.0 for m in METRICS)]
        elif rule == "fundamental4":
            ranks = [percentile({k: relative[k] for k in covered})] + [
                percentile({k: growth[k][m] for k in covered}) for m in METRICS]
            scores = {k: stats.fmean(r[k] for r in ranks) for k in covered}
    selected = tuple(sorted(eligible, key=lambda k: (-scores[k], k))[:count])
    return selected, {"universe": universe, "positive_relative": positive, "covered": covered,
                       "selected": selected, "relative_scores": relative, "network_growth": growth}


def crypto_targets(axis, assets, settings, rule, network):
    if rule in ("btc_continuous", "core_only", "residual2"):
        return base.crypto_targets(axis, assets, settings, "core_satellite" if rule == "residual2" else rule)
    if rule not in C60_CANDIDATES + C60_CONTROLS:
        raise ValueError("crypto_expansion_rule_unknown")
    btc = next(a for a in assets.values() if a.symbol == "BTCUSDT")
    first = next(t for t in range(len(axis.dates)) if btc.window(t) is not None)
    selected, targets, members = (), {}, {}
    for t in range(first, len(axis.dates)):
        market = btc.window(t)
        day = dt.date.fromisoformat(axis.dates[t])
        if (day + dt.timedelta(days=1)).day == 1:
            selected, members[t] = select_satellites(assets, t, market, axis.dates[t], rule, network)
        strength = base.trend_score(market, settings["horizons"])
        pre = {btc.asset_id: settings["core_weight"] * strength}
        live = [k for k in selected if assets[k].window(t) is not None]
        if rule == "risk_weighted4_20" and live:
            # Weights use the decision day's realized volatility; dead allocation remains cash.
            inverse = {k: 1 / max(stats.stdev(base.daily_returns(assets[k].window(t, 61))), 1e-6) for k in live}
            denominator = sum(inverse.values())
            mass = min(1.0, len(selected) / 2.0) * len(live) / len(selected)
            allocation = {k: mass * v / denominator for k, v in inverse.items()}
        else:
            allocation = {k: 1 / max(2, len(selected)) for k in live}
        for k, fraction in allocation.items():
            pre[k] = settings["satellite_weight"] * fraction * strength * base.trend_score(assets[k].window(t), settings["horizons"])
        pre = {k: w for k, w in pre.items() if w > 0}
        returns = {k: base.daily_returns(assets[k].window(t, 61)) for k in pre}
        scale = min(1.0, settings["annual_volatility_cap"] / max(base.portfolio_sigma(returns, pre, 365), 1e-6))
        targets[t] = {k: w * scale for k, w in pre.items()}
    return targets, members


def macro_scores(panel, t):
    cash = panel.total_closes["BIL"]
    return {s: stats.fmean(math.log(panel.total_closes[s][t] / panel.total_closes[s][t - h])
                           - math.log(cash[t] / cash[t - h]) for h in (63, 126)) for s in MACRO}


def macro_allocation(scores, names=MACRO_BASKET, budget=.45, *, static=False):
    selected = list(names) if static else sorted((s for s in names if scores[s] > 0), key=lambda s: (-scores[s], s))[:3]
    # Unfilled slots remain BIL, rather than increasing concentration to use up budget.
    return {s: budget / (len(names) if static else 3) for s in selected}


def rate_change(rates, series, t):
    values = rates[series]
    return None if t < 63 or values[t] is None or values[t - 63] is None else values[t] - values[t - 63]


def crisis_state(panel, t, previous, rates):
    spy = panel.total_closes["SPY"]
    r5 = spy[t] / spy[t - 5] - 1
    drawdown = spy[t] / max(spy[t - 63:t + 1]) - 1
    panic = (drawdown < -.08 and r5 < -.04) or r5 < -.08
    recovery = spy[t] > stats.fmean(spy[t - 19:t + 1]) and spy[t] / spy[t - 21] > 1
    if previous != "normal":
        return "normal" if recovery else previous
    if not panic:
        return "normal"
    real, inflation = rate_change(rates, "DFII10", t), rate_change(rates, "T10YIE", t)
    bond = panel.total_closes["IEF"][t] / panel.total_closes["IEF"][t - 63] - 1
    return "inflation" if bond < 0 and ((real is not None and real > 0) or (inflation is not None and inflation > 0)) else "deflation"


def equity_targets(panel, settings, rule, rates):
    if rule not in G20_CANDIDATES + G20_CONTROLS:
        raise ValueError("equity_expansion_rule_unknown")
    monthly, targets, events = old.g20_signals(panel), {}, []
    selected, top3, state = None, (), "normal"
    for t in range(126, len(panel.dates) - 1):
        new_state = crisis_state(panel, t, state, rates) if rule.startswith("crisis_") else "normal"
        changed = new_state != state
        state = new_state
        if t in monthly:
            selected = monthly[t]["selected"]
            ranking = sorted(G20_EXECUTION_TO_PROXY, key=lambda k: (
                -panel.closes[G20_EXECUTION_TO_PROXY[k]][t] / panel.closes[G20_EXECUTION_TO_PROXY[k]][t - 63], k))
            top3 = tuple(ranking[:3])
        if selected is None or not (t in monthly or changed):
            continue
        scores = macro_scores(panel, t)
        equity = {} if rule.startswith("macro_only_") else {selected: .05 if state != "normal" else .2}
        if rule == "multi3_macro":
            equity = {s: .2 / 3 for s in top3}
        macro = {}
        if rule == "gold20":
            macro = {"GLD": .2}
        elif rule == "duration20":
            macro = {"IEF": .2}
        elif rule in ("macro_static", "macro_only_static"):
            macro = macro_allocation(scores, static=True)
        elif rule != "g20":
            names = MACRO_BASKET
            if rule == "macro_fund":
                real = rate_change(rates, "DFII10", t)
                names = tuple(s for s in names if not (s in ("IEF", "TIP") and (real is None or real > 0)))
            macro = macro_allocation(scores, names)
        if rule == "crisis_rotation" and state != "normal":
            names = ("GLD", "DBC", "UUP") if state == "inflation" else ("IEF", "TLT")
            eligible = [s for s in names if scores[s] > 0]
            for s in eligible:
                macro[s] = macro.get(s, 0) + .15 / len(eligible)
        target = {**equity, **macro}
        target["BIL"] = 1 - sum(target.values())
        targets[t] = target
        if rule.startswith("crisis_"):
            events.append({"date": panel.dates[t], "state": state, "transition": changed, "target": target,
                           "real_rate_change": rate_change(rates, "DFII10", t),
                           "breakeven_change": rate_change(rates, "T10YIE", t)})
    return targets, events


def prepare_opens(*, contract_path, pit_cache, expansion_root, prior_open_root, out):
    require_storage(out)
    c = read_contract(contract_path)
    verify_manifest(expansion_root)
    network = json.loads((expansion_root / "network.json").read_text())
    raw, _ = load_cache(pit_cache)
    axis, assets = old.build_crypto_assets(raw)
    prior = verify_manifest(prior_open_root)
    needed = {}
    for rule in C60_CONTROLS + C60_CANDIDATES:
        targets, _ = crypto_targets(axis, assets, c["c60"], rule, network)
        for t, weights in targets.items():
            for delay in c["c60"]["delays"]:
                for i in (t + 1 + delay, t + 2 + delay):
                    if i < len(axis.dates) and axis.dates[i] >= c["c60"]["start"]:
                        for k in weights:
                            if assets[k].has(i):
                                needed.setdefault(assets[k].symbol, set()).add(axis.dates[i][:7])
        print(json.dumps({"open_coverage_rule": rule, "symbols_so_far": len(needed)}), flush=True)
    out.mkdir(parents=True, exist_ok=False)
    (out / "archives").mkdir()
    for symbol, months in needed.items():
        for month in months:
            name = f"archives/{symbol}-1d-{month}.zip"
            if name in prior:
                (out / name).write_bytes((prior_open_root / name).read_bytes())
    return acquire_opens(pit_cache, out, symbols=sorted(needed),
                         months_by_symbol={s: sorted(v) for s, v in needed.items()}, workers=16)


def paired_fast(candidate, baseline, *, annual, settings):
    """Same synchronous circular-block experiment, vectorized moments only."""
    import numpy as np
    a, b = candidate["records"], baseline["records"]
    if not a or [r["date"] for r in a] != [r["date"] for r in b]:
        raise ValueError("paired_dates_mismatch")
    ax, bx = (np.array([r["return"] - r["cash_return"] for r in rows]) for rows in (a, b))
    logs = np.array([math.log1p(x["return"]) - math.log1p(y["return"]) for x, y in zip(a, b, strict=True)])
    n, out = len(a), {}
    def sharpe(values, axis=None):
        mean, sigma = values.mean(axis=axis), values.std(axis=axis, ddof=1)
        return np.divide(mean, sigma, out=np.zeros_like(mean), where=sigma > 0) * math.sqrt(annual)
    def interval(values):
        v = sorted(float(x) for x in values)
        return [v[int(.025 * (len(v) - 1))], v[int(.975 * (len(v) - 1))]]
    for block in settings["block_lengths"]:
        rng, indices = random.Random(settings["seed"] + block), []
        for _ in range(settings["draws"]):
            starts = [rng.randrange(n) for _ in range(math.ceil(n / block))]
            indices.append([(s + j) % n for s in starts for j in range(block)][:n])
        idx = np.array(indices)
        out[str(block)] = {"annual_log_growth_difference": float(logs.mean() * annual),
            "log_growth_ci95": interval(logs[idx].mean(axis=1) * annual),
            "cash_excess_sharpe_difference": float(sharpe(ax) - sharpe(bx)),
            "sharpe_ci95": interval(sharpe(ax[idx], 1) - sharpe(bx[idx], 1)),
            "draws": settings["draws"], "role": "consumed discovery diagnostic; no post-selection significance"}
    return out


def contributions(run, dates, closes, opens, *, annual, market=None):
    """Dollar PnL oracle: old units earn overnight, new units earn intraday."""
    indices = {d: i for i, d in enumerate(dates)}
    units, pnl, held_days, fees, prior_nav = {}, {}, {}, 0.0, 1.0
    max_error = 0.0
    for r in run["records"]:
        day, previous = r["date"], dates[indices[r["date"]] - 1]
        names = set(units) | set(r["units"])
        open_nav = prior_nav + sum(units.get(k, 0) * (opens.get(k, {}).get(day, 0) - closes.get(k, {}).get(previous, 0)) for k in units)
        fee = open_nav * r["cost_fraction"]
        fees += fee
        changes = {}
        for k in names:
            opn, close, old_close = opens.get(k, {}).get(day, 0), closes.get(k, {}).get(day, 0), closes.get(k, {}).get(previous, 0)
            delta = units.get(k, 0) * (opn - old_close) + r["units"].get(k, 0) * (close - opn)
            changes[k] = delta
            pnl[k] = pnl.get(k, 0) + delta
            held_days[k] = held_days.get(k, 0) + int(r["weights"].get(k, 0) > 0)
        max_error = max(max_error, abs(sum(changes.values()) - fee - (r["nav"] - prior_nav)))
        units, prior_nav = r["units"], r["nav"]
    error = abs(sum(pnl.values()) - fees - (prior_nav - 1))
    if max(max_error, error) > 1e-9:
        raise ValueError("independent_dollar_pnl_mismatch")
    count = [sum(w > 1e-12 for k, w in r["weights"].items() if k != "BIL") for r in run["records"]]
    output = {"initial_nav_unit_pnl": pnl, "fee_initial_nav_units": fees,
              "wealth_change": prior_nav - 1, "held_days": held_days, "max_daily_pnl_error": max_error,
              "wealth_reconciliation_error": error, "mean_risk_positions": stats.fmean(count), "max_risk_positions": max(count)}
    if market:
        x = [closes[market][r["date"]] / closes[market][dates[indices[r["date"]] - 1]] - 1 for r in run["records"]]
        y = [r["return"] - r["cash_return"] for r in run["records"]]
        xm, ym = stats.fmean(x), stats.fmean(y)
        variance = sum((v - xm) ** 2 for v in x)
        beta = sum((v - xm) * (w - ym) for v, w in zip(x, y, strict=True)) / variance if variance else 0
        output["unconditional_market_regression"] = {"beta": beta, "annualized_intercept": (ym - beta * xm) * annual,
            "role": "historical descriptive regression, not hedge PnL or independent alpha"}
    return output


def window_summary(run, first, last, annual):
    """Event windows have no best-year deletion or short-window CAGR claims."""
    rows = [r for r in run["records"] if first <= r["date"] <= last]
    if not rows:
        return {"status": "outside_evaluation"}
    metrics = old._metrics([r["return"] for r in rows], annual, [r["cash_return"] for r in rows])
    return {"first": rows[0]["date"], "last": rows[-1]["date"], "bars": len(rows),
            "total_return": metrics["total_return"], "max_drawdown": metrics["max_drawdown"],
            "mean_risk_gross": stats.fmean(r["risk_gross"] for r in rows),
            "total_turnover": sum(r["turnover"] for r in rows),
            "role": "predeclared event-window diagnostic; no independent OOS"}


def run_study(*, contract_path, prior_contract, equity_root, pit_cache, expansion_root, rates_root,
              open_root, prior_results, out, repo):
    require_storage(out)
    c = read_contract(contract_path)
    if out.exists():
        raise ValueError("immutable_result_exists")
    panel, equity_audit = old.load_equity(equity_root, old.read_contract(prior_contract))
    raw, cache_hashes = load_cache(pit_cache)
    prior_files = verify_manifest(prior_results)
    prior_audit = json.loads((prior_results / "input-audit.json").read_text())
    if cache_hashes != prior_audit["cache_sha256"] or equity_audit["files"] != prior_audit["equity"]["files"]:
        raise ValueError("prior_input_identity_changed")
    panel = load_macro(panel, expansion_root)
    rates, rate_files = load_rates(rates_root, panel.dates), verify_manifest(rates_root)
    network = json.loads((expansion_root / "network.json").read_text())
    axis, assets = old.build_crypto_assets(raw)
    opens, open_files = read_opens(open_root)
    eq_close = {s: dict(zip(panel.dates, p, strict=True)) for s, p in panel.total_closes.items()}
    eq_open = {s: dict(zip(panel.dates, p, strict=True)) for s, p in panel.total_opens.items()}
    cr_close, cr_open = base.crypto_prices(axis, assets, opens)
    btc = next(k for k, a in assets.items() if a.symbol == "BTCUSDT")
    out.mkdir(parents=True)
    old.write_json(out / "contract.json", c)
    audit = {"equity": equity_audit, "cache_sha256": cache_hashes, "open_files": open_files,
             "expansion_files": verify_manifest(expansion_root), "rate_files": rate_files,
             "expansion_manifest_sha256": old.file_hash(expansion_root / "manifest.json"),
             "rate_manifest_sha256": old.file_hash(rates_root / "manifest.json"),
             "open_manifest_sha256": old.file_hash(open_root / "manifest.json"),
             "network_coverage": json.loads((expansion_root / "coverage.json").read_text()),
             "prior_result_manifest_sha256": old.file_hash(prior_results / "manifest.json"),
             "contract_sha256": old.file_hash(contract_path),
             "paths": {"equity_root": str(equity_root), "pit_cache": str(pit_cache),
                       "expansion_root": str(expansion_root), "rates_root": str(rates_root), "open_root": str(open_root)}}
    old.write_json(out / "input-audit.json", audit)
    runs, summaries, exposures, checks, attribution, crises = {}, {"g20": {}, "c60": {}}, [], {}, {}, {}
    for line, rules, dates, closes, opns, annual in (
        ("g20", G20_CONTROLS + G20_CANDIDATES, panel.dates, eq_close, eq_open, 252),
        ("c60", C60_CONTROLS + C60_CANDIDATES, axis.dates, cr_close, cr_open, 365)):
        for rule in rules:
            targets, members = (equity_targets(panel, c[line], rule, rates) if line == "g20" else
                                crypto_targets(axis, assets, c[line], rule, network))
            old.write_json(out / f"{line}-{rule}-targets.json", targets)
            old.write_json(out / f"{line}-{rule}-selection.json", members)
            for cost in c[line]["cost_bps"]:
                for delay in c[line]["delays"]:
                    cell = f"c{cost}-d{delay}"
                    aims = dict(targets)
                    if line == "g20":
                        first = next(i for i, d in enumerate(dates) if d >= c[line]["start"])
                        aims.setdefault(first - delay, {"BIL": 1.0})
                    run = base.replay_units(dates, closes, opns, aims, start=c[line]["start"],
                        lag=delay if line == "g20" else 1 + delay, cost_bps=cost, cash_asset="BIL" if line == "g20" else None)
                    key = f"{line}-{rule}-{cell}"
                    runs[key] = run
                    old.write_json(out / f"{key}-ledger.json", run)
                    result = old.summarize(run, annual)
                    result["mean_risk_gross"] = stats.fmean(r["risk_gross"] for r in run["records"])
                    result["max_risk_gross"] = max(r["risk_gross"] for r in run["records"])
                    summaries[line].setdefault(rule, {})[cell] = result
                    exposures.append({"curve": key, "role": "candidate" if rule in G20_CANDIDATES + C60_CANDIDATES else "control"})
                    if cell in (("c20-d1", "c40-d2") if line == "g20" else ("c25-d0", "c50-d1")):
                        attribution[key] = contributions(run, dates, closes, opns, annual=annual, market="SPY" if line == "g20" else btc)
                    prior_rule = {"residual2": "core_satellite"}.get(rule, rule)
                    if rule in ("g20", "btc_continuous", "core_only", "residual2"):
                        prior = json.loads((prior_results / f"{line}-{prior_rule}-{cell}-ledger.json").read_text())
                        if [r["date"] for r in run["records"]] != [r["date"] for r in prior["records"]]:
                            raise ValueError("baseline_dates_changed")
                        error = max(abs(r["return"] - s["return"]) for r, s in zip(run["records"], prior["records"], strict=True))
                        if error > 1e-12:
                            raise ValueError(f"baseline_reproduction_failed:{key}:{error}")
                        checks[key] = error
            print(json.dumps({"replayed": line + "-" + rule}), flush=True)
    contrasts = {}
    comparisons = {"g20": {r: "g20" for r in G20_CANDIDATES},
                   "c60": {r: "coverage4" if r in ("fundamental4", "usage_gate4") else "residual2" for r in C60_CANDIDATES}}
    for line, pairs in comparisons.items():
        for rule, reference in pairs.items():
            for cell in (("c20-d1", "c40-d2") if line == "g20" else ("c25-d0", "c50-d1")):
                a, b = runs[f"{line}-{rule}-{cell}"], runs[f"{line}-{reference}-{cell}"]
                contrasts[f"{line}-{rule}-vs-{reference}-{cell}"] = {
                    "paired": paired_fast(a, b, annual=252 if line == "g20" else 365, settings=c["paired_bootstrap"]),
                    "same_baseline_best_year_exclusion": paired_year_exclusion(a, b, annual=252 if line == "g20" else 365)}
    for line, windows in c["crisis_windows"].items():
        annual = 252 if line == "g20" else 365
        for key, run in runs.items():
            if key.startswith(line + "-"):
                crises[key] = {name: window_summary(run, first, last, annual)
                               for name, (first, last) in windows.items()}
    sources = {repo / "scripts/research/dual_engine_expansion.py", repo / "config/dual-engine-expansion-20261004.json"}
    for name, module in tuple(sys.modules.items()):
        path = Path(module.__file__).resolve() if getattr(module, "__file__", None) else None
        if name.startswith("qount") and path and path.suffix == ".py":
            if not path.is_relative_to(repo.resolve() / "src"):
                raise ValueError("source_outside_public_delivery")
            sources.add(path)
    hashes = {}
    for path in sorted(sources):
        relative = path.relative_to(repo)
        saved = out / "source" / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(path.read_bytes())
        hashes[str(relative)] = old.file_hash(path)
    result = {"study_id": c["study_id"], "research_only": True, "orders_authorized": False,
              "promotion_evidence": False, "data_role": c["data_role"], "summaries": summaries,
              "contrasts": contrasts, "baseline_reproduction": checks, "attribution": attribution,
              "crisis_windows": crises, "source_sha256": hashes, "curve_exposures": exposures,
              "candidate_trials": c["new_candidate_trials"], "global_trial_count": None, "dsr_pbo": c["dsr_pbo"]}
    if len(exposures) != c["planned_curves"]:
        raise ValueError("curve_inventory_mismatch")
    old.write_json(out / "results.json", result)
    files = {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}
    old.write_json(out / "manifest.json", {"research_only": True, "orders_authorized": False, "files": files})
    return result
