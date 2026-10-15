"""Run the frozen three-point MA120 band sensitivity experiment.

The contract is immutable input. The 1.5% variant is evaluated first as the
same-code control; no alternative-band result is computed unless the control
and all input hashes validate.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from qount.research.personal_trading_assistant import (  # noqa: E402
    CORE_ETF_UNIVERSE,
    PersonalTradingAssistantKernel,
    load_dataset_from_clean_indices,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def metric_directions(
    metrics: dict[str, Any], cash: dict[str, Any], buy_hold: dict[str, Any]
) -> dict[str, bool]:
    return {
        "cagr_above_cash": metrics["cagr_252_pct"] > cash["cagr_252_pct"],
        "cagr_above_buy_hold": metrics["cagr_252_pct"] > buy_hold["cagr_252_pct"],
        "drawdown_below_buy_hold": (
            metrics["max_drawdown_pct"] < buy_hold["max_drawdown_pct"]
        ),
    }


def run(contract_path: Path) -> Path:
    contract_path = contract_path.resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("artifact_type") != "preregistration":
        raise ValueError("experiment_contract_type_invalid")
    if contract.get("status") != "frozen_before_unseen_variants":
        raise ValueError("experiment_contract_not_frozen")
    if contract.get("boundary") != {
        "research_only": True,
        "orders_authorized": False,
        "promotion_evidence": False,
    }:
        raise ValueError("experiment_boundary_invalid")
    if "results" in contract or "observed_metrics" in contract:
        raise ValueError("experiment_contract_contains_results")

    input_files = contract["input_files"]
    for key in (
        "dataset",
        "kernel",
        "runner",
        "historical_reference_summary",
        "historical_reference_manifest",
    ):
        item = input_files[key]
        path = (ROOT / item["path"]).resolve()
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise ValueError(f"experiment_input_hash_mismatch:{key}")

    parameters = contract["protocol"]
    data_path = ROOT / input_files["dataset"]["path"]
    dataset = load_dataset_from_clean_indices(data_path)
    symbol = parameters["symbol"]
    meta = CORE_ETF_UNIVERSE[symbol]
    bars = [bar for bar in dataset[symbol] if bar.trade_date >= meta.listing_date]
    if not bars or bars[0].trade_date != parameters["start_date"]:
        raise ValueError("experiment_sample_start_mismatch")
    if bars[-1].trade_date != parameters["end_date"]:
        raise ValueError("experiment_sample_end_mismatch")

    output_dir = (ROOT / contract["output_dir"]).resolve()
    if output_dir.exists():
        raise FileExistsError("experiment_output_already_exists")

    kernel = PersonalTradingAssistantKernel(
        cash_apr=float(parameters["cash_apr"]),
        initial_capital=float(parameters["initial_capital"]),
    )
    cash_nav, cash_metrics = kernel.simulate_pure_cash(bars, meta)
    buy_hold_nav, buy_hold_metrics = kernel.simulate_buy_and_hold(bars, meta)
    cash_payload = asdict(cash_metrics)
    buy_hold_payload = asdict(buy_hold_metrics)

    # Validate the known 1.5% control before touching the unseen alternatives.
    control_band = float(parameters["control_band_pct"])
    control_nav, control_metrics, control_trades = kernel.simulate_trend_timing(
        bars,
        meta,
        ma_period=int(parameters["ma_period"]),
        band_pct=control_band,
        confirm_days=int(parameters["confirm_days"]),
        return_trades=True,
    )
    control_payload = asdict(control_metrics)
    if (
        control_metrics.start_date != parameters["start_date"]
        or control_metrics.end_date != parameters["end_date"]
        or len(control_nav) != len(bars)
    ):
        raise ValueError("experiment_control_sample_mismatch")

    historical_summary = json.loads(
        (ROOT / input_files["historical_reference_summary"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    historical_manifest = json.loads(
        (ROOT / input_files["historical_reference_manifest"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    historical_bindings = historical_manifest["input_files"]
    if historical_bindings["data_sha256"] != input_files["dataset"]["sha256"]:
        raise ValueError("historical_control_dataset_hash_mismatch")
    if (
        historical_manifest["output_artifacts"]["summary_json"]["sha256"]
        != input_files["historical_reference_summary"]["sha256"]
    ):
        raise ValueError("historical_control_summary_binding_mismatch")
    historical_metrics = next(
        row
        for row in historical_summary["assets"][symbol]["baselines"]
        if row.get("model_name") == f"MA{parameters['ma_period']}_Band1.5pct"
    )
    historical_code_sha256 = historical_manifest["input_files"]["code_sha256"]
    historical_control_comparison = {
        "historical_summary_sha256": input_files["historical_reference_summary"][
            "sha256"
        ],
        "historical_source_code_sha256": historical_code_sha256,
        "current_source_code_sha256": input_files["kernel"]["sha256"],
        "source_code_matches": historical_code_sha256
        == input_files["kernel"]["sha256"],
        "metric_delta_current_minus_historical": {
            key: round(float(control_payload[key]) - float(historical_metrics[key]), 10)
            for key in (
                "cagr_252_pct",
                "max_drawdown_pct",
                "calmar_ratio",
                "trade_count",
            )
            if control_payload.get(key) is not None
            and historical_metrics.get(key) is not None
        },
    }

    variants: dict[str, dict[str, Any]] = {}
    for band_pct in parameters["band_pct_variants"]:
        band_pct = float(band_pct)
        label = f"{band_pct * 100:.1f}%"
        if band_pct == control_band:
            nav, metrics_payload, trades = (
                control_nav,
                control_payload,
                control_trades,
            )
        else:
            nav, metrics, trades = kernel.simulate_trend_timing(
                bars,
                meta,
                ma_period=int(parameters["ma_period"]),
                band_pct=band_pct,
                confirm_days=int(parameters["confirm_days"]),
                return_trades=True,
            )
            metrics_payload = asdict(metrics)
        variants[label] = {
            "band_pct": band_pct,
            "metrics": metrics_payload,
            "directions": metric_directions(
                metrics_payload, cash_payload, buy_hold_payload
            ),
            "nav": [
                {"date": bar.trade_date, "equity": round(value, 8)}
                for bar, value in zip(bars, nav)
            ],
            "trades": trades,
        }

    reference = variants[f"{control_band * 100:.1f}%"]
    stable_directions = all(
        variant["directions"] == reference["directions"]
        for variant in variants.values()
    )
    result = {
        "schema_version": "1.0.0",
        "experiment_id": contract["experiment_id"],
        "boundary": contract["boundary"],
        "contract_sha256": sha256(contract_path),
        "sample": {
            "symbol": symbol,
            "start_date": bars[0].trade_date,
            "end_date": bars[-1].trade_date,
            "trading_days": len(bars),
        },
        "controls": {
            "current_1_5pct_vs_historical_report": historical_control_comparison,
            "pure_cash": {
                "metrics": cash_payload,
                "nav": [
                    {"date": bar.trade_date, "equity": round(value, 8)}
                    for bar, value in zip(bars, cash_nav)
                ],
            },
            "buy_and_hold": {
                "metrics": buy_hold_payload,
                "nav": [
                    {"date": bar.trade_date, "equity": round(value, 8)}
                    for bar, value in zip(bars, buy_hold_nav)
                ],
            },
        },
        "variants": variants,
        "pre_registered_assessment": {
            "qualitative_directions_stable_across_all_bands": stable_directions,
            "interpretation": (
                "stable sensitivity directions; no parameter-selection or promotion claim"
                if stable_directions
                else "at least one pre-registered qualitative direction flips across bands"
            ),
        },
    }

    output_dir.mkdir(parents=True)
    result_path = output_dir / "results.json"
    write_json(result_path, result)
    manifest = {
        "schema_version": "1.0.0",
        "experiment_id": contract["experiment_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "python_version": platform.python_version(),
        "boundary": contract["boundary"],
        "contract_path": str(contract_path.relative_to(ROOT)),
        "contract_sha256": sha256(contract_path),
        "input_files": input_files,
        "result_file": {"path": result_path.name, "sha256": sha256(result_path)},
    }
    write_json(output_dir / "manifest.json", manifest)
    (output_dir / "_COMPLETE").write_text(
        f"Completed at {manifest['created_at']}\n", encoding="utf-8"
    )
    return result_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        default="config/personal-assistant-band-robustness-20261012.json",
    )
    args = parser.parse_args()
    result_path = run(ROOT / args.contract)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    for label, variant in result["variants"].items():
        metrics = variant["metrics"]
        print(
            f"{label}: CAGR={metrics['cagr_252_pct']:.4f}% "
            f"MDD={metrics['max_drawdown_pct']:.4f}% "
            f"Calmar={metrics['calmar_ratio']:.6f} "
            f"trades={metrics['trade_count']} "
            f"directions={variant['directions']}"
        )
    print(
        "qualitative_directions_stable_across_all_bands="
        f"{result['pre_registered_assessment']['qualitative_directions_stable_across_all_bands']}"
    )
    print(f"result={result_path}")


if __name__ == "__main__":
    main()
