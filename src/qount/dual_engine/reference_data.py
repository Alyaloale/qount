"""Public SPY/TLT references, separate from paper decisions and accounting."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import re
from typing import Mapping

from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.dual_engine.contracts import PaperProgramSnapshot, _market_bar
from qount.dual_engine.market_data import (
    DualEngineMarketConfig, DualEngineMarketDataError, JsonGetter,
    _NEW_YORK, _number, _public_json_get, _tiingo_daily, _tiingo_daily_bar,
)
from qount.dual_engine.paper import _atomic_json, _broad_market_benchmark, _read_json


REFERENCE_PATH = Path("reference/public-etf.json")
_GUARDS = ("orders_authorized", "private_api_used", "exchange_mutation_attempted")


def validate_reference(value: dict, *, observed_at: str) -> dict:
    expected = {"schema_version", "source", "generated_at", "bars", "adjusted_closes",
                "source_hashes", "reference_hash", "research_only", *_GUARDS}
    if set(value) != expected or value["schema_version"] != 1 or value["source"] != "tiingo_public":
        raise ValueError("public_reference_schema_invalid")
    core = {key: item for key, item in value.items() if key != "reference_hash"}
    if canonical_hash(core) != value["reference_hash"]:
        raise ValueError("public_reference_hash_invalid")
    if value["research_only"] is not True or any(value[key] is not False for key in _GUARDS):
        raise ValueError("public_reference_guards_invalid")
    observed = aware_datetime(observed_at)
    generated = aware_datetime(value["generated_at"])
    if not -5 <= (observed - generated).total_seconds() <= 36 * 3600:
        raise ValueError("public_reference_stale")
    for field in ("bars", "adjusted_closes", "source_hashes"):
        if not isinstance(value[field], dict) or set(value[field]) != {"SPY", "TLT"}:
            raise ValueError("public_reference_symbols_invalid")
    for symbol in ("SPY", "TLT"):
        if not isinstance(value["source_hashes"][symbol], str) or not re.fullmatch(r"[0-9a-f]{64}", value["source_hashes"][symbol]):
            raise ValueError("public_reference_source_invalid")
        rows = value["bars"][symbol]
        prices = value["adjusted_closes"][symbol]
        if not isinstance(rows, list) or not 2 <= len(rows) <= 1000 or not isinstance(prices, list) or len(prices) != len(rows):
            raise ValueError("public_reference_rows_invalid")
        times = []
        for row, price in zip(rows, prices):
            bar = _market_bar(row, name="public_reference_bar")
            stamp = aware_datetime(str(bar["marked_at"]))
            close_at = dt.datetime.combine(stamp.date(), dt.time(16), tzinfo=_NEW_YORK)
            if close_at > generated:
                raise ValueError("public_reference_future_bar")
            times.append(stamp)
            _number(price, name="public_reference_adjusted_close")
        if times != sorted(set(times)) or (generated.date() - times[-1].date()).days > 7:
            raise ValueError("public_reference_coverage_invalid")
    return value


def read_public_reference(root: Path, *, observed_at: str) -> dict:
    path = root / REFERENCE_PATH
    if any(part.is_symlink() for part in (path, *path.parents)) or path.stat().st_size > 1_000_000:
        raise ValueError("public_reference_path_invalid")
    return validate_reference(_read_json(path, name="public_reference"), observed_at=observed_at)


def refresh_public_reference(
    root: Path, config: DualEngineMarketConfig, *, observed_at: str,
    getter: JsonGetter = _public_json_get, environment: Mapping[str, str] | None = None,
) -> dict:
    """Use the existing paper service's own public-data token; never export it."""
    config.validate()
    observed = aware_datetime(observed_at)
    token = (os.environ if environment is None else environment).get(config.tiingo_token_env, "")
    if not token:
        raise DualEngineMarketDataError("paper_tiingo_token_missing")
    bars, adjusted, hashes = {}, {}, {}
    for symbol in ("SPY", "TLT"):
        rows, digest = _tiingo_daily(symbol, start=dt.date(2026, 1, 1),
                                    end=observed.astimezone(_NEW_YORK).date(),
                                    token=token, config=config, getter=getter)
        usable = []
        for row in rows:
            session = dt.date.fromisoformat(str(row["date"])[:10])
            if session < dt.date(2026, 1, 1):
                continue
            if dt.datetime.combine(session, dt.time(16), tzinfo=_NEW_YORK) <= observed:
                usable.append(row)
        bars[symbol] = [_tiingo_daily_bar(row, symbol=symbol) for row in usable]
        adjusted[symbol] = [_number(row.get("adjClose"), name="public_reference_adjusted_close") for row in usable]
        hashes[symbol] = digest
    core = {"schema_version": 1, "source": "tiingo_public", "generated_at": observed.isoformat(),
            "bars": bars, "adjusted_closes": adjusted, "source_hashes": hashes,
            "research_only": True, **dict.fromkeys(_GUARDS, False)}
    value = validate_reference(core | {"reference_hash": canonical_hash(core)}, observed_at=observed_at)
    if any(part.is_symlink() for part in (root / REFERENCE_PATH, *(root / REFERENCE_PATH).parents)):
        raise ValueError("public_reference_path_invalid")
    _atomic_json(root / REFERENCE_PATH, value)
    return value


def with_public_benchmark(snapshot: PaperProgramSnapshot, value: dict) -> PaperProgramSnapshot:
    """Enrich display only; leave the accounting snapshot and audit files untouched."""
    validate_reference(value, observed_at=value["generated_at"])
    cutoff = aware_datetime(snapshot.data_cutoff)
    start = aware_datetime(snapshot.forward_start_at)
    rows = [row for row in value["bars"]["SPY"]
            if start.date() <= aware_datetime(row["marked_at"]).date()
            and dt.datetime.combine(aware_datetime(row["marked_at"]).date(), dt.time(16), tzinfo=_NEW_YORK) <= cutoff]
    if not rows or (cutoff.date() - aware_datetime(rows[-1]["marked_at"]).date()).days > 7:
        return snapshot
    benchmark = _broad_market_benchmark({"SPY": rows}, initial_capital=10000.0,
                                        forward_start_at=snapshot.forward_start_at)
    if not benchmark:
        return snapshot
    charts = {"interval": "1d", "bars_by_symbol": dict(snapshot.market_charts.get("bars_by_symbol", {})) | {"SPY": rows}}
    return PaperProgramSnapshot.create(
        generated_at=snapshot.generated_at, data_cutoff=snapshot.data_cutoff,
        forward_start_at=snapshot.forward_start_at, status=snapshot.status,
        contract_hash=snapshot.contract_hash,
        source_hashes=dict(snapshot.source_hashes) | {"public_reference": value["reference_hash"],
                                                    "accounting_snapshot": snapshot.snapshot_hash},
        portfolios=snapshot.portfolios, benchmarks=benchmark, market_charts=charts,
        history_reference=snapshot.history_reference, latest_decision=snapshot.latest_decision,
        audit_last_hash=snapshot.audit_last_hash, audit_row_count=snapshot.audit_row_count,
    )
