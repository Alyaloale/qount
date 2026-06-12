#!/usr/bin/env python3
"""Direct Buffett-style A-share value backtest on akshare data (no Tushare token).

Not academic — just: buy the cheapest large-caps each month, hold, net of real costs,
and see if it beats the index. Two stages (cache-first, idempotent):

  fetch : CSI300 members -> per-stock valuation (stock_value_em: PE(TTM)/PB/total_mv,
          daily 2018+) + qfq close (stock_zh_a_hist, for split/div-correct returns),
          cached under state/research_cache/ashare_value/.
  bt    : monthly cross-sectional value score (low PB + low PE), long the top quintile
          equal-weight, hold to next month-end, net of A-share round-trip costs.
          Benchmark: CSI300 buy-hold + universe equal-weight.

CAVEAT (printed in results): universe = CURRENT CSI300 -> survivorship + look-ahead bias
that FLATTERS value. A first look; if value is weak even with the bias helping, that is
itself informative.

Run on WSL:  PYTHONPATH=src .venv/bin/python scripts/research/ashare_value.py fetch [--limit N]
             PYTHONPATH=src .venv/bin/python scripts/research/ashare_value.py bt
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "state" / "research_cache" / "ashare_value"
VAL = CACHE / "val"
PX = CACHE / "px"
ROE = CACHE / "roe"
START, END = "20140101", "20260610"
ROE_LAG_DAYS = 150  # annual ROE usable only once its FY-end is this many days in the past

COST_PER_SIDE = 0.0010  # A-share round-trip ~ stamp(0.05% sell)+commission+slippage; 0.1%/side honest
TOP_QUANTILE = 0.20     # long the cheapest 20%


def _retry(fn, *, tries=3, pause=1.0):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - akshare scrapes; transient failures expected
            last = e
            time.sleep(pause * (i + 1))
    raise last


def _pick(cols, *cands):
    """Return the first column name present (defensive vs akshare version drift)."""
    for c in cands:
        if c in cols:
            return c
    return None


def csi300_codes() -> list[str]:
    import akshare as ak

    df = _retry(lambda: ak.index_stock_cons_csindex(symbol="000300"))
    col = _pick(df.columns, "成分券代码", "品种代码", "证券代码", "成份券代码", "con_code")
    codes = [str(x).split(".")[0].zfill(6) for x in df[col].tolist()]
    return sorted(set(codes))


def fetch(limit: int | None) -> None:
    import akshare as ak

    for d in (VAL, PX, ROE):
        d.mkdir(parents=True, exist_ok=True)
    codes = csi300_codes()
    if limit:
        codes = codes[:limit]
    print(f"CSI300 members: {len(codes)} (limit={limit})")
    ok_v = ok_p = ok_r = skip = fail = 0
    for i, code in enumerate(codes, 1):
        vpath, ppath, rpath = VAL / f"{code}.csv", PX / f"{code}.csv", ROE / f"{code}.csv"
        if vpath.exists() and ppath.exists() and rpath.exists():
            skip += 1
            continue
        try:
            if not vpath.exists():
                v = _retry(lambda: ak.stock_value_em(symbol=code))
                v.to_csv(vpath, index=False)
            ok_v += 1
            if not ppath.exists():
                p = _retry(lambda: ak.stock_zh_a_hist(symbol=code, period="daily",
                                                      start_date=START, end_date=END, adjust="qfq"))
                p.to_csv(ppath, index=False)
            ok_p += 1
            if not rpath.exists():
                r = _retry(lambda: ak.stock_financial_analysis_indicator(symbol=code, start_year="2015"))
                rcol = _pick(r.columns, "加权净资产收益率(%)", "净资产收益率(%)")
                dcol = list(r.columns)[0]
                r[[dcol, rcol]].rename(columns={dcol: "date", rcol: "roe"}).to_csv(rpath, index=False)
            ok_r += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  [{i}/{len(codes)}] {code} FAIL {type(e).__name__}: {str(e)[:60]}")
        if i % 25 == 0:
            print(f"  [{i}/{len(codes)}] ok_v={ok_v} ok_p={ok_p} ok_r={ok_r} skip={skip} fail={fail}")
        time.sleep(0.3)  # be polite to the scraped sources
    print(f"done: ok_v={ok_v} ok_p={ok_p} ok_r={ok_r} skip={skip} fail={fail}")


# --------------------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------------------

def _load_panels():
    import pandas as pd

    val, px, roe = {}, {}, {}
    for f in sorted(VAL.glob("*.csv")):
        code = f.stem
        try:
            dv = pd.read_csv(f)
            dp = pd.read_csv(PX / f"{code}.csv")
        except Exception:
            continue
        dcol = _pick(dv.columns, "数据日期", "trade_date", "date")
        pb = _pick(dv.columns, "市净率", "pb")
        pe = _pick(dv.columns, "PE(TTM)", "pe_ttm", "pe")
        if not (dcol and pb and pe):
            continue
        dv = dv[[dcol, pb, pe]].rename(columns={dcol: "date", pb: "pb", pe: "pe"})
        dv["date"] = pd.to_datetime(dv["date"]).dt.strftime("%Y-%m-%d")
        pdate = _pick(dp.columns, "日期", "date")
        pclose = _pick(dp.columns, "收盘", "close")
        if not (pdate and pclose):
            continue
        dp = dp[[pdate, pclose]].rename(columns={pdate: "date", pclose: "close"})
        dp["date"] = pd.to_datetime(dp["date"]).dt.strftime("%Y-%m-%d")
        val[code] = dv.set_index("date")
        px[code] = dp.set_index("date")["close"].astype(float)
        # ROE: keep only full-year (12-31) reports, as (period_end, roe) sorted ascending.
        rpath = ROE / f"{code}.csv"
        if rpath.exists():
            try:
                dr = pd.read_csv(rpath)
                dr["date"] = pd.to_datetime(dr["date"]).dt.strftime("%Y-%m-%d")
                fy = [(d, float(v)) for d, v in zip(dr["date"], dr["roe"])
                      if str(d).endswith("-12-31") and pd.notna(v)]
                roe[code] = sorted(fy)
            except Exception:
                pass
    return val, px, roe


def _roe_asof(fy_list, t: str):
    """Latest full-year ROE whose FY-end is >= ROE_LAG_DAYS before t (publication-safe)."""
    import datetime as dt

    if not fy_list:
        return None
    tt = dt.date.fromisoformat(t)
    best = None
    for d, v in fy_list:  # ascending; take the last that clears the lag
        if (tt - dt.date.fromisoformat(d)).days >= ROE_LAG_DAYS:
            best = v
    return best


def _month_ends(all_dates: list[str]) -> list[str]:
    by_month: dict[str, str] = {}
    for d in sorted(all_dates):
        by_month[d[:7]] = d  # last seen date in each YYYY-MM
    return [by_month[m] for m in sorted(by_month)]


def _stats(curve, dates):
    import math

    rets = [curve[i] / curve[i - 1] - 1.0 for i in range(1, len(curve))]
    if not rets:
        return {}
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / max(1, n - 1)
    sd = var ** 0.5
    periods_per_year = 12.0  # monthly
    ann_ret = (curve[-1] / curve[0]) ** (periods_per_year / n) - 1.0
    ann_vol = sd * math.sqrt(periods_per_year)
    sharpe = (mean / sd) * math.sqrt(periods_per_year) if sd > 0 else None
    peak = curve[0]
    maxdd = 0.0
    for v in curve:
        peak = max(peak, v)
        maxdd = min(maxdd, v / peak - 1.0)
    return {"total": curve[-1] - 1.0, "cagr": ann_ret, "vol": ann_vol,
            "sharpe": sharpe, "maxdd": maxdd, "months": n}


def _asof(series_index_sorted, prices, target):
    """Latest available price on/before target date (within ~10 days)."""
    import bisect

    i = bisect.bisect_right(series_index_sorted, target) - 1
    if i < 0:
        return None
    d = series_index_sorted[i]
    # guard against a stale price from a long-suspended stock
    if (int(target[:4]) * 12 + int(target[5:7])) - (int(d[:4]) * 12 + int(d[5:7])) > 1:
        return None
    return prices.get(d)


def backtest() -> None:
    import bisect

    val, px, roe = _load_panels()
    n_roe = sum(1 for c in val if roe.get(c))
    print(f"loaded {len(val)} stocks (valuation+price); {n_roe} with usable annual ROE")
    all_dates = sorted({d for s in px.values() for d in s.index})
    me = [d for d in _month_ends(all_dates) if d >= "2014-01-01"]
    px_sorted = {c: sorted(s.index) for c, s in px.items()}
    val_sorted = {c: sorted(s.index) for c, s in val.items()}

    # Books: each selects from the monthly cross-section, equal-weights, pays turnover cost.
    # selector(cands) -> list of chosen codes. cands rows = (code, pb, pe, roe_or_None, fwd_ret).
    def sel_value(cands, ntop):
        by_pb = {c: r for r, (c, *_2) in enumerate(sorted(cands, key=lambda x: x[1]))}
        by_pe = {c: r for r, (c, *_2) in enumerate(sorted(cands, key=lambda x: x[2]))}
        return [x[0] for x in sorted(cands, key=lambda x: by_pb[x[0]] + by_pe[x[0]])[:ntop]]

    def sel_quality(cands, ntop):
        q = [x for x in cands if x[3] is not None]
        return [x[0] for x in sorted(q, key=lambda x: -x[3])[:ntop]]  # high ROE first

    def sel_qualvalue(cands, ntop):
        q = [x for x in cands if x[3] is not None]
        by_pb = {c: r for r, (c, *_2) in enumerate(sorted(q, key=lambda x: x[1]))}
        by_pe = {c: r for r, (c, *_2) in enumerate(sorted(q, key=lambda x: x[2]))}
        by_roe = {c: r for r, (c, *_2) in enumerate(sorted(q, key=lambda x: -x[3]))}
        return [x[0] for x in sorted(q, key=lambda x: by_pb[x[0]] + by_pe[x[0]] + by_roe[x[0]])[:ntop]]

    books = {
        "VALUE (cheap)": {"sel": sel_value, "eq": [1.0], "prev": set(), "yr": {}},
        "QUALITY (hi ROE)": {"sel": sel_quality, "eq": [1.0], "prev": set(), "yr": {}},
        "QUAL×VALUE": {"sel": sel_qualvalue, "eq": [1.0], "prev": set(), "yr": {}},
    }
    eq_ew = [1.0]
    rows_used = []

    for k in range(len(me) - 1):
        t, t1 = me[k], me[k + 1]
        cands = []
        for c in val:
            j = bisect.bisect_right(val_sorted[c], t) - 1
            if j < 0:
                continue
            vd = val_sorted[c][j]
            if (int(t[:4]) * 12 + int(t[5:7])) - (int(vd[:4]) * 12 + int(vd[5:7])) > 1:
                continue
            try:
                pb = float(val[c].loc[vd, "pb"]); pe = float(val[c].loc[vd, "pe"])
            except Exception:
                continue
            p0 = _asof(px_sorted[c], px[c], t)
            p1 = _asof(px_sorted[c], px[c], t1)
            if pb <= 0 or pe <= 0 or p0 is None or p1 is None or p0 <= 0:
                continue
            cands.append((c, pb, pe, _roe_asof(roe.get(c), t), p1 / p0 - 1.0))
        if len(cands) < 20:
            for b in books.values():
                b["eq"].append(b["eq"][-1])
            eq_ew.append(eq_ew[-1])
            continue
        fwd = {x[0]: x[4] for x in cands}
        ntop = max(10, int(len(cands) * TOP_QUANTILE))
        for b in books.values():
            held = set(b["sel"](cands, ntop))
            if not held:
                b["eq"].append(b["eq"][-1])
                continue
            ret = sum(fwd[c] for c in held) / len(held)
            turnover = len(held ^ b["prev"]) / max(1, len(held))
            ret -= COST_PER_SIDE * turnover
            b["prev"] = held
            b["eq"].append(b["eq"][-1] * (1.0 + ret))
            b["yr"][t[:4]] = b["yr"].get(t[:4], 1.0) * (1.0 + ret)
        eq_ew.append(eq_ew[-1] * (1.0 + sum(fwd.values()) / len(fwd)))
        rows_used.append(t)

    bench_curve = _benchmark(me)
    start = me.index(rows_used[0]) if rows_used else 0

    def rebase(curve):
        if not curve or start >= len(curve) or not curve[start]:
            return []
        return [v / curve[start] for v in curve[start:]]

    print("\n" + "=" * 78)
    print("BUFFETT CUTS — A-share single-stock, top-20% equal-wt, monthly, net of cost")
    print("=" * 78)
    eff_start = me[start] if rows_used else me[0]
    print(f"window {eff_start} -> {me[-1]}  rebalances={len(rows_used)}  cost={COST_PER_SIDE*100:.2f}%/side")
    series = [(name, b["eq"]) for name, b in books.items()]
    series += [("EQUAL-WT (no select)", eq_ew), ("CSI300 buy-hold", bench_curve)]
    bt_dates = me[start:]
    for label, curve in series:
        s = _stats(rebase(curve), bt_dates)
        if not s:
            continue
        sh = f"{s['sharpe']:+.2f}" if s["sharpe"] is not None else " n/a"
        print(f"{label:<22} total {s['total']*100:>+7.1f}%  CAGR {s['cagr']*100:>+6.1f}%  "
              f"vol {s['vol']*100:>4.1f}%  Sharpe {sh}  maxDD {s['maxdd']*100:>6.1f}%")
    print("\nper-year (net):")
    for name, b in books.items():
        print(f"  {name:<18} " + " ".join(f"{y}:{(v-1)*100:+.0f}%" for y, v in sorted(b["yr"].items())))
    print("\nKEY COMPARISON: each selection book vs EQUAL-WT (same 300, no selection).")
    print("If a book can't beat EQUAL-WT, its selection signal adds no alpha — the return is")
    print("the equal-weight breadth premium. CAVEAT: current CSI300 -> survivorship flatters all.")


def _benchmark(me: list[str]):
    import akshare as ak
    import pandas as pd

    try:
        df = _retry(lambda: ak.stock_zh_index_daily(symbol="sh000300"))
        dcol = _pick(df.columns, "date"); ccol = _pick(df.columns, "close")
        df = df[[dcol, ccol]].copy()
        df[dcol] = pd.to_datetime(df[dcol]).dt.strftime("%Y-%m-%d")
        s = df.set_index(dcol)[ccol].astype(float)
        idx = sorted(s.index)
        import bisect
        curve = [1.0]
        base = None
        for d in me:
            j = bisect.bisect_right(idx, d) - 1
            if j < 0:
                continue
            px_ = s.loc[idx[j]]
            if base is None:
                base = px_
            curve.append(px_ / base)
        return curve[: len(me)]
    except Exception as e:  # noqa: BLE001
        print("benchmark fetch failed:", str(e)[:80])
        return []


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "bt"
    if mode == "fetch":
        limit = None
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        fetch(limit)
    elif mode == "bt":
        backtest()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
