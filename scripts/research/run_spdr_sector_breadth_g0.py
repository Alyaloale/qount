#!/usr/bin/env python3
"""Fetch/cache the eleven SPDR sector ETFs and run the no-PnL breadth G0."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qount.artifacts import persistent_research_dir  # noqa: E402
from qount.l1_cross_asset import fetch_cross_asset_panel  # noqa: E402
from qount.settings import Settings  # noqa: E402
from qount.spdr_sector_breadth import SPDR_SECTOR_ETFS  # noqa: E402
from qount.spdr_sector_breadth import build_spdr_sector_breadth_report  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    settings = Settings.from_env()
    if not settings.tiingo_api_key:
        raise RuntimeError("QOUNT_TIINGO_API_KEY is required; do not use another data source")
    cache_dir = ROOT / "state" / "research_cache" / "tiingo_spdr_sector_etf"
    panel, sources, point_counts = fetch_cross_asset_panel(
        settings=settings,
        tickers=list(SPDR_SECTOR_ETFS),
        start_date="1998-01-01",
        cache_dir=cache_dir,
    )
    manifest = []
    for ticker in SPDR_SECTOR_ETFS:
        path = cache_dir / f"tiingo_{ticker}.json"
        manifest.append({
            "ticker": ticker,
            "source": sources[ticker],
            "point_count": point_counts[ticker],
            "path": str(path),
            "sha256": _sha256(path),
        })
    report = build_spdr_sector_breadth_report(panel, cache_manifest=manifest)
    output_dir = persistent_research_dir(settings, "spdr-sector-effective-breadth-g0")
    artifact = output_dir / "spdr_sector_effective_breadth_g0.json"
    artifact.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"artifact={artifact}")
    print(f"effective_breadth={report['breadth']['effective_breadth']:.8f}")
    print(f"verdict={report['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
