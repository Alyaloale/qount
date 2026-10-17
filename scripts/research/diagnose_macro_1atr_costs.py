"""Attribute selected macro cost sensitivity on retained inputs; never orders."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

import qount.research.binance_etf_leverage as model
from qount.research.binance_macro_opportunities import (
    cost_case, fixed_fill_metrics, opportunity_status, trade_pnl_components,
)
from qount.research.engine.runs import cached_run, run_identity, save_run
from qount.research.lines.macro_1atr import inputs
from qount.research_data.bars import iso
from qount.strategies.perpetual import grid


def recorded_replay(book, signals, gates, caps, *, capital, controls, fee, slip):
    """Observe actual sizing calls without changing their inputs or results.

    This is a single-process offline diagnostic for the selected tactical rules.
    Temporary wrappers are restored even on failure; no execution module is used.
    """
    if controls["strategy"] != "macro_tactical":
        raise ValueError("diagnostic_requires_selected_tactical_rules")
    attempts, clock = [], {}
    feature_at, size = model.feature_at, model.size
    symbols = {id(d["rule"]): s for s, d in book.items()}

    def observed_feature(rows, now):
        clock["now"] = now
        return feature_at(rows, now)

    def observed_size(*args, **kwargs):
        order, reason = size(*args, **kwargs)
        config, rule, reference, price, vol, equity, budget, reserve, f, s, liquidity = args
        filters = {row["filterType"]: row for row in rule["filters"]}
        side = kwargs.get("side", 1)
        stop = grid(reference-side*config["signal"]["initial_stop_atr"]*vol,
                    filters["PRICE_FILTER"]["tickSize"], True)
        distance = side*(price-stop)/price
        attempts.append(dict(time=clock["now"], symbol=symbols[id(rule)], reason=reason,
            equity=equity, risk_budget=budget, reference_price=reference, atr=vol,
            funding_reserve_fraction=reserve, execution_friction_fraction=2*(f+s),
            total_friction_fraction=2*(f+s)+reserve,
            allowed_friction_fraction=config["cost_model"]["ordinary_friction_limit_fraction_of_stop"]*distance,
            quantity=order["quantity"] if order else None))
        return order, reason

    with patch.object(model, "feature_at", observed_feature), patch.object(model, "size", observed_size):
        result = model.replay(book, signals, capital=capital, fee=fee, slip=slip,
            entry_liquidity_caps=caps, entry_confirmations=gates, trace=True, **controls)
    return result, attempts


def frozen_trade(trade, funding, *, fee, slip):
    """Reprice the same quantity, reference prices and clocks; not a new strategy."""
    components = trade_pnl_components(trade, fee=fee, slip=slip)
    fixed = fixed_fill_metrics(trade, trade, funding, fee=fee, slip=slip)
    side, q = trade.get("side", 1), trade["quantity"]
    entry = trade["entry_price"]/(1+side*slip)*(1+2*side*slip)
    exit_ = trade["exit_price"]/(1-side*slip)*(1-2*side*slip)
    target_slip = side*q*((entry-trade["entry_price"]/(1+side*slip))
                         +(trade["exit_price"]/(1-side*slip)-exit_))
    target_fees = 2*fee*q*(entry+exit_)
    adverse_regular = sum(side*q*float(r["markPrice"])*float(r["fundingRate"])
        for r in funding if trade["entry_time"]*1000 <= int(r["fundingTime"]) < trade["exit_time"]*1000
        and r.get("rateType", "Regular") == "Regular" and side*float(r["fundingRate"]) > 0)
    loss = target_slip-components["slippage_cost"]+target_fees-components["fees"]+adverse_regular
    if not math.isclose(trade["net_pnl"]-loss, fixed["fixed_path_double_cost_pnl"], abs_tol=1e-8):
        raise AssertionError("fixed_path_components_do_not_reconcile")
    return dict(symbol=trade["symbol"], entry_time=trade["entry_time"], exit_time=trade["exit_time"],
        quantity=q, exit_reason=trade["exit_reason"], right_censored=fixed["right_censored"],
        base_net_pnl=trade["net_pnl"], fixed_double_net_pnl=fixed["fixed_path_double_cost_pnl"],
        extra_slippage=target_slip-components["slippage_cost"], extra_fees=target_fees-components["fees"],
        extra_adverse_regular_funding=adverse_regular)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=Path("state/research_runs/macro_1atr/1f01a9af9a80396377bd"))
    parser.add_argument("--double", type=Path, default=Path("state/research_runs/macro_1atr/875d9ca2861621ee4529"))
    parser.add_argument("--runs-root", type=Path, default=Path("state/research_runs"))
    args = parser.parse_args()
    retained, source_rows = {}, []
    for label, root in (("base", args.base), ("double_cost", args.double)):
        summary = json.loads((root/"summary.json").read_text())
        cached_run(root, summary["run_id"])
        retained[label] = dict(summary=summary, trades=json.loads((root/"trades.json").read_text()),
                               nav=json.loads((root/"nav.json").read_text()))
        for name in ("summary.json", "trades.json", "nav.json"):
            path = root/name
            source_rows.append(dict(path=str(path), logical_name=f"{label}/{name}",
                                    sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    base, double = retained["base"], retained["double_cost"]
    p = base["summary"]["parameters"]
    if p != {**double["summary"]["parameters"], "fee": p["fee"], "slip": p["slip"], "scenario": "base"}:
        raise ValueError("retained_scenarios_have_different_rules_or_windows")
    if double["summary"]["parameters"]["fee"] != 2*p["fee"] or double["summary"]["parameters"]["slip"] != 2*p["slip"]:
        raise ValueError("expected_double_execution_costs")
    dependencies = [Path(row["path"]) for row in base["summary"]["code"]]
    for row in base["summary"]["code"]:
        if hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("retained_replay_code_changed:"+row["path"])
    digest, identity = run_identity("macro_cost_attribution",
        dict(base_run=base["summary"]["run_id"], double_run=double["summary"]["run_id"],
             fixed_path="same_quantities_raw_fill_references_and_exit_clocks"),
        source_rows, dependencies+[Path(__file__)])
    output = args.runs_root/"macro_cost_attribution"/digest[:20]
    for row in base["summary"]["inputs"]:
        if hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("retained_input_changed:"+row["path"])
    if cached_run(output, digest) is not None:
        print(json.dumps(dict(output=str(output), reused=True)))
        return
    cache = Path("state/research_cache")
    roots = [cache/name for name in ("binance_macro_prefix_20260407_20260611",
        "binance_macro_earlier_20260611_20260730", "binance_macro_attack_20261015")]
    book, signals, gates, caps, _ = inputs(roots[-1], roots,
        cache/"binance_macro_liquidity_20261015", p["start"], p["end_exclusive"])
    attempts, replays = {}, {}
    for label, saved in retained.items():
        cost = saved["summary"]["parameters"]
        result, attempts[label] = recorded_replay(cost_case(book, label), signals, gates, caps,
            capital=p["capital"], controls=p["controls"], fee=cost["fee"], slip=cost["slip"])
        nav = [dict(t=r["time"], nav=r["equity"]/p["capital"], equity=r["equity"]) for r in result["curve"]]
        if result["trades"] != saved["trades"] or nav != saved["nav"]:
            raise AssertionError("instrumentation_changed_retained_replay:"+label)
        if result["summary"] != saved["summary"]["retained_replay_summary"]:
            raise AssertionError("instrumentation_changed_retained_summary:"+label)
        replays[label] = result
    decisions = {d["time"]: d for d in replays["double_cost"]["decisions"]}
    rows = []
    for trade in base["trades"]:
        row = frozen_trade(trade, book[trade["symbol"]]["funding"], fee=p["fee"], slip=p["slip"])
        matches = [a for a in attempts["double_cost"] if (a["time"], a["symbol"]) == (trade["entry_time"], trade["symbol"])]
        status = opportunity_status(dict(time=trade["entry_time"], symbol=trade["symbol"], engine=trade["engine"]),
                                    decisions.get(trade["entry_time"]))
        row.update(double_path_status=status, double_admission=matches[0] if matches else None)
        rows.append(row)
    capital = p["capital"]
    base_pnl = sum(r["base_net_pnl"] for r in rows)
    fixed_pnl = sum(r["fixed_double_net_pnl"] for r in rows)
    double_pnl = sum(t["net_pnl"] for t in double["trades"])
    scenarios = {}
    for label, field in (("base", "base_net_pnl"), ("fixed_path_double_cost", "fixed_double_net_pnl")):
        scenarios[label] = dict(net_pnl=sum(r[field] for r in rows),
            closed_pnl=sum(r[field] for r in rows if not r["right_censored"]),
            censored_pnl=sum(r[field] for r in rows if r["right_censored"]),
            trade_count=len(rows), closed_count=sum(not r["right_censored"] for r in rows),
            censored_count=sum(r["right_censored"] for r in rows),
            return_pct=100*sum(r[field] for r in rows)/capital)
    scenarios["full_double_cost"] = dict(net_pnl=double_pnl,
        closed_pnl=sum(t["net_pnl"] for t in double["trades"] if t["exit_reason"] != "end_of_sample"),
        censored_pnl=sum(t["net_pnl"] for t in double["trades"] if t["exit_reason"] == "end_of_sample"),
        closed_count=sum(t["exit_reason"] != "end_of_sample" for t in double["trades"]),
        censored_count=sum(t["exit_reason"] == "end_of_sample" for t in double["trades"]),
        trade_count=len(double["trades"]), return_pct=100*double_pnl/capital)
    summary = dict(result_type="frozen_path_cost_attribution", start=p["start"], end_exclusive=p["end_exclusive"],
        initial_capital=capital, symbols=list(book), scenarios=scenarios, costs=p,
        sample_kind="consumed_historical_exploration", independent_oos=False,
        fixed_path_executable=False, original_replays_exactly_reproduced=True,
        direct_cost_loss=base_pnl-fixed_pnl, path_change_residual=fixed_pnl-double_pnl,
        extra_slippage=sum(r["extra_slippage"] for r in rows), extra_fees=sum(r["extra_fees"] for r in rows),
        extra_adverse_regular_funding=sum(r["extra_adverse_regular_funding"] for r in rows),
        sizing_attempts=attempts, rejections={label:r["summary"]["rejections"] for label,r in replays.items()},
        limitations=["固定路径仅作会计归因，不重新检查仓位、止损、清算、现金或续期可执行性；不生成其净值或MDD。",
            "双成本加倍手续费、滑点和不利常规资金费；特殊资金费和有利资金费不加倍。",
            "路径残差包含机会选择、数量、复利及退出变化，不是单独放松成本门的因果收益。",
            "原始成交参考价为小时模型价格，不是历史订单簿；原成本、时点和流动性近似继续适用。",
            "末端截尾不是自然平仓；闭合损益分开列示，不将两者混成独立盈利证据。"])
    save_run(output, digest, identity, dict(summary=summary, nav=[], trades=rows))
    print(json.dumps(dict(output=str(output), reused=False, scenarios=scenarios,
        direct_cost_loss=summary["direct_cost_loss"], path_change_residual=summary["path_change_residual"]), ensure_ascii=False))
    for row in rows:
        print(json.dumps(dict(symbol=row["symbol"], entry=iso(row["entry_time"]),
            base_pnl=row["base_net_pnl"], fixed_double_pnl=row["fixed_double_net_pnl"],
            double_reason=row["double_admission"]["reason"] if row["double_admission"] else row["double_path_status"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
