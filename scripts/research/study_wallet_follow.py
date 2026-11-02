#!/usr/bin/env python3
"""Bounded case study of delayed net-direction following, with public cached fills."""
import argparse
import json
from pathlib import Path

import numpy as np

from qount.research.wallet_follow import hourly_inventory_signals, persistence_signals, reconstruct, simulate_direction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/wallet_follow_20261027"))
    parser.add_argument("--minutes", type=Path, help="Alternate minute-price cache")
    parser.add_argument("--a-extra-fills", type=Path, help="Additional source A fills; original cache stays intact")
    parser.add_argument("--a-start-ms", type=int, help="Fresh-account evaluation start for source A")
    parser.add_argument("--only-a", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    public = Path("state/research_cache/public_wallet_history_20261027")
    cache = Path("state/research_cache/wallet_follow_20261027")
    minutes = json.loads((args.minutes or cache / "minutes.json").read_text())["data"]
    today = json.loads((cache / "funding_today.json").read_text())["data"]
    funding = json.loads(Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json").read_text())["data"]
    addresses = ("0x85ecf584f25db6f146718b86d493e33c5af72052",
                 "0xf5d81a135f756ca16544e53c20fc20643ec3ad53",
                 "0x399965e15d4e61ec3529cc98b7f7ebb93b733336")
    wallets, accounts, details = {}, {}, {}
    for label, address in zip(("A", "B", "C"), addresses):
        if args.only_a and label != "A":
            continue
        fills = json.loads((public / (address + "-fills_retained.json")).read_text())
        if label == "A" and args.a_extra_fills:
            fills += json.loads(args.a_extra_fills.read_text())
        r = reconstruct(fills)
        durations = np.asarray([e["duration_seconds"] for e in r["episodes"]])
        wallets[label] = dict(address=address, stats=r["stats"], errors=r["errors"],
                              first_ms=min(f["time"] for f in fills), last_ms=max(f["time"] for f in fills),
                              closed_direction_intervals=len(durations),
                              direction_duration_quantiles_seconds=np.quantile(durations,[.1,.5,.9]).tolist(),
                              direction_under_60s_fraction=float(np.mean(durations<60)),
                              direction_under_300s_fraction=float(np.mean(durations<300)),
                              maker_fill_fraction=float(np.mean([not f["crossed"] for f in fills])),
                              signals=r["signals"], episodes=r["episodes"])
        # C's instruments are spot/HIP-3 products. No unsupported mapping to Binance.
        coins = ("ETH",) if label == "A" else ("BTC", "ETH", "SOL") if label == "B" else ()
        for coin in coins:
            key = label + "_" + coin + "USDT"
            bars = minutes[key]
            symbol = coin + "USDT"
            rates = funding[symbol + "_funding"] if label == "A" else today[symbol]
            left, right = wallets[label]["first_ms"], wallets[label]["last_ms"]
            if label == "A" and args.a_start_ms is not None:
                left = args.a_start_ms
            assert all(p.get("markPrice") for p in rates if left <= int(p["fundingTime"]) <= right)
            history_sig = [s for s in r["signals"] if s["coin"] == coin]
            sig = [s for s in history_sig if s["time_ms"] >= left]
            step = .01 if coin == "SOL" else .001
            cases = {}
            for delay in (60, 300, 900):
                for cost in (10, 30):
                    run = simulate_direction(sig, bars, rates, start_ms=left, end_ms=right,
                                             delay_seconds=delay, cost_bp=cost, quantity_step=step)
                    case = f"delay{delay}s_cost{cost}bp"
                    cases[case] = {k:v for k,v in run.items() if k not in ("points", "trades")}
                    details[key + "_" + case] = run
            persistent = [s for s in persistence_signals(history_sig, 900, last_observed_ms=right) if s["time_ms"] >= left]
            for cost in (10,30):
                run = simulate_direction(persistent, bars, rates, start_ms=left, end_ms=right,
                                         delay_seconds=60, cost_bp=cost, quantity_step=step)
                case = f"persistence900s_delay60s_cost{cost}bp"
                cases[case] = {k:v for k,v in run.items() if k not in ("points", "trades")}
                details[key + "_" + case] = run
            inventory = [s for s in hourly_inventory_signals([s for s in r["states"] if s["coin"] == coin], last_observed_ms=right) if s["time_ms"] >= left]
            for cost in (5,10,30):
                run = simulate_direction(inventory, bars, rates, start_ms=left, end_ms=right,
                                         delay_seconds=60, cost_bp=cost, quantity_step=step)
                case = f"inventory3600s_delay60s_cost{cost}bp"
                cases[case] = {k:v for k,v in run.items() if k not in ("points", "trades")}
                details[key + "_" + case] = run
            buyhold = simulate_direction([dict(time_ms=left//60000*60000,target=1)], bars, rates,
                         start_ms=left,end_ms=right,delay_seconds=0,cost_bp=10,quantity_step=step)
            accounts[key] = dict(signal_count=len(sig), persistent_policy_signals=len(persistent),
                                  hourly_inventory_signals=len(inventory), cases=cases,
                                  buyhold_control={k:v for k,v in buyhold.items() if k not in ("points", "trades")})
    result = dict(research_only=True, orders_authorized=False, independent_oos=False,
                  hypothesis="Follow only observable net direction changes; fixed quantity until direction changes; no partial-size copying",
                  selection="Three currently published leaderboard rows; post-selected historical case study, not PIT selection or strategy validation",
                  execution="Binance USDT perpetual minute opens after 60/300/900s delay from Hyperliquid public fills; latest known target at each minute wins",
                  sizing="Each asset modeled separately with initial10000USDT,target entry gross1; current quantity steps back-applied; not a combined account",
                  terminal="Liquidate at first minute boundary after last retained source fill; excludes signals arriving later",
                  costs="10bp one-way =5bp fee+5bp friction;30bp stress; inventory5bp is fee-only zero-friction bound; actual funding marks/timestamps",
                  limitations=["partial public history and current leaderboard selection", "cross-venue basis and execution assumptions",
                               "minute open drawdown misses intraminute extremes", "historical margin tiers and order-fill capacity not certified",
                               "net direction intervals ignore intramillisecond round trips", "C has no supported direct instrument mapping"],
                  wallets=wallets, accounts=accounts)
    (args.output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    (args.output / "accounts.json").write_text(json.dumps(details, separators=(",",":"), allow_nan=False) + "\n")
    for label,w in wallets.items():
        print(label,w["stats"],"errors",len(w["errors"]),"duration_seconds",w["direction_duration_quantiles_seconds"])
    for key, account in accounts.items():
        print(key, "signals", account["signal_count"],"buyhold",round(account["buyhold_control"]["return_pct"],4))
        for name,r in account["cases"].items():
            print(name, {k:round(r[k],4) for k in ("return_pct","mdd_pct","price_pnl","funding_pnl","costs","order_count")})


if __name__ == "__main__":
    main()
