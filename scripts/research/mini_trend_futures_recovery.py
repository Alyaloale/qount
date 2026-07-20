#!/usr/bin/env python3
"""Preregister or diagnose the no-carry, low-frequency USD-M recovery candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.futures_recovery import build_futures_recovery_preregistration  # noqa: E402
from qount.mini_trend.futures_recovery import FUTURES_RECOVERY_PROTOCOL  # noqa: E402
from qount.mini_trend.futures_recovery import load_live_lessons_evidence  # noqa: E402
from qount.mini_trend.futures_recovery import write_futures_recovery_preregistration_artifact  # noqa: E402
from qount.mini_trend.futures_recovery_report import build_historical_diagnostic_report  # noqa: E402
from qount.mini_trend.futures_recovery_report import write_historical_diagnostic_artifact  # noqa: E402
from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _load_object(path: str | Path) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="run the preregistered offline diagnostic")
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--live-lessons-path", required=True)
    parser.add_argument("--preregistration-path")
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--output-path")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def _month(value: str) -> tuple[int, int]:
    year, month = value[:7].split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _diagnostic_inputs(cache_dir: str) -> dict:
    inputs = {}
    for spec in FUTURES_RECOVERY_PROTOCOL.historical_diagnostic_windows:
        start, end = _month(spec["warmup_start"]), _month(spec["end"])
        inputs[spec["label"]] = {
            "bars": {
                symbol: load_klines(
                    symbol,
                    "1d",
                    start=start,
                    end=end,
                    market="um",
                    cache_dir=cache_dir,
                    fetch=_offline_only,
                )
                for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT")
            },
            "funding": {
                symbol: load_funding(
                    symbol,
                    start=start,
                    end=end,
                    cache_dir=cache_dir,
                    fetch=_offline_only,
                )
                for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT")
            },
        }
    return inputs


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rules = _load_object(args.exchange_rules_path)
    evidence = load_live_lessons_evidence(args.live_lessons_path)
    if args.run:
        if not args.preregistration_path:
            raise ValueError("--run requires --preregistration-path")
        payload = build_historical_diagnostic_report(
            _diagnostic_inputs(args.cache_dir),
            rules,
            _load_object(args.preregistration_path),
            evidence,
        )
        artifact = write_historical_diagnostic_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
    else:
        payload = build_futures_recovery_preregistration(rules, evidence)
        artifact = write_futures_recovery_preregistration_artifact(
            Settings.from_env(), payload, explicit_path=args.output_path
        )
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        if args.run:
            print(f"verdict={artifact['diagnostics']['verdict']}")
            print(f"historical_gate_passed={artifact['diagnostics']['historical_gate_passed']}")
            for row in artifact["segments"]:
                print(
                    f"segment={row['label']} control={row['control']['return_pct']}% "
                    f"candidate={row['candidate']['return_pct']}% "
                    f"incremental={row['incremental_return_pct']}%"
                )
        else:
            print(f"contract_hash={artifact['decision_contract']['contract_hash']}")
            print(f"protocol_hash={artifact['protocol']['protocol_hash']}")
            print(f"strategy_results_evaluated={artifact['meta']['strategy_results_evaluated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
