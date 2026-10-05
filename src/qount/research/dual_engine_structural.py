"""Structural G20/C60 experiments using public data and cash-unit accounting.

These are research alternatives, not mutations of the frozen paper contracts.
No credential, broker, service, scheduler or StrategyIntent interface exists.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import statistics as stats
import sys
from pathlib import Path
from typing import Mapping, Sequence

from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.research import c60_pit_universe as pit
from qount.research import dual_engine_optimization as old
from qount.research.c60_cost_study import _rank_candidates
from qount.research.c60_execution_control import acquire_opens, warm_targets
from qount.research.dual_engine_execution_study import (
    load_cache, paired_diagnostics, paired_year_exclusion, read_opens, verify_manifest,
)
from qount.research.g20_drift_control import replay_equity_control
from qount.research_data.replay_fees import trade_to_target


G20_CANDIDATES = ("winner_risk", "blend_levered", "blend_proxy")
G20_CONTROLS = ("g20", "spy_risk", "passive_levered", "passive_proxy")
C60_CANDIDATES = ("pit_continuous", "btc_continuous", "core_satellite", "core_satellite_partial")
C60_CONTROLS = ("pit", "btc_daily", "btc_static_risk", "core_only")
GROUPS = (("QQQ", "SMH"), ("XLF",), ("XLV",), ("IWM",), ("VNQ",), ("XLE",))


def read_contract(path: Path) -> dict:
    value = json.loads(path.read_text())
    expected = {
        "study_id": "dual_engine_structural_20261004", "research_only": True,
        "orders_authorized": False, "promotion_evidence": False,
        "data_role": "consumed_historical_discovery_pool", "new_candidate_trials": 7,
        "planned_curves": 60,
    }
    if any(value.get(k) != v for k, v in expected.items()):
        raise ValueError("structural_contract_invalid")
    if (tuple(value["g20"]["candidates"]) != G20_CANDIDATES
            or tuple(value["g20"]["controls"]) != G20_CONTROLS
            or tuple(value["c60"]["candidates"]) != C60_CANDIDATES
            or tuple(value["c60"]["controls"]) != C60_CONTROLS):
        raise ValueError("structural_rule_inventory_changed")
    return value


def daily_returns(prices: Sequence[float]) -> tuple[float, ...]:
    if len(prices) < 2 or any(not math.isfinite(x) or x <= 0.0 for x in prices):
        raise ValueError("invalid_price_history")
    return tuple(b / a - 1.0 for a, b in zip(prices[:-1], prices[1:], strict=True))


def trend_score(prices: Sequence[float], horizons: Sequence[int]) -> float:
    """Continuous positive trend strength; no daily binary SMA boundary.

    Dimensionless log moves are normalized by trailing daily log volatility.
    This score is a heuristic, not an estimate of expected return or probability.
    """
    if not horizons or min(horizons) < 1 or len(prices) <= max(horizons):
        raise ValueError("insufficient_trend_history")
    daily_returns(prices)
    logs = [math.log(b / a) for a, b in zip(prices[-61:-1], prices[-60:], strict=True)]
    sigma = max(stats.stdev(logs), 1e-6)
    return max(0.0, stats.fmean(math.tanh(math.log(prices[-1] / prices[-h - 1])
                                        / (sigma * math.sqrt(h))) for h in horizons))


def portfolio_sigma(returns: Mapping[str, Sequence[float]], weights: Mapping[str, float], annual: int) -> float:
    if not weights:
        return 0.0
    lengths = {len(returns[k]) for k in weights}
    if len(lengths) != 1 or min(lengths) < 2:
        raise ValueError("covariance_calendar_mismatch")
    series = [sum(w * returns[k][i] for k, w in weights.items()) for i in range(next(iter(lengths)))]
    return stats.stdev(series) * math.sqrt(annual)


def relative_strength(asset: Sequence[float], market: Sequence[float]) -> dict:
    """Causal 90-day log performance after a trailing 60-day BTC beta.

    Fits historical beta at the decision date; it is a relative-selection
    statistic. The long-only satellite itself remains exposed to crypto beta.
    """
    if len(asset) < 91 or len(market) < 91:
        raise ValueError("relative_history_insufficient")
    a = [math.log(b / x) for x, b in zip(asset[-61:-1], asset[-60:], strict=True)]
    m = [math.log(b / x) for x, b in zip(market[-61:-1], market[-60:], strict=True)]
    am, mm = stats.fmean(a), stats.fmean(m)
    variance = sum((x - mm) ** 2 for x in m)
    beta = sum((x - am) * (y - mm) for x, y in zip(a, m, strict=True)) / variance if variance > 1e-16 else 0.0
    residual_sigma = max(stats.stdev([x - beta * y for x, y in zip(a, m, strict=True)]), 1e-6)
    residual_log = math.log(asset[-1] / asset[-91]) - beta * math.log(market[-1] / market[-91])
    return {"beta": beta, "residual_log_90": residual_log,
            "score": residual_log / (residual_sigma * math.sqrt(90))}


def equity_targets(panel: old.EquityPanel, settings: Mapping, rule: str) -> dict[int, dict[str, float]]:
    if rule not in G20_CANDIDATES + G20_CONTROLS[1:]:
        raise ValueError("equity_rule_unknown")
    horizons, windows = settings["horizons"], settings["risk_windows"]
    warm = max(*horizons, *windows)
    proxy_to_execution = {v: k for k, v in G20_EXECUTION_TO_PROXY.items()}
    selected = None
    monthly = old.g20_signals(panel)
    targets = {}
    for t in range(63, len(panel.dates)):
        if t in monthly:
            selected = monthly[t]["selected"]
        if t < warm or (t - warm) % settings["rebalance_sessions"]:
            continue
        levered = rule in ("winner_risk", "blend_levered", "passive_levered")
        scores = {s: trend_score(panel.total_closes[s][t - warm:t + 1], horizons)
                  for s in proxy_to_execution}
        if rule == "winner_risk":
            shape = {selected: 1.0} if selected else {}
            confidence = 1.0
        elif rule == "spy_risk":
            shape, confidence = {"SPY": 1.0}, 1.0
        else:
            passive = rule.startswith("passive")
            shape, confidence = {}, 0.0
            for group in GROUPS:
                for proxy in group:
                    symbol = proxy_to_execution[proxy] if levered else proxy
                    risk = max(stats.stdev(daily_returns(panel.total_closes[symbol][t - w:t + 1]))
                               for w in windows) * math.sqrt(252)
                    score = 1.0 if passive else scores[proxy]
                    mass = score / (len(GROUPS) * len(group))
                    shape[symbol] = mass / max(risk, 1e-6)
                    confidence += mass
            total = sum(shape.values())
            shape = {s: w / total for s, w in shape.items() if w > 0.0} if total else {}
        cash_returns = daily_returns(panel.total_closes["BIL"][t - max(windows):t + 1])
        excess = {s: tuple(r - c for r, c in zip(
            daily_returns(panel.total_closes[s][t - max(windows):t + 1]), cash_returns, strict=True)) for s in shape}
        sigma = max((portfolio_sigma({s: v[-w:] for s, v in excess.items()}, shape, 252) for w in windows), default=0.0)
        cap = settings["levered_gross_cap"] if levered else settings["proxy_gross_cap"]
        scale = min(cap, settings["annual_volatility_budget"] / max(sigma, 1e-6)) * confidence
        target = {s: w * scale for s, w in shape.items()}
        target["BIL"] = 1.0 - sum(target.values())
        targets[t] = target
    return targets


def crypto_targets(axis: pit.Axis, assets: Mapping[str, pit.Asset], settings: Mapping, rule: str) -> tuple[dict, dict]:
    if rule in ("pit", "btc_daily"):
        return warm_targets(axis, assets, universe="pit" if rule == "pit" else "btc")
    if rule not in C60_CANDIDATES + C60_CONTROLS[2:]:
        raise ValueError("crypto_rule_unknown")
    btc = next(a for a in assets.values() if a.symbol == "BTCUSDT")
    first = next(t for t in range(len(axis.dates)) if btc.window(t) is not None)
    held, satellites = (), ()
    targets, members = {}, {}
    for t in range(first, len(axis.dates)):
        market = btc.window(t)
        if market is None:
            raise ValueError("btc_history_missing")
        day = dt.date.fromisoformat(axis.dates[t])
        if (day + dt.timedelta(days=1)).day == 1:
            universe = pit.pit_universe(assets, t)
            members[t] = universe
            held = _rank_candidates({k: assets[k].window(t) for k in universe})
            relative = {k: relative_strength(assets[k].window(t), market) for k in universe
                        if assets[k].symbol not in ("BTCUSDT", "PAXGUSDT")}
            satellites = tuple(k for k in sorted(relative, key=lambda k: (-relative[k]["score"], k))
                               if relative[k]["score"] > 0.0)[:2]
        market_score = trend_score(market, settings["horizons"])
        pre = {}
        if rule == "pit_continuous":
            for k in held:
                window = assets[k].window(t)
                if window is not None:
                    own = trend_score(window, settings["horizons"])
                    system = 1.0 if assets[k].symbol == "PAXGUSDT" else market_score
                    pre[k] = own * system / len(held)
        else:
            core = settings["core_weight"] if rule in ("core_only", "core_satellite", "core_satellite_partial") else 1.0
            pre[btc.asset_id] = core * (1.0 if rule == "btc_static_risk" else market_score)
            if rule in ("core_satellite", "core_satellite_partial"):
                for k in satellites:
                    window = assets[k].window(t)
                    if window is not None:
                        pre[k] = settings["satellite_weight"] / 2.0 * market_score * trend_score(window, settings["horizons"])
        pre = {k: w for k, w in pre.items() if w > 0.0}
        returns = {k: daily_returns(assets[k].window(t, settings["risk_window"] + 1)) for k in pre}
        sigma = portfolio_sigma(returns, pre, 365)
        scale = min(1.0, settings["annual_volatility_cap"] / max(sigma, 1e-6))
        targets[t] = {k: w * scale for k, w in pre.items()}
    return targets, members


def replay_units(dates: Sequence[str], closes: Mapping[str, Mapping[str, float]],
                 opens: Mapping[str, Mapping[str, float]], targets: Mapping[int, Mapping[str, float]], *,
                 start: str, lag: int, cost_bps: float, cash_asset: str | None = None,
                 adjustment: float = 1.0) -> dict:
    """Cash and units, close decision then future open fill; optional partial aim.

    Partial targets use PREVIOUS CLOSE holdings, never the execution open. Assets
    with zero desired weight exit fully. A risk-cap breach of the previous-close
    target gross is reduced immediately. Missing held prices receive a zero mark;
    missing opens on a day with a known close are rejected as input incompleteness.
    """
    if lag < 1 or not 0.0 < adjustment <= 1.0 or not 0.0 <= cost_bps < 5000.0:
        raise ValueError("unit_replay_settings_invalid")
    cash, units, last_marks, last_weights = 1.0, {}, {}, {}
    records = []
    first = next(i for i, d in enumerate(dates) if d >= start)
    if first < lag:
        raise ValueError("replay_warmup_insufficient")
    for t in range(first, len(dates)):
        day, prior_day = dates[t], dates[t - 1]
        signal = t - lag
        aim = targets.get(signal)
        if aim is not None:
            target = {k: adjustment * w + (1.0 - adjustment) * last_weights.get(k, 0.0)
                      for k, w in aim.items() if w > 0.0}
            # Smoothing must not defeat a freshly lower aggregate risk budget.
            gross_cap = sum(aim.values())
            if sum(target.values()) > gross_cap and cash_asset is None:
                factor = gross_cap / sum(target.values())
                target = {k: w * factor for k, w in target.items()}
        else:
            target = None
        missing = []
        previous_nav = cash + sum(units[k] * last_marks[k] for k in units)
        open_marks = {}
        for k in set(units) | set(target or {}):
            opn = opens.get(k, {}).get(day)
            if opn is None:
                if day in closes.get(k, {}):
                    raise ValueError(f"required_open_missing:{k}:{day}")
                opn = 0.0
                if k in units:
                    missing.append(k)
            if not math.isfinite(opn) or opn < 0.0:
                raise ValueError("invalid_open_mark")
            open_marks[k] = opn
        open_nav = cash + sum(units[k] * open_marks[k] for k in units)
        if open_nav <= 0.0:
            raise ValueError("account_bankrupt")
        pre = {k: units[k] * open_marks[k] / open_nav for k in units if open_marks[k] > 0.0}
        no_fills = []
        if target is not None:
            if (any(not math.isfinite(w) or w < 0.0 for w in target.values())
                    or sum(target.values()) > 1.0 + 1e-12):
                raise ValueError("long_cash_target_invalid")
            no_fills = [k for k in target if open_marks[k] == 0.0]
            target = {k: w for k, w in target.items() if open_marks[k] > 0.0}
            ratio, turnover = trade_to_target(pre, target, cost_bps)
            nav = open_nav * ratio
            units = {k: nav * w / open_marks[k] for k, w in target.items() if w > 0.0}
            cash = nav * (1.0 - sum(target.values()))
            fee = 1.0 - ratio
        else:
            units = {k: u for k, u in units.items() if open_marks[k] > 0.0}
            turnover, fee = 0.0, 0.0
        close_marks = {k: closes.get(k, {}).get(day, 0.0) for k in units}
        missing += [k for k, price in close_marks.items() if price == 0.0]
        close_nav = cash + sum(units[k] * close_marks[k] for k in units)
        if close_nav <= 0.0 or not math.isfinite(close_nav):
            raise ValueError("account_bankrupt")
        weights = {k: units[k] * close_marks[k] / close_nav for k in units if close_marks[k] > 0.0}
        records.append({"date": day, "signal_date": dates[signal] if aim is not None else None,
                        "return": close_nav / previous_nav - 1.0, "nav": close_nav,
                        "cash_return": (closes[cash_asset][day] / closes[cash_asset][prior_day] - 1.0) if cash_asset else 0.0,
                        "turnover": turnover, "cost_fraction": fee, "gross": sum(weights.values()),
                        "risk_gross": sum(w for k, w in weights.items() if k != cash_asset),
                        "weights": weights, "target_weights": target, "pretrade_weights": pre,
                        "cash": cash, "units": dict(units), "missing_marks": missing, "no_fills": no_fills})
        units = {k: u for k, u in units.items() if close_marks[k] > 0.0}
        last_marks, last_weights = close_marks, weights
    return {"records": records, "research_only": True, "orders_authorized": False}


def crypto_prices(axis, assets, opens):
    closes = {k: {axis.dates[a.start + j]: p for j, p in enumerate(a.closes)} for k, a in assets.items()}
    segmented_opens = {k: {d: v for d, v in opens.get(a.symbol, {}).items()
                          if axis.dates[a.start] <= d <= axis.dates[a.end]} for k, a in assets.items()}
    return closes, segmented_opens


def prepare_opens(*, pit_cache: Path, prior_open_root: Path, out: Path, contract_path: Path) -> dict:
    """Cover every possible new target and its next-day mark, not winning curves."""
    c = read_contract(contract_path)
    if (sys.platform != "linux" or not os.path.ismount("/mnt/e")
            or not out.resolve().is_relative_to(Path("/mnt/e/qount_data/qount/artifacts/dual_engine"))):
        raise ValueError("wsl_e_research_storage_required")
    raw, _ = load_cache(pit_cache)
    axis, assets = old.build_crypto_assets(raw)
    prior = json.loads((prior_open_root / "manifest.json").read_text())
    verify_manifest(prior_open_root)
    needed = {}
    for rule in C60_CANDIDATES + C60_CONTROLS:
        targets, _ = crypto_targets(axis, assets, c["c60"], rule)
        for t, weights in targets.items():
            for delay in c["c60"]["delays"]:
                for i in (t + 1 + delay, t + 2 + delay):
                    if i < len(axis.dates) and axis.dates[i] >= c["c60"]["start"]:
                        for k in weights:
                            if assets[k].has(i):
                                needed.setdefault(assets[k].symbol, set()).add(axis.dates[i][:7])
    # Reuse only verified required ZIPs; previous acquisitions remain immutable.
    out.mkdir(parents=True, exist_ok=False)
    (out / "archives").mkdir()
    for symbol, months in needed.items():
        for month in months:
            name = f"archives/{symbol}-1d-{month}.zip"
            if name in prior["files"]:
                (out / name).write_bytes((prior_open_root / name).read_bytes())
    return acquire_opens(pit_cache, out, symbols=sorted(needed),
                         months_by_symbol={s: sorted(v) for s, v in needed.items()}, workers=16)


def run_study(*, contract_path: Path, prior_contract: Path, equity_root: Path, pit_cache: Path,
              open_root: Path, prior_results: Path, out: Path, repo: Path) -> dict:
    c = read_contract(contract_path)
    if (sys.platform != "linux" or not os.path.ismount("/mnt/e")
            or not out.resolve().is_relative_to(Path("/mnt/e/qount_data/qount/artifacts/dual_engine"))):
        raise ValueError("wsl_e_research_storage_required")
    if out.exists():
        raise ValueError("output_exists_preserve_prior_run")
    panel, equity_audit = old.load_equity(equity_root, old.read_contract(prior_contract))
    raw, cache_hashes = load_cache(pit_cache)
    prior_files = verify_manifest(prior_results)
    audit = json.loads((prior_results / "input-audit.json").read_text())
    if cache_hashes != audit["pit_cache_sha256"] or equity_audit["files"] != audit["g20"]["files"]:
        raise ValueError("prior_input_identity_changed")
    axis, assets = old.build_crypto_assets(raw)
    opens, open_files = read_opens(open_root)
    out.mkdir(parents=True)
    old.write_json(out / "contract.json", c)
    old.write_json(out / "input-audit.json", {"equity": equity_audit, "cache_sha256": cache_hashes,
        "open_files": open_files, "prior_result_files": prior_files,
        "prior_manifest_sha256": old.file_hash(prior_results / "manifest.json"),
        "contract_sha256": old.file_hash(contract_path),
        "paths": {"equity_root": str(equity_root), "pit_cache": str(pit_cache), "open_root": str(open_root)}})
    summaries, runs, exposures, checks = {"g20": {}, "c60": {}}, {}, [], {}

    def save(line, rule, cell, run, annual):
        key = f"{line}-{rule}-{cell}"
        runs[key] = run
        old.write_json(out / f"{key}-ledger.json", run)
        result = old.summarize(run, annual)
        risks = [r.get("risk_gross", sum(w for k, w in r["weights"].items() if k != "BIL")) for r in run["records"]]
        result["mean_risk_gross"], result["max_risk_gross"] = stats.fmean(risks), max(risks)
        summaries[line].setdefault(rule, {})[cell] = result
        exposures.append({"curve": key, "role": "candidate" if rule in G20_CANDIDATES + C60_CANDIDATES else "control"})

    equity_closes = {s: dict(zip(panel.dates, p, strict=True)) for s, p in panel.total_closes.items()}
    equity_opens = {s: dict(zip(panel.dates, p, strict=True)) for s, p in panel.total_opens.items()}
    for rule in G20_CONTROLS + G20_CANDIDATES:
        signals = (old.g20_signals(panel) if rule == "g20" else equity_targets(panel, c["g20"], rule))
        old.write_json(out / f"g20-{rule}-targets.json", signals)
        for cost in c["g20"]["cost_bps"]:
            for delay in c["g20"]["delays"]:
                if rule == "g20":
                    run = replay_equity_control(panel, signals, start=c["g20"]["start"], cost_bps=cost, delay=delay)
                    unit_targets = {i: s["target"] for i, s in signals.items()}
                    first = next(i for i, d in enumerate(panel.dates) if d >= c["g20"]["start"])
                    unit_targets.setdefault(first - delay, {"BIL": 1.0})
                    oracle = replay_units(panel.dates, equity_closes, equity_opens, unit_targets,
                                         start=c["g20"]["start"], lag=delay, cost_bps=cost, cash_asset="BIL")
                    error = max(abs(a["return"] - b["return"]) for a, b in zip(run["records"], oracle["records"], strict=True))
                    checks[f"g20-oracle-c{cost}-d{delay}"] = error
                    if error > 1e-12:
                        raise ValueError("g20_unit_oracle_mismatch")
                else:
                    run = replay_units(panel.dates, equity_closes, equity_opens, signals,
                                       start=c["g20"]["start"], lag=delay, cost_bps=cost, cash_asset="BIL")
                save("g20", rule, f"c{cost}-d{delay}", run, 252)
    crypto_closes, crypto_opens = crypto_prices(axis, assets, opens)
    for rule in C60_CONTROLS + C60_CANDIDATES:
        targets, members = crypto_targets(axis, assets, c["c60"], rule)
        old.write_json(out / f"c60-{rule}-targets.json", targets)
        old.write_json(out / f"c60-{rule}-members.json", members)
        for cost in c["c60"]["cost_bps"]:
            for delay in c["c60"]["delays"]:
                adjustment = c["c60"]["adjustment_fraction"] if rule.endswith("partial") else 1.0
                run = replay_units(axis.dates, crypto_closes, crypto_opens, targets,
                    start=c["c60"]["start"], lag=1 + delay, cost_bps=cost, adjustment=adjustment)
                if rule in ("pit", "btc_daily"):
                    previous = json.loads((prior_results / f"c60-{rule}-c{cost}-d{delay}-ledger.json").read_text())
                    error = max(abs(a["return"] - b["return"]) for a, b in zip(run["records"], previous["records"], strict=True))
                    if [r["date"] for r in run["records"]] != [r["date"] for r in previous["records"]] or error > 1e-12:
                        raise ValueError("crypto_baseline_reproduction_failed")
                    checks[f"c60-{rule}-c{cost}-d{delay}"] = error
                save("c60", rule, f"c{cost}-d{delay}", run, 365)
    contrasts = {}
    comparisons = {"g20": {"winner_risk": "g20", "blend_levered": "passive_levered", "blend_proxy": "passive_proxy"},
                   "c60": {"pit_continuous": "pit", "btc_continuous": "btc_daily",
                           "core_satellite": "core_only", "core_satellite_partial": "core_satellite"}}
    for line, comparison in comparisons.items():
        annual = 252 if line == "g20" else 365
        cells = ("c20-d1", "c40-d2") if line == "g20" else ("c25-d0", "c50-d1")
        for rule, reference in comparison.items():
            for cell in cells:
                a, b = runs[f"{line}-{rule}-{cell}"], runs[f"{line}-{reference}-{cell}"]
                contrasts[f"{line}-{rule}-vs-{reference}-{cell}"] = {
                    "paired": paired_diagnostics(a, b, annual=annual, settings=c["paired_bootstrap"]),
                    "same_baseline_best_year_exclusion": paired_year_exclusion(a, b, annual=annual)}
    # Freeze the imported public implementation as part of this independent run.
    sources = {repo / "scripts/research/dual_engine_structural.py", repo / "config/dual-engine-structural-20261004.json"}
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
        "data_role": c["data_role"], "promotion_evidence": False, "summaries": summaries,
        "contrasts": contrasts, "baseline_reproduction": checks, "source_sha256": hashes,
        "curve_exposures": exposures, "candidate_trials": c["new_candidate_trials"],
        "global_trial_count": None, "dsr_pbo": c["dsr_pbo"]}
    if len(exposures) != c["planned_curves"]:
        raise ValueError("curve_inventory_mismatch")
    old.write_json(out / "results.json", result)
    files = {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}
    old.write_json(out / "manifest.json", {"research_only": True, "orders_authorized": False, "files": files})
    return result
