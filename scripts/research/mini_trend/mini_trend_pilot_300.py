#!/usr/bin/env python3
"""Compare frozen MiniTrend candidates under the owner-selected 300 USDT pilot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_funding, load_klines  # noqa: E402
from qount.mini_trend.forward import TOP3  # noqa: E402
from qount.mini_trend.futures_funding_veto import (  # noqa: E402
    FUTURES_FUNDING_VETO_PROTOCOL,
)
from qount.mini_trend.pilot_300_research import (  # noqa: E402
    build_pilot_300_research_report,
    write_pilot_300_research_artifact,
)
from qount.settings import Settings  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    year, month = value[:7].split("-", 1)
    return int(year), int(month)


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss; network disabled for {url.rsplit('/', 1)[-1]}")


def _load_object(path: str | Path) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _load_window(cache_dir: str, start: str, end: str) -> dict:
    return {
        "bars": {
            symbol: load_klines(
                symbol,
                "1d",
                start=_month(start),
                end=_month(end),
                market="um",
                cache_dir=cache_dir,
                fetch=_offline_only,
            )
            for symbol in TOP3
        },
        "funding": {
            symbol: load_funding(
                symbol,
                start=_month(start),
                end=_month(end),
                cache_dir=cache_dir,
                fetch=_offline_only,
            )
            for symbol in TOP3
        },
    }


def _historical_inputs(cache_dir: str) -> dict:
    protocol = FUTURES_FUNDING_VETO_PROTOCOL
    specs = list(protocol.historical_windows) + [protocol.full_window]
    return {
        spec["label"]: _load_window(cache_dir, spec["warmup_start"], spec["end"])
        for spec in specs
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_pilot_300_research_report(
        _historical_inputs(args.cache_dir),
        _load_object(args.exchange_rules_path),
    )
    artifact = write_pilot_300_research_artifact(
        Settings.from_env(),
        payload,
        explicit_path=args.output_path,
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"historical_profit_leader={artifact['diagnostics']['historical_profit_leader']}")
    for name, metrics in artifact["windows"]["2021-2026-full"]["candidates"].items():
        episode = artifact["rolling_30_day_pilots"]["summaries"][name]
        print(
            f"candidate={name} return={metrics['return_pct']}% "
            f"sharpe={metrics['sharpe']} maxdd={metrics['max_drawdown_pct']}% "
            f"pilot_positive_rate={episode['positive_episode_rate']} "
            f"pilot_10pct_halt_rate={episode['drawdown_halt_rate']}"
        )
    print(f"paper_or_live_allowed={artifact['meta']['paper_or_live_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
