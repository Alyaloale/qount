"""Frozen-leader later-period checks; historical checks never reselect a winner."""
from __future__ import annotations
import concurrent.futures
import csv
import datetime as dt
import json
import math
import sys
from pathlib import Path
from zoneinfo import ZoneInfo
from qount.research import dual_engine_optimization as old
from qount.research import dual_engine_structural as base
from qount.research import dual_engine_expansion as ex
from qount.research import dual_engine_nextgen as new
from qount.research.dual_engine_execution_study import verify_manifest, load_cache, read_opens
from qount.research.dual_engine_expansion_data import fetch, load_macro, load_rates
from qount.research.dual_engine_nextgen_data import load_tail
from qount.research.c60_execution_control import _parse_archive
from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY


def acquire_equity_later(*, registry_manifest_sha256, leader_frozen_at, out):
    """Transient public Yahoo fetch; orchestrator transfers and removes Mac temp."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    if now <= leader_frozen_at or len(registry_manifest_sha256) != 64 or out.exists():
        raise ValueError("later_equity_requires_prior_freeze_and_fresh_output")
    out.mkdir(parents=True)
    first = int(dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc).timestamp())
    last = int(dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc).timestamp())
    symbols = sorted({*G20_EXECUTION_TO_PROXY, *G20_EXECUTION_TO_PROXY.values(), "BIL", "SPY", *ex.MACRO, "VIXY"})
    def one(symbol):
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={first}"
               f"&period2={last}&interval=1d&events=div%2Csplits")
        body = fetch(url)
        if json.loads(body)["chart"]["result"][0]["meta"]["symbol"] != symbol:
            raise ValueError("later_equity_fetch_identity_mismatch")
        (out / f"{symbol}.source.json").write_bytes(body)
        print(json.dumps({"later_equity": symbol}), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(one, symbols))
    manifest = {"research_only": True, "orders_authorized": False,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "leader_frozen_at": leader_frozen_at,
        "registry_manifest_sha256": registry_manifest_sha256,
        "data_role": "later_period_check_global_consumption_unreconciled",
        "files": {p.name: old.file_hash(p) for p in sorted(out.iterdir()) if p.is_file()}}
    old.write_json(out / "manifest.json", manifest)
    return manifest


def frozen_versions(registry_root):
    verify_manifest(registry_root)
    registry = json.loads((registry_root / "registry.json").read_text())
    by_id = {r["version_id"]: r for r in registry["versions"]}
    leaders = {line: by_id[r["leader"]] for line, r in registry["leaders"].items()}
    return registry, leaders


def acquire_crypto_later(*, registry_root, pit_cache, out, archive_period="monthly"):
    ex.require_storage(out)
    registry, _ = frozen_versions(registry_root)
    if out.exists():
        raise ValueError("immutable_later_acquisition_exists")
    raw, hashes = load_cache(pit_cache)
    axis, assets = old.build_crypto_assets(raw)
    t = axis.index("2026-08-31")
    symbols = sorted({assets[k].symbol for k in base.pit.pit_universe(assets, t)})
    if archive_period not in ("monthly", "daily"):
        raise ValueError("later_archive_period_invalid")
    out.mkdir(parents=True)
    (out / "archives").mkdir()
    days = [(dt.date(2026, 9, 1) + dt.timedelta(days=i)).isoformat() for i in range(30)]
    jobs = [(s, period) for s in symbols for period in (["2026-09"] if archive_period == "monthly" else days)]
    def one(job):
        symbol, period = job
        name = f"{symbol}-1d-{period}.zip"
        url = f"https://data.binance.vision/data/spot/{archive_period}/klines/{symbol}/1d/{name}"
        checksum = fetch(url + ".CHECKSUM")
        expected = checksum.decode().split()[0]
        body = fetch(url)
        (out / "archives" / name).write_bytes(body)
        (out / "archives" / (name + ".CHECKSUM")).write_bytes(checksum)
        if old.file_hash(out / "archives" / name) != expected:
            raise ValueError("later_archive_checksum_mismatch")
        opens, rows = _parse_archive(body)
        if any(not "2026-09-01" <= d <= "2026-09-30" for d in rows):
            raise ValueError("later_archive_date_mismatch")
        if archive_period == "daily" and set(rows) != {period}:
            raise ValueError("later_daily_archive_identity")
        if symbol == "BTCUSDT" and len(rows) != (30 if archive_period == "monthly" else 1):
            raise ValueError("later_btc_calendar_gap")
        return symbol, {"rows": rows, "opens": opens}
    data = {s: {"rows": {}, "opens": {}} for s in symbols}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for i, (symbol, values) in enumerate(pool.map(one, jobs)):
            if set(data[symbol]["rows"]) & set(values["rows"]):
                raise ValueError("later_archive_duplicate_date")
            for name in ("rows", "opens"):
                data[symbol][name].update(values[name])
            if (i + 1) % 30 == 0 or archive_period == "monthly":
                print(json.dumps({"later_crypto": symbol, "archives_completed": i + 1}), flush=True)
    # Independent official REST bridge validates every archived September OHLC/volume.
    begin = int(dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    finish = int(dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc).timestamp() * 1000) - 1
    rest_errors = {}
    for symbol, values in data.items():
        body = fetch(f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1d&startTime={begin}&endTime={finish}&limit=1000")
        (out / f"{symbol}.rest.json").write_bytes(body)
        rows = {dt.datetime.fromtimestamp(int(r[0]) / 1000, dt.timezone.utc).date().isoformat():
                (float(r[1]), float(r[4]), float(r[7])) for r in json.loads(body)}
        if set(rows) != set(values["rows"]):
            raise ValueError("later_rest_archive_calendar_mismatch")
        error = max(abs(x / y - 1) for d, r in rows.items() for x, y in zip(r,
            (values["opens"][d], *values["rows"][d]), strict=True))
        if error > 1e-10:
            raise ValueError("later_rest_archive_row_mismatch")
        rest_errors[symbol] = error
        print(json.dumps({"later_crypto_rest_bridge": symbol, "rows": len(rows), "error": error}), flush=True)
    old.write_json(out / "crypto.json", data)
    manifest = {"research_only": True, "orders_authorized": False,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "leader_frozen_at": registry["created_at"],
        "registry_manifest_sha256": old.file_hash(registry_root / "manifest.json"),
        "prior_cache_sha256": hashes, "symbols_selected_at": "2026-08-31",
        "archive_period": archive_period, "rest_bridge_max_relative_errors": rest_errors,
        "data_role": "later_period_check_global_consumption_unreconciled",
        "files": {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}}
    old.write_json(out / "manifest.json", manifest)
    return manifest


def acquire_crypto_rest_later(*, registry_root, discovery_results, out):
    """Official closed daily bars, using the already frozen Aug31 PIT members."""
    ex.require_storage(out)
    registry, _ = frozen_versions(registry_root)
    verify_manifest(discovery_results)
    if out.exists():
        raise ValueError("immutable_later_rest_snapshot_exists")
    members = json.loads((discovery_results / "c60-residual2-selection.json").read_text())
    last = max(members, key=int)
    if int(last) != (dt.date(2026, 8, 31) - dt.date(2020, 1, 1)).days:
        raise ValueError("later_rest_universe_date_mismatch")
    symbols = sorted(k.split("@", 1)[0] for k in members[last])
    begin = int(dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    finish = int(dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc).timestamp() * 1000) - 1
    out.mkdir(parents=True)
    def one(symbol):
        body = fetch(f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1d&startTime={begin}&endTime={finish}&limit=1000")
        (out / f"{symbol}.rest.json").write_bytes(body)
        rows, opens = {}, {}
        for r in json.loads(body):
            day = dt.datetime.fromtimestamp(int(r[0]) / 1000, dt.timezone.utc).date().isoformat()
            vals = (float(r[1]), float(r[4]), float(r[7]))
            if day in rows or not "2026-09-01" <= day <= "2026-09-30" or any(not math.isfinite(v) for v in vals) or min(vals[:2]) <= 0 or vals[2] < 0:
                raise ValueError("later_rest_invalid_completed_bar")
            opens[day], rows[day] = vals[0], vals[1:]
        if len(rows) != 30:
            raise ValueError("later_rest_incomplete_calendar")
        print(json.dumps({"later_rest": symbol, "rows": len(rows)}), flush=True)
        return symbol, {"rows": rows, "opens": opens}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        data = dict(pool.map(one, symbols))
    old.write_json(out / "crypto.json", data)
    manifest = {"research_only": True, "orders_authorized": False, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "registry_manifest_sha256": old.file_hash(registry_root / "manifest.json"), "leader_frozen_at": registry["created_at"],
        "symbols_selected_at": "2026-08-31", "source": "official Binance data-api public closed daily klines",
        "PIT_members_source_sha256": old.file_hash(discovery_results / "c60-residual2-selection.json"),
        "data_role": "later_period_check_global_consumption_unreconciled",
        "files": {p.name: old.file_hash(p) for p in sorted(out.iterdir()) if p.is_file()}}
    old.write_json(out / "manifest.json", manifest)
    return manifest


def append_equity(panel, root):
    """Keep every original observation; bridge fresh price units at July 30."""
    verify_manifest(root)
    series = {}
    for symbol in panel.closes:
        result = json.loads((root / f"{symbol}.source.json").read_text())["chart"]["result"][0]
        if result["meta"]["symbol"] != symbol:
            raise ValueError("later_equity_identity_mismatch")
        q, adj = result["indicators"]["quote"][0], result["indicators"]["adjclose"][0]["adjclose"]
        rows = {}
        for i, stamp in enumerate(result["timestamp"]):
            day = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
            if "2026-07-01" <= day <= "2026-09-30":
                vals = (q["close"][i], adj[i], q["open"][i])
                if day in rows or any(v is None or not math.isfinite(v) or v <= 0 for v in vals):
                    raise ValueError("later_equity_invalid_row")
                rows[day] = (vals[0], vals[1], vals[2] * vals[1] / vals[0])
        series[symbol] = rows
    bridge = panel.dates[-1]
    extra = tuple(sorted(d for d in series["SPY"] if d > bridge))
    if not extra or extra[-1] != "2026-09-30" or any(set(d for d in rows if d > bridge) != set(extra) for rows in series.values()):
        raise ValueError("later_equity_calendar_gap")
    old_maps = (panel.closes, panel.total_closes, panel.total_opens)
    maps, errors = [dict(m) for m in old_maps], {}
    for symbol, rows in series.items():
        raw_factor = panel.closes[symbol][-1] / rows[bridge][0]
        total_factor = panel.total_closes[symbol][-1] / rows[bridge][1]
        factors = (raw_factor, total_factor, total_factor)
        overlap = [i for i, d in enumerate(panel.dates) if d in rows]
        error = max(abs(rows[panel.dates[i]][j] * factors[j] / old_maps[j][symbol][i] - 1)
                    for i in overlap for j in (0, 1))
        if error > 1e-4:
            raise ValueError(f"later_overlap_revision:{symbol}:{error}")
        errors[symbol] = error
        for j, mapping in enumerate(maps):
            mapping[symbol] += tuple(rows[d][j] * factors[j] for d in extra)
    return old.EquityPanel(panel.dates + extra, *maps), errors


def extend_rate_snapshot(*, prior_root, fresh_root, out):
    """Append new dates while preserving the original vintage on old dates."""
    ex.require_storage(out)
    prior_files, fresh_files = verify_manifest(prior_root), verify_manifest(fresh_root)
    if out.exists():
        raise ValueError("immutable_later_rate_snapshot_exists")
    out.mkdir(parents=True)
    cutoffs = {}
    for series in ("DFII10", "T10YIE"):
        with (prior_root / f"{series}.csv").open() as f:
            previous = list(csv.reader(f))
        with (fresh_root / f"{series}.csv").open() as f:
            fresh = list(csv.reader(f))
        cutoff = max(r[0] for r in previous[1:] if len(r) == 2)
        extension = [r for r in fresh[1:] if len(r) == 2 and cutoff < r[0] <= "2026-09-30"]
        if not extension or extension[-1][0] != "2026-09-30":
            raise ValueError("later_rate_end_missing")
        with (out / f"{series}.csv").open("w", newline="") as f:
            csv.writer(f).writerows(previous + extension)
        cutoffs[series] = cutoff
    manifest = {"research_only": True, "orders_authorized": False, "prior_files": prior_files,
        "fresh_files": fresh_files, "preserved_through": cutoffs,
        "historical_vintage": "old snapshot preserved; new dates latest retrieval; no PIT vintage certification",
        "files": {p.name: old.file_hash(p) for p in sorted(out.iterdir()) if p.is_file()}}
    old.write_json(out / "manifest.json", manifest)
    return manifest


def targets_for_version(version, panel, axis, assets, rates, supply, network):
    contract = json.loads(Path(version["strategy_contract_path"]).read_text())
    if old.file_hash(Path(version["strategy_contract_path"])) != version["strategy_contract_sha256"]:
        raise ValueError("frozen_strategy_contract_changed")
    for relative, digest in version["source_sha256"].items():
        if relative.startswith("src/") and old.file_hash(Path(version["artifact_root"]) / "source" / relative) != digest:
            raise ValueError("frozen_strategy_source_changed")
        # The registry is imported by the adapter but never generates signals or
        # accounts for returns. Its frozen copy is still verified above; metadata
        # binding corrections need not invalidate an unchanged strategy module.
        if relative.startswith("src/") and relative != "src/qount/research/dual_engine_registry.py" and old.file_hash(Path(relative)) != digest:
            raise ValueError("confirmation_implementation_differs_from_frozen_version")
    study, line, rule = version["study_id"], version["line"], version["rule"]
    if study == "dual_engine_nextgen_20261004":
        targets, _ = (new.equity_targets(panel, contract[line], rule, rates) if line == "g20" else
                      new.crypto_targets(axis, assets, contract[line], rule, supply))
    elif study == "dual_engine_expansion_20261004":
        targets, _ = (ex.equity_targets(panel, contract[line], rule, rates) if line == "g20" else
                      ex.crypto_targets(axis, assets, contract[line], rule, network))
    elif study == "dual_engine_structural_20261004":
        if line == "g20" and rule == "g20":
            targets = {t: r["target"] for t, r in old.g20_signals(panel).items()}
        elif line == "g20":
            targets = base.equity_targets(panel, contract[line], rule)
        else:
            targets, _ = base.crypto_targets(axis, assets, contract[line], rule)
    else:
        raise ValueError("frozen_version_later_replay_not_implemented")
    adjustment = contract[line].get("adjustment_fraction", 1.) if rule.endswith("partial") else 1.
    return targets, adjustment


def run_later(*, registry_root, discovery_results, equity_later_root, crypto_later_root, rates_later_root, out, repo):
    ex.require_storage(out)
    registry, leaders = frozen_versions(registry_root)
    if out.exists():
        raise ValueError("immutable_later_check_exists")
    verify_manifest(discovery_results)
    audit = json.loads((discovery_results / "input-audit.json").read_text())
    paths = {k: Path(v) for k, v in audit["paths"].items()}
    panel, _ = old.load_equity(paths["equity_root"], old.read_contract(repo / "config/dual-engine-optimization-20261004.json"))
    panel = load_tail(load_macro(panel, paths["expansion_root"]), paths["tail_root"])
    late_hashes = {}
    for name, root in (("equity", equity_later_root), ("crypto", crypto_later_root)):
        late_hashes[name] = verify_manifest(root)
        m = json.loads((root / "manifest.json").read_text())
        if m["registry_manifest_sha256"] != old.file_hash(registry_root / "manifest.json") or m["created_at"] <= registry["created_at"]:
            raise ValueError("later_prices_acquired_before_leader_freeze")
    panel, bridge_errors = append_equity(panel, equity_later_root)
    rates = load_rates(rates_later_root, panel.dates)
    raw, hashes = load_cache(paths["pit_cache"])
    if hashes != audit["cache_sha256"]:
        raise ValueError("later_original_cache_changed")
    opens, _ = read_opens(paths["open_root"])
    crypto = json.loads((crypto_later_root / "crypto.json").read_text())
    for symbol, values in crypto.items():
        if set(raw[symbol]) & set(values["rows"]):
            raise ValueError("later_crypto_overlap")
        raw[symbol].update(values["rows"])
        opens.setdefault(symbol, {}).update(values["opens"])
    axis, assets = old.build_crypto_assets(raw, end="2026-09-30")
    supply = json.loads((paths["supply_root"] / "supply.json").read_text())
    network = json.loads((paths["expansion_root"] / "network.json").read_text())
    eq_close = {s: dict(zip(panel.dates, p, strict=True)) for s, p in panel.total_closes.items()}
    eq_open = {s: dict(zip(panel.dates, p, strict=True)) for s, p in panel.total_opens.items()}
    cr_close, cr_open = base.crypto_prices(axis, assets, opens)
    # References fixed in preregistration; the leader is frozen before these prices.
    versions = {line: [("leader", version)] for line, version in leaders.items()}
    by_rule = {(r["study_id"], r["line"], r["rule"]): r for r in registry["versions"]}
    for line, rules in (("g20", ("g20", "gold20")), ("c60", ("residual2", "btc_continuous"))):
        versions[line] += [(rule, by_rule[("dual_engine_nextgen_20261004", line, rule)]) for rule in rules]
    out.mkdir(parents=True)
    summary, reproduction = {}, {}
    for line, pairs in versions.items():
        dates, closes, opns, annual = (panel.dates, eq_close, eq_open, 252) if line == "g20" else (axis.dates, cr_close, cr_open, 365)
        first_later = "2026-07-31" if line == "g20" else "2026-09-01"
        for label, version in pairs:
            targets, adjustment = targets_for_version(version, panel, axis, assets, rates, supply, network)
            for cell in sorted(version["cells"]):
                cost, delay = (int(v[1:]) for v in cell.split("-"))
                aims = dict(targets)
                if line == "g20":
                    first = next(i for i, d in enumerate(dates) if d >= "2018-04-02")
                    aims.setdefault(first - delay, {"BIL": 1.})
                run = base.replay_units(dates, closes, opns, aims, start="2018-04-02" if line == "g20" else "2021-01-01",
                    lag=delay if line == "g20" else 1 + delay, cost_bps=cost, cash_asset="BIL" if line == "g20" else None, adjustment=adjustment)
                old_rule = version["rule"]
                historical_path = Path(version["artifact_root"]) / f"{line}-{old_rule}-{cell}-ledger.json"
                previous = json.loads(historical_path.read_text())["records"]
                prefix = [r for r in run["records"] if r["date"] < first_later]
                if [r["date"] for r in prefix] != [r["date"] for r in previous]:
                    raise ValueError("later_historical_prefix_dates_changed")
                error = max(abs(r["return"] - p["return"]) for r, p in zip(prefix, previous, strict=True))
                if error > 1e-12:
                    raise ValueError(f"later_historical_prefix_changed:{line}:{label}:{cell}:{error}")
                key = f"{line}-{label}-{cell}"
                reproduction[key] = error
                old.write_json(out / f"{key}-ledger.json", run)
                summary[key] = {"version_id": version["version_id"], **ex.window_summary(run, first_later, "2026-09-30", annual)}
                summary[key]["role"] = "frozen later-period check; global history consumption unreconciled; descriptive only"
            print(json.dumps({"later_replayed": line + "-" + label}), flush=True)
    sources = {}
    for name, module in tuple(sys.modules.items()):
        path = Path(module.__file__).resolve() if getattr(module, "__file__", None) else None
        if name.startswith("qount") and path and path.suffix == ".py":
            if not path.is_relative_to(repo.resolve() / "src"):
                raise ValueError("confirmation_source_outside_delivery")
            relative = path.relative_to(repo)
            saved = out / "source" / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(path.read_bytes())
            sources[str(relative)] = old.file_hash(path)
    result = {"research_only": True, "orders_authorized": False, "promotion_evidence": False,
        "study_id": "dual_engine_frozen_later_check_20261004", "candidate_trials": 0,
        "registry_manifest_sha256": old.file_hash(registry_root / "manifest.json"),
        "frozen_leaders": registry["leaders"], "summaries": summary, "prefix_reproduction": reproduction,
        "equity_bridge_max_relative_errors": bridge_errors, "input_files": late_hashes,
        "rate_files": verify_manifest(rates_later_root),
        "source_sha256": sources, "global_optimum_confirmed": False, "prospective_start": "2026-10-05",
        "confirmation_status": "descriptive_later_check_completed_pending_prospective",
        "history_note": "Only Aug31 PIT members extended for Sep crypto; Sep30 selections execute outside this check; not a forward universe feed"}
    old.write_json(out / "results.json", result)
    old.write_json(out / "manifest.json", {"research_only": True, "orders_authorized": False,
        "files": {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}})
    return result
