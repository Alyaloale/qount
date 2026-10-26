"""Fixed-rule, close-time G20 small-rebalance experiments; no order or network path."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
from functools import partial
import hashlib
import json
import math
from pathlib import Path
from statistics import stdev

import analyze_g20_risk_budget as prior
import compare_g20_long_cash as cash
from compare_g20_fixed_budget import ROOT, INPUT, CASH_INPUT, schedule
from qount.research.g20_cash_execution import CashFriction
from qount.research.g20_rebalance import MODES, rebalance_decision

CASES = {"base": (CashFriction(), 1), "commission1": (CashFriction(minimum_commission=1), 1),
         "strict": (CashFriction(cost_bps=40, commission_bps=10, minimum_commission=1), 2),
         "fixed_share": (CashFriction(cost_bps=15, commission_bps=0, minimum_commission=1, commission_per_share=.005, commission_cap_rate=.01), 1),
         "fixed_share_stress": (CashFriction(cost_bps=30, commission_bps=0, minimum_commission=1, commission_per_share=.005, commission_cap_rate=.01), 2)}
RULES = {"monthly20": ("monthly20", None), "monthly15": ("monthly15", None),
         "dynamic": ("weekly_cap15", None), **{m: ("weekly_cap15", m) for m in MODES}}
NEIGHBORS = {"symmetric_0p5": .005, "symmetric_2p0": .02}


def tracking_metrics(run, panel, targets):
    dates = {d: i for i, d in enumerate(panel.dates)}
    first = dates[run["records"][0]["date"]]
    current = targets[max(i for i in targets if i < first)]
    gaps, cash_weights = [], []
    for row in run["records"]:
        i = dates[row["date"]]
        if i in targets:
            current = targets[i]
        spendable = row["equity"] - row["receivable"]
        value = sum(p["market_value"] for p in row["positions"] if p["symbol"] not in ("BIL", "DIVIDEND_RECEIVABLE"))
        gaps.append(value / spendable - sum(w for s, w in current.items() if s != "BIL"))
        cash_weights.append(row["cash"] / row["equity"])
    d = run.get("decisions", [])
    accrued = sum(e["value"] for e in run["income"] if e["side"] == "DIVIDEND_ACCRUAL")
    metrics = run["metrics"]
    price_pnl = metrics["final_equity"] - metrics["capital"] - accrued + metrics["cost"]
    previous = metrics["capital"]
    returns = []
    for row in run["records"]:
        returns.append(row["equity"]/previous-1)
        previous = row["equity"]
    years = (datetime.fromisoformat(metrics["end"])-datetime.fromisoformat(metrics["start"])).days/365.25
    return dict(average_cash_weight=sum(cash_weights)/len(cash_weights),
        distribution_entitlement=accrued, price_pnl=price_pnl,
        calmar_calendar=metrics["cagr_calendar"]/metrics["max_drawdown"] if years>=1 and metrics["max_drawdown"] else None,
        volatility_estimate_annualized=stdev(returns)*math.sqrt(252),
        mean_absolute_target_gap=sum(abs(g) for g in gaps)/len(gaps), max_positive_target_gap=max(0., *gaps),
        scheduled_decisions=len(d), skipped_decisions=sum(not v["execute"] for v in d),
        skipped_risk_reductions=sum(not v["execute"] and v["gap"] > 1e-12 and v["close_target_units"] < v["current_units"] for v in d))


def run(output):
    if output.exists():
        raise FileExistsError("preserve_previous_results")
    source = INPUT / "inputs/long-equity"
    contract = json.loads((ROOT / "config/dual-engine-optimization-20261004.json").read_text())
    long, _ = prior.load_equity(source, contract)
    cache = cash.raw_cache(source)
    policy = cash.payment_policy(cache, long.dates, cash.bil_distributions(cash.XLSX), 5)
    long_panels, long_actions, _ = cash.ledger.normalize_cache(cache, policy, execution_symbols=cash.SYMBOLS, issuer_groups={"SMH": "vaneck"})
    recent = prior.recent_panel(CASH_INPUT / "market-cache/yahoo-public", end="2026-10-23")
    recent_cache = {s: json.loads((CASH_INPUT / "market-cache/yahoo-public" / (s + "-1d.json")).read_text()) for s in cache}
    recent_policy = json.loads((ROOT / "state/research_runs/g20_cash_carriers_20261026_final/summary.json").read_text())["dividend_policy"]
    recent_panels, recent_actions, _ = cash.ledger.normalize_cache(recent_cache, recent_policy, execution_symbols=cash.SYMBOLS, issuer_groups={"SMH": "vaneck"})
    retained_long = json.loads((ROOT / "state/research_runs/g20_long_cash_20261026_reviewed/results.json").read_text())["runs"]
    retained_recent = json.loads((ROOT / "state/research_runs/g20_cash_carriers_20261026_final/results.json").read_text())["runs"]
    result = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Skip small rebalances using decision-close shares/weights, preserving original selection and risk targets.",
        case_parameters={k:dict(friction=asdict(f),delay=d) for k,(f,d) in CASES.items()},
        primary="risk_units is parameter-free; add_band/symmetric_band use one fixed absolute 1pp capital band, not optimized.",
        posthoc_sensitivity="After the 1pp mechanism comparison, add only 0.5pp/2pp symmetric neighbors at $10000. Diagnostic only; retain 1pp as the reference, do not select the best threshold.",
        assumptions=dict(band=.01, minimum_commission_is_scenario_not_broker_tariff=True,
            per_share_commission_reference="https://www.interactivebrokers.com/en/pricing/commissions-stocks.php",
            per_share_scope="IBKR Pro Fixed US commission formula only: .005/share, min $1, max 1% notional; extra 15/30bp slippage, no claim of full regulatory/FX/other broker charges.",
            long_nonbil_payment_lag=5, long_BIL_amount_conflict="issuer zero baseline retained",
            recent_payments="previous verified policy", personal_tax="gross_before_personal_tax", cash_apr=0),
        caveats=["All history consumed; long/recent overlap and are not independent OOS.",
            "Long non-BIL payments remain assumed, BIL 2022-03-01 amount conflict remains unresolved.",
            "No next-open quote is available to the close-time decision; gaps can change affordable shares.",
            "1pp band is a mechanism assumption, not an optimized risk limit or hard volatility guarantee."],
        checks=dict(cash_books=0, retained_controls=0), runs={}, diagnostics={})
    for window, panel, panels, actions, start in (("long", long, long_panels, long_actions, "2018-04-02"),
                                                 ("recent", recent, recent_panels, recent_actions, "2026-01-02")):
        for capital in (1000., 10000.):
            for case, (friction, delay) in CASES.items():
                variants = {**RULES, **({k: ("weekly_cap15", "symmetric_band") for k in NEIGHBORS} if capital == 10000 else {})}
                for label, (rule, mode) in variants.items():
                    targets = schedule(panel, rule)
                    selector = partial(rebalance_decision, mode=mode, band=NEIGHBORS.get(label, .01)) if mode else None
                    r = cash.simulate(panel, panels, actions, targets, capital=capital, friction=friction, delay=delay,
                        start=start, decision_filter=selector)
                    if mode is None:
                        old = None
                        if case not in ("base", "commission1", "strict"):
                            pass
                        elif window == "long":
                            suffix = {"base": "gross_lag5", "commission1": "commission1", "strict": "strict"}[case]
                            old = retained_long.get(f"{rule}-original-{int(capital)}-{suffix}")
                        else:
                            suffix = {"base": "integer20", "commission1": "integer20_floor1", "strict": "integer40_floor1_delay2"}[case]
                            old = retained_recent[f"{rule}-original-{int(capital)}-{suffix}"]
                        if old is not None:
                            assert r["records"] == old["records"]
                            result["checks"]["retained_controls"] += 1
                    r["metrics"].update(tracking_metrics(r, panel, targets))
                    if window == "recent":
                        r["metrics"].pop("cagr_calendar")
                    result["runs"][f"{window}-{int(capital)}-{case}-{label}"] = r
                    result["checks"]["cash_books"] += 1
                print(window, int(capital), case, "done", flush=True)
    for case in CASES:
        original = result["runs"][f"long-10000-{case}-dynamic"]
        for mode in (*MODES, *NEIGHBORS):
            result["diagnostics"][f"{case}-{mode}"] = cash.paired_diagnostics(original, result["runs"][f"long-10000-{case}-{mode}"])
    paths = [Path(__file__), ROOT / "src/qount/research/g20_rebalance.py", ROOT / "scripts/research/compare_g20_long_cash.py",
        ROOT / "src/qount/research/g20_cash_execution.py", ROOT / "src/qount/dual_engine/g20_cash.py", cash.XLSX,
        ROOT / "src/qount/dual_engine/paper.py", ROOT / "src/qount/dual_engine/contracts.py",
        ROOT / "scripts/research/compare_g20_fixed_budget.py", ROOT / "scripts/research/analyze_g20_risk_budget.py",
        ROOT / "config/dual-engine-optimization-20261004.json", *source.glob("*.json"),
        *(CASH_INPUT / "market-cache/yahoo-public").glob("*.json")]
    result["source_hashes"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output.mkdir(parents=True)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
    (output / "summary.json").write_text(json.dumps({**result, "runs": {k: v["metrics"] for k, v in result["runs"].items()}}, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps(result["checks"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
