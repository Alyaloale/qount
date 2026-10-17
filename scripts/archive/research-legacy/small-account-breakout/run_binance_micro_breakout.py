"""Run fixed four-arm Binance micro-account public replay diagnostics."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.error
from pathlib import Path

from qount.research.binance_micro_breakout import features, replay, fixed_fill_double_cost
from qount.research.small_account_breakout import parse_bars
from qount.research.small_account_breakout_data import _archive, sha, timestamp, write_json
from qount.research.small_account_breakout_study import load_continuous

WINDOWS = {
    "2025": ("2025-01-06", "2026-01-05", "state/research_cache/small_account_breakout_v03_external_2025"),
    "2026": ("2026-03-30", "2026-10-12", "state/research_cache/small_account_breakout_v02_20261013"),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=Path("config/binance-micro-regime-breakout-v01.json"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--daily-cache", type=Path, default=Path("state/research_cache/binance_micro_daily"))
    p.add_argument("--download", action="store_true")
    p.add_argument("--windows", nargs="+", choices=WINDOWS, default=list(WINDOWS))
    p.add_argument("--capital", nargs="+", type=float, default=[10,30,100])
    p.add_argument("--scenarios", nargs="+", choices=["base","double_cost","gap_1pct","gap_2pct"],
                   default=["base","double_cost","gap_1pct","gap_2pct"])
    a = p.parse_args()
    cfg = json.loads(a.config.read_text())
    if not cfg["research_only"] or cfg["orders_authorized"]:
        raise ValueError("research_only_required")
    if a.output.exists(): raise FileExistsError("refuse_overwrite_bundle")
    if any(c <= 0 for c in a.capital): raise ValueError("invalid_capital")
    a.daily_cache.mkdir(parents=True, exist_ok=True)
    daily, receipts = {}, []
    for window in a.windows:
        start_s,end_s,_ = WINDOWS[window]
        start,end = timestamp(start_s),timestamp(end_s)
        first = dt.datetime.fromtimestamp(start-205*86400,dt.timezone.utc).date().replace(day=1)
        last = dt.datetime.fromtimestamp(end-1,dt.timezone.utc).date().replace(day=1)
        current = first
        rows = {}
        while current <= last:
            month = current.strftime("%Y-%m")
            path = a.daily_cache/f"klines-BTCUSDT-1d-{month}.zip"
            packages = [(path, month, "monthly")]
            if current >= dt.date.fromisoformat(cfg["as_of"]).replace(day=1):
                last_day = dt.datetime.fromtimestamp(end-1,dt.timezone.utc).date().day
                packages = [(a.daily_cache/f"klines-BTCUSDT-1d-{current.replace(day=d).isoformat()}.zip",
                             current.replace(day=d).isoformat(), "daily") for d in range(1,last_day+1)]
            for path, date, frequency in packages:
                if a.download:
                    receipt = _archive(a.daily_cache,"klines","BTCUSDT","1d",date,frequency)
                else:
                    expected = path.with_suffix(".zip.CHECKSUM").read_text().split()[0]
                    if sha(path) != expected: raise ValueError("daily_checksum")
                    receipt = {"file":path.name,"sha256":expected}
                receipts.append(receipt)
                for b in parse_bars(path):
                    if b.t in rows and rows[b.t] != b: raise ValueError("daily_conflict")
                    if not 0 < b.l <= min(b.o,b.c) <= max(b.o,b.c) <= b.h: raise ValueError("daily_ohlc")
                    rows[b.t] = b
            current = (current.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
        needed = list(range(start-200*86400,end,86400))
        if any(t not in rows for t in needed): raise ValueError("daily_gap")
        daily[window] = [rows[t] for t in sorted(rows) if t < end]
    a.output.mkdir(parents=True)
    write_json(a.output/"contract.json", {"config":cfg,"windows":{w:WINDOWS[w] for w in a.windows},
        "capital":a.capital,"scenarios":a.scenarios,"independent_oos":False,
        "research_only":True,"orders_authorized":False,"forward_start":None,
        "assumptions":["Current design snapshot filters applied to all history; not historical rule certification",
            "Maintenance 1% plus public liquidation fee proxy, not account brackets",
            "Previous minute volume participation capped at 1%; no historical order book or IOC fill certification",
            "Funding intervals from prior settlements; native protection assumes immediate successful paper ACK",
            "Intraminute ordering is unknown; liquidation wins simultaneous minute touches",
            "Signals use official hourly archives; known minute/hour differences reported, not substituted",
            "Cash yields zero. Spot execution benchmark not certified without spot filters",
            "Fixed-fill doubled costs is accounting-only and cannot alter signals, quantities or HALT",
            "Minute-close NAV includes estimated exit costs; intraminute bound separately reported"]})
    results, quality, input_hashes = [], {}, {}
    for window in a.windows:
        start_s,end_s,cache_s = WINDOWS[window]
        start,end,cache = timestamp(start_s),timestamp(end_s),Path(cache_s)
        data = load_continuous(cache,{"crypto_symbols":cfg["universe"]},
            {"development_start":start_s,"development_end_exclusive":end_s},allow_hourly_mismatch=True)
        # Frozen design filters: do not silently inherit old strategy's different snapshot.
        snapshot = Path("state/research_runs/binance_micro_design_20261013/public-feasibility.json")
        data.rules = {r["symbol"]:r for r in json.loads(snapshot.read_text())["symbols"]}
        quality[window] = data.quality
        input_hashes[window] = sha(cache/"continuous-manifest.json")
        for interval in (1,4):
            updates,gates = features(data.hours,daily[window],interval*3600)
            for gated in (False,True):
                for capital in a.capital:
                    for scenario in a.scenarios:
                        name = f"{window}_{interval}h_{'gate' if gated else 'no_gate'}_{capital:g}_{scenario}"
                        engine,s = replay(data,cfg,updates,gates,start,end,capital,gated,scenario)
                        s.update(window=window,start=start_s,end_exclusive=end_s,interval_hours=interval,
                                 gated=gated,scenario=scenario,run=name)
                        if scenario == "base":
                            s["fixed_fill_double_cost_final_usdt"] = fixed_fill_double_cost(engine.trades,capital)
                        results.append(s)
                        write_json(a.output/f"{name}.json",{"summary":s,"trades":engine.trades,
                            "decisions":engine.decisions,"journal":engine.journal,
                            "curve_hourly":[r for r in engine.curve if r["time"]%3600 == 0]})
                        print(json.dumps({k:s[k] for k in ("run","net_return","max_drawdown","trade_count","halt")}),flush=True)
        # Market-reference only: not an executable perpetual or spot strategy benchmark.
        quality[window]["market_reference_returns"] = {symbol:data.minutes[symbol][end-60].c/data.minutes[symbol][start].o-1
            for symbol in cfg["universe"]}
        del data
    write_json(a.output/"summary.json",{"runs":results,"quality":quality,"cash_return":0,
        "spot_benchmark_status":"not_execution_certified_missing_spot_filters",
        "independent_oos":False,"research_only":True,"orders_authorized":False})
    report = ["# Binance micro breakout: fixed historical diagnostics", "",
        "All history was previously consumed. No independent OOS or forward performance claim; no tuning or promotion.",
        "Fees/slippage 5bp each per side, actual signed funding; stress sizing reserves 1% gap. Base fills use observed minute gaps; gap scenarios add 1%/2% to stops.",
        "", "| Window | Arm | Capital | Scenario | Net return | Minute MDD | Trades | Mean net R | HALT |", "|---|---|---:|---|---:|---:|---:|---:|---|"]
    for s in results:
        r = f"{s['mean_net_structural_r']:.3f}" if s['mean_net_structural_r'] is not None else "—"
        report.append(f"|{s['window']}|{s['interval_hours']}h {'gate' if s['gated'] else 'no gate'}|{s['initial_equity_usdt']:g}|{s['scenario']}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['trade_count']}|{r}|{s['halt'] or '—'}|")
    report += ["", "Full assumptions and benchmark exclusions: contract.json; minimum-order rejections, monthly returns, funding and exposure: summary.json.",
        "Paper step/checkpoint engine is implemented; no public forward collector or background service has been started. Forward start remains null.", ""]
    (a.output/"report.md").write_text("\n".join(report))
    sources = [a.config,Path(__file__),Path("src/qount/research/binance_micro_breakout.py"),
        Path("src/qount/research/small_account_breakout.py"),Path("src/qount/research/small_account_breakout_data.py"),
        Path("src/qount/research/small_account_breakout_study.py"),snapshot]
    write_json(a.output/"manifest.json",{"source_hashes":{str(f):sha(f) for f in sources},
        "input_manifest_hashes":input_hashes,"daily_archives":receipts,
        "files":{f.name:sha(f) for f in sorted(a.output.iterdir()) if f.is_file()},
        "research_only":True,"orders_authorized":False})
    (a.output/"_COMPLETE").write_text(sha(a.output/"manifest.json")+"\n")


if __name__ == "__main__": main()
