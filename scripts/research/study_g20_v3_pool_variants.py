"""Pool anatomy and universe variants for G20-LP v3 (2026-11-02).

Anatomy: correlation structure of the 11-leg pool (clusters, effective number
of bets, down-market correlation) and per-leg three-window contributions.

Variants are mechanism-based (not fitted):
* betaslim — US equity redundancy down (SPY+SMH only), geography up (EWJ+EWY)
* div11    — betaslim - XRP + EWZ (crypto concentration down, 3 countries up)
* world14  — base11 + EWJ+EWY+EWZ (pure diversification add, 6.26U/leg feasible)
* crypto2  — drop highest-beta crypto (XRP), add EWJ (crypto cluster is one bet)
* xag12    — base11 + silver (metals family completeness)

All at 2x no-gate, evaluated on era/pre/fwd; adoption requires no material
degradation on any window plus a diversification gain.

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


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


POOL = ("SOLUSDT", "BNBUSDT", "XRPUSDT", "SPYUSDT", "QQQUSDT", "SMHUSDT",
        "IWMUSDT", "XLEUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT")
CLUSTERS = {"us_equity": ("SPYUSDT", "QQQUSDT", "SMHUSDT", "IWMUSDT"),
            "crypto": ("SOLUSDT", "BNBUSDT", "XRPUSDT"),
            "commodity": ("XAUUSDT", "COPPERUSDT", "CLUSDT"),
            "energy_equity": ("XLEUSDT",)}
VARIANTS = {
    "betaslim": (("SOLUSDT", "BNBUSDT", "XRPUSDT", "SPYUSDT", "SMHUSDT",
                  "EWJUSDT", "EWYUSDT", "XLEUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT"),
                 {"EWJ": "EWJUSDT", "EWY": "EWYUSDT"}),
    "div11": (("SOLUSDT", "BNBUSDT", "SPYUSDT", "SMHUSDT", "EWJUSDT", "EWYUSDT",
               "EWZUSDT", "XLEUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT"),
              {"EWJ": "EWJUSDT", "EWY": "EWYUSDT", "EWZ": "EWZUSDT"}),
    "world14": (POOL + ("EWJUSDT", "EWYUSDT", "EWZUSDT"),
                {"EWJ": "EWJUSDT", "EWY": "EWYUSDT", "EWZ": "EWZUSDT"}),
    "crypto2": (("SOLUSDT", "BNBUSDT", "SPYUSDT", "QQQUSDT", "SMHUSDT", "IWMUSDT",
                 "XLEUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT", "EWJUSDT"),
                {"EWJ": "EWJUSDT"}),
    "xag12": (POOL + ("XAGUSDT",), {"SLV": "XAGUSDT"}),
}


def pool_panel(full, extra, names):
    idx = [list(full["symbols"]).index(s) for s in names if s in full["symbols"]]
    base_names = [s for s in names if s in full["symbols"]]
    panel = dict(symbols=tuple(base_names), times=full["times"])
    for k in ("open", "high", "low", "close", "mark_low"):
        panel[k] = full[k][:, idx]
    panel["funding_value"] = full["funding_value"][:, idx]
    panel["funding_debit"] = full["funding_debit"][:, idx]
    fund = extra["funding_annual"][:, idx]
    return panel, fund


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/g20_v3_pool_variants_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    s3 = load_module("g20_v3_study", REPO_ROOT / "scripts/research/study_g20_v3_carry_weight.py")
    hs = load_module("g20_v3_hedge", REPO_ROOT / "scripts/research/study_g20_v3_hedge_sleeves.py")
    study = s3.load_study()
    full, extra, _ = study.build_full_panel(etf_root=s3.ETF_REFRESH)
    base, base_fund = pool_panel(full, extra, POOL)
    filters = study.build_filters()

    # ---- anatomy: correlation structure on daily returns ----
    closes = base["close"]
    rets = np.log(closes[1:] / closes[:-1])
    names = list(POOL)
    corr = np.corrcoef(rets.T)
    print("== average pairwise correlation by cluster pair (full period)")
    cl_items = list(CLUSTERS.items())
    for i, (ca, sa) in enumerate(cl_items):
        ia = [names.index(s) for s in sa]
        for cb, sb in cl_items[i:]:
            ib = [names.index(s) for s in sb]
            block = corr[np.ix_(ia, ib)].copy()
            if ca == cb:
                block = block[np.triu_indices_from(block, 1)]
            print(f"  {ca:<13} x {cb:<13} mean {block.mean():.2f}")
    evals = np.linalg.eigvalsh(corr)
    eff_bets = float(evals.sum() ** 2 / (evals ** 2).sum())
    print(f"  effective number of bets (eigenvalue ratio): {eff_bets:.2f} of {len(names)}")
    ew = rets.mean(axis=1)
    down = ew < np.percentile(ew, 25)
    corr_down = np.corrcoef(rets[down].T)
    tri = corr_down[np.triu_indices_from(corr_down, 1)]
    print(f"  avg pairwise corr in worst-quartile months/days: {tri.mean():.2f} (full {corr[np.triu_indices_from(corr,1)].mean():.2f})")

    # ---- variants ----
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
    panels = {"base11": (base, base_fund, {})}
    for vtag, (vnames, tickers) in VARIANTS.items():
        panel, fund = pool_panel(full, extra, tuple(n for n in vnames if n in full["symbols"]))
        panel = hs.extended_panel(panel, tickers)
        fund = np.hstack([fund, np.zeros((len(fund), len(tickers)))])
        panels[vtag] = (panel, fund, hs.build_filters_for(set(tickers.values())))

    results = {}
    for vtag, (panel, fund, extra_filters) in panels.items():
        f = dict(filters)
        f.update(extra_filters)
        vol = study.vol_matrix(panel)
        for wtag, (w0, w1) in windows.items():
            run = s3.replay_v3(panel, fund, start=w0, end=w1, capital=43.87,
                               gross=2.0, gate_threshold=None, filters=f, vol=vol)
            s = run["summary"]
            results[f"{vtag}_{wtag}"] = dict(
                legs=len(panel["symbols"]),
                leg_notional_usdt=round(43.87 * 2 / len(panel["symbols"]), 2),
                summary=s)
            print(f"{vtag + '_' + wtag:<18} legs={len(panel['symbols']):>2} "
                  f"({43.87*2/len(panel['symbols']):.1f}U/leg) total={s['return_pct']:7.1f}%  "
                  f"cagr={s['cagr_pct']:6.1f}%  mdd={s['mdd_pct']:5.1f}%  "
                  f"calmar={round(s['calmar'],2) if s['calmar'] else None}")

    payload = dict(research_only=True, orders_authorized=False,
                   generated_at=datetime.now(timezone.utc).isoformat(),
                   anatomy=dict(cluster_pairs="see stdout", effective_bets=eff_bets),
                   assumptions=[
                       "EWJ/EWY/EWZ/XAG are Yahoo proxies on Binance perp specs (5U tier), "
                       "zero funding unmodeled; perp tracking error calibrated only SPY/QQQ",
                       "Pool feasibility at 43.87U/2x: max ~17 legs before per-leg target "
                       "falls under the 5U minimum",
                       "Adoption rule: no material degradation on any window plus "
                       "diversification gain; window-specific gains are candidates only",
                   ],
                   experiments=results)
    (args.output / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n")


if __name__ == "__main__":
    main()
