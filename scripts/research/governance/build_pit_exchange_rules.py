#!/usr/bin/env python3
"""Build a PIT exchange-rules snapshot artifact for the LiquidTrend10 UM universe.

Fetches the current UM exchangeInfo, extracts rules (status, min_notional,
tick_size, step_size, onboardDate) for all 10 LiquidTrend10 symbols, and writes
a JSON artifact that the liquidity_capacity_meta G0 can consume via
``--exchange-rules-path``.

The current snapshot is NOT a PIT revision chain. Historical delisting/status
changes require an append-only snapshot chain from now forward. This artifact
marks ``pit_revision_available=false`` until such a chain is built.

Run on WSL/Windows (direct or Liangxin Cloud proxy; never Sophie home proxy).
Mac tests use a mock fetcher.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from qount.mini_trend.liquid_trend import LIQUID_TREND_UNIVERSE  # noqa: E402
from qount.research_data.lifecycle import (  # noqa: E402
    EXCHANGE_INFO_URLS,
    build_rules_dict,
    fetch_exchange_info,
    parse_lifecycle_state,
    parse_valid_from,
    parse_valid_to,
)

DEFAULT_OUTPUT_ROOT = ROOT / "state" / "research_runs"


def build_pit_exchange_rules(
    *,
    market: str = "um",
    fetch=None,
    target_universe: tuple[str, ...] = LIQUID_TREND_UNIVERSE,
    observed_at: str | None = None,
) -> dict:
    payload, source_hash = fetch_exchange_info(market=market, fetch=fetch)
    observed = observed_at or datetime.now(timezone.utc).isoformat()
    symbols_list = payload.get("symbols", [])
    indexed = {
        str(s.get("symbol", "")).upper(): s
        for s in symbols_list
        if isinstance(s, dict) and s.get("symbol")
    }
    rules: list[dict] = []
    for symbol in target_universe:
        info = indexed.get(symbol)
        if info is None:
            rules.append({
                "symbol": symbol,
                "present": False,
                "status": None,
                "trading": False,
            })
            continue
        rules_dict = build_rules_dict(info, market=market)
        rules.append({
            "symbol": symbol,
            "present": True,
            "status": rules_dict.get("status", ""),
            "trading": rules_dict.get("status", "") == "TRADING",
            "min_notional": rules_dict.get("min_notional", ""),
            "tick_size": rules_dict.get("tick_size", ""),
            "step_size": rules_dict.get("step_size", ""),
            "min_qty": rules_dict.get("min_qty", ""),
            "onboard_date": parse_valid_from(info),
            "delivery_date": parse_valid_to(info),
            "lifecycle_state": parse_lifecycle_state(info),
            "rules_hash": _rules_hash(rules_dict),
        })
    present = sum(1 for r in rules if r["present"])
    trading = sum(1 for r in rules if r.get("trading"))
    return {
        "market": market,
        "source_type": "runtime_exchange_info",
        "source_url": EXCHANGE_INFO_URLS.get(market, ""),
        "source_hash": source_hash,
        "observed_at": observed,
        "pit_revision_available": False,
        "pit_revision_note": "current snapshot only; historical delisting/status requires append-only chain from now",
        "universe_size": len(target_universe),
        "rules_present": present,
        "rules_trading": trading,
        "coverage": present / len(target_universe) if target_universe else 0.0,
        "rules": rules,
        "orders_authorized": False,
    }


def _rules_hash(rules_dict: dict) -> str:
    import hashlib
    encoded = json.dumps(rules_dict, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default="um")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--mock", action="store_true", help="use mock fetcher (test mode, no network)")
    return parser.parse_args(argv)


def _mock_fetch(url: str) -> bytes:
    mock_symbols = []
    for i, sym in enumerate(LIQUID_TREND_UNIVERSE):
        mock_symbols.append({
            "symbol": sym,
            "status": "TRADING",
            "onboardDate": 1577836800000 + i * 86400000 * 30,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
            ],
        })
    return json.dumps({"symbols": mock_symbols}).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    fetch = _mock_fetch if args.mock else None
    report = build_pit_exchange_rules(market=args.market, fetch=fetch)
    ts = report["observed_at"].replace(":", "").replace("-", "").split(".")[0]
    out_dir = args.output_root.expanduser().resolve() / f"{ts}-pit-exchange-rules-{args.market}"
    out_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    artifact_path = out_dir / f"pit_exchange_rules_{args.market}.json"
    artifact_path.write_text(
        json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({
        "artifact_path": str(artifact_path),
        "coverage": report["coverage"],
        "rules_present": report["rules_present"],
        "rules_trading": report["rules_trading"],
        "pit_revision_available": report["pit_revision_available"],
        "orders_authorized": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
