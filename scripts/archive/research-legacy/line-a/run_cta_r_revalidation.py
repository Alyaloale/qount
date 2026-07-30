#!/usr/bin/env python3
"""Run the frozen CTA-R ETF selection-free revalidation and publish an immutable bundle.

This is discovery evidence only. It uses the fixed eight-ETF A-share-account panel,
long-only exposure, gross at or below 1.0, the R0 frozen ETF cost model, and a doubled-cost
stress. Historical membership, QDII premium, tracking error, and certified execution costs
remain explicit blockers for promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash
from qount.cta_data import AKSHARE_DEFAULT_UNIVERSE
from qount.cta_data import ETF_ASSET_CLASS
from qount.cta_data import align_on_common_dates
from qount.cta_data import read_etf_adjusted_close_from_zip
from qount.cta_eval import run_walkforward_eval
from qount.cta_sim import SimConfig
from qount.cta_sim import run_paper_sim
from qount.governance import CandidateRevalidationRecord
from qount.governance import GlobalExperimentRecord
from qount.research_data.cost_model import default_cta_r_etf_cost_model


DEFAULT_ZIP = ROOT / "state" / "cta_r" / "etf_source" / "etf_data.zip"
DEFAULT_OUTPUT_DIR = ROOT / "state" / "research_governance" / "cta_r_revalidation"
FAMILY_MAPPING_ID = "85789056ef3e25c4f385b9ae7ce2d381a2f110345682e897544b94c16b1f2c1e"


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
            raise RuntimeError(f"cta_r_revalidation_readback_mismatch:{path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"cta_r_revalidation_mode_invalid:{path}")
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
        refs.append(
            {"path": path.name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    return refs


def _load_panel(zip_path: Path) -> tuple[list[str], dict[str, list[float]], dict[str, Any]]:
    by_symbol: dict[str, dict[str, float]] = {}
    symbol_audit: dict[str, dict[str, Any]] = {}
    for symbol in AKSHARE_DEFAULT_UNIVERSE:
        series = read_etf_adjusted_close_from_zip(str(zip_path), symbol)
        if not series:
            raise RuntimeError(f"cta_r_source_missing_symbol:{symbol}")
        rows = [[date, series[date]] for date in sorted(series)]
        by_symbol[symbol] = series
        symbol_audit[symbol] = {
            "asset_class": ETF_ASSET_CLASS.get(symbol, "unknown"),
            "first_date": rows[0][0],
            "last_date": rows[-1][0],
            "row_count": len(rows),
            "series_hash": canonical_hash({"symbol": symbol, "rows": rows}),
        }

    common_dates = sorted(set.intersection(*(set(series) for series in by_symbol.values())))
    if len(common_dates) < 756:
        raise RuntimeError(f"cta_r_common_history_insufficient:{len(common_dates)}")
    prices = align_on_common_dates(by_symbol)
    for symbol, audit in symbol_audit.items():
        audit["common_row_count"] = len(common_dates)
        audit["rows_excluded_by_intersection"] = audit["row_count"] - len(common_dates)

    panel_hash = canonical_hash(
        {
            "symbols": list(AKSHARE_DEFAULT_UNIVERSE),
            "dates": common_dates,
            "prices": prices,
        }
    )
    audit = {
        "dataset_id": panel_hash,
        "source_type": "current_etf_archive_snapshot",
        "data_role": "consumed_historical_discovery_pool",
        "symbols": symbol_audit,
        "common_first_date": common_dates[0],
        "common_last_date": common_dates[-1],
        "common_row_count": len(common_dates),
        "point_in_time_lifecycle_complete": False,
        "lifecycle_blockers": [
            "historical_listing_and_delisting_snapshots_unavailable",
            "historical_tracking_error_not_reconstructed",
            "historical_qdii_premium_discount_not_reconstructed",
            "current_archive_membership_cannot_prove_historical_membership",
        ],
        "orders_authorized": False,
    }
    return common_dates, prices, audit


def _fixed_runtime_summary(prices: dict[str, list[float]], cost_per_side_pct: float) -> dict[str, Any]:
    config = SimConfig(
        lookback_days=(63, 126, 252),
        vol_lookback_days=63,
        rebalance_days=21,
        target_vol=0.12,
        max_leverage=1.0,
        long_only=True,
        max_weight=1.0,
        cost_per_side_pct=cost_per_side_pct,
    )
    result = run_paper_sim(prices, config)
    reconstructed_nav = 1.0
    for daily_return in result["net_daily_returns"]:
        reconstructed_nav *= 1.0 + daily_return
    nav_difference = abs(reconstructed_nav - (1.0 + result["total_return_pct"]))
    return {
        "config": {
            "lookback_days": list(config.lookback_days),
            "vol_lookback_days": config.vol_lookback_days,
            "rebalance_days": config.rebalance_days,
            "target_vol": config.target_vol,
            "max_leverage": config.max_leverage,
            "long_only": config.long_only,
            "max_weight": config.max_weight,
            "cost_per_side_pct": config.cost_per_side_pct,
        },
        "cagr": result["cagr"],
        "sharpe": result["sharpe"],
        "max_drawdown": result["max_drawdown"],
        "total_return_pct": result["total_return_pct"],
        "total_turnover": result["total_turnover"],
        "avg_gross_exposure": result["avg_gross_exposure"],
        "effective_breadth": result["effective_breadth"],
        "independent_nav_reconciliation_difference": nav_difference,
        "independent_nav_reconciliation_pass": nav_difference <= 1e-12,
    }


def _verify_bundle(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    core = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if manifest["manifest_hash"] != canonical_hash(core):
        raise RuntimeError("cta_r_manifest_hash_invalid")
    for member in manifest["member_files"]:
        path = bundle_dir / member["path"]
        if not path.is_file():
            raise RuntimeError(f"cta_r_member_missing:{member['path']}")
        raw = path.read_bytes()
        if len(raw) != member["size_bytes"] or hashlib.sha256(raw).hexdigest() != member["sha256"]:
            raise RuntimeError(f"cta_r_member_hash_invalid:{member['path']}")
        json.loads(raw.decode("ascii"))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run immutable CTA-R ETF revalidation")
    parser.add_argument("--zip-path", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--trial-number", type=int, default=1)
    args = parser.parse_args(argv)

    zip_path = args.zip_path.expanduser().resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)
    if args.trial_number < 1:
        raise ValueError("trial-number must be >= 1")

    observed_at = datetime.now(timezone.utc).isoformat()
    common_dates, prices, data_audit = _load_panel(zip_path)
    cost_model = default_cta_r_etf_cost_model(frozen_at=observed_at)
    errors = cost_model.validate()
    if errors:
        raise RuntimeError(f"cta_r_cost_model_invalid:{','.join(errors)}")
    cost_per_side = cost_model.total_round_trip_rate / 2.0

    baseline = run_walkforward_eval(
        prices,
        long_only=True,
        max_leverage=1.0,
        max_weight=1.0,
        cost_per_side_pct=cost_per_side,
    )
    doubled_cost = run_walkforward_eval(
        prices,
        long_only=True,
        max_leverage=1.0,
        max_weight=1.0,
        cost_per_side_pct=cost_per_side * 2.0,
    )
    fixed_runtime = _fixed_runtime_summary(prices, cost_per_side)

    baseline_pass = bool(baseline.get("selection_free_robust"))
    doubled_cost_pass = bool(doubled_cost.get("selection_free_robust"))
    discovery_decision = (
        "retain_for_discovery_revalidation"
        if baseline_pass and doubled_cost_pass and fixed_runtime["independent_nav_reconciliation_pass"]
        else "revise_or_reject"
    )

    code_paths = (
        Path("src/qount/cta_sim.py"),
        Path("src/qount/cta_eval.py"),
        Path("src/qount/cta_data.py"),
        Path("src/qount/research_data/cost_model.py"),
        Path("scripts/research/run_cta_r_revalidation.py"),
    )
    code_source_hashes = {str(path): _file_sha256(ROOT / path) for path in code_paths}
    source_hashes = {
        "etf_zip": _file_sha256(zip_path),
        **{f"series_{symbol}": audit["series_hash"] for symbol, audit in data_audit["symbols"].items()},
        **code_source_hashes,
    }
    config = {
        "schema_version": 1,
        "universe": list(AKSHARE_DEFAULT_UNIVERSE),
        "selection_contract": "12_cell_equal_weight_ensemble_plus_past_only_walkforward_plus_fixed_apriori",
        "fixed_lookbacks": [63, 126, 252],
        "long_only": True,
        "max_leverage": 1.0,
        "max_weight": 1.0,
        "cost_per_side_pct": cost_per_side,
        "doubled_cost_per_side_pct": cost_per_side * 2.0,
        "cost_model_hash": cost_model.model_hash,
        "holdout_role": "consumed_historical_discovery_pool",
    }
    config_hash = canonical_hash(config)
    code_hash = canonical_hash(code_source_hashes)
    results = {
        "schema_version": 1,
        "hypothesis_family": "cta_r_cross_asset",
        "candidate_id": "cta_r_selection_free_a_share_etf_v1",
        "data_role": "consumed_historical_discovery_pool",
        "baseline": baseline,
        "doubled_cost": doubled_cost,
        "fixed_runtime": fixed_runtime,
        "discovery_decision": discovery_decision,
        "candidate_pnl_ready": False,
        "promotion_evidence": False,
        "orders_authorized": False,
        "remaining_blockers": [
            "point_in_time_lifecycle_incomplete",
            "qdii_premium_and_tracking_error_unmodeled",
            "execution_costs_estimated_not_certified",
            "one_extra_bar_delay_and_missed_order_stress_pending",
            "asset_class_and_regime_contribution_audit_pending",
            "eligible_new_time_evidence_missing",
        ],
    }
    result_hash = canonical_hash(results)

    experiment = GlobalExperimentRecord.create(
        hypothesis_family="cta_r_cross_asset",
        trial_number_within_family=args.trial_number,
        research_question=(
            "Does the fixed selection-free A-share ETF trend ensemble remain robust under the "
            "R0 frozen execution cost and doubled-cost stress?"
        ),
        economic_mechanism=(
            "Low-frequency time-series momentum rotates a long-only, unlevered account across "
            "equity, bond, gold, and foreign-equity ETF sleeves."
        ),
        baseline_ids=("cta_r_legacy_selection_free_consumed", "cash_zero_return"),
        preregistered_primary_metric="selection_free_walkforward_sharpe_and_fold_stability",
        preregistered_failure_conditions=(
            "selection_free_robust_false_at_frozen_cost",
            "selection_free_robust_false_at_doubled_cost",
            "independent_nav_reconciliation_failure",
            "point_in_time_lifecycle_gap",
        ),
        allowed_sensitivity_range={"cost_multiplier": [1.0, 2.0]},
        dataset_ids=(data_audit["dataset_id"],),
        data_role="consumed_historical_discovery_pool",
        untouched_data_ids=(),
        code_hash=code_hash,
        config_hash=config_hash,
        source_hashes=source_hashes,
        first_result_observed_at=observed_at,
        reviewer_observations=(
            {
                "role": "automated",
                "at": observed_at,
                "note": "Frozen-cost CTA-R selection-free revalidation completed.",
            },
        ),
        result_artifact_hash=result_hash,
        decision="active_research",
        contamination_notes=(
            "All ETF history has already been viewed and remains discovery evidence only.",
            "The current archive cannot prove historical point-in-time membership.",
        ),
    )
    experiment_errors = experiment.validate()
    if experiment_errors:
        raise RuntimeError(f"cta_r_experiment_record_invalid:{','.join(experiment_errors)}")

    candidate = CandidateRevalidationRecord.create(
        candidate_id="cta-r-cross-asset-revalidation-v7",
        hypothesis_family="cta_r_cross_asset",
        historical_evidence_ids=(FAMILY_MAPPING_ID, "cta_r_legacy_selection_free_consumed"),
        current_data_ids=(data_audit["dataset_id"],),
        untouched_data_ids=(),
        venue_and_account_scope="research_cn_etf_account_only; no broker or order permission",
        baseline_ids=("cash_zero_return", "fixed_63_126_252"),
        frozen_cost_model={
            **cost_model.to_dict(),
            "cost_per_side_pct": cost_per_side,
            "cost_certification_status": "estimated_not_certified",
        },
        execution_contract={
            "mode": "research_virtual",
            "long_only": True,
            "effective_gross_max": 1.0,
            "orders_allowed": False,
            "research_execution_allowed": True,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
        },
        standalone_nav_artifacts=(result_hash,),
        factor_and_beta_plan={
            "effective_breadth": fixed_runtime["effective_breadth"],
            "asset_class_contribution_status": "pending",
            "regime_concentration_status": "pending",
        },
        tail_scenarios=(
            "cost_doubling",
            "one_extra_bar_delay_pending",
            "missed_orders_pending",
            "qdii_premium_shock_pending",
            "bond_gold_regime_reversal_pending",
        ),
        primary_metric="selection_free_walkforward_sharpe_and_fold_stability",
        kill_tests=(
            "selection_free_robust_false_at_frozen_cost",
            "selection_free_robust_false_at_doubled_cost",
            "independent_nav_reconciliation_failure",
            "point_in_time_data_gap",
        ),
        trial_budget=3,
        owner_authorization_state="owner_authorized_research",
        decision="active_research",
    )
    candidate_errors = candidate.validate()
    if candidate_errors:
        raise RuntimeError(f"cta_r_candidate_record_invalid:{','.join(candidate_errors)}")

    bundle_core = {
        "schema_version": 1,
        "artifact_type": "cta_r_selection_free_revalidation_bundle",
        "observed_at": observed_at,
        "dataset_id": data_audit["dataset_id"],
        "result_hash": result_hash,
        "config_hash": config_hash,
        "code_hash": code_hash,
        "candidate_record_hash": candidate.record_hash,
        "experiment_record_hash": experiment.record_hash,
        "discovery_decision": discovery_decision,
        "candidate_pnl_ready": False,
        "promotion_evidence": False,
        "orders_authorized": False,
    }
    bundle_id = canonical_hash(bundle_core)
    bundle_dir = args.output_dir.expanduser().resolve() / bundle_id
    bundle_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(bundle_dir, 0o700)

    _write_once(bundle_dir / "config.json", config)
    _write_once(bundle_dir / "cost_model.json", cost_model.to_dict())
    _write_once(bundle_dir / "data_audit.json", data_audit)
    _write_once(bundle_dir / "results.json", results)
    _write_once(bundle_dir / "candidate_record.json", asdict(candidate))
    _write_once(bundle_dir / "global_experiment_record.json", asdict(experiment))

    manifest_core = {
        **bundle_core,
        "bundle_id": bundle_id,
        "source_hashes": source_hashes,
        "member_files": _member_refs(bundle_dir),
    }
    manifest = {**manifest_core, "manifest_hash": canonical_hash(manifest_core)}
    _write_once(bundle_dir / "manifest.json", manifest)
    verified = _verify_bundle(bundle_dir)

    summary = {
        "bundle_id": verified["bundle_id"],
        "bundle_path": str(bundle_dir),
        "dataset_range": [common_dates[0], common_dates[-1]],
        "common_rows": len(common_dates),
        "frozen_cost_per_side_bps": cost_per_side * 10_000.0,
        "baseline_walkforward_sharpe": baseline["walk_forward"]["ann_sharpe"],
        "baseline_walkforward_cagr": baseline["walk_forward"]["cagr"],
        "baseline_walkforward_max_drawdown": baseline["walk_forward"]["max_drawdown"],
        "doubled_cost_walkforward_sharpe": doubled_cost["walk_forward"]["ann_sharpe"],
        "doubled_cost_walkforward_cagr": doubled_cost["walk_forward"]["cagr"],
        "doubled_cost_walkforward_max_drawdown": doubled_cost["walk_forward"]["max_drawdown"],
        "discovery_decision": discovery_decision,
        "candidate_pnl_ready": False,
        "promotion_evidence": False,
        "orders_authorized": False,
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
