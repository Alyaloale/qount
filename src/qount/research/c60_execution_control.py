"""C60 closed-bar intent validation and next-open research accounting.

This module has no paper state, account, credential or order interface.  Historical
daily opens are bar prices, not evidence of an executable bid/ask or market fill.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import io
import json
import math
import os
import statistics
import sys
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path
from typing import Mapping, Sequence

from qount.dual_engine.contracts import DualEnginePaperContract
from qount.dual_engine.strategy import _portfolio_volatility
from qount.research import c60_pit_universe as pit
from qount.research.c60_cost_study import _rank_candidates
from qount.research.dual_engine_optimization import _raw_gate, build_crypto_assets
from qount.research_data.replay_fees import trade_to_target


class C60ExecutionError(ValueError):
    pass


def warm_targets(axis: pit.Axis, assets: Mapping[str, pit.Asset], *, universe: str = "pit",
                 confirmation: int = 1, btc_gradient: bool = False) -> tuple[dict[int, dict[str, float]], dict[int, list[str]]]:
    """Carry actual monthly selections through warmup; never reset at evaluation.

    ``btc`` keeps the existing daily momentum control; ``btc_monthly`` uses the
    same monthly positive-momentum eligibility clock as the PIT strategy.
    """
    if universe not in ("pit", "survivor", "btc", "btc_monthly") or confirmation not in (1, 2):
        raise C60ExecutionError("target_rule_invalid")
    btc_names = [a for a in assets.values() if a.symbol == "BTCUSDT"]
    if len(btc_names) != 1:
        raise C60ExecutionError("one_continuous_btc_asset_required")
    btc = btc_names[0]
    contract = DualEnginePaperContract.frozen_v1()
    first = next((t for t in range(len(axis.dates)) if btc.window(t) is not None), None)
    if first is None:
        raise C60ExecutionError("btc_warmup_insufficient")
    held: tuple[str, ...] = ()
    targets, members = {}, {}
    for t in range(first, len(axis.dates)):
        day = dt.date.fromisoformat(axis.dates[t])
        month_end = (day + dt.timedelta(days=1)).day == 1
        btc_window = btc.window(t)
        if btc_window is None:
            raise C60ExecutionError("btc_completed_bar_missing")
        if universe == "btc" or (universe == "btc_monthly" and month_end):
            held = (btc.asset_id,) if btc_window[-1] / btc_window[-91] - 1.0 > 0.0 else ()
            if month_end:
                members[t] = [btc.asset_id]
        elif month_end:
            selection = pit.pit_universe(assets, t) if universe == "pit" else pit.survivor_universe(assets, t)
            members[t] = selection
            held = _rank_candidates({k: assets[k].window(t) for k in selection})
        pre, windows = {}, {}
        for k in held:
            asset = assets[k]
            window = asset.window(t)
            if btc_gradient:
                if confirmation != 1:
                    raise C60ExecutionError("gradient_confirmation_not_registered")
                own_pass = window is not None and window[-1] > statistics.fmean(window[-20:])
                exposure = (1.0 if asset.symbol == "PAXGUSDT" else
                            gradient_exposure(btc_window[-1] / statistics.fmean(btc_window[-50:]) - 1.0))
                passed = own_pass and exposure > 0.0
            else:
                passed = all(_raw_gate(asset, btc, t - offset) for offset in range(confirmation))
                exposure = 1.0
            if passed:
                pre[k] = exposure / len(held)
                windows[k] = asset.window(t)
        vol = _portfolio_volatility(windows, pre, window=contract.c60_volatility_window)
        scalar = 1.0 if vol == 0.0 else min(1.0, contract.c60_volatility_target / vol)
        targets[t] = {k: w * scalar for k, w in pre.items()}
    return targets, members


def gradient_exposure(distance: float) -> float:
    """One frozen BTC SMA50 staircase; thresholds are discovery assumptions."""
    if not math.isfinite(distance):
        raise C60ExecutionError("gradient_distance_invalid")
    if distance <= -.02:
        return 0.0
    if distance <= 0.0:
        return .35
    if distance <= .02:
        return .70
    return 1.0


def _validate_weights(weights: Mapping[str, float]) -> None:
    if any(not math.isfinite(w) or w < 0.0 for w in weights.values()) or sum(weights.values()) > 1.0 + 1e-12:
        raise C60ExecutionError("long_cash_weights_invalid")


def solve_cost(pre_weights: Mapping[str, float], target: Mapping[str, float], cost_bps: float,
               *, exact: bool = True) -> dict:
    """Solve self-financing fees with targets expressed as post-fee NAV weights.

    For pretrade NAV=1, fee c and rate k, trades are (1-c)*target-pre.
    The exact solution is c=k*L1(trades), including both rotation sides.
    """
    _validate_weights(pre_weights)
    _validate_weights(target)
    if not math.isfinite(cost_bps) or not 0.0 <= cost_bps < 5_000.0:
        raise C60ExecutionError("fee_rate_invalid")
    rate = cost_bps / 10_000.0
    names = sorted(set(pre_weights) | set(target))
    requested = sum(abs(target.get(k, 0.0) - pre_weights.get(k, 0.0)) for k in names)

    post_fee_ratio, turnover = trade_to_target(pre_weights, target, cost_bps, exact=exact)
    cost = 1.0 - post_fee_ratio
    if not 0.0 <= cost < 1.0:
        raise C60ExecutionError("fee_exhausts_nav")
    nominal = {k: (1.0 - cost) * target.get(k, 0.0) - pre_weights.get(k, 0.0) for k in names}
    actual_turnover = sum(abs(v) for v in nominal.values())
    return {"cost_fraction": cost, "turnover": turnover, "requested_turnover": requested,
            "actual_turnover": actual_turnover,
            "nominal_trades": nominal, "fee_residual": cost - rate * actual_turnover,
            "post_fee_cash": (1.0 - cost) * (1.0 - sum(target.values()))}


def _open_price(opens: Mapping[str, Mapping[str, float]], asset: pit.Asset, day: str) -> float | None:
    value = opens.get(asset.symbol, {}).get(day)
    if value is not None and (not math.isfinite(value) or value <= 0.0):
        raise C60ExecutionError(f"invalid_open:{asset.symbol}:{day}")
    return value


def _mark(weights: Mapping[str, float], ratios: Mapping[str, float]) -> tuple[float, dict[str, float]]:
    factor = 1.0 + sum(w * (ratios[k] - 1.0) for k, w in weights.items())
    if factor <= 0.0 or not math.isfinite(factor):
        raise C60ExecutionError("portfolio_bankrupt")
    return factor, {k: w * ratios[k] / factor for k, w in weights.items() if w * ratios[k] > 0.0}


def replay_crypto_open(axis: pit.Axis, assets: Mapping[str, pit.Asset],
                       opens: Mapping[str, Mapping[str, float]], targets: Mapping[int, Mapping[str, float]], *,
                       start: str = "2021-01-01", cost_bps: float, delay: int = 0,
                       cancel_stale: bool = False, exact_fees: bool = True,
                       rebalance_deadband: float = 0.0) -> dict:
    """Execute a completed-close intent at the following open (plus delay).

    The stale filter only suppresses purchases, using yesterday's finalized
    closes.  It neither observes today's open to decide nor advances a sale.
    Every invocation starts from cash on the same declared evaluation date.
    """
    if delay not in (0, 1):
        raise C60ExecutionError("execution_delay_invalid")
    if not math.isfinite(rebalance_deadband) or not 0.0 <= rebalance_deadband < 1.0:
        raise C60ExecutionError("rebalance_deadband_invalid")
    if not math.isfinite(cost_bps) or not 0.0 <= cost_bps < 5_000.0:
        raise C60ExecutionError("fee_rate_invalid")
    first = next((t for t, d in enumerate(axis.dates) if d >= start), None)
    if first is None or first < 1 + delay:
        raise C60ExecutionError("evaluation_start_invalid")
    btc_names = [a for a in assets.values() if a.symbol == "BTCUSDT"]
    if len(btc_names) != 1:
        raise C60ExecutionError("one_continuous_btc_asset_required")
    btc = btc_names[0]
    weights: dict[str, float] = {}
    records = []
    for t in range(first, len(axis.dates)):
        day = axis.dates[t]
        overnight_ratios, overnight_missing = {}, []
        for k in weights:
            asset = assets[k]
            opn = _open_price(opens, asset, day)
            if opn is None or not asset.has(t - 1):
                overnight_ratios[k] = 0.0
                overnight_missing.append(k)
            else:
                overnight_ratios[k] = opn / asset.close(t - 1)
        overnight_writeoff = sum(weights[k] for k in overnight_missing)
        overnight, pre_weights = _mark(weights, overnight_ratios)
        signal = t - 1 - delay
        requested = dict(targets.get(signal, {}))
        _validate_weights(requested)
        if any(k not in assets for k in requested):
            raise C60ExecutionError("target_asset_unknown")
        no_fills, canceled, target = [], {}, {}
        for k, requested_weight in requested.items():
            asset = assets[k]
            opn = _open_price(opens, asset, day)
            if opn is None or not asset.has(t - 1):
                no_fills.append(k)
                continue
            weight = requested_weight
            if cancel_stale and delay == 1 and not _raw_gate(asset, btc, t - 1):
                weight = min(weight, pre_weights.get(k, 0.0))
                if weight < requested_weight:
                    canceled[k] = requested_weight - weight
            if weight > 0.0:
                target[k] = weight
        _validate_weights(target)
        before_deadband = dict(target)
        suggested_turnover = sum(abs(target.get(k, 0.0) - pre_weights.get(k, 0.0))
                                 for k in set(target) | set(pre_weights))
        suppressed = rebalance_deadband > 0.0 and suggested_turnover <= rebalance_deadband + 1e-12
        if suppressed:
            target = dict(pre_weights)
        fees = solve_cost(pre_weights, target, cost_bps, exact=exact_fees)
        intraday_ratios, intraday_missing = {}, []
        for k in target:
            asset = assets[k]
            if not asset.has(t):
                intraday_ratios[k] = 0.0
                intraday_missing.append(k)
            else:
                intraday_ratios[k] = asset.close(t) / _open_price(opens, asset, day)
        intraday_writeoff = sum(target[k] for k in intraday_missing)
        intraday, weights = _mark(target, intraday_ratios)
        cost = fees["cost_fraction"]
        records.append({"date": day, "return": overnight * (1.0 - cost) * intraday - 1.0,
                        "cash_return": 0.0, "signal_date": axis.dates[signal],
                        "validation_date": axis.dates[t - 1] if cancel_stale and delay == 1 else None,
                        "turnover": fees["turnover"], "requested_turnover": fees["requested_turnover"],
                        "actual_turnover": fees["actual_turnover"],
                        "cost_fraction": cost, "fee_residual": fees["fee_residual"],
                        "cost_fraction_prior_close_nav": overnight * cost,
                        "overnight_factor": overnight, "intraday_factor": intraday,
                        "gross": sum(target.values()), "weights": dict(target),
                        "close_weights": dict(weights), "pretrade_weights": dict(pre_weights),
                        "requested_weights": requested, "nominal_trades": fees["nominal_trades"],
                        "before_deadband_weights": before_deadband,
                        "suggested_turnover": suggested_turnover,
                        "deadband_suppressed": suppressed,
                        "post_fee_cash": fees["post_fee_cash"], "canceled_buys": canceled,
                        "no_fills": no_fills,
                        "missing_marks": overnight_missing + intraday_missing,
                        "overnight_missing_marks": overnight_missing,
                        "intraday_missing_marks": intraday_missing,
                        "overnight_writeoff_weight": overnight_writeoff,
                        "intraday_writeoff_weight": intraday_writeoff,
                        "writeoff_weight": overnight_writeoff + overnight * (1.0 - cost) * intraday_writeoff,
                        "exact_fees": exact_fees})
    return {"records": records, "research_only": True, "orders_authorized": False,
            "execution": "daily next-open proxy; completed-close validation; no certified market fill"}


def _parse_archive(raw: bytes) -> tuple[dict[str, float], dict[str, tuple[float, float]]]:
    opens, rows = {}, {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8")
            parsed = pit.parse_kline_csv(text)
            rows.update(parsed)
            for line in text.splitlines():
                cols = line.split(",")
                if len(cols) < 8 or not cols[0].strip().isdigit():
                    continue
                stamp = int(cols[0])
                if stamp > 10**14:
                    stamp //= 1000
                day = dt.datetime.fromtimestamp(stamp / 1000, dt.timezone.utc).date().isoformat()
                if day not in parsed:
                    continue
                value = float(cols[1])
                if not math.isfinite(value) or value <= 0.0:
                    raise C60ExecutionError(f"archive_open_invalid:{day}")
                if day in opens and opens[day] != value:
                    raise C60ExecutionError("archive_duplicate_open_conflict")
                opens[day] = value
    return opens, rows


def _get_archive(url: str) -> bytes:
    # Some existing archive symbols use Unicode names; encode only the URL, not
    # their stored identities or immutable archive filenames.
    url = urllib.parse.quote(url, safe=":/?=&%")
    request = urllib.request.Request(url, headers={"User-Agent": "qount-public-research"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _check_acquisition_storage(out: Path) -> None:
    root = Path("/mnt/e/qount_data/qount/artifacts/dual_engine")
    if sys.platform != "linux" or not os.path.ismount("/mnt/e") or not out.resolve().is_relative_to(root):
        raise C60ExecutionError("wsl_mounted_research_storage_required")


def acquire_opens(pit_cache: Path, out: Path, *, symbols: Sequence[str] | None = None,
                  workers: int = 8, months_by_symbol: Mapping[str, Sequence[str]] | None = None) -> dict:
    """Acquire immutable official archives bound to the old cache ZIP hashes.

    No download starts merely by importing the module.  A failed acquisition
    retains partial evidence but never publishes a completed manifest.  A partial
    directory can resume only after every existing ZIP matches its original
    cache hash.  Sparse requested months do not change source or row parity.
    """
    _check_acquisition_storage(out)
    if not isinstance(workers, int) or not 1 <= workers <= 16:
        raise C60ExecutionError("acquisition_workers_invalid")
    paths = sorted(Path(pit_cache).glob("*.json"))
    bodies, cache_hashes = {}, {}
    for path in paths:
        raw_cache = path.read_bytes()
        bodies[path.stem] = json.loads(raw_cache)
        cache_hashes[path.stem] = hashlib.sha256(raw_cache).hexdigest()
    if symbols is None:
        if months_by_symbol is not None:
            symbols = sorted(months_by_symbol)
        else:
            raw = {s: body["rows"] for s, body in bodies.items() if body["rows"]}
            axis, assets = build_crypto_assets(raw)
            targets, _ = warm_targets(axis, assets)
            symbols = sorted({assets[k].symbol for target in targets.values() for k in target} | {"BTCUSDT"})
    selected = sorted(set(symbols))
    if not selected or any(s not in bodies or not bodies[s].get("rows") for s in selected):
        raise C60ExecutionError("selected_cache_symbol_missing")
    if months_by_symbol is not None and set(months_by_symbol) != set(selected):
        raise C60ExecutionError("requested_month_symbols_mismatch")
    requested_months = {s: sorted(set(months_by_symbol[s])) if months_by_symbol is not None
                        else sorted(bodies[s]["files"]) for s in selected}
    if any(not months or any(m not in bodies[s]["files"] for m in months)
           for s, months in requested_months.items()):
        raise C60ExecutionError("requested_month_not_in_original_cache")
    jobs = [(s, m, bodies[s]["files"][m]) for s in selected for m in requested_months[s]]
    if not jobs:
        raise C60ExecutionError("cache_archive_hashes_missing")
    if (out / "manifest.json").exists():
        raise C60ExecutionError("completed_acquisition_is_immutable")
    out.mkdir(parents=True, exist_ok=True)
    (out / "archives").mkdir(exist_ok=True)
    archive_hashes = {}
    existing_sources = set()
    all_opens = {s: {} for s in selected}
    all_rows = {s: {} for s in selected}
    actual_months = {s: set(requested_months[s]) for s in selected}
    names = {f"{s}-1d-{m}.zip": (s, m, digest)
             for s, body in bodies.items() for m, digest in body.get("files", {}).items()}
    for path in sorted((out / "archives").iterdir()):
        if not path.is_file() or path.name not in names:
            raise C60ExecutionError(f"unrecognized_partial_archive:{path.name}")
        symbol, month, expected = names[path.name]
        raw_archive = path.read_bytes()
        digest = hashlib.sha256(raw_archive).hexdigest()
        if digest != expected:
            raise C60ExecutionError(f"original_archive_hash_mismatch:{symbol}:{month}")
        values, rows = _parse_archive(raw_archive)
        expected_dates = {d for d in bodies[symbol]["rows"] if d[:7] == month}
        if set(rows) != expected_dates or set(values) != expected_dates:
            raise C60ExecutionError(f"original_cache_calendar_mismatch:{symbol}:{month}")
        for day, row in rows.items():
            if list(row) != bodies[symbol]["rows"][day]:
                raise C60ExecutionError(f"original_cache_row_mismatch:{symbol}:{day}")
        all_opens.setdefault(symbol, {}).update(values)
        all_rows.setdefault(symbol, {}).update(rows)
        actual_months.setdefault(symbol, set()).add(month)
        archive_hashes[f"archives/{path.name}"] = digest
        existing_sources.add(symbol)

    def acquire(job: tuple[str, str, str]) -> tuple[str, str, dict, dict, str, bool]:
        symbol, month, expected = job
        archive_path = out / "archives" / f"{symbol}-1d-{month}.zip"
        reused = archive_path.exists()
        raw = archive_path.read_bytes() if reused else _get_archive(pit.ARCHIVE.format(symbol=symbol, month=month))
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected:
            raise C60ExecutionError(f"original_archive_hash_mismatch:{symbol}:{month}")
        opens, parsed = _parse_archive(raw)
        expected_dates = {d for d in bodies[symbol]["rows"] if d[:7] == month}
        if set(parsed) != expected_dates or set(opens) != expected_dates:
            raise C60ExecutionError(f"original_cache_calendar_mismatch:{symbol}:{month}")
        for day, row in parsed.items():
            if day not in bodies[symbol]["rows"] or list(row) != bodies[symbol]["rows"][day]:
                raise C60ExecutionError(f"original_cache_row_mismatch:{symbol}:{day}")
        if not reused:
            with archive_path.open("xb") as stream:
                stream.write(raw)
        return symbol, month, opens, parsed, digest, reused

    reused_count = downloaded_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for symbol, month, values, rows, digest, reused in executor.map(acquire, jobs):
            for day, value in values.items():
                if day in all_opens[symbol] and all_opens[symbol][day] != value:
                    raise C60ExecutionError("archive_overlap_conflict")
                all_opens[symbol][day] = value
            all_rows[symbol].update(rows)
            archive_hashes[f"archives/{symbol}-1d-{month}.zip"] = digest
            reused_count += int(reused)
            downloaded_count += int(not reused)
    for symbol, months in actual_months.items():
        expected_dates = {d for d in bodies[symbol]["rows"] if d[:7] in months}
        if set(all_rows[symbol]) != expected_dates or set(all_opens[symbol]) != expected_dates:
            raise C60ExecutionError(f"original_cache_calendar_mismatch:{symbol}")
    for symbol in set(selected) | existing_sources:
        if hashlib.sha256((Path(pit_cache) / (symbol + ".json")).read_bytes()).hexdigest() != cache_hashes[symbol]:
            raise C60ExecutionError(f"cache_changed_during_acquisition:{symbol}")
    current_archives = {f"archives/{path.name}" for path in (out / "archives").iterdir() if path.is_file()}
    if current_archives != set(archive_hashes):
        raise C60ExecutionError("partial_archive_set_changed_during_acquisition")
    for relative, digest in archive_hashes.items():
        if hashlib.sha256((out / relative).read_bytes()).hexdigest() != digest:
            raise C60ExecutionError(f"archive_changed_during_acquisition:{relative}")
    opens_path = out / "opens.json"
    serialized = (json.dumps(all_opens, sort_keys=True, allow_nan=False) + "\n").encode()
    if opens_path.exists():
        if opens_path.read_bytes() != serialized:
            raise C60ExecutionError("partial_opens_are_immutable_and_do_not_match_request")
    else:
        with opens_path.open("xb") as stream:
            stream.write(serialized)
    manifest = {"research_only": True, "orders_authorized": False,
                "source": "official Binance monthly spot 1d archives; original ZIP SHA256 unchanged",
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "symbols": sorted(all_opens), "requested_symbols": selected,
                "archive_symbols": sorted(all_opens), "archive_count": len(archive_hashes), "workers": workers,
                "requested_months": requested_months,
                "requested_months_by_symbol": requested_months, "requested_archive_count": len(jobs),
                "reused_requested_archive_count": reused_count, "downloaded_archive_count": downloaded_count,
                "cache_sha256": {s + ".json": cache_hashes[s] for s in sorted(set(selected) | existing_sources)},
                "files": archive_hashes | {"opens.json": hashlib.sha256(opens_path.read_bytes()).hexdigest()}}
    with (out / "manifest.json").open("x") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return manifest
