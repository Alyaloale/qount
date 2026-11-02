#!/usr/bin/env python3
"""Historical-roster replication using positions, without retained-fill inference."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from qount.research.wallet_consensus import relative_addition_targets, target_signals, vote_policies
from qount.research.wallet_follow import simulate_direction, summarize_portfolio

HOUR = 3_600_000
COINS = ["BTC", "ETH", "HYPE", "ZEC"]


def midnight(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp() * 1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=Path("state/research_cache/wallet_consensus_20261027/historical_snapshot_panel.json"))
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/snapshot_flow_20261027"))
    parser.add_argument("--sparse-pilot", action="store_true", help="Use the two verified Sept1/16 files; test15-day accumulation, not a24h replication")
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    panel = json.loads(args.panel.read_text())
    small = json.loads(Path("state/research_cache/wallet_consensus_20261027/historical_selection.json").read_text())
    hash24 = {r["address"] for r in small["selected"]}
    addresses = panel["addresses"]
    assert len(addresses) == len(set(addresses)) == 470 and hash24 <= set(addresses)
    old = Path("state/research_cache/slow_wallets_20261027")
    original = json.loads(Path("state/research_cache/position_flow_20261027/hourly.json").read_text())["data"]
    extra = json.loads((old / "additional_market_data.json").read_text())["data"]
    original_funding = json.loads(Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json").read_text())["data"]
    filters = {s["symbol"]: s for s in json.loads((old / "exchange_filters.json").read_text())["symbols"]}
    markets = {}; rates = {}; steps = {}
    for coin in COINS:
        symbol = coin + "USDT"
        bars = original.get(symbol + "_futures", extra.get(symbol + "_klines"))
        markets[coin] = np.asarray(bars, float)
        rates[coin] = original_funding[symbol + "_funding"] if coin in ("BTC", "ETH") else extra[symbol + "_funding"]
        steps[coin] = float(next(f["stepSize"] for f in filters[symbol]["filters"] if f["filterType"] == "LOT_SIZE"))
        assert np.all(np.diff(markets[coin][:, 0]) == HOUR) and np.all(np.isfinite(markets[coin]))
    result = {}; curves = {}; event_detail = []
    windows = [("sept02_09", "2026-09-01", "2026-09-08", "2026-09-02", "2026-09-09"),
               ("sept16_23", "2026-09-15", "2026-09-22", "2026-09-16", "2026-09-23")]
    if args.sparse_pilot:
        windows = [("accumulation15d_sept16_23", "2026-09-01", "2026-09-16", "2026-09-16", "2026-09-23")]
    for name, first, last, begin, finish in windows:
        snapshots = sorted((s for s in panel["snapshots"] if first <= s["date"] <= last), key=lambda s: s["time_ms"])
        expected = 2 if args.sparse_pilot else 8
        assert len(snapshots) == expected and len({s["date"] for s in snapshots}) == expected
        times = np.array([s["time_ms"] for s in snapshots[1:]], np.int64)
        gaps = np.diff([s["time_ms"] for s in snapshots]) / HOUR
        if not args.sparse_pilot:
            assert np.all((gaps >= 18) & (gaps <= 30)), "daily_snapshot_gap"
        split, end = midnight(begin), midnight(finish)
        window = dict(start_ms=split, end_ms=end, snapshot_intervals_hours=gaps.tolist(), cohorts={})
        for cohort_name, members in (("historical470", addresses), ("hash24", sorted(hash24))):
            policies = {}; diagnostics = {}
            for coin in COINS:
                q = np.array([[s["positions"][a][coin] for s in snapshots] for a in members], float)
                assert np.all(np.isfinite(q)), "invalid_snapshot_quantity"
                current, previous = q[:, 1:], q[:, :-1]
                change = current - previous
                tolerance = 1e-10 * np.maximum(1, np.maximum(abs(current), abs(previous)))
                votes = np.where((current * change > 0) & (abs(change) > tolerance), np.sign(current), 0).astype(int)
                targets = vote_policies(votes, np.sign(current).astype(int))
                # The original fixed rules; no selection by replication returns.
                targets["reverse_any_newrisk"] = -targets["any_newrisk"]
                diagnostics[coin] = dict(positive_new_votes=np.sum(votes > 0, axis=0).tolist(),
                                         negative_new_votes=np.sum(votes < 0, axis=0).tolist())
                for policy, target in targets.items():
                    if policy == "reverse_newrisk":
                        continue
                    policies.setdefault(policy, {})[coin] = target_signals(times, target)
                    if policy == "any_newrisk":
                        for t, side, pos, neg in zip(times, target, diagnostics[coin]["positive_new_votes"], diagnostics[coin]["negative_new_votes"]):
                            event_detail.append(dict(window=name, cohort=cohort_name, coin=coin, decision_ms=int(t),
                                                     target=int(side), positive=pos, negative=neg))
            # Exploratory mechanism added AFTER inspecting the directional replay.
            positive=[diagnostics[c]['positive_new_votes'] for c in COINS]
            negative=[diagnostics[c]['negative_new_votes'] for c in COINS]
            relative,scores=relative_addition_targets(positive,negative)
            for policy,targets in [('relative_additions',relative),('reverse_relative_additions',-relative),
                                   ('initial_relative_static',np.repeat(relative[:,:1],relative.shape[1],axis=1))]:
                policies[policy]={c:target_signals(times,targets[i]) for i,c in enumerate(COINS)}
            accounts = {}; base_runs = {}
            for policy, signals in policies.items():
                accounts[policy] = {}
                for delay, cost in ((3600, 10), (3600, 30), (21600, 10)):
                    runs = []; by_coin = {}
                    for coin in COINS:
                        assert markets[coin][0, 0] <= split and markets[coin][-1, 0] >= end
                        payments = [r for r in rates[coin] if split <= r["fundingTime"] <= end]
                        assert payments and all(r.get("markPrice") for r in payments)
                        assert max(np.diff([r["fundingTime"] for r in payments])) <= 8.01 * HOUR
                        run = simulate_direction(signals[coin], markets[coin], rates[coin], start_ms=split, end_ms=end,
                                                 delay_seconds=delay, cost_bp=cost, initial=2500,
                                                 quantity_step=steps[coin], bar_ms=HOUR)
                        runs.append(run)
                        by_coin[coin] = {k: v for k, v in run.items() if k not in ("points", "trades")}
                        if policy == "any_newrisk" and delay == 3600 and cost == 10:
                            base_runs[coin] = run
                    summary, t, equity = summarize_portfolio(runs, 10000)
                    key = f"delay{delay}s_cost{cost}bp"
                    accounts[policy][key] = dict(summary=summary, by_coin=by_coin)
                    curves["/".join((name, cohort_name, policy, key))] = dict(times=t, equity=equity)
            base = accounts["any_newrisk"]["delay3600s_cost10bp"]["summary"]
            removed = {coin: base["return_pct"] - (r["final_equity"] - 2500) / 100 for coin, r in base_runs.items()}
            window["cohorts"][cohort_name] = dict(size=len(members), diagnostics=diagnostics, accounts=accounts,
                                                 relative_vote_scores=dict(zip(COINS,scores.tolist())),
                                                 remove_asset_keep_cash_return_pct=removed)
        result[name] = window
    payload = dict(research_only=True, orders_authorized=False, independent_oos=False,
                   selection="Sept1 historical equity>=100k, gross/equity<=3, <=10 markets, holding one of fixed four assets; all470 retained, no return/style/history-coverage filter",
                   execution="10000USDT, four fixed2500 initial sleeves; entry notional about1x current sleeve equity, fixed quantity while direction unchanged; each new snapshot decision delayed1h then next hourly open; hold target until next snapshot; exact funding; terminal liquidation",
                   factor=("15-day accumulation pilot, NOT24h replication; " if args.sparse_pilot else "Adjacent daily snapshot replication; ") + "one address one vote for signed perpetual position additions; q_now*(q_now-q_previous)>0; strict majority, minimum1 or2; no intraday reconstruction",
                   windows=result, event_detail=event_detail,
                   limits=panel["limits"] + [("One short pilot, only four asset directions; not independent OOS or annualized evidence" if args.sparse_pilot else "Rules reused after prior research; two short retrospective windows, not independent OOS or annualized evidence"),
                                            "Missing snapshot rows interpreted as zero under publisher full-snapshot assumption",
                                            "Daily observations differ from the earlier hourly trailing24h version; not an exact replication",
                                            "Current quantity steps back-applied; hourly drawdowns exclude intrahour loss; USDC/USDT basis and capacity unqualified",
                                            "Perpetual positions may hedge spot or other venues; contract additions do not establish total-owner risk or intent",
                                            "Relative asset vote ranking was added after directional results; exploratory same-data ablation; four fixed sleeves, two active, entry notional only approximately balanced, not beta-neutral",
                                            "Different addresses are not verified independent owners; sample selection itself is exploratory"])
    (args.output / "results.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    (args.output / "curves.json").write_text(json.dumps(curves, separators=(",", ":"), allow_nan=False) + "\n")
    for name, window in result.items():
        for cohort, row in window["cohorts"].items():
            print(name, cohort, "interval_hours", [round(x, 3) for x in window["snapshot_intervals_hours"]])
            for policy, values in row["accounts"].items():
                print(policy, {k: (round(v["summary"]["return_pct"], 4), round(v["summary"]["hourly_open_mdd_pct"], 4), v["summary"]["orders"]) for k, v in values.items()})
            print("remove_assets_keep_cash", row["remove_asset_keep_cash_return_pct"])


if __name__ == "__main__":
    main()
