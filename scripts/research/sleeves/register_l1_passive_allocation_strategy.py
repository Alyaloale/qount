#!/usr/bin/env python3
"""Publish the preregistered L1 passive sleeve into the research strategy registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from qount.artifacts import persistent_research_dir  # noqa: E402
from qount.contracts import canonical_hash  # noqa: E402
from qount.governance import StrategyRegistry  # noqa: E402
from qount.models import utc_now  # noqa: E402
from qount.persistence import write_immutable_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402
from qount.strategies import passive_allocation_strategy_registration  # noqa: E402


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid_preregistration:{path}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"invalid_preregistration:{path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preregistration", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    preregistration = _read_json(args.preregistration)
    source_files = (
        ROOT / "src" / "qount" / "research" / "sleeves" / "l1_passive_allocation.py",
        ROOT / "src" / "qount" / "strategies" / "passive_allocation.py",
    )
    code_hash = canonical_hash(
        {str(path.relative_to(ROOT)): _sha256(path) for path in source_files}
    )
    config_hash = canonical_hash(
        {
            "preregistration_contract_hash": preregistration.get("contract_hash"),
            "promotion_status": "research",
            "maximum_stress_loss_fraction": 1.0,
            "maximum_gross": 1.0,
        }
    )
    registered_at = utc_now().isoformat()
    registration = passive_allocation_strategy_registration(
        preregistration=preregistration,
        code_hash=code_hash,
        config_hash=config_hash,
        registered_at=registered_at,
    )
    registry = StrategyRegistry.create((registration,), created_at=registered_at)
    directory = persistent_research_dir(
        Settings.from_env(), "l1-passive-allocation", "strategy-registry"
    )
    registration_path = directory / "strategy_registration.json"
    registry_path = directory / "strategy_registry.json"
    write_immutable_artifact(registration_path, registration)
    write_immutable_artifact(registry_path, registry)
    print(f"registration={registration_path}")
    print(f"registry={registry_path}")
    print(f"strategy_id={registration.strategy_id}")
    print("promotion_status=research")
    print("strategy_intent_authorized=false")
    print("paper_or_live_allowed=false")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
