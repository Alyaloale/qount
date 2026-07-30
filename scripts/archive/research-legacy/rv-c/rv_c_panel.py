#!/usr/bin/env python3
"""RV-C breadth panel: is the dated-basis carry edge BROAD or a BTC/ETH artefact? (线 C).

§3 of ``docs/rv-c-plan.md`` passed BTC/ETH at the L=3 gate, hardened twice (inverse account +
hourly liq granularity). This panel runs the *same* hard-anchor hypothesis across the next
most-liquid COIN-M coins that carry dated quarterlies -- a robustness check, NOT a search. The
universe is fixed by **liquidity + dated-history availability** (probed: BNB/XRP/ADA/LINK/LTC/
BCH/DOT have 2021+ dated; SOL is 2024+), so this does not trip 杀手3 (multiple testing): we are
not cherry-picking pairs, we take every liquid COIN-M with a dated contract.

Pre-registered breadth verdict (write before running):
    Each symbol judged on the §3 L=3 gate over ITS available years (inverse account):
        (1) annualized net > +2%   (2) >= 66% years net-positive   (3) total net > 0
    BREADTH PASS  if a clear majority (>= 5 of the ~8) pass the gate -> the basis edge is a
                  broad risk premium, BTC/ETH were not special.
    BREADTH FAIL  if only BTC/ETH (or <= a couple) pass -> the edge is narrow/fragile; treat
                  the BTC/ETH pass as instrument-specific, not a general RV result.

Run on Mac (network; daily bars -- hourly already showed daily doesn't understate liq at L=3):
    .venv/bin/python scripts/research/rv_c_panel.py
"""
from __future__ import annotations

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
GATE_LEVERAGE = 3.0

# Fixed universe: BTC/ETH (already passed) + every liquid COIN-M with a dated quarterly.
# (cm_base, spot_symbol). Probed availability: all 2021+ except SOL (2024+).
PANEL = [
    ("BTCUSD", "BTCUSDT"), ("ETHUSD", "ETHUSDT"), ("BNBUSD", "BNBUSDT"),
    ("XRPUSD", "XRPUSDT"), ("ADAUSD", "ADAUSDT"), ("LINKUSD", "LINKUSDT"),
    ("LTCUSD", "LTCUSDT"), ("BCHUSD", "BCHUSDT"), ("DOTUSD", "DOTUSDT"),
    ("SOLUSD", "SOLUSDT"),
]


def _annualized(net: float, n_bars: int) -> float:
    years = n_bars / 365.0
    if years <= 0:
        return 0.0
    if 1.0 + net <= 0.0:
        return -1.0
    return (1.0 + net) ** (1.0 / years) - 1.0


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))

    # S2 maker scenario (best-case, assumes fills): open/roll/rebalance as maker at BNB-discount
    # retail rates (spot 0.075% / dated 0.02%); liq-reopen stays taker. A pass here that fails
    # under taker is a fee-relief upper bound (see run_basis_carry docstring).
    MAKER_KW = dict(spot_maker=0.00075, dated_maker=0.0002,
                    maker_open=True, maker_roll=True, maker_rebalance=True)

    def _gate(active, **extra):
        r = run_basis_carry(active, liq_leverage=GATE_LEVERAGE, inverse=True, **extra)
        ann = _annualized(r.net_return, r.n_bars)
        won = sum(1 for y in r.per_year if y.net_return > 0)
        ny = len(r.per_year)
        passed = ann > 0.02 and (ny > 0 and won / ny >= 0.66) and r.net_return > 0.0
        return r, ann, won, ny, passed

    print(f"[RV-C panel] dated-basis carry breadth {start}..{end}, inverse L={GATE_LEVERAGE:g}x")
    print(f"  universe (fixed by liquidity+dated-history): {len(PANEL)} COIN-M coins")
    print(f"  taker = spot 10bp/dated 5bp; maker = spot 7.5bp/dated 2bp (best-case, assumes fills)\n")

    rows = []
    for cm_base, spot_sym in PANEL:
        spot = load_klines(spot_sym, "1d", start=(sy, sm), end=(ey, em), market="spot",
                           skip_missing=True)
        contracts = load_contract_set(start=(sy, sm), end=(ey, em), base=cm_base)
        if not spot or not contracts:
            print(f"  {cm_base:9s} -- no data, skipped")
            continue
        active = build_active_series(spot, contracts, roll_buffer_days=ROLL_BUFFER_DAYS)
        if not active:
            print(f"  {cm_base:9s} -- no aligned bars, skipped")
            continue
        rt, ann_t, won_t, ny, pass_t = _gate(active)
        rm, ann_m, won_m, _, pass_m = _gate(active, **MAKER_KW)
        flip = pass_m and not pass_t
        rows.append({
            "cm_base": cm_base, "spot": spot_sym, "n_bars": rt.n_bars,
            "from": active[0].spot.date, "to": active[-1].spot.date,
            "entry_basis_ann": rt.entry_basis_ann, "years": ny,
            "taker": {"net": rt.net_return, "ann": ann_t, "won": won_t,
                      "liq": rt.liq_events, "fees": rt.fee_cost, "passed": pass_t},
            "maker": {"net": rm.net_return, "ann": ann_m, "won": won_m,
                      "fees": rm.fee_cost, "passed": pass_m},
            "carry": rt.carry_pnl, "flip": flip,
        })
        mt = "✓" if pass_t else "✗"
        mm = "✓" if pass_m else "✗"
        flag = " <== FLIP" if flip else ""
        print(f"  {cm_base:9s} {rows[-1]['from']}..{rows[-1]['to']} | carry {rt.carry_pnl:+6.1%} "
              f"| taker ann {ann_t:+6.2%} {mt}  ->  maker ann {ann_m:+6.2%} {mm} "
              f"(fees {rt.fee_cost:.1%}->{rm.fee_cost:.1%}){flag}")

    n_pass = sum(1 for r in rows if r["taker"]["passed"])
    n_pass_m = sum(1 for r in rows if r["maker"]["passed"])
    flips = [r["cm_base"] for r in rows if r["flip"]]
    n_tot = len(rows)
    breadth_pass = n_pass >= 5
    print(f"\n=== RV-C breadth verdict (pre-registered: >= 5 of ~8 pass L=3 gate) ===")
    print(f"  taker: passed {n_pass}/{n_tot};  maker(best-case): passed {n_pass_m}/{n_tot}"
          f"{'  flips: ' + ','.join(flips) if flips else '  (no flips)'}")
    if breadth_pass:
        verdict = (f"广度成立(taker {n_pass}/{n_tot} 过)→ dated 基差 carry 是宽风险溢价。")
    else:
        verdict = (f"广度不成立(taker {n_pass}/{n_tot} 过)→ edge 窄而真,仅最深 majors 成立。"
                   f"maker(best-case)拓宽至 {n_pass_m}/{n_tot}"
                   f"{'(翻盘 ' + ','.join(flips) + ')' if flips else '(无翻盘 → 薄 carry 才是主杀手,非费)'}。")
    print(f"  → {verdict}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARTIFACT_DIR / f"panel_{start}_{end}_{stamp}.json"
    payload = {
        "start": start, "end": end, "gate_leverage": GATE_LEVERAGE,
        "roll_buffer_days": ROLL_BUFFER_DAYS,
        "n_pass_taker": n_pass, "n_pass_maker": n_pass_m, "n_total": n_tot,
        "breadth_pass": breadth_pass, "flips": flips, "verdict": verdict,
        "rows": rows,
    }
    out.write_text(json.dumps(payload, indent=2, default=float))
    print(f"\n  artifact: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
