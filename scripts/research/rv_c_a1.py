#!/usr/bin/env python3
"""RV-C A1: basis-conditional deployment sweep on the certified BTC/ETH (docs/rv-c-plan.md §7.9).

Always-on cash-and-carry harvests whatever basis exists, including the thin / backwardation drag.
A1 deploys only while the annualized basis is fat (>= threshold) and stands flat in cash otherwise.
This sweeps the threshold to see the SHAPE: a robust monotone improvement across a band = a real
effect; a knife-edge peak = overfit. The threshold is a NEW parameter -> the chosen value must be
re-validated by S3 (rv_c_s3.py); this script only maps the response surface.

Reports per threshold: annualized net, Sharpe, % bars deployed, positive years -- maker + inverse,
L=3. ``None`` row = the always-on baseline (= §7.x certified numbers).

Run on Mac (network; reuses cached daily klines):
    .venv/bin/python scripts/research/rv_c_a1.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_klines  # noqa: E402
from qount.rv.basis import build_active_series  # noqa: E402
from qount.rv.backtest import run_basis_carry  # noqa: E402
from qount.rv.data import load_contract_set  # noqa: E402
from qount.rv.stats import returns_from_curve, sharpe  # noqa: E402

ARTIFACT_DIR = REPO / "state" / "rv_c" / "research_runs"
ROLL_BUFFER_DAYS = 5.0
PPY = 365.0
PAIRS = [("BTCUSD", "BTCUSDT"), ("ETHUSD", "ETHUSDT")]
THRESHOLDS = [None, 0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20]
MAKER_KW = dict(spot_maker=0.00075, dated_maker=0.0002,
                maker_open=True, maker_roll=True, maker_rebalance=True)


def _ann(net: float, n: int) -> float:
    yrs = n / PPY
    if yrs <= 0 or 1.0 + net <= 0.0:
        return -1.0 if 1.0 + net <= 0.0 else 0.0
    return (1.0 + net) ** (1.0 / yrs) - 1.0


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    print(f"[RV-C A1] basis-conditional deployment sweep {start}..{end}, inverse L=3, maker")
    out_rows = {}
    for cm_base, spot_sym in PAIRS:
        spot = load_klines(spot_sym, "1d", start=(sy, sm), end=(ey, em), market="spot",
                           skip_missing=True)
        contracts = load_contract_set(start=(sy, sm), end=(ey, em), base=cm_base)
        active = build_active_series(spot, contracts, roll_buffer_days=ROLL_BUFFER_DAYS)
        print(f"\n=== {cm_base} ({active[0].spot.date}..{active[-1].spot.date}, {len(active)}d) ===")
        print(f"  {'thresh':>7s} {'annNet':>7s} {'Sharpe':>7s} {'deploy%':>8s} {'posYr':>6s} {'liq':>4s}")
        rows = []
        for thr in THRESHOLDS:
            r = run_basis_carry(active, liq_leverage=3.0, inverse=True, min_ann_basis=thr,
                                **MAKER_KW)
            rets = returns_from_curve(r.curve)
            shp = sharpe(rets, periods_per_year=PPY) if rets else 0.0
            ann = _ann(r.net_return, r.n_bars)
            won = sum(1 for y in r.per_year if y.net_return > 0)
            ny = len(r.per_year)
            label = "always" if thr is None else f"{thr:.0%}"
            print(f"  {label:>7s} {ann:+7.2%} {shp:+7.2f} {r.deployed_fraction:8.1%} "
                  f"{won:>3d}/{ny} {r.liq_events:>4d}")
            rows.append({"thresh": thr, "ann": ann, "sharpe": shp, "net": r.net_return,
                         "deployed": r.deployed_fraction, "won": won, "years": ny,
                         "liq": r.liq_events})
        out_rows[cm_base] = rows

    print("\n  读法:annNet=对总资本年化(空仓期摊薄);Sharpe 升+deploy%降 = 跳过死时段抬风险调整后"
          "收益。\n  若改善跨多个阈值稳健(非单点峰)→ 真效应,选稳健带中点上 S3 复检;若刀尖峰 → 过拟合,弃。")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARTIFACT_DIR / f"a1_sweep_{start}_{end}_{stamp}.json"
    out.write_text(json.dumps({"start": start, "end": end, "thresholds": THRESHOLDS,
                               "rows": out_rows}, indent=2, default=float))
    print(f"\n  artifact: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
