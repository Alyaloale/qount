"""G20-SLT v2 out-of-sample forward test on 2026 data + perp carrier calibration.

Consumes the 2026-01..2026-10 sample that the v2 rule set has never been tuned
on (design and ablations stop at 2025-12-31), using refreshed Yahoo ETF proxies
(closing 2026-11-02) alongside the panel_seven crypto klines (closing
2026-10-26).  The forward window is a standalone account start, not a
continuation of the era curve.

Also calibrates the two long-standing proxy assumptions against real Binance
USDM SPY/QQQ perp mark data (2026-04-06..2026-10-31): price-path tracking and
realized funding.  No strategy replay runs on perp-only data — two legs and no
120-bar warmup make it uninformative.

research_only=true / orders_authorized=false.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ETF_REFRESH = Path("state/research_cache/yahoo_etf_refresh_20261102")
PERP_CACHE = Path("state/research_cache/binance_etf_leverage_20261015")
DAY = 86400


def load_study():
    spec = importlib.util.spec_from_file_location(
        "study_v2", REPO_ROOT / "scripts/research/study_g20_v2_small_leverage.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def perp_daily(symbol):
    """Aggregate hourly mark klines to UTC-day OHLC; daily funding sums."""
    marks = json.loads((PERP_CACHE / f"{symbol}-mark-1775520000-1790899200.json").read_text())
    bars = {}
    for row in marks:
        day = int(row[0]) // 1000 // DAY * DAY
        o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
        if day in bars:
            p = bars[day]
            bars[day] = (p[0], max(p[1], h), min(p[2], l), c)
        else:
            bars[day] = (o, h, l, c)
    funding_rows = json.loads(
        (PERP_CACHE / f"{symbol}-funding-1775520000-1790899200.json").read_text())
    daily_funding = {}
    for r in funding_rows:
        day = int(r["fundingTime"]) // 1000 // DAY * DAY
        daily_funding[day] = daily_funding.get(day, 0.0) + float(r["fundingRate"])
    return bars, daily_funding


def calibrate(study, panel):
    """Proxy (Yahoo-adjusted) vs real perp mark, common UTC days."""
    out = {}
    for symbol in ("SPYUSDT", "QQQUSDT"):
        bars, daily_funding = perp_daily(symbol)
        j = list(panel["symbols"]).index(symbol)
        proxy = {int(panel["times"][i]): float(panel["close"][i, j])
                 for i in range(len(panel["times"]))}
        days = sorted(set(bars) & set(proxy))
        p_close = np.asarray([proxy[d] for d in days])
        r_close = np.asarray([bars[d][3] for d in days])
        pr = np.diff(p_close) / p_close[:-1]
        rr = np.diff(r_close) / r_close[:-1]
        common = np.isfinite(pr) & np.isfinite(rr)
        # Funding stats over the full funding span (weekends included); the
        # trading-day comparison above would drop 2/7 of the accruals.
        rates_all = list(daily_funding.values())
        span_all = (max(daily_funding) - min(daily_funding)) / (365.25 * DAY)
        out[symbol] = dict(
            window=f"{datetime.fromtimestamp(days[0], timezone.utc).date()}.."
                   f"{datetime.fromtimestamp(days[-1], timezone.utc).date()}",
            days=len(days),
            proxy_total_return_pct=round((p_close[-1] / p_close[0] - 1) * 100, 2),
            perp_total_return_pct=round((r_close[-1] / r_close[0] - 1) * 100, 2),
            daily_return_corr=round(float(np.corrcoef(pr[common], rr[common])[0, 1]), 4),
            tracking_error_daily_bp=round(float(np.std(pr[common] - rr[common]) * 1e4), 1),
            max_abs_daily_diff_bp=round(float(np.max(np.abs(pr[common] - rr[common]))) * 1e4, 1),
            perp_funding_total_pct=round(sum(rates_all) * 100, 3),
            perp_funding_annual_pct=round(sum(rates_all) / span_all * 100, 2),
            funding_note="positive = longs pay; full funding-file span, not the "
                         "trading-day comparison window",
        )
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/g20_v2_forward_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    study = load_study()
    panel, extra, sources = study.build_full_panel(etf_root=ETF_REFRESH)
    filters = study.build_filters()
    days = panel["times"]
    fwd_left = int(np.searchsorted(days, int(datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp())))
    fwd = (int(days[fwd_left]), int(days[-1]))
    print("forward window:", datetime.fromtimestamp(fwd[0], timezone.utc).date(),
          "..", datetime.fromtimestamp(fwd[1], timezone.utc).date(),
          f"({len(days) - fwd_left} bars)")

    v2 = dict(max_positions=3, position_gross=2.0, core_mode="pool",
              exit_mode="either", position_mode="risk_parity",
              require_rank_positive=False, min_trend_age=20, max_crypto=1,
              crypto_symbols=study.CRYPTO)
    # fraction mode sizes per slot; 2/3 per slot matches the 2.0 total gross.
    eq_notional = dict(v2, position_mode="fraction", position_gross=2.0 / 3)

    def ladder(tag, window):
        return [
            (f"v2_core_2x3_{tag}", dict(v2), True, True, *window),
            (f"v2_age0_{tag}", dict(v2, min_trend_age=0), True, True, *window),
            (f"v2_age10_{tag}", dict(v2, min_trend_age=10), True, True, *window),
            (f"v2_age40_{tag}", dict(v2, min_trend_age=40), True, True, *window),
            (f"v2_equal_notional_{tag}", dict(eq_notional), True, True, *window),
        ]

    grid_4387 = study.run_cells(panel, extra, ladder("fwd", fwd), filters, capital=43.87)
    grid_2125 = study.run_cells(panel, extra,
                                [("v2_core_2x3_fwd", dict(v2), True, True, *fwd)],
                                filters, capital=21.25)
    # Matched-era reference on the refreshed panel: same 2x3 cells, same data,
    # so the cross-window comparison is config-matched (era archives ran the
    # age ladder at 3x3 on the pre-refresh ETF files).
    era_end = int(np.searchsorted(days, int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())))
    era_window = (int(days[int(np.searchsorted(days, int(
        datetime(2022, 6, 28, tzinfo=timezone.utc).timestamp())))]), int(days[era_end - 1]))
    grid_era = study.run_cells(panel, extra, ladder("era", era_window), filters, capital=43.87)

    # ---- deliberate drawdown de-leveraging (pre-registered mechanism test) ----
    # While account equity sits >=10%/20% below its highwater mark, resize and
    # entry gross is halved and restores on recovery.  Controls: core 2x3 (no
    # rule, in the grids above) and a constant 1x/3 book — the rule must add
    # value over simply running less leverage.
    dd_cells = [
        ("dd10_half_era", dict(v2, dd_deleverage_threshold=0.10,
                               dd_deleverage_factor=0.5), True, True, *era_window),
        ("dd20_half_era", dict(v2, dd_deleverage_threshold=0.20,
                               dd_deleverage_factor=0.5), True, True, *era_window),
        ("core_1x3_era", dict(v2, position_gross=1.0), True, True, *era_window),
        ("dd10_half_fwd", dict(v2, dd_deleverage_threshold=0.10,
                               dd_deleverage_factor=0.5), True, True, *fwd),
        ("dd20_half_fwd", dict(v2, dd_deleverage_threshold=0.20,
                               dd_deleverage_factor=0.5), True, True, *fwd),
        ("core_1x3_fwd", dict(v2, position_gross=1.0), True, True, *fwd),
    ]
    grid_dd = study.run_cells(panel, extra, dd_cells, filters, capital=43.87)

    # ---- crypto latency/slippage stress on the signal-price fill assumption ----
    # slip10/slip20 = +10bp/+20bp one-way surcharge on crypto legs only
    # (total crypto cost 20bp/30bp vs the 10bp base; ETF legs unchanged).
    grid_slip = {}
    for tag, surcharge in (("slip10", 20.0), ("slip20", 30.0)):
        cells = [(f"core_{tag}_era", dict(v2), True, True, *era_window),
                 (f"core_{tag}_fwd", dict(v2), True, True, *fwd)]
        grid_slip.update(study.run_cells(panel, extra, cells, filters,
                                         capital=43.87, crypto_cost_bp=surcharge))

    cli = study.load_cli()
    baselines = {
        "ew_14_fwd": cli.equal_weight_baseline(
            panel, fwd_left, len(days) - 1, capital=43.87),
        "ew_14_era_refreshed": cli.equal_weight_baseline(
            panel, int(np.searchsorted(days, era_window[0])),
            era_end - 1, capital=43.87),
    }

    payload = dict(
        research_only=True, orders_authorized=False,
        generated_at=datetime.now(timezone.utc).isoformat(),
        sample_identity="standalone forward account start 2026-01-02; v2 rules never "
                        "tuned on 2026 data (design/ablations end 2025-12-31); 2026 "
                        "markets were already observed in sibling G20 lines, so this "
                        "is out-of-sample for the rule set, not an unseen market",
        sources=dict(full=sources, perp_marks=[
            str(PERP_CACHE / f"{s}-{k}-1775520000-1790899200.json")
            for s in ("SPYUSDT", "QQQUSDT") for k in ("mark", "funding")]),
        assumptions=[
            "Same contract as g20_v2_small_leverage (2x/3 slots, risk_parity, "
            "min_trend_age=20, max_crypto=1, either exit, 10bp, MM 2.5%).",
            "Sizing: below-minimum resize targets go to cash (min_notional_exit).",
            "Crypto fills at signal price; ETF proxies zero funding; refreshed "
            "Yahoo files close 2026-11-02 and may revisit dividends after the "
            "era archive (era numbers are not re-certified here).",
            "CAGR over a <1 year window is reported for shape only; read totals.",
        ],
        experiments=dict(forward_capital4387=grid_4387,
                         forward_capital2125=grid_2125,
                         era_reference_2x3=grid_era,
                         drawdown_rule=grid_dd,
                         crypto_slippage_stress=grid_slip,
                         baselines=baselines,
                         perp_calibration=calibrate(study, panel)),
    )
    (args.output / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n")

    for tag, grid in (("43.87U", grid_4387), ("21.25U", grid_2125)):
        print(f"== forward 2026-01-02..{datetime.fromtimestamp(fwd[1], timezone.utc).date()} @{tag}")
        for key, row in grid.items():
            print(key, study.fmt(row))
    print("== era reference (matched 2x3 cells, refreshed panel) @43.87U")
    for key, row in grid_era.items():
        print(key, study.fmt(row))
    print("== drawdown de-leverage rule + constant 1x control @43.87U")
    for key, row in grid_dd.items():
        print(key, study.fmt(row))
    print("== crypto slippage stress @43.87U")
    for key, row in grid_slip.items():
        print(key, study.fmt(row))
    print("== baselines:", json.dumps(baselines, indent=1))
    print("== perp calibration:", json.dumps(payload["experiments"]["perp_calibration"], indent=1))


if __name__ == "__main__":
    main()
