"""G20-SLT v3 validation: full-pool leveraged hold + funding carry gate.

Pre-registered contract (design 2026-11-02, run same day):

* 11-leg 5U-tier pool (SOL/BNB/XRP + 8 ETF proxies), equal weight, total
  gross 2.0x, weekly rebalance (5 bars) + 25% relative drift band.
* Funding carry discipline: a leg whose trailing 30-bar annualized funding
  exceeds the gate (default 6%/yr) goes to cash at the next resize; BNB
  (structurally negative funding) is exempt.  No trend entry/exit, no
  ranking, no slot caps, no drawdown de-leveraging.
* Min-notional semantics (fixed 2026-11-02): a resize target below the
  exchange minimum closes the slot to cash, never freezes stale lots.
* Shared wallet, MM 2.5% flat, liquidation fee 1%, 10bp one-way.

Verdict gates (pre-registered, both windows, Calmar):
  1. core must beat the no-gate variant, else the funding gate is dead weight.
  2. core must beat v2 core (era 30.12%/47.00%, 2026 +13.0%/26.66%), else the
     redesign adds nothing.

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

from qount.research.crypto_g20_rotation import rounded_quantity

ETF_REFRESH = Path("state/research_cache/yahoo_etf_refresh_20261102")
DAY = 86400
POOL = ("SOLUSDT", "BNBUSDT", "XRPUSDT", "SPYUSDT", "QQQUSDT", "SMHUSDT",
        "IWMUSDT", "XLEUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT")
BNB = "BNBUSDT"


def load_study():
    spec = importlib.util.spec_from_file_location(
        "study_v2", REPO_ROOT / "scripts/research/study_g20_v2_small_leverage.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def replay_v3(panel, funding_annual, *, start, end, capital, gross=2.0,
              weight_mode="equal", gate_threshold=0.06, gate_window=30,
              bnb_floor=0.0, rebalance_bars=5, drift_band=0.25,
              cost_bp=10.0, filters=None, maintenance=0.025,
              liquidation_fee=0.01, vol=None):
    times = np.asarray(panel["times"], dtype=np.int64)
    names = tuple(panel["symbols"])
    left = int(np.searchsorted(times, start, side="left"))
    right = int(np.searchsorted(times, end, side="left"))
    if left < 1 or right <= left or right >= len(times):
        raise ValueError("invalid_v3_window")
    fee = cost_bp / 10000.0
    equity = float(capital)
    positions = {}  # symbol -> (col, qty, entry index)
    fills, curve = [], []
    counts = dict(entry=0, min_notional_exit=0, minimum_notional_skip=0,
                  resize_intervals=0, terminal_exit=0, shared_liquidation=0,
                  ruin=0, gate_events=0)
    attribution = {s: dict(price=0.0, funding=0.0, costs=0.0) for s in names}
    symbol_trades = {}
    highwater = equity
    gross_history = []

    def fee_of(_symbol):
        return fee

    def close_symbol(symbol, i, reason, price=None):
        nonlocal equity
        j, q, _entry = positions.pop(symbol)
        px = float(panel["open"][i, j] if price is None else price)
        charge = q * px * fee_of(symbol)
        equity -= charge
        attribution[symbol]["costs"] += charge
        fills.append(dict(time=int(times[i]), symbol=symbol, side="SELL",
                          quantity=float(q), price=px, costs=float(charge),
                          reason=reason))
        counts[reason] = counts.get(reason, 0) + 1

    def gate_state(signal):
        out = {}
        for j, s in enumerate(names):
            if s == BNB or gate_threshold is None:
                out[s] = False
                continue
            lo = max(0, signal - gate_window + 1)
            trail = float(np.mean(funding_annual[lo:signal + 1, j]))
            out[s] = bool(trail > gate_threshold)
        return out

    def shares_of(signal, gated):
        if weight_mode == "inverse_vol":
            inv = {s: 1.0 / max(float(vol[signal, j]), 0.05) for j, s in enumerate(names)}
        else:
            inv = {s: 1.0 for s in names}
        gated_sum = sum(w for s, w in inv.items() if gated.get(s))
        live = {s: w for s, w in inv.items() if not gated.get(s)}
        total = sum(live.values())
        shares = {s: (live[s] / total if s in live else 0.0) for s in names}
        if bnb_floor > 0 and BNB in names:
            extra = max(0.0, bnb_floor - shares[BNB])
            others = sum(v for s, v in shares.items() if s != BNB and v > 0)
            if extra > 0 and others > 0:
                for s in names:
                    if s != BNB and shares[s] > 0:
                        shares[s] -= extra * shares[s] / others
                shares[BNB] = bnb_floor
        return shares

    for i in range(left, right):
        signal = i - 1
        before = equity
        gated = gate_state(signal)
        shares = shares_of(signal, gated)

        def target_of(symbol):
            j = names.index(symbol)
            return (equity * gross * (0.0 if gated[symbol] else shares[symbol])
                    if not gated[symbol] else 0.0)

        scheduled = (i - left) % rebalance_bars == 0
        breach = False
        for symbol, (j, q, _e) in positions.items():
            tgt = target_of(symbol)
            actual = q * float(panel["open"][i, j])
            if tgt <= 0 or (tgt > 0 and abs(actual / tgt - 1.0) > drift_band):
                breach = True
        do_resize = (scheduled or breach) and equity > 0
        if do_resize:
            counts["resize_intervals"] += 1
            counts["gate_events"] += sum(1 for s in names if gated[s])
            for j, symbol in enumerate(names):
                tgt = target_of(symbol)
                price = float(panel["open"][i, j])
                quantity = rounded_quantity(tgt, price, symbol, filters)
                held = symbol in positions
                if quantity <= 0:
                    if held:
                        close_symbol(symbol, i, "min_notional_exit")
                    elif tgt > 0:
                        counts["minimum_notional_skip"] += 1
                    continue
                old_q = positions[symbol][1] if held else 0.0
                delta = quantity - old_q
                if delta:
                    charge = abs(delta) * price * fee_of(symbol)
                    equity -= charge
                    attribution[symbol]["costs"] += charge
                    if held:
                        # Record resize delta fills so cash-flow recount from
                        # fills is exact (entries record their own fill below).
                        fills.append(dict(time=int(times[i]), symbol=symbol,
                                          side="BUY" if delta > 0 else "SELL",
                                          quantity=float(abs(delta)), price=price,
                                          costs=float(charge), reason="resize"))
                if held:
                    positions[symbol] = (j, quantity, positions[symbol][2])
                else:
                    positions[symbol] = (j, quantity, i)
                    fills.append(dict(time=int(times[i]), symbol=symbol,
                                      side="BUY", quantity=float(quantity),
                                      price=price, costs=float(charge if delta else 0.0),
                                      reason="weight_entry"))
                    counts["entry"] += 1
                    symbol_trades[symbol] = symbol_trades.get(symbol, 0) + 1

        # shared-wallet liquidation on the bar's worst mark
        worst = float(equity)
        mark_notional = maintenance_value = 0.0
        for j, q, _e in positions.values():
            low = float(panel["mark_low"][i, j])
            debit = float(panel["funding_debit"][i, j])
            worst += q * (low - float(panel["open"][i, j]) - debit)
            mark_notional += q * low
            maintenance_value += q * low * maintenance
        liquidated = bool(positions and worst <= maintenance_value)
        price_pnl = funding_pnl = 0.0
        if liquidated:
            for symbol, (j, q, _e) in list(positions.items()):
                low = float(panel["mark_low"][i, j])
                debit = float(panel["funding_debit"][i, j])
                attribution[symbol]["price"] += q * (low - float(panel["open"][i, j]))
                attribution[symbol]["funding"] -= q * debit
                fills.append(dict(time=int(times[i]), symbol=symbol, side="SELL",
                                  quantity=float(q), price=low, costs=0.0,
                                  reason="shared_liquidation"))
                price_pnl += q * (low - float(panel["open"][i, j]))
                funding_pnl -= q * debit
            positions.clear()
            counts["shared_liquidation"] += 1
            equity = max(0.0, worst - mark_notional * liquidation_fee)
            counts["ruin"] += int(equity <= 0)
        else:
            for symbol, (j, q, _e) in list(positions.items()):
                pnl = q * (float(panel["open"][i + 1, j]) - float(panel["open"][i, j]))
                funding = -q * float(panel["funding_value"][i, j])
                equity += pnl + funding
                price_pnl += pnl
                funding_pnl += funding
                attribution[symbol]["price"] += pnl
                attribution[symbol]["funding"] += funding

        if i == right - 1 and positions and equity > 0:
            for symbol in list(positions):
                close_symbol(symbol, i + 1, "terminal_exit")
        if equity <= 0:
            equity = 0.0
            positions.clear()
            if not counts["ruin"]:
                counts["ruin"] = 1
        highwater = max(highwater, equity)
        gross_now = (sum(q * float(panel["open"][i, j]) for j, q, _e in positions.values())
                     / max(equity, 1e-30))
        gross_history.append(gross_now)
        curve.append(dict(time=int(times[i + 1]), equity=float(equity),
                          returns=float(equity / before - 1) if before else 0.0,
                          price_pnl=float(price_pnl), funding_pnl=float(funding_pnl),
                          gross=float(gross_now),
                          positions=tuple(sorted(positions))))

    nav = np.asarray([capital, *[r["equity"] for r in curve]]) / capital
    mdd = float(np.max(1 - nav / np.maximum.accumulate(nav)))
    years = (int(times[right]) - int(times[left])) / (365.25 * DAY)
    cagr = float(nav[-1] ** (1 / years) - 1) if nav[-1] > 0 else -1.0
    nets = {s: v["price"] + v["funding"] - v["costs"] for s, v in attribution.items()}
    positives = sorted((v for v in nets.values() if v > 0), reverse=True)
    psum = float(sum(positives))
    summary = dict(
        start=datetime.fromtimestamp(int(times[left]), timezone.utc).isoformat(),
        end_open=datetime.fromtimestamp(int(times[right]), timezone.utc).isoformat(),
        initial_usdt=float(capital), final_usdt=float(equity),
        return_pct=float((nav[-1] - 1) * 100), cagr_pct=cagr * 100,
        mdd_pct=mdd * 100, calmar=cagr / mdd if mdd else None,
        max_actual_gross=float(max(gross_history)) if gross_history else 0.0,
        mean_actual_gross=float(np.mean(gross_history)) if gross_history else 0.0,
        funding_pnl=float(sum(v["funding"] for v in attribution.values())),
        costs=float(sum(v["costs"] for v in attribution.values())),
        trades=int(sum(symbol_trades.values())), symbol_trades=dict(symbol_trades),
        top1_positive_pnl_share=float(positives[0] / psum) if psum > 0 else None,
        counts=dict(counts), attribution=attribution,
    )
    return dict(summary=summary, curve=curve, fills=fills)


def fmt(s):
    return (f"final={s['final_usdt']:>8.2f}  total={s['return_pct']:>7.1f}%  "
            f"cagr={s['cagr_pct']:>6.1f}%  mdd={s['mdd_pct']:>5.1f}%  "
            f"calmar={s['calmar'] if s['calmar'] is None else round(s['calmar'], 2)!s:>5}  "
            f"gross={s['mean_actual_gross']:.2f}/{s['max_actual_gross']:.2f}  "
            f"trades={s['trades']:>3}  gate_out={s['counts'].get('gate_events', 0)}  "
            f"funding={s['funding_pnl']:>6.2f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/g20_v3_carry_weight_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    study = load_study()
    full, extra, sources = study.build_full_panel(etf_root=ETF_REFRESH)
    filters = study.build_filters()
    # v3 contract pool: the 11 5U-tier legs only (ETH/LTC/LINK are 20U tier).
    idx = [list(full["symbols"]).index(s) for s in POOL]
    panel = dict(symbols=POOL, times=full["times"])
    for k in ("open", "high", "low", "close", "mark_low"):
        panel[k] = full[k][:, idx]
    panel["funding_value"] = full["funding_value"][:, idx]
    panel["funding_debit"] = full["funding_debit"][:, idx]
    funding_annual = extra["funding_annual"][:, idx]
    vol = study.vol_matrix(panel)
    days = panel["times"]
    era0 = int(np.searchsorted(days, int(datetime(2022, 6, 28, tzinfo=timezone.utc).timestamp())))
    era_end = int(np.searchsorted(days, int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())))
    windows = {
        "era": (int(days[era0]), int(days[era_end - 1])),
        "fwd": (int(days[int(np.searchsorted(days, int(
            datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp())))]),
            int(days[-1])),
        # bear stress the original grid missed (v2's pre window) + start-date drift
        "pre": (int(days[int(np.searchsorted(days, int(
            datetime(2021, 7, 1, tzinfo=timezone.utc).timestamp())))]),
            int(days[era0])),
        "era_m5": (int(days[era0 - 5]), int(days[era_end - 1])),
        "era_p5": (int(days[era0 + 5]), int(days[era_end - 1])),
    }

    configs = {
        "v3_core_2x": dict(gross=2.0, gate_threshold=0.06),
        "v3_no_gate_2x": dict(gross=2.0, gate_threshold=None),
        "v3_gross15": dict(gross=1.5, gate_threshold=0.06),
        "v3_gross25": dict(gross=2.5, gate_threshold=0.06),
        "v3_gate4": dict(gross=2.0, gate_threshold=0.04),
        "v3_gate8": dict(gross=2.0, gate_threshold=0.08),
        "v3_inv_vol": dict(gross=2.0, gate_threshold=0.06, weight_mode="inverse_vol"),
        "v3_bnb_floor25": dict(gross=2.0, gate_threshold=0.06, bnb_floor=0.25),
        # structural follow-ups (working core = no-gate after gate-1 verdict)
        "v3_static_2x": dict(gross=2.0, gate_threshold=None,
                             rebalance_bars=10 ** 9, drift_band=1e9),
        "v3_monthly": dict(gross=2.0, gate_threshold=None, rebalance_bars=21),
        "v3_band10": dict(gross=2.0, gate_threshold=None, drift_band=0.10),
        "v3_cost20": dict(gross=2.0, gate_threshold=None, cost_bp=20.0),
        "v3_cost30": dict(gross=2.0, gate_threshold=None, cost_bp=30.0),
    }
    results = {}
    for wtag, (w0, w1) in windows.items():
        for ctag, cfg in configs.items():
            run = replay_v3(panel, funding_annual, start=w0, end=w1,
                            capital=43.87, filters=filters, vol=vol, **cfg)
            results[f"{ctag}_{wtag}"] = dict(config=cfg, summary=run["summary"])
            print(f"{ctag + '_' + wtag:<26}", fmt(run["summary"]))

    cli = study.load_cli()
    baselines = {}
    for wtag, (w0, w1) in windows.items():
        l = int(np.searchsorted(days, w0))
        r = int(np.searchsorted(days, w1, "left"))
        baselines[f"ew11_{wtag}"] = cli.equal_weight_baseline(panel, l, r, capital=43.87)
        baselines[f"ew14_{wtag}"] = cli.equal_weight_baseline(full, l, r, capital=43.87)
    print("baselines:", json.dumps(baselines, indent=1))

    payload = dict(
        research_only=True, orders_authorized=False,
        generated_at=datetime.now(timezone.utc).isoformat(),
        contract="g20_v3_carry_weight (design 2026-11-02): 11-leg 5U-tier equal weight, "
                 "2x gross, weekly rebalance + 25% drift band, funding gate 6% trailing "
                 "30d annualized (BNB exempt), min-notional cash semantics, no trend logic",
        verdict_gates=[
            "core beats no-gate on Calmar in both windows (else funding gate is dead weight)",
            "core beats v2 core (era 30.12%/47.00%, fwd +13.0%/26.66%) on Calmar in both "
            "windows (else redesign adds nothing)",
        ],
        sources=dict(full=sources),
        assumptions=[
            "ETF proxy legs carry zero funding in backtest; measured SPY (-4.85%/yr to "
            "longs) and QQQ (+0.54%/yr) never gate; other ETF perp funding unmodeled, so "
            "the gate effectively operates on crypto legs only",
            "Funding gate is evaluated from the daily funding series; ETF Yahoo prices as "
            "in v2 (proxy overstates real perp by ~3pp/half-year)",
            "Gate hypothesis under test: avoided funding cost vs missed trend drift on "
            "gated legs — gate 1 decides, no post-hoc retuning",
        ],
        experiments=dict(results=results, baselines=baselines),
    )
    (args.output / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n")


if __name__ == "__main__":
    main()
