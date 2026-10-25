"""Attribute the frozen G20 paper book and compare one bounded risk-cap hypothesis."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import correlation, stdev
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY  # noqa: E402
from qount.research.dual_engine_optimization import EquityPanel, g20_signals, load_equity  # noqa: E402
from qount.research.dual_engine_structural import replay_units  # noqa: E402
from qount.research.dual_engine_execution_verify import independent_metrics  # noqa: E402
from qount.research.etf_risk_budget import summarize  # noqa: E402


RULES = ("monthly20", "weekly20", "weekly_cap15", "tqqq20", "qqq60", "qqq_vol15")


def recent_panel(root: Path, end="2026-10-09") -> EquityPanel:
    rows = {}
    for symbol in sorted({*G20_EXECUTION_TO_PROXY, *G20_EXECUTION_TO_PROXY.values(), "BIL"}):
        body = json.loads((root / f"{symbol}-1d.json").read_text())
        series = {}
        for r in body["rows"]:
            if r["date"] > end:
                continue
            o, c, a = (float(r[k]) for k in ("open", "close", "adjClose"))
            if not all(math.isfinite(x) and x > 0 for x in (o, c, a)):
                raise ValueError(f"invalid_price:{symbol}:{r['date']}")
            if r["date"] in series:
                raise ValueError("duplicate_session")
            series[r["date"]] = (c, a, o * a / c)
        rows[symbol] = series
    # Cache requests began one calendar day apart; trim only their warm-up prefix.
    first_common = max(min(v) for v in rows.values())
    rows = {s: {d:v for d,v in series.items() if d >= first_common} for s,series in rows.items()}
    dates = tuple(sorted(rows["QQQ"]))
    if any(set(v) != set(dates) for v in rows.values()):
        raise ValueError("recent_calendar_mismatch")
    return EquityPanel(dates, *({s: tuple(v[d][i] for d in dates) for s, v in rows.items()} for i in range(3)))


def monthly_signals(panel: EquityPanel, *, basis="adjusted") -> dict:
    if basis not in ("adjusted", "raw"):
        raise ValueError("unknown_signal_basis")
    signal_panel = panel if basis == "raw" else EquityPanel(
        panel.dates, panel.total_closes, panel.total_closes, panel.total_opens)
    return g20_signals(signal_panel)


def targets(panel: EquityPanel, rule: str) -> dict:
    if rule not in RULES:
        raise ValueError("unknown_rule")
    # Production uses adjClose, including distributions; old discovery used raw close.
    monthly = monthly_signals(panel)
    if rule == "monthly20":
        return {i: v["target"] for i, v in monthly.items()}
    result, selected, week = {}, None, None
    for i, day in enumerate(panel.dates):
        current_week = datetime.fromisoformat(day).isocalendar()[:2]
        new_week = current_week != week
        week = current_week
        if i in monthly:
            selected = monthly[i]["selected"]
        if i < 63 or selected is None:
            continue
        if rule in ("tqqq20", "qqq60"):
            if i in monthly:
                symbol, weight = ("TQQQ", .2) if rule == "tqqq20" else ("QQQ", .6)
                result[i] = {symbol: weight, "BIL": 1 - weight}
            continue
        if not (new_week or i in monthly):
            continue
        symbol = "QQQ" if rule == "qqq_vol15" else selected
        maximum = 1.0 if rule == "qqq_vol15" else .2
        values = panel.total_closes[symbol]
        sigma = stdev(values[j] / values[j - 1] - 1 for j in range(i - 19, i + 1)) * math.sqrt(252)
        weight = maximum if rule == "weekly20" else min(maximum, .15 / sigma) if sigma else maximum
        result[i] = {symbol: weight, "BIL": 1 - weight}
    return result


def prices(panel):
    closes = {s: dict(zip(panel.dates, v)) for s, v in panel.total_closes.items()}
    opens = {s: dict(zip(panel.dates, v)) for s, v in panel.total_opens.items()}
    return closes, opens


def metrics(run):
    records = run["records"]
    m = independent_metrics([r["return"] for r in records], 252, [r["cash_return"] for r in records])
    years = (datetime.fromisoformat(records[-1]["date"]) - datetime.fromisoformat(records[0]["date"])).days / 365.25
    m.update(first=records[0]["date"], last=records[-1]["date"],
             cagr_calendar=(1 + m["total_return"]) ** (1 / years) - 1,
             average_risk_weight=sum(r["risk_gross"] for r in records) / len(records),
             annual_turnover=sum(r["turnover"] for r in records) / years,
             trade_sessions=sum(r["turnover"] > 1e-12 for r in records))
    m["calmar_calendar"] = m["cagr_calendar"] / -m["max_drawdown"] if m["max_drawdown"] else None
    return m


def slice_metrics(records, start, end):
    rows = [r for r in records if start <= r["date"] <= end]
    return independent_metrics([r["return"] for r in rows], 252, [r["cash_return"] for r in rows])


def equal_capital_combination(left, right):
    """Two independently funded sleeves, half initial capital each, no transfers.

    Child account fees are already in NAV. Scaling these fractional unit books
    preserves self financing; this is not a continuously fixed 50/50 allocation.
    """
    if [r["date"] for r in left] != [r["date"] for r in right]:
        raise ValueError("combination_date_mismatch")
    previous, returns, nav, risk_weights = 1.0, [], [], []
    for a, b in zip(left, right):
        value = (a["nav"] + b["nav"]) / 2
        returns.append(value / previous - 1)
        previous = value
        nav.append(dict(date=a["date"], nav=value))
        risk_weights.append((a["nav"] * a["risk_gross"] + b["nav"] * b["risk_gross"]) / (2 * value))
    m = independent_metrics(returns, 252, [r["cash_return"] for r in left])
    years = (datetime.fromisoformat(left[-1]["date"]) - datetime.fromisoformat(left[0]["date"])).days / 365.25
    m["cagr_calendar"] = (1 + m["total_return"]) ** (1 / years) - 1
    m["calmar_calendar"] = m["cagr_calendar"] / -m["max_drawdown"] if m["max_drawdown"] else None
    m["average_risk_weight"] = sum(risk_weights) / len(risk_weights)
    return dict(metrics=m, nav=nav,
                cash_excess_correlation=correlation([r["return"] - r["cash_return"] for r in left],
                                                     [r["return"] - r["cash_return"] for r in right]),
                final_left_capital_fraction=left[-1]["nav"] / (left[-1]["nav"] + right[-1]["nav"]),
                selection_note="Added after individual results; one fixed initial 50/50 ratio, no optimization, no rebalancing.")


def paper_review(snapshot, state, bil_cache):
    g = next(p for p in snapshot["portfolios"] if p["portfolio_id"] == "dual-engine-paper-g20")
    events = g["rebalances"]["events"]
    contributions, fees, quantities = {}, {}, {}
    cash = float(g["initial_capital"])
    for event in events:
        for f in event["fills"]:
            s = f["symbol"]
            sign = 1 if f["side"] == "buy" else -1
            quantities[s] = quantities.get(s, 0.0) + sign * f["quantity"]
            amount = -sign * f["notional"] - f["cost"]
            contributions[s] = contributions.get(s, 0.0) + amount
            fees[s] = fees.get(s, 0.0) + f["cost"]
            cash += amount
    for h in g["holdings"]:
        assert math.isclose(quantities[h["symbol"]], h["quantity"], abs_tol=1e-9)
        contributions[h["symbol"]] += h["market_value"]
    assert math.isclose(cash, g["allocation"]["cash"], abs_tol=1e-7)
    profit = g["nav"]["executable_equity"] if "executable_equity" in g["nav"] else g["nav"]["executable"] * 10000
    profit -= 10000
    assert math.isclose(sum(contributions.values()), profit, abs_tol=1e-7)
    history = state["portfolios"]["dual-engine-paper-g20"]["history"]
    windows = {}
    for label, start in (("ytd", "2026-01-01"), ("june_onward", "2026-06-01"),
                         ("august_deployment_onward", "2026-08-03")):
        before = [r for r in history if r["marked_at"] < start]
        initial = before[-1]["executable_equity"] if before else 10000
        rows = [dict(date=r["marked_at"][:10].replace("-", ""), equity=r["executable_equity"], weight=0)
                for r in history if r["marked_at"] >= start]
        m = summarize(rows, initial)
        windows[label] = dict(anchor=before[-1]["marked_at"] if before else "initial_capital",
                             anchor_equity=initial, total_return_pct=m["total_return_pct"],
                             max_drawdown_pct=m["max_drawdown_pct"])
    june_quantities, june_cash = {}, 10000.0
    for event in events:
        if event["observed_at"] >= "2026-06-01":
            continue
        for f in event["fills"]:
            sign = 1 if f["side"] == "buy" else -1
            june_quantities[f["symbol"]] = june_quantities.get(f["symbol"], 0.0) + sign * f["quantity"]
            june_cash -= sign * f["notional"] + f["cost"]
    june_marks = {s:q * next(b["close"] for b in reversed(snapshot["market_charts"]["bars_by_symbol"][s])
                                  if b["marked_at"][:10] < "2026-06-01")
                  for s,q in june_quantities.items() if q}
    june_equity = windows["june_onward"]["anchor_equity"]
    assert math.isclose(june_cash + sum(june_marks.values()), june_equity, abs_tol=1e-7)
    june_pnl = {s:-v for s,v in june_marks.items()}
    for event in events:
        if event["observed_at"] < "2026-06-01":
            continue
        for f in event["fills"]:
            sign = 1 if f["side"] == "buy" else -1
            june_pnl[f["symbol"]] = june_pnl.get(f["symbol"], 0.0) - sign * f["notional"] - f["cost"]
    for h in g["holdings"]:
        june_pnl[h["symbol"]] = june_pnl.get(h["symbol"], 0.0) + h["market_value"]
    assert math.isclose(sum(june_pnl.values()), profit + 10000 - june_equity, abs_tol=1e-7)
    dividend_entitlements = []
    dividends = bil_cache["events"]["dividends"].values()
    for dividend in sorted(dividends, key=lambda d: d["date"]):
        ex_date = datetime.fromtimestamp(dividend["date"], timezone.utc).date().isoformat()
        if not "2026-01-02" < ex_date <= snapshot["data_cutoff"][:10]:
            continue
        quantity = sum((1 if f["side"] == "buy" else -1) * f["quantity"]
                       for e in events if e["observed_at"][:10] < ex_date
                       for f in e["fills"] if f["symbol"] == "BIL")
        dividend_entitlements.append(dict(ex_date=ex_date, quantity=quantity,
                                          per_share=dividend["amount"], entitlement=quantity * dividend["amount"]))
    return dict(generated_at=snapshot["generated_at"], data_cutoff=snapshot["data_cutoff"],
                profit=profit, contribution_by_asset=contributions, fees_by_asset=fees,
                cash_reconciled_without_dividends=cash, windows=windows,
                june_onward_contribution_by_asset=june_pnl,
                may_end_actual_risk_weight=sum(v for s,v in june_marks.items() if s != "BIL") / june_equity,
                bil_fixed_path_dividend_entitlements=dividend_entitlements,
                bil_fixed_path_entitlement_total=sum(d["entitlement"] for d in dividend_entitlements),
                entitlement_is_not_executable_return_correction=True,
                point_count=len(history), rebalances=events)


def run(root: Path, output: Path):
    if output.exists():
        raise FileExistsError("use_new_result_directory")
    inputs = root / "inputs"
    contract = json.loads((ROOT / "config/dual-engine-optimization-20261004.json").read_text())
    long_panel, audit = load_equity(inputs / "long-equity", contract)
    recent = recent_panel(inputs / "recent-equity")
    snapshot = json.loads((inputs / "paper-snapshot.json").read_text())
    state = json.loads((inputs / "paper-state.json").read_text())
    result = dict(research_only=True, orders_authorized=False, independent_oos=False,
                  hypothesis="15% risk cap, 20-session actual carrier volatility, never exceed original 20% target; isolate weekly reset",
                  generated_at=datetime.now(timezone.utc).isoformat(),
                  paper=paper_review(snapshot, state, json.loads((inputs / "recent-equity/BIL-1d.json").read_text())),
                  signal_basis="adjusted_close_like_production", panels={},
                  previous_control_reproduction={}, selector_basis_differences={},
                  combinations={}, nasdaq_etf_same_window={})
    old = json.loads((ROOT / "state/research_runs/dual_engine_structural_20261004/results.json").read_text())
    for name, panel, start in (("long", long_panel, "2018-04-02"), ("recent", recent, "2026-01-02")):
        closes, opens = prices(panel)
        runs = {}
        raw, adjusted = monthly_signals(panel, basis="raw"), monthly_signals(panel)
        result["selector_basis_differences"][name] = [dict(signal_date=panel.dates[i],
            raw=raw[i]["selected"], adjusted=adjusted[i]["selected"])
            for i in raw if i in adjusted and raw[i]["selected"] != adjusted[i]["selected"]]
        for cost in (20, 40):
            for delay in (1, 2):
                for rule in RULES:
                    schedule = targets(panel, rule)
                    first = next(i for i,d in enumerate(panel.dates) if d >= start)
                    # Same fresh-cash convention as the retained G20 control.
                    schedule.setdefault(first - delay, {"BIL": 1.0})
                    replay = replay_units(panel.dates, closes, opens, schedule,
                                          start=start, lag=delay, cost_bps=cost, cash_asset="BIL")
                    key = f"{rule}-c{cost}-d{delay}"
                    m = metrics(replay)
                    runs[key] = dict(metrics=m,
                        annual={y: slice_metrics(replay["records"], f"{y}-01-01", f"{y}-12-31")
                                for y in sorted({r["date"][:4] for r in replay["records"]})},
                        records=replay["records"])
                    if name == "long" and rule == "monthly20":
                        # Reproduce the original raw-signal control separately, without
                        # conflating it with the production-aligned adjusted selector.
                        raw_schedule = {i:v["target"] for i,v in raw.items()}
                        raw_schedule.setdefault(first - delay, {"BIL": 1.0})
                        raw_run = replay_units(panel.dates, closes, opens, raw_schedule,
                            start=start, lag=delay, cost_bps=cost, cash_asset="BIL")
                        raw_metrics = metrics(raw_run)
                        original = old["summaries"]["g20"]["g20"][f"c{cost}-d{delay}"]
                        diffs = {k: raw_metrics[k] - original[k] for k in ("cagr", "cash_excess_sharpe", "max_drawdown")}
                        if max(abs(v) for v in diffs.values()) > 1e-10:
                            raise AssertionError((key, diffs))
                        result["previous_control_reproduction"][key] = diffs
        result["panels"][name] = runs
        result["combinations"][name] = {f"{rule}-plus-qqq_vol15-c{cost}-d{delay}":
            equal_capital_combination(runs[f"{rule}-c{cost}-d{delay}"]["records"],
                                     runs[f"qqq_vol15-c{cost}-d{delay}"]["records"])
            for rule in ("monthly20", "weekly_cap15") for cost in (20,40) for delay in (1,2)}
    etf = json.loads((ROOT / "state/research_runs/etf_risk_budget_20261025_final/results.json").read_text())
    for start in ("20260101", "20260601", "20260803"):
        result["nasdaq_etf_same_window"][start] = {}
        for policy, replay in etf["primary"]["513100.SH"].items():
            rows = replay["nav"]
            first = next(i for i, r in enumerate(rows) if r["date"] >= start)
            initial = rows[first - 1]["equity"]
            m = summarize(rows[first:], initial)
            result["nasdaq_etf_same_window"][start][policy] = {k:m[k] for k in ("total_return_pct", "max_drawdown_pct")}
    paths = [p for p in inputs.rglob("*.json")] + [Path(__file__),
             ROOT / "src/qount/research/dual_engine_structural.py",
             ROOT / "src/qount/research/dual_engine_optimization.py"]
    result["input_source_hashes"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output.mkdir(parents=True)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    brief = dict(paper=result["paper"], previous_control_reproduction=result["previous_control_reproduction"],
                 selector_basis_differences=result["selector_basis_differences"],
                 combinations={name:{k:{x:y for x,y in v.items() if x != "nav"} for k,v in runs.items()}
                               for name,runs in result["combinations"].items()},
                 panels={name:{k:v["metrics"] for k,v in runs.items()} for name,runs in result["panels"].items()},
                 nasdaq_etf_same_window=result["nasdaq_etf_same_window"])
    (output / "summary.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(output=str(output), scenarios=sum(len(v) for v in result["panels"].values()),
                          paper_profit=result["paper"]["profit"], controls_reproduced=len(result["previous_control_reproduction"])) ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "state/research_runs/g20_risk_synthesis_20261025")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve())
