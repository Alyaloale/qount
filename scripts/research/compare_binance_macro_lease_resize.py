"""Original full exit versus paid partial reduction at funding lease reviews."""
import argparse
import hashlib
import itertools
import json
import math
from decimal import Decimal
from pathlib import Path

from qount.research.binance_etf_leverage import load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_entry_episodes import episode_confirmations
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, trade_pnl_components
from qount.research.binance_macro_setup import setup_policies
from qount.research.binance_macro_validation import available_atr, frozen_trade, minute_windows
from qount.research.engine.perpetual import common_step
from qount.research_data.archives import timestamp


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--download", action="store_true", help="Missing public minute windows only")
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_lease_resize")
    cache = Path("state/research_cache/binance_macro_attack_20261015")
    features, sources = macro_features(cache, "2026-10-15")
    symbols = tuple(CONTRACT_SIGNALS)
    data, inputs = load_inputs(cache, timestamp("2026-07-30"), timestamp("2026-10-15"), symbols=symbols)
    sources += inputs
    for folder, start, end, subset in (
        ("binance_macro_earlier_20260611_20260730", "2026-06-11", "2026-07-30", tuple(s for s in symbols if s != "SMHUSDT")),
        ("binance_macro_prefix_20260407_20260611", "2026-04-07", "2026-06-11", ("SPYUSDT", "QQQUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT")),
    ):
        prefix, inputs = load_inputs(Path("state/research_cache")/folder, timestamp(start), timestamp(end), symbols=subset)
        sources += inputs
        data = {s: {**d, **{k: prefix[s][k]+d[k] for k in ("trade", "mark", "funding")}}
                if s in prefix else d for s, d in data.items()}
    book, signals = directional_book(data, features, "long", 20/3)
    gates = episode_confirmations(book, signals, "no_chase")
    cap_cache = Path("state/research_cache/binance_macro_liquidity_20261015")
    caps, cap_sources, _ = load_capacity_contexts(list(gates), cap_cache)
    sources += cap_sources
    end = timestamp("2026-10-15")
    review_clocks = {(s, now+hours*3600) for (s,now), c in gates.items() if c["setup"] == "mean_reversion"
                     for hours in (168,336) if now+hours*3600 < end}
    exit_caps, cap_sources, _ = load_capacity_contexts(review_clocks, cap_cache, args.download)
    sources += cap_sources
    params = dict(strategy="macro_tactical", gross_cap=20, risk_fraction=.5, exchange_leverage=50,
        liquidation_stop_multiple=1.25, account_controls=False, funding_policy="debit_stress", sizing_gap_reserve=.03,
        allow_partial_histories=True, tactical_setup_policies=setup_policies(7, 21), funding_lease_hours=168,
        funding_lease_budget="risk", entry_confirmations=gates)
    bundles, controls = {}, 0
    for policy, capital, scenario, capacity in itertools.product(
            ("full_exit", "partial_reduce"), (10,100), ("base","double_cost"), ("causal","without_short_volume_cap")):
        fee, slip = (.001,.005) if scenario == "double_cost" else (.0005,.0025)
        b = replay(cost_case(book,scenario), signals, **params, capital=capital, fee=fee, slip=slip,
            entry_liquidity_caps=caps if capacity == "causal" else None,
            funding_lease_resize=policy == "partial_reduce", lease_exit_liquidity_caps=exit_caps if policy == "partial_reduce" else None)
        if policy == "full_exit":
            old = json.loads(Path(f"state/research_runs/binance_macro_entry_sleeves_20261015/shared_{capital}_{scenario}_{capacity}.json").read_text())
            assert b["trades"] == old["trades"] and b["curve"] == old["curve"]
            controls += 1
        r = b["summary"]
        closed = [t for t in b["trades"] if t["exit_reason"] != "end_of_sample"]
        censored = [t for t in b["trades"] if t["exit_reason"] == "end_of_sample"]
        r.update(policy=policy, capital=capital, scenario=scenario, capacity=capacity,
            executable_constraint_set=capacity == "causal", closed_trades=len(closed), censored_trades=len(censored),
            closed_pnl=sum(t["net_pnl"] for t in closed), censored_pnl=sum(t["net_pnl"] for t in censored),
            partial_exits=sum(len(t.get("partial_exits",[])) for t in b["trades"]),
            reduction_fees=sum(x["fee"] for t in b["trades"] for x in t.get("partial_exits",[])),
            realized_cash_pnl_before_sample_liquidation=sum(t["net_pnl"] for t in closed)+sum(
                t.get("partial_realized_pnl",0)-t["entry_fee"]+t["funding"] for t in censored))
        for t in b["trades"]:
            t["pnl_components"] = trade_pnl_components(t, fee=fee, slip=slip)
        bundles[policy,capital,scenario,capacity] = b
    print(json.dumps(dict(phase="accounts", accounts=len(bundles), controls=controls,
        partial_exits=sum(b["summary"]["partial_exits"] for b in bundles.values()))),flush=True)
    # Independent checks on each actual reduction and the post-cost review.
    reduction_checks = 0
    for (policy,capital,scenario,capacity), b in bundles.items():
        for t in b["trades"]:
            parts = t.get("partial_exits",[])
            if not parts:
                continue
            assert t["quantity"] == t["initial_quantity"]
            assert math.isclose(t["quantity"], t["remaining_quantity"]+sum(x["quantity"] for x in parts),abs_tol=1e-9)
            initial_base = t["stress_risk_usdt"]-t["notional_usdt"]*t["funding_reserve_fraction"]
            assert math.isclose(t["funding_cost_cap_usdt"],max(0,t["risk_budget_usdt"]-initial_base),abs_tol=1e-8)
            lots = [f for f in data[t["symbol"]]["rule"]["filters"] if f["filterType"] in ("LOT_SIZE","MARKET_LOT_SIZE")]
            step = common_step(lots)
            previous_q, previous_sunk = t["quantity"],0
            for x in parts:
                assert t["entry_time"] < x["time"] < t["exit_time"]
                assert x["quantity"] <= exit_caps[t["symbol"],x["time"]]["quantity_cap"]+1e-9
                assert x["liquidity"]["asof"] <= x["time"]-60
                assert Decimal(str(x["quantity"])) % step == 0
                assert Decimal(str(x["remaining_quantity"])) % step == 0
                assert 0 < x["remaining_quantity"] < previous_q
                assert x["partial_risk_spent_usdt"] >= previous_sunk
                previous_q,previous_sunk=x["remaining_quantity"],x["partial_risk_spent_usdt"]
                review = next(r for r in t["funding_lease_reviews"] if r["time"] == x["time"] and r.get("phase") == "after_reduction")
                assert review["allowed"]
                assert review["funding_cost_cap"] == t["funding_cost_cap_usdt"]
                assert review["cumulative_cost_with_reserve"] <= t["funding_cost_cap_usdt"]+1e-9
                assert review["forecast_cost"] <= review["remaining_free_cash"]+1e-9
                assert review["stress_risk"] <= min(t["risk_budget_usdt"],.5*review["equity"])+1e-9
                assert t["initial_margin_usdt"]*x["remaining_quantity"]/t["quantity"] <= .8*review["equity"]+1e-9
                reduction_checks += 1
    longest = {}
    for b in bundles.values():
        for t in b["trades"]:
            key=t["symbol"],t["entry_time"]
            if key not in longest or t["exit_time"] > longest[key]["exit_time"]:longest[key]=t
    minutes, minute_sources = minute_windows(list(longest.values()),Path("state/research_cache/binance_macro_minutes_20261015"),end,args.download)
    sources += minute_sources
    atrs={s:available_atr(d["trade"]) for s,d in data.items()}
    count=0
    for (policy,capital,scenario,capacity),b in bundles.items():
        fee,slip=(.001,.005) if scenario == "double_cost" else (.0005,.0025)
        cb=cost_case(data,scenario)
        equity=peak=capital
        mdd,checked=0,[]
        for t in b["trades"]:
            s=t["symbol"];m=minutes[s,t["entry_time"]]
            result=frozen_trade({**t,"equity_before_entry":equity},m["trade"],m["mark"],cb[s]["funding"],atrs[s],data[s]["rule"],fee=fee,slip=slip)
            assert result["status"] == "executed"
            for row in result.pop("curve"):
                mdd=max(mdd,1-row["equity"]/peak);peak=max(peak,row["equity"])
            result.update(pnl_difference=result["net_pnl"]-t["net_pnl"],
                changed_exit=result["exit_time"] != t["exit_time"] or result["exit_reason"] != t["exit_reason"],
                partial_schedule_changed=[(x["time"],x["quantity"]) for x in result.get("partial_exits",[])] != [(x["time"],x["quantity"]) for x in t.get("partial_exits",[])],
                entry_risk_breach=result["entry_stress_risk_usdt"] > .5*equity+1e-9,
                entry_margin_breach=result["entry_margin_fraction"] > .8+1e-9)
            equity+=result["net_pnl"];checked.append(result);count+=1
        b["minute_checks"]=checked
        b["summary"].update(minute_schedule_return=equity/capital-1,minute_close_mdd=mdd,
            minute_pnl_difference=equity-b["summary"]["final_equity"],minute_exit_changes=sum(t["changed_exit"] for t in checked),
            minute_partial_schedule_changes=sum(t["partial_schedule_changed"] for t in checked),
            minute_entry_risk_breaches=sum(t["entry_risk_breach"] for t in checked),minute_entry_margin_breaches=sum(t["entry_margin_breach"] for t in checked))
    unique={s["path"]:s for s in sources}
    for s in unique.values():assert hashlib.sha256(Path(s["path"]).read_bytes()).hexdigest()==s["sha256"]
    args.output.mkdir(parents=True)
    for key,b in bundles.items():
        (args.output/("_".join(map(str,key))+".json")).write_text(json.dumps(b,allow_nan=False)+"\n")
    result=dict(start="2026-04-07",end_exclusive="2026-10-15",runs=[b["summary"] for b in bundles.values()],
        minute_trade_checks=count,reduction_budget_checks=reduction_checks,legacy_controls=controls,sources=list(unique.values()),
        code_sources=[dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in (Path(__file__),
            Path("src/qount/research/binance_macro_funding_lease.py"),Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"),
            Path("src/qount/research/binance_macro_validation.py"),Path("src/qount/research/binance_macro_opportunities.py"))],
        research_only=True,orders_authorized=False,independent_oos=False,
        assumptions=["All signals/no-chase/entry costs/stops/risk/holding and funding caps unchanged; only failed7/14day review may reduce, never add quantity or extend21day deadline.",
            "Largest residual satisfying original and current risk, unchanged lifetime adverse funding cap, cash and80% margin limits after reduction costs; sunk risk never reset or offset by favorable cash flows.",
            "Paid historical funding overspend still exits next hour; reduction cannot erase spending. Failed regime/unknown forecast/no grid-valid residual/no causal exit volume means original full exit.",
            "Reduce-only reduction uses lot grid/minQty, not entry minimum notional; official USD-M API docs confirm reduce-only exception, but native account behavior is untested.",
            "Both capacity arms retain causal short-window limits for new partial reductions; removing entry short-volume cap is diagnostic only. Original full-exit liquidity remains approximate.",
            "Minute checks freeze quantities, scheduled partial reductions and final exits, not complete minute-level decisions. Current historical filters/MMR/proxy signals remain approximations."])
    (args.output/"summary.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    lines=["# Paid partial funding-lease reductions", "", "|Policy|Capital|Costs|Entry capacity|Minute return|Minute MDD|Closed parent PnL|Censored parent PnL|Reductions|",
           "|---|---:|---|---|---:|---:|---:|---:|---:|"]
    for r in result["runs"]:
        lines.append(f"|{r['policy']}|{r['capital']}|{r['scenario']}|{r['capacity']}|{r['minute_schedule_return']:.2%}|{r['minute_close_mdd']:.2%}|{r['closed_pnl']:.5f}|{r['censored_pnl']:.5f}|{r['partial_exits']}|")
    lines += ["", "## Assumptions", ""]+["- "+a for a in result["assumptions"]]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output),accounts=len(bundles),minute_checks=count,reduction_checks=reduction_checks,controls=controls)),flush=True)


if __name__ == "__main__":
    main()
