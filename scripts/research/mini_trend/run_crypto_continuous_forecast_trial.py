#!/usr/bin/env python3
"""Preregister or run formal crypto trial 146 (continuous z-score forecast) on existing TOP3 UM daily data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.governance import GlobalExperimentRecord  # noqa: E402
from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.backtest import align_bars  # noqa: E402
from qount.mini_trend.forward import TOP3, frozen_top3_config  # noqa: E402
from qount.mini_trend.multi_speed_continuous_forecast import (  # noqa: E402
    CONTINUOUS_FORECAST_PROTOCOL,
    build_continuous_forecast_preregistration,
    build_continuous_forecast_report,
    research_rules,
    validate_continuous_forecast_preregistration,
)


DEFAULT_KLINE_CACHE = ROOT / "state" / "r0_runtime" / "klines"
DEFAULT_FUNDING_CACHE = ROOT / "state" / "r0_runtime" / "funding"
DEFAULT_OUTPUT_ROOT = ROOT / "state" / "research_governance" / "crypto_continuous_forecast"
_DAY_MS = 86_400_000


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        .encode("ascii")
        + b"\n"
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_once(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    raw = _canonical_bytes(value)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        fd = -1
        os.link(tmp, path)
        _fsync_directory(path.parent)
        if path.read_bytes() != raw:
            raise RuntimeError(f"continuous_forecast_readback_mismatch:{path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"continuous_forecast_mode_invalid:{path}")
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp.exists():
            tmp.unlink()


def _member_refs(directory: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        raw = path.read_bytes()
        refs.append({"path": path.name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return refs


def _verify_bundle(bundle_dir: Path) -> dict[str, Any]:
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="ascii"))
    core = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if manifest["manifest_hash"] != canonical_hash(core):
        raise RuntimeError("continuous_forecast_manifest_hash_invalid")
    for member in manifest["member_files"]:
        path = bundle_dir / member["path"]
        raw = path.read_bytes()
        if len(raw) != member["size_bytes"] or hashlib.sha256(raw).hexdigest() != member["sha256"]:
            raise RuntimeError(f"continuous_forecast_member_hash_invalid:{member['path']}")
        json.loads(raw.decode("ascii"))
    return manifest


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-", 1)
    return int(year), int(month)


def _months(start: tuple[int, int], end: tuple[int, int]) -> Iterator[tuple[int, int]]:
    year, month = start
    while (year, month) <= end:
        yield year, month
        month += 1
        if month == 13:
            year += 1
            month = 1


def _source_inventory(kline_cache: Path, funding_cache: Path) -> list[dict[str, Any]]:
    protocol = CONTINUOUS_FORECAST_PROTOCOL
    rows: list[dict[str, Any]] = []
    for symbol in TOP3:
        for year, month in _months(_month(protocol.start_month), _month(protocol.end_month)):
            paths = (
                kline_cache / f"um-{symbol}-1d-{year:04d}-{month:02d}.zip",
                funding_cache / f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip",
            )
            for path in paths:
                if not path.is_file() or path.stat().st_size <= 0:
                    raise FileNotFoundError(f"required offline research input missing: {path}")
                rows.append({
                    "path": str(path.relative_to(ROOT)),
                    "size_bytes": path.stat().st_size,
                    "sha256": _file_sha256(path),
                })
    return rows


def _funding_audit(bars_by_symbol: dict, funding_by_symbol: dict) -> dict[str, Any]:
    aligned = align_bars(bars_by_symbol, TOP3)
    warmup = max(
        frozen_top3_config().gate_sma,
        frozen_top3_config().trend_sma,
        frozen_top3_config().slow_sma,
    )
    by_symbol: dict[str, Any] = {}
    for symbol in TOP3:
        zero_intervals: list[str] = []
        counts: list[int] = []
        funding = funding_by_symbol[symbol]
        for index in range(warmup, len(aligned[symbol]) - 1):
            start_ms = aligned[symbol][index].ts_ms + _DAY_MS
            end_ms = aligned[symbol][index + 1].ts_ms + _DAY_MS
            count = sum(start_ms < row.ts_ms <= end_ms for row in funding)
            counts.append(count)
            if count == 0:
                zero_intervals.append(aligned[symbol][index].date)
        by_symbol[symbol] = {
            "holding_intervals": len(counts),
            "minimum_settlement_count": min(counts) if counts else 0,
            "maximum_settlement_count": max(counts) if counts else 0,
            "zero_settlement_interval_count": len(zero_intervals),
            "zero_settlement_dates": zero_intervals,
        }
    return {
        "by_symbol": by_symbol,
        "complete": all(row["zero_settlement_interval_count"] == 0 for row in by_symbol.values()),
    }


def _load_inputs(kline_cache: Path, funding_cache: Path) -> tuple[dict, dict]:
    protocol = CONTINUOUS_FORECAST_PROTOCOL
    start = _month(protocol.start_month)
    end = _month(protocol.end_month)
    bars = {
        symbol: load_klines(
            symbol, protocol.interval, start=start, end=end, market=protocol.market,
            cache_dir=str(kline_cache), fetch=_offline_only,
        )
        for symbol in TOP3
    }
    funding = {
        symbol: load_funding(
            symbol, start=start, end=end, cache_dir=str(funding_cache), fetch=_offline_only,
        )
        for symbol in TOP3
    }
    return bars, funding


def _preregister(output_root: Path) -> Path:
    protocol = CONTINUOUS_FORECAST_PROTOCOL
    path = output_root / "preregistrations" / protocol.protocol_hash / "preregistration.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="ascii"))
        validate_continuous_forecast_preregistration(existing)
        return path
    payload = build_continuous_forecast_preregistration(datetime.now(timezone.utc).isoformat())
    _write_once(path, payload)
    return path


def _run(args: argparse.Namespace) -> dict[str, Any]:
    prereg_path = args.preregistration_path.expanduser().resolve()
    prereg = json.loads(prereg_path.read_text(encoding="ascii"))
    validate_continuous_forecast_preregistration(prereg)
    observed_at = datetime.now(timezone.utc).isoformat()
    inventory = _source_inventory(args.kline_cache, args.funding_cache)
    bars, funding = _load_inputs(args.kline_cache, args.funding_cache)
    funding_audit = _funding_audit(bars, funding)
    report, trajectories = build_continuous_forecast_report(
        bars, funding, prereg,
        funding_complete=bool(funding_audit["complete"]),
        observed_at=observed_at,
    )

    data_audit = {
        "data_role": "consumed_historical_discovery_pool",
        "existing_cache_only": True,
        "network_download_used": False,
        "source_archive_count": len(inventory),
        "source_archive_inventory_hash": canonical_hash(inventory),
        "source_archives": inventory,
        "funding": funding_audit,
        "data_hash": report["data"]["data_hash"],
        "point_in_time_rules_complete": False,
        "orders_authorized": False,
    }
    code_paths = (
        Path("src/qount/mini_trend/multi_speed_continuous_forecast.py"),
        Path("src/qount/mini_trend/multi_speed_trend.py"),
        Path("src/qount/mini_trend/futures_recovery_backtest.py"),
        Path("src/qount/mini_trend/signals.py"),
        Path("scripts/research/mini_trend/run_crypto_continuous_forecast_trial.py"),
    )
    code_source_hashes = {str(path): _file_sha256(ROOT / path) for path in code_paths}
    source_hashes = {
        "source_archive_inventory": data_audit["source_archive_inventory_hash"],
        "aligned_market_and_funding_data": report["data"]["data_hash"],
        "preregistration": _file_sha256(prereg_path),
        **code_source_hashes,
    }
    code_hash = canonical_hash(code_source_hashes)
    result_hash = canonical_hash(report)
    retained = report["diagnostics"]["verdict"].startswith("retain_")
    experiment = GlobalExperimentRecord.create(
        hypothesis_family=CONTINUOUS_FORECAST_PROTOCOL.hypothesis_family,
        trial_number_within_family=CONTINUOUS_FORECAST_PROTOCOL.trial_number_within_family,
        research_question=(
            "Does a continuous z-score composite of 20/60/120-day returns, standardized "
            "against a past-only 252-day window, improve TOP3 standalone CAGR versus Base "
            "v0.2 without materially worsening drawdown?"
        ),
        economic_mechanism=(
            "Standardizing trailing returns against their own recent distribution separates "
            "regime-adjusted trend persistence from raw return magnitude; the clipped composite "
            "modulates eligibility and relative allocation through the same vol-inverse sizing."
        ),
        baseline_ids=("MiniTrend-UM-Base-v0.2", "cash_zero_return"),
        preregistered_primary_metric=CONTINUOUS_FORECAST_PROTOCOL.protocol_basis["primary_metric"],
        preregistered_failure_conditions=CONTINUOUS_FORECAST_PROTOCOL.protocol_basis["failure_conditions"],
        allowed_sensitivity_range=CONTINUOUS_FORECAST_PROTOCOL.protocol_basis["allowed_sensitivity_range"],
        dataset_ids=(report["data"]["data_hash"],),
        data_role="consumed_historical_discovery_pool",
        untouched_data_ids=(),
        code_hash=code_hash,
        config_hash=CONTINUOUS_FORECAST_PROTOCOL.protocol_hash,
        source_hashes=source_hashes,
        first_result_observed_at=observed_at,
        reviewer_observations=({
            "role": "automated",
            "at": observed_at,
            "note": "Formal global trial 146 completed from the frozen preregistration.",
        },),
        result_artifact_hash=result_hash,
        decision="retain" if retained else "reject",
        contamination_notes=(
            "All 2020-02 through 2026-06 history is already consumed discovery data.",
            "The result cannot support promotion, paper, live, or order authority.",
            "Trial 145 direction-consistency parameters remain frozen and are not rescued.",
        ),
    )
    errors = experiment.validate()
    if errors:
        raise RuntimeError(f"continuous_forecast_experiment_record_invalid:{','.join(errors)}")

    bundle_core = {
        "schema_version": 1,
        "artifact_type": "crypto_multi_speed_continuous_forecast_bundle",
        "observed_at": observed_at,
        "global_trial_number": CONTINUOUS_FORECAST_PROTOCOL.global_trial_number,
        "trial_number_within_family": CONTINUOUS_FORECAST_PROTOCOL.trial_number_within_family,
        "hypothesis_family": CONTINUOUS_FORECAST_PROTOCOL.hypothesis_family,
        "contract_hash": CONTINUOUS_FORECAST_PROTOCOL.contract_hash,
        "protocol_hash": CONTINUOUS_FORECAST_PROTOCOL.protocol_hash,
        "data_hash": report["data"]["data_hash"],
        "result_hash": result_hash,
        "code_hash": code_hash,
        "experiment_record_hash": experiment.record_hash,
        "verdict": report["diagnostics"]["verdict"],
        "candidate_pnl_ready": False,
        "promotion_evidence": False,
        "orders_authorized": False,
    }
    bundle_id = canonical_hash(bundle_core)
    bundle_dir = args.output_root.expanduser().resolve() / "bundles" / bundle_id
    bundle_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(bundle_dir, 0o700)
    _write_once(bundle_dir / "preregistration.json", prereg)
    _write_once(bundle_dir / "data_audit.json", data_audit)
    _write_once(bundle_dir / "results.json", report)
    _write_once(bundle_dir / "trajectories.json", trajectories)
    _write_once(bundle_dir / "global_experiment_record.json", asdict(experiment))
    manifest_core = {
        **bundle_core,
        "bundle_id": bundle_id,
        "source_hashes": source_hashes,
        "member_files": _member_refs(bundle_dir),
    }
    manifest = {**manifest_core, "manifest_hash": canonical_hash(manifest_core)}
    _write_once(bundle_dir / "manifest.json", manifest)
    _verify_bundle(bundle_dir)
    return {
        "bundle_id": bundle_id,
        "bundle_path": str(bundle_dir),
        "verdict": report["diagnostics"]["verdict"],
        "passed_gates": report["diagnostics"]["passed_gate_count"],
        "gate_count": report["diagnostics"]["gate_count"],
        "base": report["summaries"]["base"],
        "candidate": report["summaries"]["candidate"],
        "candidate_doubled_cost": report["summaries"]["candidate_doubled_cost"],
        "candidate_one_bar_delay": report["summaries"]["candidate_one_bar_delay"],
        "top3_beta_residual": report["beta_residual"]["top3_equal_weight"],
        "segment_outperformance_count": report["diagnostics"]["segment_outperformance_count"],
        "candidate_pnl_ready": False,
        "promotion_evidence": False,
        "orders_authorized": False,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--preregistration-path", type=Path)
    parser.add_argument("--kline-cache", type=Path, default=DEFAULT_KLINE_CACHE)
    parser.add_argument("--funding-cache", type=Path, default=DEFAULT_FUNDING_CACHE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.run:
        path = _preregister(args.output_root.expanduser().resolve())
        print(json.dumps({
            "preregistration_path": str(path),
            "contract_hash": CONTINUOUS_FORECAST_PROTOCOL.contract_hash,
            "protocol_hash": CONTINUOUS_FORECAST_PROTOCOL.protocol_hash,
            "global_trial_number": CONTINUOUS_FORECAST_PROTOCOL.global_trial_number,
            "trial_number_within_family": CONTINUOUS_FORECAST_PROTOCOL.trial_number_within_family,
            "strategy_results_evaluated": False,
            "orders_authorized": False,
        }, indent=2, sort_keys=True))
        return 0
    if args.preregistration_path is None:
        raise ValueError("--run requires --preregistration-path")
    print(json.dumps(_run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
