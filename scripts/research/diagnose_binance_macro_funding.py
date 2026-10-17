"""Frozen-opportunity funding admission and forecast errors; not a portfolio."""
import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from qount.research.binance_etf_leverage import FUNDING_POLICIES, funding_reserve, load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, macro_features
from qount.research.binance_macro_opportunities import fixed_fill_metrics
from qount.research_data.archives import timestamp


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015"))
    p.add_argument("--catalog", type=Path, default=Path("state/research_runs/binance_macro_opportunities_20261015_handover/opportunities.json"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_diagnosis")
    features, _ = macro_features(args.cache, "2026-10-15")
    data, _ = load_inputs(args.cache, timestamp("2026-07-30"), timestamp("2026-10-15"), symbols=tuple(CONTRACT_SIGNALS))
    catalog = [e for e in json.loads(args.catalog.read_text()) if e["engine"] == "tactical"]
    first = {}
    for e in catalog:
        if e.get("path_status") == "available":
            first.setdefault(e["episode"], e["id"])
    events = []
    for e in catalog:
        for policy in FUNDING_POLICIES:
            if e.get("path_status") != "available":
                events.append(dict(id=e["id"], policy=policy, status=e["path_status"]))
                continue
            symbol = e["symbol"]
            result = replay({symbol: data[symbol]}, {symbol: features[symbol]},
                            strategy="macro_tactical", gross_cap=3, risk_fraction=.20,
                            account_controls=False, funding_policy=policy,
                            forced_entry=dict(time=e["time"], symbol=symbol, engine="tactical"))
            row = dict(id=e["id"], episode=e["episode"], first_observable=first[e["episode"]] == e["id"],
                       policy=policy, status="rejected", rejections=result["summary"]["rejections"],
                       forecast=funding_reserve(data[symbol]["funding"], e["time"], 168, policy))
            if result["trades"]:
                assert len(result["trades"]) == 1
                t = result["trades"][0]
                frozen = e["outcomes"]["signal_only"]
                assert t["exit_time"] == frozen["exit_time"] and t["exit_reason"] == frozen["exit_reason"]
                assert math.isclose(t["net_pnl"]/t["notional_usdt"], frozen["net_pnl"]/frozen["notional"], abs_tol=1e-10)
                actual = sum(float(f["markPrice"])/t["entry_price"]*max(0, float(f["fundingRate"]))
                             for f in data[symbol]["funding"]
                             if t["entry_time"]*1000 <= int(f["fundingTime"]) < t["exit_time"]*1000
                             and f.get("rateType", "Regular") == "Regular")
                fixed = fixed_fill_metrics(t, t, data[symbol]["funding"])
                row.update(status="accepted", censored=t["exit_reason"] == "end_of_sample",
                           net_bps=t["net_pnl"]/t["notional_usdt"]*10000,
                           fixed_double_bps=fixed["fixed_path_double_cost_pnl"]/t["notional_usdt"]*10000,
                           actual_regular_debit_fraction=actual,
                           hours=(t["exit_time"]-t["entry_time"])/3600)
            events.append(row)
    summaries = []
    for policy in FUNDING_POLICIES:
        for first_only in (False, True):
            accepted = [e for e in events if e["policy"] == policy and e["status"] == "accepted"
                        and (not first_only or e["first_observable"])]
            closed = [e for e in accepted if not e["censored"]]
            summaries.append(dict(policy=policy, first_episode_only=first_only, accepted=len(accepted),
                                  closed=len(closed), censored=len(accepted)-len(closed),
                                  mean_net_bps=statistics.mean(e["net_bps"] for e in closed) if closed else None,
                                  mean_fixed_double_bps=statistics.mean(e["fixed_double_bps"] for e in closed) if closed else None,
                                  underreserved=sum(e["actual_regular_debit_fraction"] > e["forecast"]+1e-12 for e in closed)))
    result = dict(events=events, summaries=summaries,
                  catalog_sha256=hashlib.sha256(args.catalog.read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  assumptions=["Fixed10USDT,20% risk,3x gross, no account DD controls; event paths may overlap and cannot be summed as portfolio returns.",
                               "All accepted paths verified against frozen entry/exit unit economics; first episode selection precedes payoff.",
                               "Forecast errors are retrospective; actual holding times never enter admission. Censored paths excluded from closed expectancy.",
                               "Same consumed history, no independent OOS or fitted tail coverage claim."],
                  research_only=True, orders_authorized=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps(summaries))


if __name__ == "__main__":
    main()
