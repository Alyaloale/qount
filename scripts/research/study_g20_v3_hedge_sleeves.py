"""Bear-hedge inventory and defensive-sleeve variants for G20-LP v3.

Question (owner, 2026-11-02): don't we have bear-market safe havens in the ETF
set?  Answer has three parts, all measured here:

1. Channel inventory: Binance USDM actually lists explicit bear instruments
   (SQQQ/SOXS/TZA inverse equity, UVXY VIX, TBT/TMF bond leverage, XAG/XPT/
   XPD/PAXG metals, GDX miners) — all 5U tier.  TLT/UUP (bond/dollar cash
   ETFs) exist as data only, no perp listing.
2. Stress-window behavior of every available hedge in the three v3 drawdown
   windows plus the 2022 bear year and the 2023-2025 bull (carry cost).
3. Structural variants of the v3 pool at 2x (no gate): +metals sleeve
   (XAG+GDX), +SQQQ insurance leg, +UVXY insurance leg.

research_only=true / orders_authorized=false.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qount.research.binance_macro_history import adjusted_bars

ETF_REFRESH = Path("state/research_cache/yahoo_etf_refresh_20261102")
DAY = 86400
# ticker -> (perp symbol, minQty, stepSize, minNotional) from Binance exchange-info
HEDGE_TICKERS = {
    "SLV": ("XAGUSDT", 0.001, 0.001, 5.0),
    "GDX": ("GDXUSDT", 0.01, 0.01, 5.0),
    "SQQQ": ("SQQQUSDT", 0.01, 0.01, 5.0),
    "UVXY": ("UVXYUSDT", 0.01, 0.01, 5.0),
    "TBT": ("TBTUSDT", 0.01, 0.01, 5.0),
    "TMF": ("TMFUSDT", 0.01, 0.01, 5.0),
    "TLT": (None, None, None, None),   # data only, no perp
    "UUP": (None, None, None, None),   # data only, no perp
}
STRESS_WINDOWS = {
    "W1_bear_DD 2021-11-09..2022-06-17": ("2021-11-09", "2022-06-17"),
    "W2_calendar2022": ("2022-01-01", "2022-12-31"),
    "W3_era_DD 2025-01-24..04-09": ("2025-01-24", "2025-04-09"),
    "W4_fwd_DD 2026-01-29..02-06": ("2026-01-29", "2026-02-06"),
    "W5_bull 2023-01-01..2025-12-31 (cost)": ("2023-01-01", "2025-12-31"),
}


def load_study():
    spec = importlib.util.spec_from_file_location(
        "study_v2", REPO_ROOT / "scripts/research/study_g20_v2_small_leverage.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def yahoo_closes(ticker):
    path = ETF_REFRESH / f"yahoo-{ticker}-20160101-2026-11-02.json"
    if not path.exists():
        path = Path("/tmp") / f"yh_{ticker}.json"
    bars = adjusted_bars(json.loads(path.read_text()))
    return {b.t // DAY * DAY: b.c for b in bars}


def stress_table():
    rows = {}
    for ticker in ["SPY", "QQQ", "SMH", "IWM", "XLE", "GLD", "SLV", "GDX",
                   "CPER", "USO", "TLT", "UUP", "SQQQ", "UVXY", "TBT", "TMF"]:
        closes = yahoo_closes(ticker)
        days = sorted(closes)
        out = {}
        for wtag, (d0, d1) in STRESS_WINDOWS.items():
            k0 = int(datetime.fromisoformat(d0).replace(tzinfo=timezone.utc).timestamp()) // DAY * DAY
            k1 = int(datetime.fromisoformat(d1).replace(tzinfo=timezone.utc).timestamp()) // DAY * DAY
            seg = [closes[d] for d in days if k0 <= d <= k1]
            out[wtag] = round((seg[-1] / seg[0] - 1) * 100, 1) if len(seg) >= 2 else None
        rows[ticker] = out
    return rows


def extended_panel(base_panel, ticker_map):
    """Append Yahoo legs to the 11-leg pool panel (zero funding)."""
    names = list(base_panel["symbols"])
    cols = {}
    for ticker, symbol in ticker_map.items():
        closes = yahoo_closes(ticker)
        cols[symbol] = [closes.get(int(d)) for d in base_panel["times"]]
    n, m = len(base_panel["times"]), len(names) + len(cols)
    panel = dict(symbols=tuple(names + list(cols)), times=base_panel["times"])
    for k in ("open", "high", "low", "close", "mark_low"):
        arr = np.zeros((n, m))
        arr[:, :len(names)] = base_panel[k]
        for j, (symbol, series) in enumerate(cols.items()):
            arr[:, len(names) + j] = series
        panel[k] = arr
    # keep base-leg funding, zero the appended legs (their funding is unmodeled)
    fv = np.zeros((n - 1, m))
    fd = np.zeros((n - 1, m))
    fv[:, :len(names)] = base_panel["funding_value"]
    fd[:, :len(names)] = base_panel["funding_debit"]
    panel["funding_value"] = fv
    panel["funding_debit"] = fd
    return panel


def build_filters_for(symbols):
    info = json.loads((Path("state/research_cache/binance_etf_leverage_20261015")
                       / "exchange-info.json").read_text())
    out = {}
    for s in info.get("symbols", []):
        if s.get("symbol") in symbols:
            rows = {f["filterType"]: f for f in s.get("filters", [])}
            lot, mn = rows.get("MARKET_LOT_SIZE", {}), rows.get("MIN_NOTIONAL", {})
            out[s["symbol"]] = {"filters": [
                {"filterType": "MARKET_LOT_SIZE", "minQty": float(lot.get("minQty", 0)),
                 "stepSize": float(lot.get("stepSize", 0.001)),
                 "maxQty": float(lot.get("maxQty", 1e9))},
                {"filterType": "MIN_NOTIONAL", "notional": float(mn.get("notional", 5))}]}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/g20_v3_hedge_sleeves_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    s3_spec = importlib.util.spec_from_file_location(
        "g20_v3_study", REPO_ROOT / "scripts/research/study_g20_v3_carry_weight.py")
    s3 = importlib.util.module_from_spec(s3_spec)
    s3_spec.loader.exec_module(s3)
    study = s3.load_study()

    stress = stress_table()
    print("== stress windows (%) — perp-tradable marked *; TLT/UUP data-only")
    for t, row in stress.items():
        mark = "*" if HEDGE_TICKERS.get(t, (None,))[0] or t in ("SPY", "QQQ", "SMH", "IWM", "XLE", "GLD", "CPER", "USO") else " "
        print(f"{mark}{t:<5}", {k.split()[0]: v for k, v in row.items()})

    full, extra, _ = study.build_full_panel(etf_root=s3.ETF_REFRESH)
    idx = [list(full["symbols"]).index(s) for s in s3.POOL]
    base = dict(symbols=s3.POOL, times=full["times"])
    for k in ("open", "high", "low", "close", "mark_low"):
        base[k] = full[k][:, idx]
    base["funding_value"] = full["funding_value"][:, idx]
    base["funding_debit"] = full["funding_debit"][:, idx]
    base_fund = extra["funding_annual"][:, idx]
    filters = study.build_filters()

    variants = {
        "base11": (base, base_fund, {}),
        "metals13": (extended_panel(base, {"SLV": "XAGUSDT", "GDX": "GDXUSDT"}),
                     np.hstack([base_fund, np.zeros((len(base_fund), 2))]),
                     build_filters_for({"XAGUSDT", "GDXUSDT"})),
        "ins_sqqq12": (extended_panel(base, {"SQQQ": "SQQQUSDT"}),
                       np.hstack([base_fund, np.zeros((len(base_fund), 1))]),
                       build_filters_for({"SQQQUSDT"})),
        "ins_uvxy12": (extended_panel(base, {"UVXY": "UVXYUSDT"}),
                       np.hstack([base_fund, np.zeros((len(base_fund), 1))]),
                       build_filters_for({"UVXYUSDT"})),
    }
    days = base["times"]
    era0 = int(np.searchsorted(days, int(datetime(2022, 6, 28, tzinfo=timezone.utc).timestamp())))
    era_end = int(np.searchsorted(days, int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())))
    windows = {
        "era": (int(days[era0]), int(days[era_end - 1])),
        "pre": (int(days[int(np.searchsorted(days, int(
            datetime(2021, 7, 1, tzinfo=timezone.utc).timestamp())))]), int(days[era0])),
        "fwd": (int(days[int(np.searchsorted(days, int(
            datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp())))]), int(days[-1])),
    }

    results = {}
    for vtag, (panel, fund, extra_filters) in variants.items():
        f = dict(filters)
        f.update(extra_filters)
        vol = study.vol_matrix(panel)
        for wtag, (w0, w1) in windows.items():
            run = s3.replay_v3(panel, fund, start=w0, end=w1, capital=43.87,
                               gross=2.0, gate_threshold=None, filters=f, vol=vol)
            s = run["summary"]
            results[f"{vtag}_{wtag}"] = dict(summary=s)
            print(f"{vtag + '_' + wtag:<20} total={s['return_pct']:7.1f}%  "
                  f"cagr={s['cagr_pct']:6.1f}%  mdd={s['mdd_pct']:5.1f}%  "
                  f"calmar={round(s['calmar'], 2) if s['calmar'] else None}")

    payload = dict(research_only=True, orders_authorized=False,
                   generated_at=datetime.now(timezone.utc).isoformat(),
                   channel_inventory={t: v[0] for t, v in HEDGE_TICKERS.items()},
                   stress_windows=stress,
                   assumptions=[
                       "Hedge legs are Yahoo ETF proxies on Binance perp contract specs "
                       "(same pattern as v2/v3); perp tracking calibrated only for SPY/QQQ "
                       "(~3pp/half-year overstatement), inverse/leveraged products uncalibrated",
                       "Zero funding on hedge legs (real perp funding unknown; inverse "
                       "products often carry rich funding in bears)",
                       "SQQQ/UVXY/TBT/TMF have structural decay/leverage effects — a static "
                       "sleeve pays the decay in bulls as insurance premium",
                   ],
                   experiments=results)
    (args.output / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n")


if __name__ == "__main__":
    main()
