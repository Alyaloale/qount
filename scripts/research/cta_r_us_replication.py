"""Run Trial 151: frozen CTA-R rule on the class-matched US ETF universe.

research_only=true / orders_authorized=false. Public Tiingo daily prices only.
The token is read from QOUNT_TIINGO_API_KEY (environment first, else the single line in --env-file);
it is used only as an HTTP header and never printed or written to the bundle.
Preregistration: docs/cta-r-us-replication-and-c60-vol-matched-2026-09.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from qount.contracts import canonical_hash
from qount.research.cta_r_us_replication import UNIVERSE, evaluate, fetch_adjusted_closes

KEY = "QOUNT_TIINGO_API_KEY"


def _token(env_file: Path) -> str:
    value = os.environ.get(KEY, "")
    if value or not env_file.is_file():
        return value
    for line in env_file.read_text().splitlines():
        name, sep, raw = line.strip().partition("=")
        if sep and name.strip().removeprefix("export ").strip() == KEY:
            return raw.strip().strip('"').strip("'")
    return ""


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--cache", type=Path, default=None, help="reuse a closes JSON instead of fetching")
    parser.add_argument("--out-root", type=Path, default=Path("state/research_runs/cta_r_us_replication_v1"))
    args = parser.parse_args(argv)

    observed = dt.datetime.now(dt.timezone.utc)
    if args.cache:
        series = json.loads(args.cache.read_text())
    else:
        token = _token(args.env_file)
        end = observed.date() - dt.timedelta(days=1)
        series = {s: fetch_adjusted_closes(s, token=token, end=end) for s in sorted(UNIVERSE)}
        del token
    result = evaluate(series) | {"observed_at": observed.isoformat()}
    bundle = args.out_root / canonical_hash({"data": result["data"]["data_hash"],
                                             "prereg": result["preregistration_hash"]})[:16]
    bundle.mkdir(parents=True, exist_ok=True)
    os.chmod(bundle, 0o700)
    _write(bundle / "closes.json", series)
    _write(bundle / "results.json", result)
    _write(bundle / "manifest.json", {"files": {n: canonical_hash(json.loads((bundle / n).read_text()))
                                                for n in ("closes.json", "results.json")},
                                      "research_only": True, "orders_authorized": False})
    print(json.dumps({"bundle": str(bundle), "verdict": result["verdict"], "gates": result["gates"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
