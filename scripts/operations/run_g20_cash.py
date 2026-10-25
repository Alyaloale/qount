"""Refresh only the revised order-free G20 cash book from the existing public cache."""
import argparse
import datetime as dt
import json
from pathlib import Path

from qount.dual_engine.g20_cash import refresh


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root",type=Path,required=True)
    parser.add_argument("--policy",type=Path,default=Path(__file__).resolve().parents[2]/"config/g20-cash-distributions.json")
    parser.add_argument("--observed-at",default=None)
    parser.add_argument("--bootstrap",action="store_true")
    args=parser.parse_args()
    d=refresh(args.state_root,policy_path=args.policy,
              observed_at=args.observed_at or dt.datetime.now(dt.timezone.utc).isoformat(),bootstrap=args.bootstrap)
    print(json.dumps(dict(status="updated_or_unchanged" if d else "not_enabled",
        orders_authorized=False,observations=len(d["observations"]) if d else 0,
        equity=d["observations"][-1]["equity"] if d else None,
        distributions_received=d["distributions_received"] if d else None)))
