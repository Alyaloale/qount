"""Recalculate saved ledgers/NAV and check causal signal prefixes, without rerunning returns."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
from collections import Counter
from pathlib import Path

from qount.research.small_account_breakout import MarketData, generate_signals, load_data
from qount.research.small_account_breakout_data import sha, timestamp, write_json


def close(a: float, b: float) -> None:
    if not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8):
        raise AssertionError(f"recalculation_mismatch:{a}:{b}")


def seconds(value: str) -> int:
    return int(dt.datetime.fromisoformat(value).timestamp())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle",type=Path,required=True)
    parser.add_argument("--cache",type=Path,default=Path("state/research_cache/small_account_breakout_v01_20261013"))
    parser.add_argument("--receipt",type=Path,required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise FileExistsError("refuse_overwrite_verification")
    root = args.bundle
    manifest = json.loads((root / "manifest.json").read_text())
    assert (root / "_COMPLETE").read_text().strip() == sha(root / "manifest.json")
    for name,expected in manifest["files"].items():
        assert sha(root / name) == expected
    for name,expected in manifest["source_hashes"].items():
        assert sha(Path(name)) == expected
    cfg = json.loads((root / "config.json").read_text())
    summary = json.loads((root / "summary.json").read_text())
    trade_total = 0
    primary = []
    for path in sorted(root.glob("2026-*.json")):
        run = json.loads(path.read_text())
        s,trades = run["summary"],run["trades"]
        assert s in summary["runs"]
        previous_exit = None
        for row in trades:
            side = 1 if row["side"]=="long" else -1
            entered,exited = seconds(row["entry_time"]),seconds(row["exit_time"])
            assert seconds(row["decision_time"]) < entered <= exited
            assert previous_exit is None or previous_exit < entered
            previous_exit = exited
            close(row["net_pnl_usdt"],side*row["quantity"]*(row["exit_price"]-row["entry_price"])
                  -row["fees_usdt"]+row["funding_net_usdt"])
            close(row["equity_after"]-row["equity_before"],row["net_pnl_usdt"])
            close(row["notional_usdt"],row["quantity"]*row["entry_price"])
            close(row["margin_usdt"],row["notional_usdt"]/row["leverage_setting"])
            close(row["actual_gross"],row["notional_usdt"]/row["equity_before"])
            assert row["margin_usdt"] <= cfg["max_margin_fraction"]*row["equity_before"]+1e-8
            assert row["planned_risk_usdt"] <= row["risk_budget_usdt"]+1e-8
            assert row["liquidation_distance"] >= 3*abs(row["entry_price"]-row["initial_stop"])/row["entry_price"]
            mult = 2 if s["scenario"]=="double_cost" else 1
            fee = row["quantity"]*(row["entry_price"]+row["exit_price"])*cfg[f"{row['market']}_fee_per_side"]*mult
            assert row["exit_reason"] != "liquidation", "extend verifier if liquidation observed"
            close(row["fees_usdt"],fee)
            funding_rows = json.loads((args.cache / f"funding-{row['symbol']}-{s['week_start']}.json").read_text())
            funding_mult = 2 if s["scenario"]=="funding_2x" else 1
            funding = sum(-side*row["quantity"]*float(f["markPrice"])*float(f["fundingRate"])*funding_mult
                          for f in funding_rows if entered < int(f["fundingTime"])//60000*60 <= exited)
            close(row["funding_net_usdt"],funding)
            assert row["risk_contract"]["research_only"] is True
            assert row["risk_contract"]["orders_authorized"] is False
        trade_total += len(trades)
        close(s["final_equity_usdt"],10+sum(row["net_pnl_usdt"] for row in trades))
        with (root / f"{path.stem}_equity.csv").open() as stream:
            curve = list(csv.DictReader(stream))
        assert len(curve)==10080
        peak,mdd = 10.0,0.0
        for row in curve:
            value = float(row["equity_usdt"])
            assert math.isfinite(value)
            peak = max(peak,value)
            mdd = max(mdd,1-value/peak)
        close(s["max_drawdown"],mdd)
        close(s["final_equity_usdt"],float(curve[-1]["equity_usdt"]))
        if s["variant"]=="combined" and s["risk_fraction"]==0.1 and s["scenario"]=="base":
            primary += trades
    assert len(summary["runs"])==65
    prefix_checks,stock_ratios,stock_stops = [],[],[]
    for week in sorted(cfg["draw_order"]):
        data = load_data(args.cache,cfg,week)
        start,cut,end = timestamp(week),timestamp(week)+3*86400,timestamp(week)+7*86400
        full,_ = generate_signals(data,cfg,start,end)
        prefix = MarketData({symbol:{t:bar for t,bar in rows.items() if t+60 <= cut}
                             for symbol,rows in data.minutes.items()}, {},
                            {symbol:[bar for bar in rows if bar.t+3600 <= cut]
                             for symbol,rows in data.hours.items()},data.funding,data.rules,{})
        trimmed,_ = generate_signals(prefix,cfg,start,cut)
        assert [s for s in full if s.decision_time < cut]==trimmed
        prefix_checks.append({"week":week,"signals_checked":len(trimmed),"identical":True})
        for sig in full:
            if sig.market!="stock":
                continue
            now = sig.decision_time+60
            price = data.minutes[sig.symbol][now].o*(1+sig.side*cfg["stock_slippage_per_side"])
            known = [abs(float(f["fundingRate"])) for f in data.funding[sig.symbol]
                     if (now-72*3600)*1000 <= int(f["fundingTime"]) < now*1000]
            cost = 2*(cfg["stock_fee_per_side"]+cfg["stock_slippage_per_side"])+max(known)
            stop = cfg["initial_stop_atr"]*sig.atr/price
            stock_stops.append(stop)
            stock_ratios.append(cost/stop)
    net = sum(row["net_pnl_usdt"] for row in primary)
    costs = sum(row["fees_usdt"]+row["slippage_usdt"]-row["funding_net_usdt"] for row in primary)
    receipt = {"status":"passed","bundle_manifest_sha256":sha(root / "manifest.json"),
        "verifier_sha256":sha(Path(__file__)),"runs_verified":65,"ledger_trades_verified":trade_total,
        "nav_points_verified":65*10080,"causal_prefix_checks":prefix_checks,
        "primary":{"trade_count":len(primary),"wins":sum(row["net_pnl_usdt"]>0 for row in primary),
            "by_symbol":dict(Counter(row["symbol"] for row in primary)),"net_pnl_usdt":net,
            "gross_pnl_before_costs_usdt":net+costs,"total_friction_usdt":costs,
            "fees_usdt":sum(row["fees_usdt"] for row in primary),
            "slippage_usdt":sum(row["slippage_usdt"] for row in primary),
            "funding_net_usdt":sum(row["funding_net_usdt"] for row in primary)},
        "stock_diagnostic":{"raw_signals":len(stock_ratios),
            "friction_gate_passes":sum(r<=cfg["max_friction_to_stop"] for r in stock_ratios),
            "min_friction_to_stop":min(stock_ratios),"max_friction_to_stop":max(stock_ratios),
            "median_friction_to_stop":sorted(stock_ratios)[len(stock_ratios)//2],
            "min_stop_distance":min(stock_stops),"max_stop_distance":max(stock_stops)},
        "scope":"saved arithmetic and causal prefixes; not independent market-source or exact matching certification",
        "research_only":True,"orders_authorized":False}
    write_json(args.receipt,receipt)
    print(json.dumps(receipt,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
