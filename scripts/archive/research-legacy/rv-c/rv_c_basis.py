#!/usr/bin/env python3
"""RV-C: dated quarterly-futures basis cash-and-carry kill-test (docs/rv-c-plan.md).

线 C (RV-C), hard-anchor relative value, isolated from 线 A/B. Long spot + short the active
COIN-M quarterly future, Δ≈0, harvesting the annualized basis premium that the dated
contract is *contractually forced* to converge into the short leg at expiry -- the hard anchor
H3's perpetual (线 B, dead) lacked. The kill question (§3): does the thin basis survive
two-leg retail fees + quarterly roll cost + the physical liquidation tail (L=3x)?

Pre-registered verdict (§3, do not change after seeing the number; L=3 is the gate):
    (1) annualized net > +2%
    (2) >= 4/6 (>=66%) tradeable years net-positive  (esp. backwardation bear segments)
    (3) tail survival: total net > 0 with liquidation tail + deepest backwardation included
    All three -> hard-anchor RV alive; else -> RV family dead at its hardest anchor -> 收口.

Leverage sweep (∞/10/5/3x) is reported; L=3 is the pre-registered judging leverage.

Run on Mac (needs network to data.binance.vision: spot klines + futures/cm dated klines):
    .venv/bin/python scripts/research/rv_c_basis.py BTCUSD BTCUSDT 2021-01 2026-05
    .venv/bin/python scripts/research/rv_c_basis.py ETHUSD ETHUSDT 2021-01 2026-05
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import load_klines  # noqa: E402
from qount.legacy.rv_c.basis import build_active_series  # noqa: E402
from qount.legacy.rv_c.backtest import run_basis_carry  # noqa: E402
from qount.legacy.rv_c.data import load_contract_set  # noqa: E402

ARTIFACT_DIR = REPO / "state" / "rv_c" / "research_runs"
ROLL_BUFFER_DAYS = 5.0
SWEEP = [None, 10.0, 5.0, 3.0]   # ∞/10/5/3x; 3x is the pre-registered gate
GATE_LEVERAGE = 3.0


def _annualized(net: float, n_bars: int, bars_per_year: float = 365.0) -> float:
    years = n_bars / bars_per_year
    if years <= 0:
        return 0.0
    if 1.0 + net <= 0.0:
        return -1.0
    return (1.0 + net) ** (1.0 / years) - 1.0


def main(argv: list[str]) -> int:
    cm_base = argv[1] if len(argv) > 1 else "BTCUSD"     # COIN-M dated base (BTCUSD/ETHUSD)
    spot_sym = argv[2] if len(argv) > 2 else "BTCUSDT"   # spot symbol
    start = argv[3] if len(argv) > 3 else "2021-01"
    end = argv[4] if len(argv) > 4 else "2026-05"
    interval = argv[5] if len(argv) > 5 else "1d"   # "1d" or "1h" (hourly liq-precision check)
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    # daily margin top-up cadence; hourly bars check liquidation intrabar but rebalance daily.
    bars_per_year = 365.0 if interval == "1d" else 365.0 * 24.0
    rebalance_bars = 1 if interval == "1d" else 24

    print(f"[RV-C] {cm_base} dated basis vs {spot_sym} spot {start}..{end} ({interval})")
    spot = load_klines(spot_sym, interval, start=(sy, sm), end=(ey, em), market="spot",
                       skip_missing=True)
    contracts = load_contract_set(start=(sy, sm), end=(ey, em), base=cm_base, interval=interval)
    if not spot or not contracts:
        print("  missing spot or dated contracts on binance.vision")
        return 2
    active = build_active_series(spot, contracts, roll_buffer_days=ROLL_BUFFER_DAYS)
    if not active:
        print("  no aligned spot/dated bars after splice")
        return 2
    n_rolls = sum(1 for ab in active if ab.is_roll)
    print(f"  spot bars: {len(spot)}; dated contracts: {len(contracts)}; "
          f"active spliced bars: {len(active)} ({active[0].spot.date}..{active[-1].spot.date}); "
          f"rolls: {n_rolls}; rebalance every {rebalance_bars} bar(s); "
          f"entry ann-basis: {active[0].annualized_basis:+.2%}")

    # Inverse-hardened is the primary verdict (RV-C #1 hole: COIN-M dated is coin-margined;
    # under daily rebalance carry is first-order identical but the liq trigger sits later).
    sweep_results = {}
    gate = None
    for lev in SWEEP:
        r = run_basis_carry(active, liq_leverage=lev, inverse=True, rebalance_bars=rebalance_bars)
        sweep_results[str(lev)] = r
        ann = _annualized(r.net_return, r.n_bars, bars_per_year)
        won = sum(1 for y in r.per_year if y.net_return > 0)
        tag = "∞" if lev is None else f"{lev:g}x"
        print(f"\n=== L={tag} (inverse) ===")
        print(f"  {r.verdict}")
        print(f"  net {r.net_return:+.2%} (annualized {ann:+.2%}); "
              f"net-positive years {won}/{len(r.per_year)}")
        print(f"  decomposition: carry {r.carry_pnl:+.2%} − roll {r.roll_cost:.2%} "
              f"− fees {r.fee_cost:.2%} − liq {r.liq_cost:.2%} ({r.liq_events}x); "
              f"maxDD {r.max_drawdown:.2%}")
        if lev == GATE_LEVERAGE:
            gate = r

    lin_gate = run_basis_carry(active, liq_leverage=GATE_LEVERAGE, inverse=False,
                               rebalance_bars=rebalance_bars)
    print(f"\n  [linear-vs-inverse L={GATE_LEVERAGE:g}x] linear net {lin_gate.net_return:+.2%} "
          f"({lin_gate.liq_events}x liq) vs inverse net {gate.net_return:+.2%} "
          f"({gate.liq_events}x liq) -- inverse should be >= linear (later liq trigger)")

    assert gate is not None
    ann_g = _annualized(gate.net_return, gate.n_bars, bars_per_year)
    won_g = sum(1 for y in gate.per_year if y.net_return > 0)
    n_years = len(gate.per_year)
    c1 = ann_g > 0.02
    c2 = n_years > 0 and won_g / n_years >= 0.66
    c3 = gate.net_return > 0.0   # tail (liq + backwardation) already in net
    passed = c1 and c2 and c3
    print(f"\n=== RV-C verdict (§3 pre-registered; L={GATE_LEVERAGE:g}x is the gate) ===")
    print(f"  (1) annualized net > +2%        : {'✓' if c1 else '✗'}  ({ann_g:+.2%})")
    print(f"  (2) >= 66% years net-positive   : {'✓' if c2 else '✗'}  ({won_g}/{n_years})")
    print(f"  (3) tail-survival net > 0       : {'✓' if c3 else '✗'}  ({gate.net_return:+.2%})")
    if passed:
        verdict = "硬锚 RV 成立(L=3 三项全过)→ 扩赎回锚对 + S2 盘口 + S3 DSR/PBO"
    else:
        verdict = "硬锚 RV 也 sub-gate(连最硬的锚都不够 edge)→ 与线 B 同型收口,RV 族判死"
    print(f"  → {verdict}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARTIFACT_DIR / f"basis_{cm_base}_{start}_{end}_{interval}_{stamp}.json"
    payload = {
        "cm_base": cm_base, "spot_symbol": spot_sym, "start": start, "end": end,
        "interval": interval, "rebalance_bars": rebalance_bars,
        "roll_buffer_days": ROLL_BUFFER_DAYS, "n_active_bars": len(active),
        "n_contracts": len(contracts), "n_rolls": n_rolls,
        "gate_leverage": GATE_LEVERAGE,
        "criteria": {"c1_ann_gt_2pct": c1, "c2_years": c2, "c3_tail": c3, "passed": passed},
        "verdict": verdict,
        "sweep": {
            lev: {k: v for k, v in dataclasses.asdict(r).items() if k != "curve"}
            for lev, r in sweep_results.items()
        },
    }
    out.write_text(json.dumps(payload, indent=2, default=float))
    print(f"\n  artifact: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
