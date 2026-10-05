"""Independent file, cash and unit verification for offline execution studies.

The oracle does not import any replay, weight-growth or fee-solver function.
Equity prices supplied here represent adjusted return units, not brokerage
shares or cash dividends. Crypto cash earns zero in the study contract.
"""

from __future__ import annotations

import hashlib
import datetime as dt
import io
import json
import math
import zipfile
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo


class ExecutionVerificationError(ValueError):
    pass


def _fail(message: str) -> None:
    raise ExecutionVerificationError(message)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(f"nonfinite_or_non_numeric:{label}")
    return float(value)


def _check(actual: object, expected: float, label: str, errors: dict, *, atol: float = 2e-10) -> None:
    value = _number(actual, label)
    error = abs(value - expected)
    errors[label.split(':', 1)[0]] = max(errors.get(label.split(':', 1)[0], 0.0), error)
    if error > atol * max(1.0, abs(expected)):
        _fail(f"identity_mismatch:{label}:{value}:{expected}")


def _check_weights(actual: Mapping[str, float], expected: Mapping[str, float], label: str,
                   errors: dict) -> None:
    if not isinstance(actual, Mapping):
        _fail(f"weights_not_mapping:{label}")
    for name in set(actual) | set(expected):
        _check(actual.get(name, 0.0), expected.get(name, 0.0), f"{label}:{name}", errors)


def equity_prices(panel: object) -> dict:
    """Rearrange supplied adjusted-unit prices without replay calculations."""
    dates = tuple(panel.dates)
    return {"dates": dates,
            "opens": {s: dict(zip(dates, values, strict=True)) for s, values in panel.total_opens.items()},
            "closes": {s: dict(zip(dates, values, strict=True)) for s, values in panel.total_closes.items()},
            "cash_asset": "BIL"}


def crypto_prices(axis: object, assets: Mapping, opens: Mapping) -> dict:
    """Map source symbols to immutable asset IDs; absent prices remain absent."""
    dates = tuple(axis.dates)
    return {"dates": dates,
            "opens": {k: dict(opens.get(a.symbol, {})) for k, a in assets.items()},
            "closes": {k: dict(zip(dates[a.start:a.start + len(a.closes)], a.closes, strict=True))
                       for k, a in assets.items()},
            "cash_asset": None}


def _price(prices: Mapping, kind: str, symbol: str, day: str) -> float | None:
    value = prices[kind].get(symbol, {}).get(day)
    if value is None:
        return None
    result = _number(value, f"{kind}:{symbol}:{day}")
    if result <= 0.0:
        _fail(f"nonpositive_price:{kind}:{symbol}:{day}")
    return result


def independent_metrics(returns: Sequence[float], annual: int,
                        cash_returns: Sequence[float] | None = None) -> dict:
    """Calculate metrics directly, without importing the research summary."""
    values = [_number(value, "return") for value in returns]
    if not values or annual <= 0 or any(value <= -1.0 for value in values):
        _fail("invalid_metric_series")
    cash = list(cash_returns) if cash_returns is not None else [0.0] * len(values)
    if len(cash) != len(values):
        _fail("cash_series_length_mismatch")
    excess = [r - _number(c, "cash_return") for r, c in zip(values, cash, strict=True)]

    def annual_vol(series: Sequence[float]) -> float:
        mean = math.fsum(series) / len(series)
        variance = math.fsum((r - mean) ** 2 for r in series) / (len(series) - 1) if len(series) > 1 else 0.0
        return math.sqrt(variance * annual)

    nav = peak = 1.0
    drawdown = 0.0
    for value in values:
        nav *= 1.0 + value
        peak = max(peak, nav)
        drawdown = min(drawdown, nav / peak - 1.0)
    vol, excess_vol = annual_vol(values), annual_vol(excess)
    return {"cagr": math.expm1(math.fsum(math.log1p(r) for r in values) * annual / len(values)),
            "sharpe": math.fsum(values) / len(values) * annual / vol if vol else 0.0,
            "cash_excess_sharpe": math.fsum(excess) / len(excess) * annual / excess_vol if excess_vol else 0.0,
            "max_drawdown": drawdown, "annual_volatility": vol, "total_return": nav - 1.0}


def verify_ledger(run: Mapping, prices: Mapping, annual: int, *, cost_bps: float | None = None) -> dict:
    """Rebuild a fresh-cash daily close-marked account using asset units.

    Prices have ``dates``, ``opens[asset][date]`` and ``closes[asset][date]``.
    Each record supplies pretrade and post-open weights, a fee ratio and close
    weights. Fees are tested against actual dollar trades for exact accounts;
    the explicitly labelled approximation is tested against its requested L1.
    Unavailable marks remove the corresponding units permanently. Nothing in
    this function decides which strategy target should have been requested.
    """
    records = run.get("records")
    if not isinstance(records, list) or not records:
        _fail("ledger_empty_or_not_list")
    dates = tuple(prices["dates"])
    if len(set(dates)) != len(dates) or tuple(sorted(dates)) != dates:
        _fail("price_axis_invalid")
    positions = {day: i for i, day in enumerate(dates)}
    if cost_bps is not None and not 0.0 <= _number(cost_bps, "cost_bps") < 10_000.0:
        _fail("fee_rate_invalid")
    rate = cost_bps / 10_000.0 if cost_bps is not None else None
    units: dict[str, float] = {}
    cash = previous_nav = 1.0
    previous_close_weights: dict[str, float] = {}
    previous_index: int | None = None
    errors: dict[str, float] = {}
    returns, cash_returns, turnovers, costs = [], [], [], []
    actual_fee_residual_max = 0.0
    for record in records:
        day = record["date"]
        if day not in positions or (previous_index is not None and positions[day] != previous_index + 1):
            _fail(f"ledger_axis_gap_or_unknown:{day}")
        index = positions[day]
        previous_day = dates[index - 1] if index > 0 else None
        pre_values, overnight_missing = {}, []
        for symbol, count in units.items():
            opn = _price(prices, "opens", symbol, day)
            prior_close = _price(prices, "closes", symbol, previous_day) if previous_day is not None else None
            if opn is None or prior_close is None:
                pre_values[symbol] = 0.0
                overnight_missing.append(symbol)
            else:
                pre_values[symbol] = count * opn
        pre_nav = cash + math.fsum(pre_values.values())
        if pre_nav <= 0.0:
            _fail(f"account_bankrupt_at_open:{day}")
        pre_weights = {s: value / pre_nav for s, value in pre_values.items() if value > 0.0}
        supplied_pre = record.get("pre_trade_weights", record.get("pretrade_weights"))
        if supplied_pre is None:
            _fail(f"pretrade_weights_missing:{day}")
        _check_weights(supplied_pre, pre_weights, "pretrade_weights", errors)
        post_weights = record.get("post_open_weights", record.get("posttrade_weights", record.get("weights")))
        if not isinstance(post_weights, Mapping):
            _fail(f"posttrade_weights_missing:{day}")
        if any(_number(w, "post_weight") < 0.0 for w in post_weights.values()) or sum(post_weights.values()) > 1.0 + 1e-12:
            _fail(f"posttrade_weights_invalid:{day}")
        cost = _number(record["cost_fraction"], "cost_fraction")
        if not 0.0 <= cost < 1.0:
            _fail(f"fee_exhausts_nav:{day}")
        remaining = 1.0 - cost
        if "nav_after_fee_ratio" in record:
            _check(record["nav_after_fee_ratio"], remaining, "nav_after_fee_ratio", errors)
        post_nav = pre_nav * remaining
        post_values = {s: post_nav * w for s, w in post_weights.items() if w > 0.0}
        trades = {s: post_values.get(s, 0.0) - pre_values.get(s, 0.0) for s in set(post_values) | set(pre_values)}
        actual_turnover = math.fsum(abs(value) for value in trades.values()) / pre_nav
        requested_turnover = math.fsum(abs(post_weights.get(s, 0.0) - pre_weights.get(s, 0.0))
                                       for s in set(post_weights) | set(pre_weights))
        exact = record.get("exact_fees", run.get("fee_model") != "legacy_approximation")
        if not isinstance(exact, bool):
            _fail(f"fee_model_not_boolean:{day}")
        turnover = actual_turnover if exact else requested_turnover
        _check(record["turnover"], turnover, "turnover", errors)
        if "actual_turnover" in record:
            _check(record["actual_turnover"], actual_turnover, "actual_turnover", errors)
        if rate is not None:
            _check(cost, rate * turnover, "fee_identity", errors)
            actual_fee_residual_max = max(actual_fee_residual_max, abs(cost - rate * actual_turnover))
            if "fee_residual" in record:
                _check(record["fee_residual"], cost - rate * actual_turnover, "fee_residual", errors)
        fee_dollars = pre_nav * cost
        after_cash = cash - math.fsum(trades.values()) - fee_dollars
        expected_cash = post_nav * (1.0 - math.fsum(post_weights.values()))
        _check(after_cash, expected_cash, "self_financing_cash", errors)
        if after_cash < -2e-10 * max(1.0, post_nav):
            _fail(f"cash_negative:{day}")
        if "nominal_trades" in record:
            _check_weights(record["nominal_trades"], {s: v / pre_nav for s, v in trades.items()},
                           "nominal_trades", errors)
        if "post_fee_cash" in record:
            _check(record["post_fee_cash"], after_cash / pre_nav, "post_fee_cash", errors)
        if "overnight_factor" in record:
            _check(record["overnight_factor"], pre_nav / previous_nav, "overnight_factor", errors)
        if "cost_fraction_prior_close_nav" in record:
            _check(record["cost_fraction_prior_close_nav"], fee_dollars / previous_nav,
                   "cost_fraction_prior_close_nav", errors)
        next_units, close_values, intraday_missing = {}, {}, []
        for symbol, value in post_values.items():
            opn = _price(prices, "opens", symbol, day)
            if opn is None:
                _fail(f"positive_position_without_open:{symbol}:{day}")
            count = value / opn
            close = _price(prices, "closes", symbol, day)
            if close is None:
                close_values[symbol] = 0.0
                intraday_missing.append(symbol)
            else:
                close_values[symbol] = count * close
                next_units[symbol] = count
        close_nav = after_cash + math.fsum(close_values.values())
        if close_nav <= 0.0:
            _fail(f"account_bankrupt_at_close:{day}")
        close_weights = {s: value / close_nav for s, value in close_values.items() if value > 0.0}
        supplied_close = record.get("close_weights", record.get("weights"))
        _check_weights(supplied_close, close_weights, "close_weights", errors)
        expected_return = close_nav / previous_nav - 1.0
        _check(record["return"], expected_return, "return", errors)
        if "intraday_factor" in record:
            _check(record["intraday_factor"], close_nav / post_nav, "intraday_factor", errors)
        for key, missing in (("overnight_missing_marks", overnight_missing),
                             ("intraday_missing_marks", intraday_missing)):
            if key in record and sorted(record[key]) != sorted(missing):
                _fail(f"missing_marks_mismatch:{key}:{day}")
        if "missing_marks" in record and sorted(record["missing_marks"]) != sorted(overnight_missing + intraday_missing):
            _fail(f"missing_marks_mismatch:{day}")
        if "writeoff_weight" in record:
            overnight_loss = math.fsum(previous_close_weights.get(s, 0.0) for s in overnight_missing)
            intraday_loss = math.fsum(post_weights.get(s, 0.0) for s in intraday_missing)
            writeoff = overnight_loss + post_nav / previous_nav * intraday_loss
            _check(record["writeoff_weight"], writeoff, "writeoff_weight", errors)
            if "overnight_writeoff_weight" in record:
                _check(record["overnight_writeoff_weight"], overnight_loss, "overnight_writeoff_weight", errors)
            if "intraday_writeoff_weight" in record:
                _check(record["intraday_writeoff_weight"], intraday_loss, "intraday_writeoff_weight", errors)
        cash_asset = prices.get("cash_asset")
        expected_cash_return = 0.0
        if cash_asset is not None:
            prior = _price(prices, "closes", cash_asset, previous_day) if previous_day is not None else None
            current = _price(prices, "closes", cash_asset, day)
            if prior is None or current is None:
                _fail(f"cash_return_reference_missing:{day}")
            expected_cash_return = current / prior - 1.0
        _check(record.get("cash_return", 0.0), expected_cash_return, "cash_return", errors)
        returns.append(expected_return)
        cash_returns.append(expected_cash_return)
        turnovers.append(turnover)
        costs.append(cost)
        cash, units, previous_nav = max(0.0, after_cash), next_units, close_nav
        previous_close_weights, previous_index = close_weights, index
    years = len(records) / annual
    return {"verified": True, "first": records[0]["date"], "last": records[-1]["date"],
            "bars": len(records), "final_nav": previous_nav,
            **independent_metrics(returns, annual, cash_returns),
            "annual_turnover": math.fsum(turnovers) / years,
            "annual_cost_fraction": math.fsum(costs) / years,
            "max_identity_errors": errors, "max_actual_fee_residual": actual_fee_residual_max,
            "oracle": "independent cash and asset units; no replay, growth or fee helper imports"}


def verify_bound_files(root: Path, expected: Mapping[str, str], *, exact_files: bool = False,
                       ignored: Sequence[str] = ()) -> dict:
    """Check each declared SHA256 and optionally reject all undeclared files."""
    root = Path(root).resolve()
    for name, digest in expected.items():
        relative = Path(name)
        path = root / relative
        if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                or not path.resolve().is_relative_to(root) or not path.is_file()):
            _fail(f"manifest_path_invalid_or_missing:{name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            _fail(f"manifest_hash_mismatch:{name}")
    if exact_files:
        actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() or p.is_symlink()}
        actual -= set(ignored)
        if actual != set(expected):
            _fail(f"manifest_fileset_mismatch:missing={sorted(set(expected)-actual)}:extra={sorted(actual-set(expected))}")
    return {"verified": True, "files": len(expected), "exact_fileset": exact_files}


def verify_manifest(root: Path, *, manifest_name: str = "manifest.json") -> dict:
    root = Path(root)
    manifest = json.loads((root / manifest_name).read_text())
    result = verify_bound_files(root, manifest["files"], exact_files=True, ignored=(manifest_name,))
    return result | {"manifest_sha256": hashlib.sha256((root / manifest_name).read_bytes()).hexdigest()}


def _equity_source_prices(root: Path, contract: Mapping) -> dict:
    """Independently interpret the frozen Yahoo adjusted-unit convention."""
    files = json.loads((root / "manifest.json").read_text())["files"]
    rows = {}
    settings = contract["g20"]
    for name in files:
        body = json.loads((root / name).read_text())["chart"]["result"][0]
        symbol = body["meta"]["symbol"]
        if name != f"{symbol}.source.json" or symbol in rows:
            _fail("equity_source_symbol_mismatch")
        quote = body["indicators"]["quote"][0]
        adjusted = body["indicators"]["adjclose"][0]["adjclose"]
        series = {}
        for i, stamp in enumerate(body["timestamp"]):
            day = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
            if not settings["data_start"] <= day <= settings["evaluation_end"]:
                continue
            close = _number(quote["close"][i], "equity_close")
            adj = _number(adjusted[i], "equity_adjusted_close")
            opn = _number(quote["open"][i], "equity_open")
            if min(close, adj, opn) <= 0.0 or day in series:
                _fail("equity_source_price_or_date_invalid")
            series[day] = (opn * adj / close, adj)
        rows[symbol] = series
    if "SPY" not in rows or "BIL" not in rows:
        _fail("equity_reference_missing")
    dates = tuple(sorted(rows["SPY"]))
    if any(set(series) != set(dates) for series in rows.values()):
        _fail("equity_calendar_gap")
    return {"dates": dates, "cash_asset": "BIL",
            "opens": {s: {d: pair[0] for d, pair in series.items()} for s, series in rows.items()},
            "closes": {s: {d: pair[1] for d, pair in series.items()} for s, series in rows.items()}}


def _crypto_source_prices(cache: Mapping, opens: Mapping, end: str) -> dict:
    rows = {symbol: {d: pair for d, pair in body["rows"].items() if d <= end}
            for symbol, body in cache.items() if body["rows"]}
    first = min(min(series) for series in rows.values())
    start_date, end_date = dt.date.fromisoformat(first), dt.date.fromisoformat(end)
    dates = tuple((start_date + dt.timedelta(days=i)).isoformat()
                  for i in range((end_date - start_date).days + 1))
    asset_closes, asset_opens = {}, {}
    for symbol, series in rows.items():
        previous = None
        asset_id = None
        for day in sorted(series):
            if previous is None or (dt.date.fromisoformat(day) - dt.date.fromisoformat(previous)).days != 1:
                asset_id = f"{symbol}@{day}"
                asset_closes[asset_id] = {}
                asset_opens[asset_id] = dict(opens.get(symbol, {}))
            asset_closes[asset_id][day] = _number(series[day][0], "cache_close")
            previous = day
    return {"dates": dates, "opens": asset_opens, "closes": asset_closes, "cash_asset": None}


def _verify_archive_bridge(root: Path, cache: Mapping, manifest: Mapping, *, needed_months: Mapping | None = None) -> dict:
    """Check official ZIP prices against both old cache rows and new opens."""
    opens = json.loads((root / "opens.json").read_text())
    selected = manifest["symbols"]
    if sorted(opens) != sorted(selected) or len(set(selected)) != len(selected):
        _fail("archive_bridge_symbol_set_mismatch")
    archive_names = set(manifest["files"]) - {"opens.json"}
    requested = manifest.get("requested_months", manifest.get("requested_months_by_symbol"))
    if requested is None:
        requested = {symbol: sorted(cache[symbol]["files"]) for symbol in selected}
    requested = {s: sorted(set(months)) for s, months in requested.items()}
    if "requested_months" in manifest and "requested_months_by_symbol" in manifest:
        alias = {s: sorted(set(months)) for s, months in manifest["requested_months_by_symbol"].items()}
        if requested != alias:
            _fail("archive_bridge_requested_month_alias_mismatch")
    if needed_months is not None and requested != {s: sorted(set(months)) for s, months in needed_months.items()}:
        _fail("archive_bridge_requested_requirement_mismatch")
    expected_names = {f"archives/{symbol}-1d-{month}.zip" for symbol, months in requested.items() for month in months}
    if not expected_names.issubset(archive_names):
        _fail("archive_bridge_requested_zip_missing")
    months_present: dict[str, list[str]] = {}
    for name in archive_names:
        path = Path(name)
        if path.parent.as_posix() != "archives" or not path.name.endswith(".zip") or "-1d-" not in path.name:
            _fail(f"archive_bridge_archive_name_invalid:{name}")
        symbol, month = path.name[:-4].rsplit("-1d-", 1)
        if symbol not in cache or month not in cache[symbol]["files"]:
            _fail(f"archive_bridge_archive_not_in_original_cache:{name}")
        months_present.setdefault(symbol, []).append(month)
    if "archive_symbols" in manifest and sorted(manifest["archive_symbols"]) != sorted(selected):
        _fail("archive_bridge_archive_symbols_mismatch")
    row_count = 0
    for symbol, actual_months in months_present.items():
        all_rows, all_opens = {}, {}
        for month in sorted(actual_months):
            digest = cache[symbol]["files"][month]
            name = f"archives/{symbol}-1d-{month}.zip"
            if manifest["files"][name] != digest:
                _fail(f"archive_bridge_old_zip_hash_mismatch:{name}")
            with zipfile.ZipFile(io.BytesIO((root / name).read_bytes())) as archive:
                for member in archive.namelist():
                    for line in archive.read(member).decode("utf-8").splitlines():
                        columns = line.split(",")
                        if len(columns) < 8 or not columns[0].strip().isdigit():
                            continue
                        stamp = int(columns[0])
                        if stamp > 10**14:
                            stamp //= 1000
                        day = dt.datetime.fromtimestamp(stamp / 1000, dt.timezone.utc).date().isoformat()
                        close, quote = float(columns[4]), float(columns[7])
                        if not math.isfinite(close) or close <= 0.0 or not math.isfinite(quote):
                            continue
                        opn = _number(float(columns[1]), "archive_open")
                        if opn <= 0.0:
                            _fail(f"archive_bridge_open_invalid:{symbol}:{day}")
                        row = [close, max(0.0, quote)]
                        if day in all_rows and (all_rows[day] != row or all_opens[day] != opn):
                            _fail(f"archive_bridge_duplicate_conflict:{symbol}:{day}")
                        all_rows[day], all_opens[day] = row, opn
        expected_rows = {d: row for d, row in cache[symbol]["rows"].items() if d[:7] in actual_months}
        if all_rows != expected_rows:
            _fail(f"archive_bridge_values_or_calendar_mismatch:{symbol}")
        supplied_opens = opens.get(symbol, {})
        if supplied_opens != all_opens:
            _fail(f"archive_bridge_open_value_or_calendar_mismatch:{symbol}")
        required_dates = {d for d in cache[symbol]["rows"] if d[:7] in requested.get(symbol, [])}
        if not required_dates.issubset(supplied_opens):
            _fail(f"archive_bridge_requested_open_missing:{symbol}")
        # Unrequested partial-download surplus remains in both ZIPs and opens.
        row_count += len(all_rows)
    if any(symbol not in months_present and opens[symbol] for symbol in selected):
        _fail("archive_bridge_open_symbol_without_zip")
    return {"verified": True, "symbols": len(selected), "archives": len(archive_names),
            "requested_archives": len(expected_names),
            "rows": row_count, "opens": opens}


def _required_open_months(out: Path, prices: Mapping, cache: Mapping, contract: Mapping) -> dict:
    dates = prices["dates"]
    start, end = contract["c60"]["start"], contract["c60"]["end"]
    needed = {"BTCUSDT": {day[:7] for day in dates if start <= day <= end}}
    for rule in ("pit", "confirmation", "btc_daily", "btc_monthly"):
        targets = json.loads((out / f"c60-{rule}-warm-targets.json").read_text())
        for signal, weights in targets.items():
            for delay in contract["c60"]["delays"]:
                execution = int(signal) + 1 + delay
                if execution >= len(dates) or dates[execution] < start or dates[execution] > end:
                    continue
                for asset, weight in weights.items():
                    if weight <= 0.0:
                        continue
                    if asset not in prices["closes"]:
                        _fail(f"warm_target_asset_unknown:{asset}")
                    symbol = asset.rsplit("@", 1)[0]
                    for t in (execution, execution + 1):
                        if t < len(dates) and dates[t] <= end:
                            needed.setdefault(symbol, set()).add(dates[t][:7])
    return {symbol: sorted(months & set(cache[symbol]["files"])) for symbol, months in needed.items()}


def _ledger_metrics(run: Mapping, annual: int) -> dict:
    rows = run["records"]
    returns = [r["return"] for r in rows]
    cash = [r.get("cash_return", 0.0) for r in rows]
    result = independent_metrics(returns, annual, cash)
    years = len(rows) / annual
    return result | {"annual_turnover": math.fsum(r["turnover"] for r in rows) / years,
                     "annual_cost_fraction": math.fsum(r["cost_fraction"] for r in rows) / years,
                     "first": rows[0]["date"], "last": rows[-1]["date"], "bars": len(rows)}


def verify_study(out: Path, original_root: Path, open_root: Path, equity_root: Path,
                 pit_cache: Path, original_contract: Path | Mapping) -> dict:
    """Read-only verification; callers save this receipt beside frozen output.

    All 64 declared ledgers receive independent metric checks. The 40 new
    open-execution/fee-sensitivity ledgers additionally receive the cash/unit
    oracle. The 24 original-rule diagnoses retain their original schema and
    twelve declared primary ledgers are checked against their original curves.
    """
    out, original_root, open_root, equity_root, pit_cache = map(Path, (out, original_root, open_root, equity_root, pit_cache))
    output_integrity = verify_manifest(out)
    original_integrity = verify_manifest(original_root)
    open_integrity = verify_manifest(open_root)
    equity_integrity = verify_manifest(equity_root)
    results = json.loads((out / "results.json").read_text())
    contract = json.loads((out / "preregistration.json").read_text())
    audit = json.loads((out / "input-audit.json").read_text())
    old_audit = json.loads((original_root / "input-audit.json").read_text())
    if original_integrity["manifest_sha256"] != contract["original_manifest_sha256"]:
        _fail("original_manifest_binding_mismatch")
    if audit["original_result_manifest_sha256"] != original_integrity["manifest_sha256"]:
        _fail("input_original_manifest_binding_mismatch")
    if audit["open_manifest_sha256"] != open_integrity["manifest_sha256"]:
        _fail("input_open_manifest_binding_mismatch")
    equity_manifest = json.loads((equity_root / "manifest.json").read_text())
    open_manifest = json.loads((open_root / "manifest.json").read_text())
    if (equity_manifest["files"] != old_audit["g20"]["files"]
            or audit["g20"]["files"] != equity_manifest["files"]
            or audit["open_files_sha256"] != open_manifest["files"]):
        _fail("input_file_binding_mismatch")
    if equity_integrity["manifest_sha256"] != old_audit["g20"]["source_manifest_sha256"]:
        _fail("equity_source_manifest_binding_mismatch")
    if audit["pit_cache_sha256"] != old_audit["pit_cache_sha256"]:
        _fail("cache_old_binding_mismatch")
    cache_integrity = verify_bound_files(pit_cache, audit["pit_cache_sha256"], exact_files=True)
    cache = {Path(name).stem: json.loads((pit_cache / name).read_text()) for name in audit["pit_cache_sha256"]}
    for name, digest in open_manifest["cache_sha256"].items():
        if audit["pit_cache_sha256"].get(name) != digest:
            _fail(f"open_cache_binding_mismatch:{name}")
    if isinstance(original_contract, Mapping):
        old_contract = original_contract
    else:
        original_contract = Path(original_contract)
        if hashlib.sha256(original_contract.read_bytes()).hexdigest() != old_audit["contract_sha256"]:
            _fail("original_contract_binding_mismatch")
        old_contract = json.loads(original_contract.read_text())
    if results["source_sha256"] != audit["source_sha256"]:
        _fail("source_metadata_binding_mismatch")
    source_integrity = verify_bound_files(out / "source", results["source_sha256"], exact_files=True)
    preliminary_crypto = _crypto_source_prices(cache, {}, contract["c60"]["end"])
    required_months = _required_open_months(out, preliminary_crypto, cache, contract)
    bridge = _verify_archive_bridge(open_root, cache, open_manifest, needed_months=required_months)
    equity = _equity_source_prices(equity_root, old_contract)
    crypto = _crypto_source_prices(cache, bridge.pop("opens"), contract["c60"]["end"])
    expected_summaries = {}
    for group, rules in results["results"].items():
        for rule, cells in rules.items():
            for cell, report in cells.items():
                expected_summaries[f"{group}-{rule}-{cell}"] = report
    for key, report in results["fee_approximation_diagnostic"].items():
        expected_summaries[key] = report["approximate"]
    exposures = results["curve_exposures"]
    exposed = [item["curve"] for item in exposures]
    actual = {p.name[:-len("-ledger.json")] for p in out.glob("*-ledger.json")}
    if (len(set(exposed)) != len(exposed) or set(exposed) != actual or actual != set(expected_summaries)
            or len(exposed) != contract["planned_curve_exposures"]):
        _fail("curve_exposure_fileset_mismatch")
    curve_checks, ledger_runs, metric_errors = {}, {}, {}
    metric_keys = ("cagr", "sharpe", "cash_excess_sharpe", "max_drawdown", "annual_volatility",
                   "total_return", "annual_turnover", "annual_cost_fraction")
    unit_curves = 0
    for key in sorted(actual):
        run = json.loads((out / f"{key}-ledger.json").read_text())
        ledger_runs[key] = run
        annual = 252 if key.startswith(("g20-", "old_g20-")) else 365
        computed = _ledger_metrics(run, annual)
        for name in metric_keys:
            _check(expected_summaries[key][name], computed[name], f"metric_{name}", metric_errors)
        if any(computed[name] != expected_summaries[key][name] for name in ("first", "last", "bars")):
            _fail(f"summary_axis_mismatch:{key}")
        if not key.startswith("old_"):
            cost_bps = int(key.rsplit("-c", 1)[1].split("-", 1)[0])
            oracle = verify_ledger(run, equity if annual == 252 else crypto, annual, cost_bps=cost_bps)
            for name in metric_keys:
                _check(oracle[name], computed[name], f"oracle_metric_{name}", metric_errors)
            curve_checks[key] = oracle
            unit_curves += 1
        else:
            curve_checks[key] = computed | {"verified": True, "oracle": "independent metrics; original ledger schema"}
    original_errors = {}
    for name, declared_error in results["original_return_reproduction"].items():
        if name.startswith("g20-"):
            _, rule, scenario = name.split("-")
            key = f"old_g20-{'absolute' if rule == 'candidate' else rule}-{'c20-d1' if scenario == 'base' else 'c40-d2'}"
        else:
            scenario = name.rsplit("-", 1)[1]
            rule = "btc" if name.startswith("c60-btc-") else ("confirmation" if "-candidate-" in name else "baseline")
            key = f"old_c60-{rule}-{'c25-d0' if scenario == 'base' else 'c50-d1'}"
        original = json.loads((original_root / f"{name}-ledger.json").read_text())["records"]
        reproduced = ledger_runs[key]["records"]
        if [r["date"] for r in original] != [r["date"] for r in reproduced]:
            _fail(f"original_reproduction_axis_mismatch:{name}")
        error = max(abs(a["return"] - b["return"]) for a, b in zip(original, reproduced, strict=True))
        if error > 1e-12:
            _fail(f"original_reproduction_return_mismatch:{name}")
        _check(declared_error, error, "declared_reproduction_error", metric_errors)
        original_errors[name] = error
    for cost in contract["c60"]["cost_bps"]:
        if ledger_runs[f"c60-candidate-c{cost}-d0"] != ledger_runs[f"c60-pit-c{cost}-d0"]:
            _fail("delay0_noop_mismatch")
    if not results["delay0_noop"]:
        _fail("delay0_noop_metadata_false")
    return {"verified": True, "research_only": True, "orders_authorized": False,
            "verification_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "output_integrity": output_integrity, "original_integrity": original_integrity,
            "open_integrity": open_integrity, "equity_integrity": equity_integrity,
            "cache_integrity": cache_integrity, "source_integrity": source_integrity,
            "archive_bridge": bridge, "curves": len(curve_checks), "cash_unit_oracle_curves": unit_curves,
            "original_return_reproduction": original_errors, "delay0_noop": True,
            "max_metric_errors": metric_errors, "curve_checks": curve_checks}
