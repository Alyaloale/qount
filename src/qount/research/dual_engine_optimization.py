"""Bounded G20/C60 discovery study. No paper state, credentials or order calls."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import platform
import random
import statistics
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from qount.dual_engine.contracts import C60_SYMBOLS, G20_EXECUTION_TO_PROXY, DualEnginePaperContract
from qount.dual_engine.strategy import _portfolio_volatility, build_g20_decision
from qount.research import c60_pit_universe as pit
from qount.research.c60_cost_study import _rank_candidates


class OptimizationStudyError(ValueError):
    pass


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def read_contract(path: Path) -> dict:
    contract = json.loads(path.read_text())
    if (contract.get("study_id") != "dual_engine_optimization_20261004"
            or contract.get("research_only") is not True or contract.get("orders_authorized") is not False
            or contract.get("holdout_role") != "discovery" or contract.get("promotion_evidence") is not False
            or contract.get("local_candidate_trials") != 2):
        raise OptimizationStudyError("study_contract_invalid")
    g20, c60 = contract["g20"], contract["c60"]
    if (g20["risk_weight"] != 0.2 or c60["entry_confirmation_days"] != 2
            or c60["evaluation_start"] != "2020-12-06" or c60["evaluation_end"] != pit.EVAL_END
            or contract["discovery_slices"] != 5
            or [(g20[s]["cost_bps"], g20[s]["execution_delay_sessions"]) for s in ("base", "stress")] != [(20, 1), (40, 2)]
            or [(c60[s]["cost_bps"], c60[s]["execution_delay_sessions"]) for s in ("base", "stress")] != [(25, 0), (50, 1)]):
        raise OptimizationStudyError("fixed_research_settings_changed")
    return contract


def acquire_equity(out: Path, contract: Mapping) -> dict:
    """Public Yahoo input snapshot; an incomplete acquisition has no manifest."""
    settings = contract["g20"]
    out.mkdir(parents=True, exist_ok=False)
    first = int(dt.datetime.fromisoformat(settings["data_start"]).replace(tzinfo=dt.timezone.utc).timestamp())
    last = int((dt.datetime.fromisoformat(settings["evaluation_end"]) + dt.timedelta(days=1))
               .replace(tzinfo=dt.timezone.utc).timestamp())
    symbols = sorted({*G20_EXECUTION_TO_PROXY, *G20_EXECUTION_TO_PROXY.values(), "BIL", "SPY"})
    manifest = {"source": "Yahoo Finance public chart", "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "start": settings["data_start"], "end": settings["evaluation_end"],
                "research_only": True, "orders_authorized": False, "files": {}}
    for symbol in symbols:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={first}"
               f"&period2={last}&interval=1d&events=div%2Csplits")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        body = json.loads(raw)
        result = body["chart"]["result"][0]
        if result["meta"]["symbol"] != symbol:
            raise OptimizationStudyError("equity_source_symbol_mismatch")
        path = out / f"{symbol}.source.json"
        path.write_bytes(raw)
        manifest["files"][path.name] = file_hash(path)
        print(json.dumps({"acquired": symbol, "bars": len(result["timestamp"])}), flush=True)
    write_json(out / "manifest.json", manifest)
    return manifest


@dataclass(frozen=True)
class EquityPanel:
    dates: tuple[str, ...]
    closes: Mapping[str, tuple[float, ...]]
    total_closes: Mapping[str, tuple[float, ...]]
    total_opens: Mapping[str, tuple[float, ...]]


def load_equity(root: Path, contract: Mapping) -> tuple[EquityPanel, dict]:
    manifest = json.loads((root / "manifest.json").read_text())
    symbols = sorted({*G20_EXECUTION_TO_PROXY, *G20_EXECUTION_TO_PROXY.values(), "BIL", "SPY"})
    expected = {f"{symbol}.source.json" for symbol in symbols}
    if set(manifest["files"]) != expected:
        raise OptimizationStudyError("equity_source_universe_invalid")
    rows, events = {}, {}
    for symbol in symbols:
        path = root / f"{symbol}.source.json"
        if file_hash(path) != manifest["files"][path.name]:
            raise OptimizationStudyError(f"equity_hash_mismatch:{symbol}")
        result = json.loads(path.read_text())["chart"]["result"][0]
        if result["meta"]["symbol"] != symbol:
            raise OptimizationStudyError("equity_source_symbol_mismatch")
        quote = result["indicators"]["quote"][0]
        adjusted = result["indicators"]["adjclose"][0]["adjclose"]
        series = {}
        previous = ""
        for i, stamp in enumerate(result["timestamp"]):
            day = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).astimezone(ZoneInfo("America/New_York"))
            day = day.date().isoformat()
            if not contract["g20"]["data_start"] <= day <= contract["g20"]["evaluation_end"]:
                continue
            if day <= previous:
                raise OptimizationStudyError(f"equity_date_order_invalid:{symbol}")
            previous = day
            values = [quote["open"][i], quote["close"][i], adjusted[i]]
            if any(v is None or not math.isfinite(v) or v <= 0.0 for v in values):
                raise OptimizationStudyError(f"equity_invalid_price:{symbol}:{day}")
            opn, close, adj = values
            series[day] = (close, adj, opn * adj / close)
        rows[symbol] = series
        events[symbol] = {name: len(result.get("events", {}).get(name, {})) for name in ("dividends", "splits")}
    dates = tuple(sorted(rows["SPY"]))
    if len(dates) < 100 or any(set(series) != set(dates) for series in rows.values()):
        raise OptimizationStudyError("equity_calendar_gap; no forward filling allowed")
    panel = EquityPanel(dates, *({s: tuple(rows[s][d][k] for d in dates) for s in symbols} for k in range(3)))
    audit = {"source_manifest_sha256": file_hash(root / "manifest.json"), "files": manifest["files"],
             "first": dates[0], "last": dates[-1], "bars": len(dates), "corporate_event_counts": events,
             "calendar": "SPY source sessions; no independent exchange-calendar certification",
             "execution": "adjusted open = raw open * adjusted close / raw close; total-return unit model",
             "source_equivalence": "Yahoo alternative; not Tiingo/first-minute production certification"}
    return panel, audit


def g20_signals(panel: EquityPanel, *, absolute_momentum: bool = False) -> dict[int, dict]:
    signals = {}
    for i in range(63, len(panel.dates) - 1):
        if panel.dates[i][:7] == panel.dates[i + 1][:7]:
            continue
        window = {s: panel.closes[s][i - 63:i + 1] for s in G20_EXECUTION_TO_PROXY.values()}
        decision = build_g20_decision(window)
        rejected = absolute_momentum and decision.momentum_63d[decision.selected_symbol] <= 0.0
        signals[i] = {"signal_date": panel.dates[i], "selected": decision.selected_symbol,
                      "momentum": decision.momentum_63d[decision.selected_symbol],
                      "target": {"BIL": 1.0} if rejected else dict(decision.target_weights)}
    return signals


def _l1(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    return sum(abs(left.get(s, 0.0) - right.get(s, 0.0)) for s in sorted(set(left) | set(right)))


def _grow(weights: Mapping[str, float], ratios: Mapping[str, float]) -> tuple[float, dict[str, float]]:
    factor = 1.0 + sum(w * (ratios[s] - 1.0) for s, w in weights.items())
    if factor <= 0.0 or not math.isfinite(factor):
        raise OptimizationStudyError("nonpositive_nav")
    return factor, {s: w * ratios[s] / factor for s, w in weights.items() if w * ratios[s] > 0.0}


def replay_equity(panel: EquityPanel, signals: Mapping[int, Mapping], *, start: str, cost_bps: float,
                  delay: int, benchmark: bool = False) -> dict:
    if delay not in (1, 2) or not math.isfinite(cost_bps) or cost_bps < 0.0:
        raise OptimizationStudyError("equity_execution_invalid")
    first = next((i for i, day in enumerate(panel.dates) if day >= start), None)
    if first is None or first == 0:
        raise OptimizationStudyError("equity_start_invalid")
    schedule = {i + delay: (dict(v) | {"target": {"SPY": 0.6, "BIL": 0.4}} if benchmark else dict(v))
                for i, v in signals.items() if i + delay < len(panel.dates)}
    weights: dict[str, float] = {}
    records = []
    for i in range(first, len(panel.dates)):
        overnight, weights = _grow(weights, {s: panel.total_opens[s][i] / panel.total_closes[s][i - 1]
                                            for s in weights})
        trade = schedule.get(i)
        target = trade["target"] if trade else ({"BIL": 1.0} if i == first else None)
        turnover = 0.0
        if target is not None:
            turnover = _l1(weights, target)
            weights = dict(target)
        cost = turnover * cost_bps / 10_000.0
        if cost >= 1.0:
            raise OptimizationStudyError("equity_cost_exhausts_nav")
        intraday, weights = _grow(weights, {s: panel.total_closes[s][i] / panel.total_opens[s][i] for s in weights})
        records.append({"date": panel.dates[i], "return": overnight * (1.0 - cost) * intraday - 1.0,
                        "cash_return": panel.total_closes["BIL"][i] / panel.total_closes["BIL"][i - 1] - 1.0,
                        "turnover": turnover, "cost_fraction": cost, "gross": sum(weights.values()),
                        "signal_date": trade["signal_date"] if trade else None, "weights": dict(weights)})
    return {"records": records}


def _raw_gate(asset: pit.Asset, btc: pit.Asset, t: int) -> bool:
    window, btc_window = asset.window(t), btc.window(t)
    if window is None or btc_window is None:
        return False
    return (window[-1] > statistics.fmean(window[-20:])
            and (asset.symbol == "PAXGUSDT" or btc_window[-1] > statistics.fmean(btc_window[-50:])))


def build_crypto_assets(raw: Mapping, *, end: str = pit.EVAL_END) -> tuple[pit.Axis, dict[str, pit.Asset]]:
    """Segment IDs depend on their start, never on the number of future gaps."""
    rows = {s: {d: v for d, v in series.items() if d <= end} for s, series in raw.items()}
    rows = {s: series for s, series in rows.items() if series}
    if "BTCUSDT" not in rows:
        raise OptimizationStudyError("btc_source_missing")
    first = min(dt.date.fromisoformat(min(series)) for series in rows.values())
    last = dt.date.fromisoformat(end)
    axis = pit.Axis(tuple((first + dt.timedelta(days=i)).isoformat() for i in range((last - first).days + 1)))
    assets = {}
    for symbol, series in sorted(rows.items()):
        runs: list[list[str]] = []
        for day in sorted(series):
            close, quote = map(float, series[day])
            if not math.isfinite(close) or close <= 0.0 or not math.isfinite(quote) or quote < 0.0:
                raise OptimizationStudyError(f"crypto_source_price_volume_invalid:{symbol}:{day}")
            if runs and (dt.date.fromisoformat(day) - dt.date.fromisoformat(runs[-1][-1])).days == 1:
                runs[-1].append(day)
            else:
                runs.append([day])
        for run in runs:
            asset_id = f"{symbol}@{run[0]}"
            assets[asset_id] = pit.Asset(asset_id, symbol, axis.index(run[0]),
                                         tuple(float(series[d][0]) for d in run),
                                         tuple(float(series[d][1]) for d in run))
    btc = [a for a in assets.values() if a.symbol == "BTCUSDT"]
    if (len(btc) != 1 or btc[0].window(axis.index(pit.FIRST_DECISION)) is None
            or btc[0].end != len(axis.dates) - 1):
        raise OptimizationStudyError("btc_source_not_continuous")
    return axis, assets


def c60_targets(axis: pit.Axis, assets: Mapping[str, pit.Asset], *, universe: str,
                confirmation: int = 1, legacy_exit: bool = False) -> tuple[dict, dict]:
    if confirmation not in (1, 2) or universe not in ("pit", "survivor", "btc"):
        raise OptimizationStudyError("c60_candidate_invalid")
    btc = next(a for a in assets.values() if a.symbol == "BTCUSDT")
    contract = DualEnginePaperContract.frozen_v1()
    first = axis.index(pit.FIRST_DECISION)
    held: tuple[str, ...] = ()
    targets, members = {}, {}
    for t in range(first, len(axis.dates) - 1):
        day = dt.date.fromisoformat(axis.dates[t])
        if universe == "btc":
            w = btc.window(t)
            held = (btc.asset_id,) if w[-1] / w[-91] - 1.0 > 0.0 else ()
        elif (day + dt.timedelta(days=1)).day == 1:
            selection = pit.pit_universe(assets, t) if universe == "pit" else pit.survivor_universe(assets, t)
            members[t] = selection
            held = _rank_candidates({k: assets[k].window(t) for k in selection})
        pre, windows = {}, {}
        for k in held:
            a = assets[k]
            if legacy_exit and not a.has(t + 1):
                continue  # Explicit optimistic diagnostic, never candidate evidence.
            if all(_raw_gate(a, btc, t - offset) for offset in range(confirmation)):
                pre[k] = 1.0 / len(held)
                windows[k] = a.window(t)
        vol = _portfolio_volatility(windows, pre, window=contract.c60_volatility_window)
        scalar = 1.0 if vol == 0.0 else min(1.0, contract.c60_volatility_target / vol)
        targets[t] = {k: w * scalar for k, w in pre.items()}
    return targets, members


def replay_crypto(axis: pit.Axis, assets: Mapping[str, pit.Asset], targets: Mapping[int, Mapping], *,
                  cost_bps: float, delay: int = 0) -> dict:
    if delay not in (0, 1) or not math.isfinite(cost_bps) or cost_bps < 0.0:
        raise OptimizationStudyError("crypto_execution_invalid")
    first = axis.index(pit.FIRST_DECISION)
    weights: dict[str, float] = {}
    records = []
    for t in range(first, len(axis.dates) - 1):
        # No fill is invented for a name already unavailable on the execution day.
        requested = targets.get(t - delay, {})
        target = {k: w for k, w in requested.items() if assets[k].has(t)}
        turnover = _l1(weights, target)
        cost = turnover * cost_bps / 10_000.0
        if cost >= 1.0:
            raise OptimizationStudyError("crypto_cost_exhausts_nav")
        missing = [k for k in target if not assets[k].has(t + 1)]
        ratios = {k: (assets[k].close(t + 1) / assets[k].close(t) if assets[k].has(t + 1) else 0.0)
                  for k in target}
        factor = 1.0 + sum(w * (ratios[k] - 1.0) for k, w in target.items())
        weights = {k: w * ratios[k] / factor for k, w in target.items() if factor > 0.0 and w * ratios[k] > 0.0}
        records.append({"date": axis.dates[t + 1], "return": (1.0 - cost) * factor - 1.0,
                        "cash_return": 0.0, "turnover": turnover, "cost_fraction": cost,
                        "gross": sum(target.values()), "missing_marks": missing,
                        "writeoff_weight": sum(target[k] for k in missing), "weights": dict(target)})
    return {"records": records}


def _metrics(values: Sequence[float], annual: int, cash: Sequence[float] | None = None) -> dict:
    if not values or any(not math.isfinite(r) or r <= -1.0 for r in values):
        raise OptimizationStudyError("return_series_invalid_or_bankrupt")
    vol = statistics.stdev(values) * math.sqrt(annual) if len(values) > 1 else 0.0
    mean = statistics.fmean(values) * annual
    excess = [r - c for r, c in zip(values, cash, strict=True)] if cash is not None else list(values)
    excess_vol = statistics.stdev(excess) * math.sqrt(annual) if len(excess) > 1 else 0.0
    nav = peak = 1.0
    mdd = 0.0
    for r in values:
        nav *= 1.0 + r
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1.0)
    return {"cagr": math.expm1(sum(math.log1p(r) for r in values) * annual / len(values)),
            "sharpe": mean / vol if vol else 0.0,
            "cash_excess_sharpe": statistics.fmean(excess) * annual / excess_vol if excess_vol else 0.0,
            "max_drawdown": mdd, "annual_volatility": vol, "total_return": nav - 1.0}


def summarize(run: Mapping, annual: int, *, slices: int = 5) -> dict:
    records = run["records"]
    dates = [r["date"] for r in records]
    values = [r["return"] for r in records]
    cash = [r["cash_return"] for r in records]
    by_year = {}
    for day, r in zip(dates, values, strict=True):
        by_year[day[:4]] = by_year.get(day[:4], 1.0) * (1.0 + r)
    complete = [y for y in by_year if any(d.startswith(y + "-01") for d in dates)
                and any(d.startswith(y + "-12") for d in dates)]
    best = max(complete, key=by_year.get) if complete else None
    keep = [i for i, d in enumerate(dates) if d[:4] != best]
    ex2021 = [i for i, d in enumerate(dates) if d[:4] != "2021"]
    partitions = []
    for k in range(slices):
        lo, hi = k * len(values) // slices, (k + 1) * len(values) // slices
        partitions.append({"first": dates[lo], "last": dates[hi - 1],
                           **_metrics(values[lo:hi], annual, cash[lo:hi])})
    years = len(values) / annual
    return {"first": dates[0], "last": dates[-1], "bars": len(values), **_metrics(values, annual, cash),
            "annual_turnover": sum(r["turnover"] for r in records) / years,
            "annual_cost_fraction": sum(r["cost_fraction"] for r in records) / years,
            "average_gross": statistics.fmean(r["gross"] for r in records),
            "missing_mark_events": sum(len(r.get("missing_marks", [])) for r in records),
            "writeoff_weight_sum": sum(r.get("writeoff_weight", 0.0) for r in records),
            "yearly": {y: v - 1.0 for y, v in by_year.items()}, "complete_years": complete,
            "excluded_best_complete_year": best,
            "excluding_best_year": _metrics([values[i] for i in keep], annual, [cash[i] for i in keep]),
            "excluding_2021": _metrics([values[i] for i in ex2021], annual, [cash[i] for i in ex2021]),
            "discovery_slices": partitions}


def paired_intervals(candidate: Mapping, baseline: Mapping, *, annual: int, settings: Mapping) -> dict:
    left, right = candidate["records"], baseline["records"]
    if [r["date"] for r in left] != [r["date"] for r in right]:
        raise OptimizationStudyError("paired_dates_mismatch")
    # Synchronous circular moving blocks retain the cross-strategy pairing.
    differences = [math.log1p(a["return"]) - math.log1p(b["return"]) for a, b in zip(left, right, strict=True)]
    n = len(differences)
    out = {}
    for length in settings["block_lengths"]:
        rng = random.Random(settings["seed"] + length)
        draws = []
        for _ in range(settings["draws"]):
            sample = []
            while len(sample) < n:
                first = rng.randrange(n)
                sample.extend(differences[(first + i) % n] for i in range(min(length, n - len(sample))))
            draws.append(statistics.fmean(sample) * annual)
        draws.sort()
        out[str(length)] = {"annual_log_growth_difference": statistics.fmean(differences) * annual,
                            "ci95": [draws[int(0.025 * (len(draws) - 1))], draws[int(0.975 * (len(draws) - 1))]],
                            "draws": len(draws), "role": "discovery diagnostic; not selection or promotion"}
    return out


def candidate_gates(results: Mapping[str, Mapping], contract: Mapping) -> dict:
    out = {}
    for line in ("g20", "c60"):
        a, b = results[line]["candidate"], results[line]["baseline"]
        metric = "cash_excess_sharpe" if line == "g20" else "sharpe"
        settings = contract[line]["gates"]
        slices = sum(x[metric] > y[metric] for x, y in zip(a["base"]["discovery_slices"],
                                                        b["base"]["discovery_slices"], strict=True))
        gates = {"max_drawdown_not_worse": all(a[s]["max_drawdown"] + 1e-12 >= b[s]["max_drawdown"] for s in ("base", "stress")),
                 "slice_stability": slices >= settings["minimum_positive_discovery_slices"],
                 "excluding_best_year_positive": a["base"]["excluding_best_year"]["cagr"] > 0.0}
        if line == "g20":
            gates["cash_excess_sharpe_improvement"] = all(a[s][metric] > b[s][metric] for s in ("base", "stress"))
            gates["cagr_sacrifice_within_budget"] = (a["base"]["cagr"] >= b["base"]["cagr"]
                                                    - settings["maximum_base_cagr_sacrifice"])
        else:
            gates["turnover_reduction"] = a["base"]["annual_turnover"] <= b["base"]["annual_turnover"] * settings["maximum_base_turnover_ratio"]
            gates["sharpe_improvement"] = all(a[s][metric] - b[s][metric] >= settings["minimum_sharpe_improvement_both_scenarios"] for s in ("base", "stress"))
            gates["ex_2021_above_btc"] = all(a[s]["excluding_2021"][metric] > results[line]["btc"][s]["excluding_2021"][metric] for s in ("base", "stress"))
        out[line] = {"gates": gates, "positive_discovery_slices": slices,
                     "verdict": "retain_for_new_forward_design" if all(gates.values()) else "reject_discovery_candidate"}
    return out


def run_study(*, equity_root: Path, pit_cache: Path, contract_path: Path, out: Path, repo: Path) -> dict:
    contract = read_contract(contract_path)
    storage = Path("/mnt/e/qount_data/qount")
    if sys.platform != "linux" or not os.path.ismount("/mnt/e") or not storage.is_dir():
        raise OptimizationStudyError("wsl_mounted_e_storage_required")
    if not out.resolve().is_relative_to(storage / "artifacts/dual_engine"):
        raise OptimizationStudyError("output_outside_declared_research_storage")
    if out.exists():
        raise OptimizationStudyError("output_exists; preserve prior artifacts")
    panel, equity_audit = load_equity(equity_root, contract)
    cache_files = sorted(pit_cache.glob("*.json"))
    if not cache_files:
        raise OptimizationStudyError("pit_cache_empty")
    raw, hashes = {}, {}
    for path in cache_files:
        hashes[path.name] = file_hash(path)
        body = json.loads(path.read_text())
        if body["rows"]:
            raw[path.stem] = body["rows"]
    axis, assets = build_crypto_assets(raw)
    if axis.dates[-1] != contract["c60"]["evaluation_end"]:
        raise OptimizationStudyError("pit_end_contract_mismatch")
    sources = {repo / "scripts/research/dual_engine_optimization.py"}
    for name, module in tuple(sys.modules.items()):
        if name == "qount" or name.startswith("qount."):
            path = Path(module.__file__).resolve() if getattr(module, "__file__", None) else None
            if path is not None and path.suffix == ".py":
                if not path.is_relative_to(repo.resolve() / "src"):
                    raise OptimizationStudyError("imported_source_outside_declared_repo")
                sources.add(path)
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "preregistration.json", contract)
    source_hashes = {}
    for path in sorted(sources):
        relative = path.relative_to(repo)
        saved = out / "source" / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(path.read_bytes())
        source_hashes[str(relative)] = file_hash(path)
    write_json(out / "input-audit.json", {"g20": equity_audit, "pit_cache_sha256": hashes,
                                          "pit_assets": len(assets), "symbols_with_rows": len(raw),
                                          "contract_sha256": file_hash(contract_path), "source_sha256": source_hashes})
    summaries = {"g20": {}, "c60": {}, "survivor_diagnostic": {}}
    runs = {}
    exposures = []
    for name, gate in (("baseline", False), ("candidate", True), ("benchmark", False)):
        signals = g20_signals(panel, absolute_momentum=gate)
        write_json(out / f"g20-{name}-signals.json", signals)
        summaries["g20"][name] = {}
        for scenario in ("base", "stress"):
            settings = contract["g20"][scenario]
            run = replay_equity(panel, signals, start=contract["g20"]["evaluation_start"],
                                cost_bps=settings["cost_bps"], delay=settings["execution_delay_sessions"],
                                benchmark=name == "benchmark")
            key = f"g20-{name}-{scenario}"
            runs[key] = run
            write_json(out / f"{key}-ledger.json", run)
            summaries["g20"][name][scenario] = summarize(run, 252)
            exposures.append({"curve": key, "candidate_trial": "g20-1" if gate else None, "role": "discovery"})
    for universe, group in (("pit", "c60"), ("survivor", "survivor_diagnostic")):
        for name, confirmation in (("baseline", 1), ("candidate", 2)):
            targets, members = c60_targets(axis, assets, universe=universe, confirmation=confirmation)
            write_json(out / f"c60-{universe}-{name}-targets.json", targets)
            if name == "baseline":
                write_json(out / f"c60-{universe}-members.json", members)
            summaries[group][name] = {}
            for scenario in ("base", "stress"):
                settings = contract["c60"][scenario]
                run = replay_crypto(axis, assets, targets, cost_bps=settings["cost_bps"], delay=settings["execution_delay_sessions"])
                key = f"c60-{universe}-{name}-{scenario}"
                runs[key] = run
                write_json(out / f"{key}-ledger.json", run)
                summaries[group][name][scenario] = summarize(run, 365)
                exposures.append({"curve": key, "candidate_trial": "c60-1" if confirmation == 2 else None,
                                  "role": "discovery" if universe == "pit" else "survivor bias diagnostic"})
    targets, _ = c60_targets(axis, assets, universe="btc")
    summaries["c60"]["btc"] = {}
    for scenario in ("base", "stress"):
        settings = contract["c60"][scenario]
        run = replay_crypto(axis, assets, targets, cost_bps=settings["cost_bps"], delay=settings["execution_delay_sessions"])
        key = f"c60-btc-{scenario}"
        write_json(out / f"{key}-ledger.json", run)
        summaries["c60"]["btc"][scenario] = summarize(run, 365)
        exposures.append({"curve": key, "candidate_trial": None, "role": "existing BTC control"})
    legacy_targets, _ = c60_targets(axis, assets, universe="pit", legacy_exit=True)
    original_targets, _ = pit.target_path(axis, assets, pit.pit_universe)
    if legacy_targets != original_targets:
        raise OptimizationStudyError("legacy_target_reproduction_failed")
    legacy = replay_crypto(axis, assets, legacy_targets, cost_bps=25.0)
    original = pit.simulate(axis, assets, original_targets)
    error = max(abs(a["return"] - b) for a, b in zip(legacy["records"], original["returns"], strict=True))
    if error > 1e-12:
        raise OptimizationStudyError("legacy_ledger_reproduction_failed")
    write_json(out / "c60-legacy-lookahead-ledger.json", legacy)
    exposures.append({"curve": "c60-legacy-lookahead", "candidate_trial": None, "role": "optimistic lookahead diagnostic"})
    intervals = {}
    for line, annual in (("g20", 252), ("c60", 365)):
        intervals[line] = {}
        for scenario in ("base", "stress"):
            prefix = "g20" if line == "g20" else "c60-pit"
            intervals[line][scenario] = paired_intervals(runs[f"{prefix}-candidate-{scenario}"],
                                                         runs[f"{prefix}-baseline-{scenario}"],
                                                         annual=annual, settings=contract["paired_bootstrap"])
    result = {"study_id": contract["study_id"], "research_only": True, "orders_authorized": False,
              "holdout_role": "discovery", "promotion_evidence": False,
              "local_candidate_trials": 2, "global_trial_count": None,
              "global_trial_reconciliation": contract["global_trial_reconciliation"],
              "dsr_pbo": contract["dsr_pbo"], "results": summaries, "decisions": candidate_gates(summaries, contract),
              "paired_intervals": intervals, "curve_exposures": exposures,
              "legacy_consistency": {"max_return_error": error, "summary": summarize(legacy, 365)},
              "source_sha256": source_hashes, "contract_sha256": file_hash(contract_path),
              "environment": {"python": sys.version, "platform": platform.platform()},
              "completed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    write_json(out / "results.json", result)
    write_json(out / "manifest.json", {"files": {str(p.relative_to(out)): file_hash(p)
                                                   for p in sorted(out.rglob("*")) if p.is_file()},
                                       "research_only": True, "orders_authorized": False})
    return result
