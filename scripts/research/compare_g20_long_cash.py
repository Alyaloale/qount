"""Long-window cash sensitivity: issuer BIL payments, explicit other-payment assumptions."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from datetime import datetime, time
from functools import partial
import hashlib
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np

import analyze_g20_risk_budget as prior
from compare_g20_fixed_budget import ROOT, INPUT, CASH_INPUT, schedule
from compare_g20_cash_carriers import SYMBOLS
from qount.dual_engine import g20_cash as ledger
from qount.contracts import canonical_hash
from qount.research.g20_cash_execution import CashFriction, rebalance_cash
from qount.research.g20_carriers import proxy_schedule

XLSX = ROOT / "state/research_runs/g20_cash_repair_20261025/sources/ssga-distributions.xlsx"
BIL_SOURCE = "https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx"
CASES = {
    "gross_lag5": (5, 1., CashFriction(), 1),
    "gross_lag10": (10, 1., CashFriction(), 1),
    "nonbil_unpaid": (None, 1., CashFriction(), 1),
    "commission1": (5, 1., CashFriction(minimum_commission=1.), 1),
    "strict": (5, 1., CashFriction(cost_bps=40, commission_bps=10, minimum_commission=1.), 2),
    "retain70": (5, .7, CashFriction(), 1),
    "bil_amount_conflicts": (5, 1., CashFriction(), 1),
}


def bil_distributions(path, *, start="2017-09-01", end="2026-07-30"):
    """Read the saved issuer XLSX using only the standard library, preserving physical amounts."""
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(path) as archive:
        strings = ["".join(t.itertext()) for t in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", ns)]
        rows = ET.fromstring(archive.read("xl/worksheets/sheet1.xml")).findall(".//s:row", ns)
    found = {}
    for row in rows:
        cells = {}
        for cell in row:
            value = cell.find("s:v", ns)
            cells[cell.get("r").rstrip("0123456789")] = (
                strings[int(value.text)] if cell.get("t") == "s" else value.text) if value is not None else ""
        if cells.get("B") != "BIL":
            continue
        ex, pay = (datetime.strptime(cells[k], "%m/%d/%Y").date().isoformat() for k in ("D", "F"))
        # Validate the research period; an unrelated 2008 source-row date error
        # must not be silently repaired or imported into this 2017+ experiment.
        if not start <= ex <= end:
            continue
        amount = sum(float(cells.get(k) or 0) for k in ("G", "H", "I"))
        if ex in found or not math.isfinite(amount) or amount < 0 or pay < ex:
            raise ValueError("BIL_issuer_distribution_invalid")
        found[ex] = dict(symbol="BIL", ex_date=ex, pay_date=pay, amount=amount, source=BIL_SOURCE)
    if not found:
        raise ValueError("BIL_history_incomplete")
    return found


def raw_cache(root):
    out = {}
    for symbol in sorted({*SYMBOLS, *ledger.G20_PROXY_SYMBOLS}):
        node = json.loads((root / (symbol + ".source.json")).read_text())["chart"]["result"][0]
        if node["meta"]["symbol"] != symbol:
            raise ValueError("cash_source_identity_invalid")
        quote = node["indicators"]["quote"][0]
        adjusted = node["indicators"]["adjclose"][0]["adjclose"]
        out[symbol] = dict(rows=[dict(date=datetime.fromtimestamp(stamp, ledger.NY).date().isoformat(),
            **{k: quote[k][i] for k in ("open", "high", "low", "close")}, adjClose=adjusted[i])
            for i, stamp in enumerate(node["timestamp"])], events=node.get("events", {}))
    return out


def payment_policy(cache, dates, issuer, lag):
    """BIL dates are observed. All other dates remain declared scenario assumptions."""
    dates = tuple(dates)
    for event in cache.get("BIL", {}).get("events", {}).get("dividends", {}).values():
        day = datetime.fromtimestamp(event["date"], ledger.NY).date().isoformat()
        if dates[0] <= day <= dates[-1] and day not in issuer:
            raise ValueError("BIL_issuer_pay_date_missing")
    if any(dates[0] <= d <= dates[-1] and v["amount"] > 0 and d not in dates for d, v in issuer.items()):
        raise ValueError("BIL_issuer_nontrading_ex_date")
    pay = {}
    for value in cache.values():
        for event in value.get("events", {}).get("dividends", {}).values():
            day = datetime.fromtimestamp(event["date"], ledger.NY).date().isoformat()
            j = bisect_left(dates, day)
            pay[day] = dates[j + lag] if lag is not None and j + lag < len(dates) else None
    return dict(verified_actions=[v for d, v in sorted(issuer.items()) if dates[0] <= d <= dates[-1]],
        sources={"BIL": BIL_SOURCE, **{g: "ASSUMED_payment_session_offset_not_issuer_verified"
            for g in ("direxion", "proshares", "vaneck")}},
        pay_dates={g: dict(pay) for g in ("direxion", "proshares", "vaneck")})


def bil_amount_conflicts(cache, issuer, *, rounding_tolerance=.0011):
    """Compare physical share amounts; preserve disagreement instead of silently repairing sources."""
    events = cache["BIL"].get("events", {})
    splits = [(datetime.fromtimestamp(e["date"], ledger.NY).date().isoformat(),
               float(e["numerator"]) / float(e["denominator"])) for e in events.get("splits", {}).values()]
    found = []
    for e in events.get("dividends", {}).values():
        day = datetime.fromtimestamp(e["date"], ledger.NY).date().isoformat()
        value = float(e["amount"]) * math.prod(r for d, r in splits if day < d)
        if day in issuer and abs(value - issuer[day]["amount"]) > rounding_tolerance:
            found.append(dict(ex_date=day, issuer_amount=issuer[day]["amount"], yahoo_physical_amount=value,
                issuer_pay_date=issuer[day]["pay_date"], status="unresolved_source_amount_conflict"))
    return sorted(found, key=lambda r: r["ex_date"])


def simulate(panel, panels, actions, targets, *, capital, friction, delay, start="2018-04-02", decision_filter=None):
    """Stream unchanged cash-step calculations; keep full history outside ephemeral snapshots."""
    first = next(i for i, d in enumerate(panel.dates) if d >= start)
    data = ledger.new_account("2026-10-26T00:00:00+00:00")
    data["initial_equity"] = data["layer"]["sleeves"]["g20"]["cash"] = capital
    records, trades, income = [], [], []
    decisions = []
    plans = targets if decision_filter is None else {i: t for i, t in targets.items() if i < first}
    if decision_filter is not None:
        from qount.research.g20_rebalance import selected_symbol
        known = [j for j in targets if j < first]
        previous_symbol = selected_symbol(targets[max(known)]) if known else None
    rebalancer = partial(rebalance_cash, friction=friction)
    for i in range(first, len(panel.dates)):
        day = panel.dates[i]
        j = i - delay
        if j in plans:
            data["pending"] = dict(target=plans[j], decision_date=panel.dates[j],
                available_at=datetime.combine(datetime.fromisoformat(panel.dates[j]), time(16), ledger.NY).isoformat())
        data = ledger.step(data, day=day, bar={s: panels[s][day] for s in SYMBOLS},
            actions=actions.get(day, []), decision=None,
            opening=datetime.combine(datetime.fromisoformat(day), time(9, 30), ledger.NY),
            observed_at="2026-10-26T00:00:00+00:00", reconstructed=True, historical_replay=True,
            execution_symbols=SYMBOLS, rebalance=rebalancer)
        if decision_filter is not None and i in targets:
            sleeve = data["layer"]["sleeves"]["g20"]
            decision = decision_filter(target=targets[i], positions=sleeve["positions"], cash=sleeve["cash"],
                prices={s: panels[s][day]["close"] for s in SYMBOLS}, previous_symbol=previous_symbol)
            decisions.append(dict(date=day, **decision))
            previous_symbol = decision["selected"]
            if decision["execute"]:
                plans[i] = targets[i]
        for key, history in (("observations", records), ("trades", trades), ("income", income)):
            history.extend(data[key])
            data[key] = []
        # This bounded snapshot is never published as a paper account/history.
        data["state_hash"] = canonical_hash({k: v for k, v in data.items() if k != "state_hash"})
    peak, dd, risk = capital, 0., []
    for r in records:
        peak = max(peak, r["equity"])
        dd = max(dd, 1 - r["equity"] / peak)
        risk.append(sum(p["weight"] for p in r["positions"] if p["symbol"] not in ("BIL", "DIVIDEND_RECEIVABLE")))
    cash, held, costs = capital, {}, 0.
    split_entitlements = []
    for t in trades:
        if t["side"] == "CORPORATE_ACTION_SPLIT":
            held[t["symbol"]] = held.get(t["symbol"], 0.) * t["split_ratio"]
            split_entitlements.append(t)
            continue
        assert t["decision_date"] < t["date"]
        assert math.isclose(t["quantity"], round(t["quantity"]), abs_tol=1e-8)
        assert math.isclose(t["cost"], friction.fee(t["quantity"] * t["price"], t["quantity"]), abs_tol=1e-8)
        sign = 1 if t["side"] == "BUY" else -1
        held[t["symbol"]] = held.get(t["symbol"], 0.) + sign * t["quantity"]
        cash -= sign * t["quantity"] * t["price"] + t["cost"]
        costs += t["cost"]
    paid = sum(e["value"] for e in income if e["side"] == "DIVIDEND_PAYMENT")
    assert math.isclose(cash + paid, records[-1]["cash"], abs_tol=1e-6)
    assert math.isclose(costs, data["layer"]["cumulative_cost"], abs_tol=1e-7)
    assert math.isclose(paid, data["distributions_received"], abs_tol=1e-7)
    for s in set(held) | set(data["layer"]["sleeves"]["g20"]["positions"]):
        assert math.isclose(held.get(s, 0.), data["layer"]["sleeves"]["g20"]["positions"].get(s, 0.), abs_tol=1e-7)
    years = (datetime.fromisoformat(records[-1]["date"]) - datetime.fromisoformat(records[0]["date"])).days / 365.25
    nav = records[-1]["equity"] / capital
    annual = {}
    for y in sorted({r["date"][:4] for r in records}):
        group = [i for i, r in enumerate(records) if r["date"].startswith(y)]
        a, b = group[0], group[-1]
        annual[y] = records[b]["equity"] / (records[a - 1]["equity"] if a else capital) - 1
    metrics = dict(capital=capital, start=records[0]["date"], end=records[-1]["date"],
        total_return=nav - 1, cagr_calendar=nav ** (1 / years) - 1, max_drawdown=dd,
        final_equity=records[-1]["equity"], average_risk_weight=sum(risk) / len(risk),
        trade_count=sum(t["side"] != "CORPORATE_ACTION_SPLIT" for t in trades), cost=costs,
        dividends_paid=paid, receivable=records[-1]["receivable"],
        gross_entitlement=sum(e["quantity"] * e.get("gross_amount", e["amount"]) for e in income if e["side"] == "DIVIDEND_ACCRUAL"),
        entitlement_deduction=sum(e["quantity"] * (e.get("gross_amount", e["amount"]) - e["amount"]) for e in income if e["side"] == "DIVIDEND_ACCRUAL"),
        split_count=len(split_entitlements), annual_returns=annual)
    result = dict(metrics=metrics, records=records, trades=trades, income=income)
    if decision_filter is not None:
        result["decisions"] = decisions
    return result


def paired_diagnostics(original, candidate, *, draws=1000):
    """Paired log-return concentration/blocks; deleting terms does not retrade an account."""
    a, b = original["records"], candidate["records"]
    if [r["date"] for r in a] != [r["date"] for r in b] or not a:
        raise ValueError("paired_cash_calendar_invalid")
    left = np.diff(np.log([original["metrics"]["capital"]] + [r["equity"] for r in a]))
    right = np.diff(np.log([candidate["metrics"]["capital"]] + [r["equity"] for r in b]))
    diff = right - left
    years = sorted({r["date"][:4] for r in a})
    by_year = {y: float(sum(v for r, v in zip(a, diff) if r["date"].startswith(y))) for y in years}
    intervals = {}
    for block in (40, 120):
        if len(diff) < block:
            continue
        rng = np.random.default_rng(20261026 + block)
        estimates = []
        for _ in range(draws):
            starts = rng.integers(0, len(diff) - block + 1, (len(diff) + block - 1) // block)
            sample = np.concatenate([diff[j:j + block] for j in starts])[:len(diff)]
            estimates.append(float(np.mean(sample) * 252 * 100))
        intervals[str(block)] = [float(v) for v in np.quantile(estimates, [.025, .975])]
    return dict(independent_oos=False, draws=draws,
        annual_log_return_difference_pct=float(np.mean(diff) * 252 * 100),
        paired_block_95pct=intervals, cumulative_log_difference=float(sum(diff)),
        contribution_by_year=by_year,
        leave_year_terms_out={y: float(sum(diff) - value) for y, value in by_year.items()},
        note="Continuous-account return-term diagnostics only; not retraded portfolios or independent OOS.")


def run(output):
    if output.exists():
        raise FileExistsError("preserve_previous_results")
    source = INPUT / "inputs/long-equity"
    contract = json.loads((ROOT / "config/dual-engine-optimization-20261004.json").read_text())
    panel, audit = prior.load_equity(source, contract)
    cache, issuer = raw_cache(source), bil_distributions(XLSX)
    conflicts = bil_amount_conflicts(cache, issuer)
    result = dict(research_only=True, orders_authorized=False, independent_oos=False,
        scope="Assumption-sensitive long cash research; only BIL payments verified. Not full issuer/broker cash certification.",
        source_audit=audit, BIL_issuer_records=len(issuer),
        BIL_positive_records=sum(v["amount"] > 0 for v in issuer.values()),
        BIL_amount_conflicts=conflicts,
        cases={k: dict(nonbil_lag_sessions=lag, distribution_retention=keep, cost_bps=f.cost_bps,
            commission_bps=f.commission_bps, minimum_commission=f.minimum_commission, delay=d)
            for k, (lag, keep, f, d) in CASES.items()},
        caveats=["Non-BIL payable dates are assumed, not historically observed; 5/10 sessions are sensitivities, not verified bounds.",
            "retain70 is a hypothetical uniform distribution haircut, not a legal tax rate or personal after-tax estimate.",
            "Splits producing fractional shares fail; no invented cash-in-lieu value or payment date.",
            "BIL baseline retains saved issuer amounts, including any unresolved amount conflict; a separate Yahoo-amount sensitivity keeps issuer payment dates.",
            "No FX, full broker settlement, auction-depth, actual fills or independent OOS certification."],
        checks=dict(long_cash_books=0, recent_control_books=0), runs={})
    schedules = {}
    for rule in ("monthly20", "monthly15", "weekly_cap15"):
        original = schedule(panel, rule)
        proxy, _ = proxy_schedule(panel.dates, panel.total_closes, original)
        schedules[rule] = {"original": original, "SMH": {i: proxy[i] if t.get("SOXL", 0) else t for i, t in original.items()}}
    for label, (lag, keep, friction, delay) in CASES.items():
        policy = payment_policy(cache, panel.dates, issuer, lag)
        if label == "bil_amount_conflicts":
            replacements = {r["ex_date"]: r["yahoo_physical_amount"] for r in conflicts}
            for a in policy["verified_actions"]:
                if a["ex_date"] in replacements:
                    a["amount"] = replacements[a["ex_date"]]
                    a["source"] = "Yahoo_amount_conflict_sensitivity_not_resolved"
        panels, actions, dates = ledger.normalize_cache(cache, policy, execution_symbols=SYMBOLS, issuer_groups={"SMH": "vaneck"})
        assert tuple(dates) == panel.dates
        for events in actions.values():
            for a in events:
                if a["kind"] == "dividend":
                    a["gross_amount"] = a["amount"]
                    a["amount"] *= keep
        for rule, variants in schedules.items():
            for capital in ((1000., 10000.) if label == "gross_lag5" else (10000.,)):
                for name, targets in variants.items():
                    key = f"{rule}-{name}-{int(capital)}-{label}"
                    result["runs"][key] = simulate(panel, panels, actions, targets,
                        capital=capital, friction=friction, delay=delay)
                    result["checks"]["long_cash_books"] += 1
        print(label, "done", flush=True)
    result["paired_diagnostics"] = {}
    for rule in schedules:
        for label in ("gross_lag5", "strict"):
            result["paired_diagnostics"][f"{rule}-{label}"] = paired_diagnostics(
                result["runs"][f"{rule}-original-10000-{label}"],
                result["runs"][f"{rule}-SMH-10000-{label}"])
    # Prove streaming is accounting-equivalent to the prior full-history implementation.
    previous = json.loads((ROOT / "state/research_runs/g20_fixed_budget_20261025_final/results.json").read_text())["cash"]
    recent = prior.recent_panel(CASH_INPUT / "market-cache/yahoo-public", end="2026-10-23")
    recent_cache = {s: json.loads((CASH_INPUT / "market-cache/yahoo-public" / (s + "-1d.json")).read_text()) for s in cache}
    policy = json.loads((ROOT / "state/research_runs/g20_cash_carriers_20261026_final/summary.json").read_text())["dividend_policy"]
    panels, actions, _ = ledger.normalize_cache(recent_cache, policy, execution_symbols=SYMBOLS, issuer_groups={"SMH": "vaneck"})
    for old in previous:
        if old["capital"] not in (1000, 10000) or old["rule"] not in schedules:
            continue
        r = simulate(recent, panels, actions, schedule(recent, old["rule"]), capital=old["capital"], friction=CashFriction(), delay=1, start="2026-01-02")
        assert [(v["date"], v["equity"]) for v in r["records"]] == [(v["date"], v["equity"]) for v in old["records"]]
        result["checks"]["recent_control_books"] += 1
    paths = [Path(__file__), XLSX, ROOT / "src/qount/dual_engine/g20_cash.py", ROOT / "src/qount/research/g20_cash_execution.py",
        ROOT / "src/qount/research/g20_carriers.py", ROOT / "scripts/research/compare_g20_fixed_budget.py",
        ROOT / "scripts/research/analyze_g20_risk_budget.py", ROOT / "config/dual-engine-optimization-20261004.json",
        ROOT / "scripts/research/compare_g20_cash_carriers.py", ROOT / "src/qount/dual_engine/contracts.py",
        ROOT / "src/qount/dual_engine/paper.py", ROOT / "src/qount/research/dual_engine_optimization.py", *source.glob("*.json")]
    result["source_hashes"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output.mkdir(parents=True)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
    (output / "summary.json").write_text(json.dumps({**result, "runs": {k: v["metrics"] for k, v in result["runs"].items()}}, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps(result["checks"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
