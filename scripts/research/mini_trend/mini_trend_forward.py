#!/usr/bin/env python3
"""Preregister or run the frozen low-frequency MiniTrend TOP3 forward replay."""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_klines  # noqa: E402
from qount.mini_trend.forward import FROZEN_TOP3_FORWARD_PROTOCOL  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.forward import build_forward_preregistration  # noqa: E402
from qount.mini_trend.forward import build_forward_report  # noqa: E402
from qount.mini_trend.forward import load_anchor_evidence  # noqa: E402
from qount.mini_trend.forward import write_forward_preregistration_artifact  # noqa: E402
from qount.mini_trend.forward import write_forward_report_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


DEFAULT_ANCHOR = (
    REPO
    / "state/mini_trend/research_runs/20260711T132000Z-mini-trend-top3-backtest-2025-2026"
)


def _month(value: str) -> tuple[int, int]:
    try:
        year_text, month_text = value.split("-", 1)
        year, month = int(year_text), int(month_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM") from exc
    if not 1 <= month <= 12:
        raise argparse.ArgumentTypeError("month must be 1..12")
    return year, month


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preregister", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--preregistration-path")
    parser.add_argument("--anchor-dir", type=Path, default=DEFAULT_ANCHOR)
    parser.add_argument("--end", type=_month, default=None, help="last source month, YYYY-MM")
    parser.add_argument("--cache-dir", default="state/grid_b/klines")
    parser.add_argument("--request-retries", type=int, default=3)
    parser.add_argument("--output-path")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def _load_json(path: str | Path) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _fetch_with_retries(url: str, *, retries: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qount-mini-trend-forward/0.1"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt >= retries:
                raise
        except (OSError, TimeoutError, urllib.error.URLError):
            if attempt >= retries:
                raise
        time.sleep(0.25 * (2**attempt))
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rules = _load_json(args.exchange_rules_path)
    anchor = load_anchor_evidence(args.anchor_dir)
    settings = Settings.from_env()
    if args.preregister:
        payload = build_forward_preregistration(rules, anchor)
        artifact = write_forward_preregistration_artifact(
            settings, payload, explicit_path=args.output_path
        )
        diagnostics = {
            "artifact": artifact["artifact_path"],
            "contract_hash": artifact["decision_contract"]["contract_hash"],
            "protocol_hash": artifact["protocol"]["protocol_hash"],
            "strategy_results_evaluated": artifact["meta"]["strategy_results_evaluated"],
        }
    else:
        if not args.preregistration_path:
            raise ValueError("--run requires --preregistration-path")
        preregistration = _load_json(args.preregistration_path)
        start = _month(FROZEN_TOP3_FORWARD_PROTOCOL.warmup_start_month)
        now = dt.datetime.now(dt.UTC)
        end = args.end or (now.year, now.month)
        if end >= (now.year, now.month):
            expected_end = now.date() - dt.timedelta(days=1)
        else:
            expected_end = dt.date(end[0], end[1], calendar.monthrange(*end)[1])
        bars = {
            symbol: load_klines(
                symbol,
                FROZEN_TOP3_FORWARD_PROTOCOL.interval,
                start=start,
                end=end,
                market=FROZEN_TOP3_FORWARD_PROTOCOL.market,
                cache_dir=args.cache_dir,
                fetch=lambda url: _fetch_with_retries(url, retries=args.request_retries),
                skip_missing=True,
            )
            for symbol in TOP3
        }
        payload = build_forward_report(
            bars,
            rules,
            preregistration,
            anchor,
            expected_end_date=expected_end.isoformat(),
        )
        artifact = write_forward_report_artifact(settings, payload, explicit_path=args.output_path)
        diagnostics = {
            "artifact": artifact["artifact_path"],
            "verdict": artifact["diagnostics"]["verdict"],
            "evaluation": artifact["evaluation"],
            "latest_signal": artifact["latest_signal"],
            "data_hash": artifact["meta"]["data_hash"],
        }
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        for key, value in diagnostics.items():
            serialized = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, dict) else value
            print(f"{key}={serialized}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
