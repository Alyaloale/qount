"""G20-LP v3 chop-window wear study: what does 2x hold+rebalance cost in
flat, high-volatility, no-trend regimes?

Motivation (owner request 2026-11-03): the three consumed v3 windows all
contain trend segments.  The wear mechanism -- variance drain from leverage
maintenance plus funding plus costs when the pool drifts sideways -- has no
dedicated measurement.  This study sets an empirical expectation for it.

Pre-registered design (written before any replay result was produced):

* Windows: index-aligned bars, primary W=120 (robustness W=90, 180),
  step 20, interior only (engine constraint right < n).
* Pool descriptors per window (EW index of the 11 legs, close-to-close,
  window-local entry weighting: each leg normalized to 1 at the window
  start, then averaged -- the true equal-weight buy-and-hold basket):
  net = total return; vol = annualized daily std (x sqrt(365));
  excursion = max |index/index0 - 1| (distinguishes calm flat from violent
  round-trip flat).  (An initial run normalized legs at the panel start
  instead of the window start -- ratio of means, endogenous weights; the
  flat set was contaminated.  Found via static2x price attribution, fixed
  before any conclusion; faithfulness gates held throughout.)
* Flat/chop set (primary): |net| <= 10% AND vol >= 40% annualized.  The vol
  gate is explicit but non-binding for this pool (full-sample EW vol ~79%);
  wear is additionally stratified by vol band (40-60 / 60-80 / >=80).
* Non-overlapping headline subset: greedy earliest-start among W=120 flat
  windows (overlapping windows inflate n; the regime map shows all).
* Configs per window (capital 43.87 USDT = live design point, 10bp one-way,
  historical funding, MM 2.5% flat, liquidation fee 1%):
  1. ew1x        gross 1.0, weekly + 25% band, fractional quantities
  2. static2x    gross 2.0, fixed entry quantities, never rebalance
  3. v3_mech     gross 2.0, weekly + 25% band, fractional quantities
  4. v3_faithful gross 2.0, weekly + 25% band, REAL 5U exchange rules
     (= published replay semantics)
  5. v3_reject   same + MIN_NOTIONAL delta rejection (= live semantics)
  Fractional configs isolate the mechanism from exchange lot/notional
  plumbing; (4)-(3) prices that plumbing, (5)-(4) the live reject overlay.
* Decomposition on the flat set (pp of total return; log points where noted):
  rebalance+maintenance effect = v3_mech - static2x (same entry leverage),
  vs GBM reference -(L^2-L)*sigma^2*T/2 = -sigma^2*T for L=2 on measured EW
  vol; funding and costs in USDT/month; total live wear = v3_reject - ew1x.
* Regime map over ALL W=120 windows: drift bucket x vol bucket -> mean/worst
  v3_reject return and MDD, so the flat-set numbers cannot be cherry-picked.
* Faithfulness gates (hard fail):
  A. replay_delta_min(skip_small_deltas=False) reproduces replay_v3's equity
     path on the era window (review 2026-11-02 reported zero residual).
  B. published v3_no_gate_2x era/pre/fwd headline numbers reproduce from
     results.json within 1e-6 abs on return_pct/mdd_pct.

Research only: research_only=true / orders_authorized=false.
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

POOL = ("SOLUSDT", "BNBUSDT", "XRPUSDT", "SPYUSDT", "QQQUSDT", "SMHUSDT",
        "IWMUSDT", "XLEUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT")
CAPITAL = 43.87
COST_BP = 10.0
STEP = 20
PRIMARY_W = 120
ROBUST_W = (90, 180)
FLAT_NET_MAX = 0.10
CHOP_VOL_MIN = 0.40
DRIFT_BUCKETS = (-0.15, -0.05, 0.05, 0.15)   # -> 5 buckets
VOL_BUCKETS = (0.45, 0.65, 0.85)             # -> 4 buckets
DAY = 86400


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


v2 = load("study_v2", REPO_ROOT / "scripts/research/study_g20_v2_small_leverage.py")
v3 = load("g20v3", REPO_ROOT / "scripts/research/study_g20_v3_carry_weight.py")
ed = load("exec_delta_min",
          REPO_ROOT / "state/research_runs/g20_v3_review_20261102/exec_delta_min_notional.py")

NEVER = 10 ** 9


def build_pool_panel():
    full, extra, sources = v2.build_full_panel(etf_root=v3.ETF_REFRESH)
    idx = [list(full["symbols"]).index(s) for s in POOL]
    panel = dict(symbols=POOL, times=full["times"])
    for k in ("open", "high", "low", "close", "mark_low"):
        panel[k] = full[k][:, idx]
    panel["funding_value"] = full["funding_value"][:, idx]
    panel["funding_debit"] = full["funding_debit"][:, idx]
    funding_annual = extra["funding_annual"][:, idx]
    return panel, funding_annual, sources


def run_config(kind, panel, funding_annual, start, end, filters_real):
    if kind == "v3_reject":
        r = ed.replay_delta_min(panel, funding_annual, start=start, end=end,
                                capital=CAPITAL, gross=2.0, gate_threshold=None,
                                cost_bp=COST_BP, filters=filters_real,
                                skip_small_deltas=True)
    elif kind == "v3_faithful":
        r = ed.replay_delta_min(panel, funding_annual, start=start, end=end,
                                capital=CAPITAL, gross=2.0, gate_threshold=None,
                                cost_bp=COST_BP, filters=filters_real,
                                skip_small_deltas=False)
    elif kind == "ew1x":
        r = v3.replay_v3(panel, funding_annual, start=start, end=end,
                         capital=CAPITAL, gross=1.0, gate_threshold=None,
                         cost_bp=COST_BP, filters=None)["summary"]
    elif kind == "static2x":
        r = v3.replay_v3(panel, funding_annual, start=start, end=end,
                         capital=CAPITAL, gross=2.0, gate_threshold=None,
                         cost_bp=COST_BP, filters=None,
                         rebalance_bars=NEVER, drift_band=1e9)["summary"]
    elif kind == "v3_mech":
        r = v3.replay_v3(panel, funding_annual, start=start, end=end,
                         capital=CAPITAL, gross=2.0, gate_threshold=None,
                         cost_bp=COST_BP, filters=None)["summary"]
    else:
        raise ValueError(kind)
    return {k: r.get(k) for k in ("final_usdt", "return_pct", "cagr_pct",
                                  "mdd_pct", "calmar", "counts",
                                  "funding_pnl", "costs")}


CONFIGS = ("ew1x", "static2x", "v3_mech", "v3_faithful", "v3_reject")


def descriptors(close, k, w):
    # Window-local entry-weighted EW basket: each leg normalized at window
    # start, then averaged (true equal-weight buy-and-hold).
    seg = (close[k:k + w + 1] / close[k]).mean(axis=1)
    r = seg[1:] / seg[:-1] - 1.0
    return dict(net=float(seg[-1] - 1.0),
                vol=float(r.std() * np.sqrt(365.0)),
                excursion=float(np.max(np.abs(seg - 1.0))))


def bucket(value, edges):
    for i, e in enumerate(edges):
        if value < e:
            return i
    return len(edges)


def faithfulness(panel, funding_annual, filters_real, published_path):
    days = panel["times"]
    era0 = int(np.searchsorted(days, int(datetime(2022, 6, 28, tzinfo=timezone.utc).timestamp())))
    era_end = int(np.searchsorted(days, int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())))
    windows = {
        "era": (int(days[era0]), int(days[era_end - 1])),
        "pre": (int(days[int(np.searchsorted(days, int(
            datetime(2021, 7, 1, tzinfo=timezone.utc).timestamp())))]), int(days[era0])),
        "fwd": (int(days[int(np.searchsorted(days, int(
            datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp())))]), int(days[-1])),
    }
    w0, w1 = windows["era"]
    ref = v3.replay_v3(panel, funding_annual, start=w0, end=w1, capital=CAPITAL,
                       gross=2.0, gate_threshold=None, filters=filters_real)
    faithful = ed.replay_delta_min(panel, funding_annual, start=w0, end=w1,
                                   capital=CAPITAL, gross=2.0, gate_threshold=None,
                                   filters=filters_real, skip_small_deltas=False)
    ref_eq = np.asarray([c["equity"] for c in ref["curve"]])
    got_eq = np.asarray([c["equity"] for c in faithful["curve"]])
    resid_a = float(np.max(np.abs(ref_eq - got_eq))) if len(ref_eq) == len(got_eq) else float("inf")
    assert resid_a <= 1e-9, f"gate_A_failed:{resid_a}"

    published = json.loads(published_path.read_text())["experiments"]["results"]
    checks = {}
    for tag, (s, e) in windows.items():
        got = v3.replay_v3(panel, funding_annual, start=s, end=e, capital=CAPITAL,
                           gross=2.0, gate_threshold=None, filters=filters_real)["summary"]
        want = published[f"v3_no_gate_2x_{tag}"]["summary"]
        for key in ("return_pct", "mdd_pct"):
            resid = abs(got[key] - want[key])
            assert resid <= 1e-6, f"gate_B_failed:{tag}:{key}:{resid}"
        checks[tag] = dict(return_pct=got["return_pct"], mdd_pct=got["mdd_pct"],
                           published_return_pct=want["return_pct"],
                           published_mdd_pct=want["mdd_pct"])

    # Gate C: static 1x with zero funding/costs must equal the mean-of-ratios
    # open-to-open EW basket exactly (pins descriptor vs replay arithmetic).
    anchor = windows["pre"]
    nofund = {**panel,
              "funding_value": np.zeros_like(panel["funding_value"]),
              "funding_debit": np.zeros_like(panel["funding_debit"])}
    stat1 = v3.replay_v3(nofund, funding_annual, start=anchor[0], end=anchor[1],
                         capital=CAPITAL, gross=1.0, gate_threshold=None,
                         cost_bp=0.0, filters=None,
                         rebalance_bars=NEVER, drift_band=1e9)["summary"]
    k0 = int(np.searchsorted(panel["times"], anchor[0]))
    k1 = int(np.searchsorted(panel["times"], anchor[1]))
    basket_oo = float((panel["open"][k1] / panel["open"][k0]).mean() - 1.0) * 100.0
    resid_c = abs(stat1["return_pct"] - basket_oo)
    assert resid_c <= 1e-6, f"gate_C_failed:{resid_c}"
    return dict(gate_A_max_equity_residual=resid_a, gate_B=checks,
                gate_C_static_vs_basket_residual_pp=resid_c)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path,
                    default=Path("state/research_runs/g20_v3_chop_windows_20261103"))
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    panel, funding_annual, sources = build_pool_panel()
    filters_real = v2.build_filters()
    times = panel["times"]
    close = panel["close"]
    norm = close / close[0]
    ew = norm.mean(axis=1)

    faith = faithfulness(panel, funding_annual, filters_real,
                         REPO_ROOT / "state/research_runs/g20_v3_carry_weight_20261102/results.json")

    windows_out = {}
    for w in (PRIMARY_W, *ROBUST_W):
        rows = []
        for k in range(1, len(times) - w, STEP):
            d0 = int(times[k])
            d1 = int(times[k + w])
            desc = descriptors(close, k, w)
            configs = {kind: run_config(kind, panel, funding_annual, d0, d1, filters_real)
                       for kind in CONFIGS}
            months = (d1 - d0) / (365.25 * DAY) * 12.0
            mech, stat = configs["v3_mech"]["return_pct"], configs["static2x"]["return_pct"]
            ew1, rej = configs["ew1x"]["return_pct"], configs["v3_reject"]["return_pct"]
            fai = configs["v3_faithful"]["return_pct"]
            sigma, t_years = desc["vol"], months / 12.0
            gbm_ref_pp = float((np.exp(-(sigma ** 2) * t_years) - 1.0) * 100.0)
            rows.append(dict(
                k=k,
                start=datetime.fromtimestamp(d0, timezone.utc).strftime("%Y-%m-%d"),
                end=datetime.fromtimestamp(d1, timezone.utc).strftime("%Y-%m-%d"),
                months=months, **{f"desc_{key}": val for key, val in desc.items()},
                configs=configs,
                decomp=dict(
                    rebalance_effect_pp=mech - stat,
                    gbm_reference_pp=gbm_ref_pp,
                    plumbing_pp=fai - mech,
                    reject_pp=rej - fai,
                    live_wear_vs_pool_pp=rej - ew1,
                ),
            ))
        windows_out[str(w)] = rows

    primary = windows_out[str(PRIMARY_W)]
    flat = [r for r in primary
            if abs(r["desc_net"]) <= FLAT_NET_MAX and r["desc_vol"] >= CHOP_VOL_MIN]
    nonoverlap, last = [], -10 ** 9
    for r in sorted(flat, key=lambda x: x["k"]):
        if r["k"] >= last + PRIMARY_W:
            nonoverlap.append(r)
            last = r["k"]

    def agg(rows):
        if not rows:
            return None
        out = dict(n=len(rows))
        for kind in CONFIGS:
            rets = [r["configs"][kind]["return_pct"] for r in rows]
            mdds = [r["configs"][kind]["mdd_pct"] for r in rows]
            entry = dict(mean_return_pct=float(np.mean(rets)),
                         median_return_pct=float(np.median(rets)),
                         min_return_pct=float(np.min(rets)),
                         worst_mdd_pct=float(np.max(mdds)))
            for key in ("funding_pnl", "costs"):
                vals = [r["configs"][kind][key] for r in rows
                        if r["configs"][kind].get(key) is not None]
                entry[f"mean_{key}_usdt"] = float(np.mean(vals)) if vals else None
            out[kind] = entry
        for key in ("rebalance_effect_pp", "gbm_reference_pp", "plumbing_pp",
                    "reject_pp", "live_wear_vs_pool_pp"):
            vals = [r["decomp"][key] for r in rows]
            out[key] = dict(mean=float(np.mean(vals)), median=float(np.median(vals)),
                            min=float(np.min(vals)), max=float(np.max(vals)))
        return out

    vol_strata = {}
    for lo, hi, tag in ((CHOP_VOL_MIN, 0.60, "40-60"), (0.60, 0.80, "60-80"),
                        (0.80, float("inf"), ">=80")):
        sel = [r for r in flat if lo <= r["desc_vol"] < hi]
        vol_strata[tag] = agg(sel)

    regime_map = {}
    for r in primary:
        db = bucket(r["desc_net"], DRIFT_BUCKETS)
        vb = bucket(r["desc_vol"], VOL_BUCKETS)
        regime_map.setdefault(f"d{db}_v{vb}", []).append(r)
    regime_out = {}
    for cell, rows in sorted(regime_map.items()):
        a = agg(rows)
        regime_out[cell] = dict(n=a["n"],
                                mean_net=float(np.mean([x["desc_net"] for x in rows])),
                                mean_vol=float(np.mean([x["desc_vol"] for x in rows])),
                                v3_reject=a["v3_reject"],
                                rebalance_effect_pp=a["rebalance_effect_pp"])

    out = dict(
        research_only=True, orders_authorized=False,
        generated_at=datetime.now(timezone.utc).isoformat(),
        question="wear of 2x hold + weekly rebalance in flat high-vol no-trend "
                 "windows (expectation-setting for g20_leveraged_pool_v3 live)",
        design=dict(capital_usdt=CAPITAL, cost_bp=COST_BP, step=STEP,
                    primary_w=PRIMARY_W, robust_w=list(ROBUST_W),
                    flat_net_max=FLAT_NET_MAX, chop_vol_min=CHOP_VOL_MIN,
                    drift_buckets=list(DRIFT_BUCKETS), vol_buckets=list(VOL_BUCKETS),
                    configs=list(CONFIGS)),
        faithfulness=faith,
        panel=dict(days=len(times),
                   start=datetime.fromtimestamp(int(times[0]), timezone.utc).strftime("%Y-%m-%d"),
                   end=datetime.fromtimestamp(int(times[-1]), timezone.utc).strftime("%Y-%m-%d"),
                   ew_full_net=float(ew[-1] / ew[0] - 1.0),
                   ew_full_vol=float((ew[1:] / ew[:-1] - 1).std() * np.sqrt(365.0)),
                   sources=[str(s) for s in sources]),
        flat_windows=flat,
        windows_all={w: [dict(start=r["start"], end=r["end"], months=r["months"],
                              desc_net=r["desc_net"], desc_vol=r["desc_vol"],
                              desc_excursion=r["desc_excursion"],
                              configs={k: dict(return_pct=v["return_pct"],
                                               mdd_pct=v["mdd_pct"],
                                               funding_pnl=v.get("funding_pnl"),
                                               costs=v.get("costs"))
                                       for k, v in r["configs"].items()},
                              decomp=r["decomp"]) for r in rows_list]
                     for w, rows_list in windows_out.items()},
        flat_nonoverlap=[dict(start=r["start"], end=r["end"]) for r in nonoverlap],
        aggregates=dict(flat_all=agg(flat), flat_nonoverlap=agg(nonoverlap),
                        vol_strata=vol_strata),
        regime_map=dict(buckets=dict(drift=list(DRIFT_BUCKETS), vol=list(VOL_BUCKETS)),
                        cells=regime_out),
        robustness={w: dict(n=len(windows_out[w]),
                            flat_n=sum(1 for r in windows_out[w]
                                       if abs(r["desc_net"]) <= FLAT_NET_MAX
                                       and r["desc_vol"] >= CHOP_VOL_MIN),
                            flat=agg([r for r in windows_out[w]
                                      if abs(r["desc_net"]) <= FLAT_NET_MAX
                                      and r["desc_vol"] >= CHOP_VOL_MIN]))
                    for w in map(str, ROBUST_W)},
    )
    (args.output / "results.json").write_text(json.dumps(out, indent=1, default=str))

    print("faithfulness A residual:", faith["gate_A_max_equity_residual"])
    print("faithfulness B:", json.dumps(faith["gate_B"], indent=1))
    print(f"panel {out['panel']['start']}..{out['panel']['end']}  "
          f"EW net {out['panel']['ew_full_net']:+.1%}  vol {out['panel']['ew_full_vol']:.0%}")
    print(f"flat W={PRIMARY_W}: {len(flat)} windows, non-overlap {len(nonoverlap)}")
    for tag, a in (("flat_all", out["aggregates"]["flat_all"]),
                   ("flat_nonoverlap", out["aggregates"]["flat_nonoverlap"])):
        if not a:
            continue
        print(f"\n[{tag}] n={a['n']}")
        for kind in CONFIGS:
            c = a[kind]
            fund = c.get("mean_funding_pnl_usdt")
            fund_s = f"fund {fund:+6.2f}U" if fund is not None else "fund     --  "
            cost = c.get("mean_costs_usdt")
            cost_s = f"cost {cost:5.2f}U" if cost is not None else "cost    --  "
            print(f"  {kind:12s} ret mean {c['mean_return_pct']:+7.1f}%  "
                  f"med {c['median_return_pct']:+7.1f}%  min {c['min_return_pct']:+7.1f}%  "
                  f"worst_mdd {c['worst_mdd_pct']:5.1f}%  {fund_s}  {cost_s}")
        for key in ("rebalance_effect_pp", "gbm_reference_pp", "plumbing_pp",
                    "reject_pp", "live_wear_vs_pool_pp"):
            d = a[key]
            print(f"  {key:22s} mean {d['mean']:+7.1f}pp  med {d['median']:+7.1f}pp  "
                  f"range [{d['min']:+.1f}, {d['max']:+.1f}]")
    print("\n[vol strata, flat set]")
    for tag, a in vol_strata.items():
        if not a:
            continue
        print(f"  vol {tag}: n={a['n']}  v3_reject mean {a['v3_reject']['mean_return_pct']:+7.1f}%  "
              f"rebalance_effect {a['rebalance_effect_pp']['mean']:+6.1f}pp  "
              f"gbm_ref {a['gbm_reference_pp']['mean']:+6.1f}pp  "
              f"live_wear {a['live_wear_vs_pool_pp']['mean']:+6.1f}pp")
    print("\n[flat windows detail]")
    for r in flat:
        c = r["configs"]
        print(f"  {r['start']}..{r['end']} net{r['desc_net']:+6.1%} vol{r['desc_vol']:4.0%} "
              f"exc{r['desc_excursion']:4.0%} | ew1x{c['ew1x']['return_pct']:+7.1f} "
              f"static2x{c['static2x']['return_pct']:+7.1f} mech{c['v3_mech']['return_pct']:+7.1f} "
              f"faith{c['v3_faithful']['return_pct']:+7.1f} reject{c['v3_reject']['return_pct']:+7.1f} "
              f"| mdd_rej{c['v3_reject']['mdd_pct']:5.1f} wear{r['decomp']['live_wear_vs_pool_pp']:+7.1f}pp")
    print("\n[regime map, W=120] (drift x vol -> n, mean net/vol, v3_reject ret, rebal effect)")
    for cell, a in regime_out.items():
        print(f"  {cell}: n={a['n']:2d} net{a['mean_net']:+7.1%} vol{a['mean_vol']:4.0%} "
              f"ret {a['v3_reject']['mean_return_pct']:+7.1f}%  "
              f"rebal {a['rebalance_effect_pp']['mean']:+6.1f}pp")


if __name__ == "__main__":
    main()
