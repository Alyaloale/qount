#!/usr/bin/env python3
"""Seal the separate research-only L1 passive 60/40 allocation contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from qount.artifacts import persistent_research_dir  # noqa: E402
from qount.l1_passive_allocation import build_l1_passive_allocation_preregistration  # noqa: E402
from qount.l1_passive_allocation import validate_l1_passive_allocation_preregistration  # noqa: E402
from qount.persistence import write_immutable_json_document  # noqa: E402
from qount.settings import Settings  # noqa: E402


def main() -> int:
    payload = build_l1_passive_allocation_preregistration()
    validate_l1_passive_allocation_preregistration(payload)
    directory = persistent_research_dir(
        Settings.from_env(), "l1-passive-allocation", "preregistration"
    )
    path = directory / "l1_passive_allocation_preregistration.json"
    write_immutable_json_document(path, payload)
    print(f"artifact={path}")
    print(f"contract_hash={payload['contract_hash']}")
    print("allocation=SPY:0.60,TLT:0.40,USD_cash:0.00")
    print("rebalance=annual_first_eligible_full_NYSE_session")
    print("strategy_intent_authorized=false")
    print("orders_authorized=false")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
