"""Fixed-horizon G20 entry information test; offline, no order interface."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import numpy as np

from study_crypto_g20_rotation import load
from qount.research.crypto_g20_rotation import Rule, decision, features, replay


def opportunities(panel, f, *, start="2021-05-04", end="2026-10-20", delay=2, cost_bp=10):
    """Weekly, nonoverlapping seven-day opportunities, unit entry notional.

    All returns are independent event economics, not an account NAV. No trend
    exits or stops obscure entry quality. Entry and exit each pay friction;
    fixed quantity funding owns precisely (entry open, exit open].
    """
    dates, close = panel["dates"], panel["close"]
    rows = []
    for signal in range(119, len(dates) - delay - 7):
        if (int(np.datetime64(dates[signal], "D").astype(int)) + 3) % 7 != 6:
            continue
        entry, exit_ = signal + delay, signal + delay + 7
        if dates[entry] < start or dates[exit_] > end:
            continue
        mom = close[signal] / close[signal - 63] - 1
        eligible = (mom > 0) & (close[signal] > f["ma"][signal])
        winner, _ = decision(panel, f, signal, Rule(gross=1))
        if winner is None:
            continue
        price = panel["open"][exit_] / panel["open"][entry] - 1
        funding = -panel["funding_value"][entry:exit_].sum(axis=0) / panel["open"][entry]
        costs = cost_bp / 10000 * (1 + panel["open"][exit_] / panel["open"][entry])
        net = price + funding - costs
        rows.append(dict(signal=str(dates[signal]), entry=str(dates[entry]), exit=str(dates[exit_]),
            symbol=panel["symbols"][winner], eligible_count=int(eligible.sum()),
            price_return=float(price[winner]), funding_return=float(funding[winner]),
            cost_return=float(costs[winner]), net_return=float(net[winner]),
            eligible_equal_return=float(net[eligible].mean()), btc_same_date_return=float(net[0]),
            pullback=bool(f["pullback"][signal, winner]),
            funding_cool=bool(f["funding_cool"][signal, winner])))
    return rows


def quarter(date):
    return date[:4] + "Q" + str((int(date[5:7]) - 1) // 3 + 1)


def block_mean_ci(values, dates, *, samples=4000, seed=20):
    """Calendar-week moving blocks; preserve gaps with a weighted mean."""
    if not len(values):
        return None
    stamps = np.asarray(dates, dtype="datetime64[D]").astype(int)
    offsets = ((stamps - stamps[0]) // 7).astype(int)
    n = int(offsets[-1]) + 1
    x, w = np.zeros(n), np.zeros(n)
    x[offsets], w[offsets] = values, 1
    rng = np.random.default_rng(seed)
    answer = {}
    for length in (4, 12):
        starts = rng.integers(0, n, (samples, (n + length - 1) // length))
        indices = ((starts[..., None] + np.arange(length)) % n).reshape(samples, -1)[:, :n]
        count = w[indices].sum(axis=1)
        means = x[indices].sum(axis=1)[count > 0] / count[count > 0]
        answer[str(length)] = (np.quantile(means, [.025, .975]) * 100).tolist()
    return answer


def summarize_events(rows):
    if not rows:
        return dict(count=0)
    def avg(key):
        return float(np.mean([r[key] for r in rows]) * 100)
    excess = [r["net_return"] - r["eligible_equal_return"] for r in rows]
    return dict(count=len(rows), mean_net_pct=avg("net_return"),
        median_net_pct=float(np.median([r["net_return"] for r in rows]) * 100),
        mean_price_pct=avg("price_return"), mean_funding_pct=avg("funding_return"),
        mean_cost_pct=avg("cost_return"), mean_eligible_equal_pct=avg("eligible_equal_return"),
        mean_btc_same_date_pct=avg("btc_same_date_return"),
        winner_minus_eligible_pct=float(np.mean(excess) * 100),
        winner_minus_eligible_block95_pct=block_mean_ci(excess, [r["entry"] for r in rows]),
        selected_symbols={s: sum(r["symbol"] == s for r in rows) for s in sorted({r["symbol"] for r in rows})})


def matched_random(rows, selected, *, samples=5000, seed=20):
    """Same count within each calendar quarter; compare conditional mean.

    This controls trade count and coarse market phase, without replacing
    excluded trades with zero and calling lower exposure an information gain.
    """
    if not selected:
        return None
    rng = np.random.default_rng(seed)
    simulated = np.zeros(samples)
    expected = 0.
    for q in sorted({quarter(r["entry"]) for r in selected}):
        population = np.asarray([r["net_return"] for r in rows if quarter(r["entry"]) == q])
        count = sum(quarter(r["entry"]) == q for r in selected)
        expected += count * population.mean()
        # Random ranks sample without replacement within each quarter.
        indices = np.argsort(rng.random((samples, len(population))), axis=1)[:, :count]
        simulated += population[indices].sum(axis=1)
    simulated /= len(selected)
    actual = float(np.mean([r["net_return"] for r in selected]))
    return dict(observed_mean_pct=actual * 100, random_expected_pct=float(expected / len(selected) * 100),
        improvement_pct=float((actual - expected / len(selected)) * 100),
        random_mean95_pct=(np.quantile(simulated, [.025, .975]) * 100).tolist(),
        percentile=float(np.mean(simulated <= actual) * 100), samples=samples,
        note="Exploratory conditional randomization, not an independent test or multiple-testing-adjusted significance.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json"))
    parser.add_argument("--mark-input", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/mark_daily.json"))
    parser.add_argument("--filters", type=Path, default=Path("state/research_cache/crypto_g20_rotation_20261102/exchange_filters.json"))
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/crypto_g20_entries_20261102"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    panel = load(args.input, args.mark_input)
    f = features(panel)
    filters = {r["symbol"]: r for r in json.loads(args.filters.read_text())["symbols"]}
    windows = {"2021_2023": ("2021-05-04", "2024-01-02"),
               "2024": ("2024-01-02", "2024-12-31"),
               "2025": ("2025-01-07", "2025-12-30"),
               "2026": ("2026-01-06", "2026-10-20"),
               "2024_2026": ("2024-01-02", "2026-10-20")}
    rules = {gate: Rule(gross=1, max_hold_bars=7, trend_exit=False, entry_filter=gate)
             for gate in ("none", "pullback", "funding_cool", "both")}
    events = opportunities(panel, f)
    event_results, accounts, curves = {}, {}, {}
    for name, (start, end) in windows.items():
        rows = [r for r in events if start <= r["entry"] and r["exit"] <= end]
        event_results[name], accounts[name] = {}, {}
        for gate, rule in rules.items():
            subset = [r for r in rows if (gate == "none" or
                      (r["pullback"] and r["funding_cool"] if gate == "both" else r[gate]))]
            event_results[name][gate] = dict(summary=summarize_events(subset),
                matched_quarter_random=matched_random(rows, subset) if gate != "none" else None)
            accounts[name][gate] = {}
            for label, capital, units, cost, delay in (
                ("unit1000", 1000., None, 10., 2),
                ("small21", 21.25, filters, 10., 2),
                ("small21_cost30", 21.25, filters, 30., 2),
                ("small21_delay3", 21.25, filters, 10., 3)):
                # The delay stress shifts the whole weekly book one day,
                # preserving complete seven-day slots and identical signals.
                shift = delay - 2
                shifted_start = str(np.datetime64(start) + np.timedelta64(shift, "D"))
                shifted_end = str(np.datetime64(end) + np.timedelta64(shift, "D"))
                run = replay(panel, f, replace(rule, delay=delay), start=shifted_start,
                    end=shifted_end, capital=capital, filters=units, cost_bp=cost)
                accounts[name][gate][label] = run["summary"]
                if name == "2024_2026":
                    curves[gate + ":" + label] = run
        # Baseline is unchanged; compare complete prior summary dictionaries.
    control = replay(panel, f, Rule(gross=1), start="2024-01-01", end="2026-10-26",
                     capital=21.25, filters=filters)
    old = json.loads(Path("state/research_runs/crypto_g20_rotation_20261102/results.json").read_text())
    expected = old["small_accounts"]["weekly_trend_1x"]["21.25"]["2024_2026"]
    assert control["summary"] == expected, "prior_control_changed"
    # Independent unit economics must reproduce the complete weekly book,
    # including every entry and exit fee, funding and fixed seven-day holds.
    for gate in rules:
        rows = [r for r in events if "2024-01-02" <= r["entry"] and r["exit"] <= "2026-10-20"]
        subset = [r for r in rows if gate == "none" or
                  (r["pullback"] and r["funding_cool"] if gate == "both" else r[gate])]
        expected_nav = np.prod([1 + r["net_return"] / 1.001 for r in subset])
        actual_nav = accounts["2024_2026"][gate]["unit1000"]["final_usdt"] / 1000
        assert np.isclose(expected_nav, actual_nav, atol=1e-10), (gate, expected_nav, actual_nav)
    payload = dict(research_only=True, orders_authorized=False, independent_oos=False,
        hypothesis="Does winner rank add to same-date eligible market exposure; do pullback or own-history low funding improve fixed-horizon entry information?",
        universe=panel["symbols"], rules={k: asdict(v) for k, v in rules.items()}, windows=windows,
        pullback_definition="Close at signal <= close three days earlier, within the original 63-day positive momentum / MA120 trend.",
        funding_definition="Past seven days mean realized daily funding <= median of the prior 90 seven-day means; no future rate estimates.",
        event_cost_one_way_bp=10, hold_days=7, signal_delay_bars=2,
        event_return_definition="Fixed entry notional, two-sided costs and settlement funding; independent opportunities, not NAV.",
        matched_random_seed=20, source_hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (args.input, args.mark_input, args.filters)},
        prior_small_account_control_exact=True, independent_event_account_tieout=True,
        events=event_results, accounts=accounts,
        limitations=["All historical samples already consumed; four specified gates, no parameter optimization or independent OOS claim.",
            "Seven surviving contracts, retrospective universe and current exchange filters; not a historical whole-market executable universe.",
            "Funding is a payment measure, not a direct measure of investor positioning; past low rates do not ensure future low rates.",
            "Daily mark extremes and fixed MMR/fee approximate liquidation; intraday peak NAV, matching, capacity and historical risk tiers not reconstructed.",
            "Before 2024 missing settlement marks use daily trade open; early diagnostic windows retain this limitation.",
            "Small-account random selection controls cannot certify identical executable positions; unit event analysis separates information from rounding.",
            "Annual windows restart independently and exclude partial weeks; never multiply them to reconstruct continuous NAV."])
    (args.output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (args.output / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (args.output / "curves.json").write_text(json.dumps(curves, ensure_ascii=False, allow_nan=False) + "\n")
    for window in windows:
        print(window)
        for gate in rules:
            e = event_results[window][gate]
            a = accounts[window][gate]["small21"]
            print(gate, "n/mean", e["summary"].get("count"), e["summary"].get("mean_net_pct"),
                  "random", e["matched_quarter_random"], "account return/mdd", a["return_pct"], a["mdd_pct"])


if __name__ == "__main__":
    main()
