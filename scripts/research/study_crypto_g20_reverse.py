"""Test reversing the retained hourly rotation's actual position direction."""
import json
from pathlib import Path

from qount.research.crypto_g20_rotation import Rule, features, replay
from study_crypto_g20_intraday import load_hour_panel, WINDOWS


def main():
    original_root = Path("state/research_runs/crypto_g20_intraday_20261102")
    output = Path("state/research_runs/crypto_g20_reverse_20261102")
    output.mkdir(parents=True, exist_ok=True)
    retained = json.loads((original_root / "results.json").read_text())
    original_curves = json.loads((original_root / "curves.json").read_text())
    cache = Path("state/research_cache/crypto_g20_rotation_20261102")
    marks = json.loads((cache / "mark_hourly_windows.json").read_text())["data"]
    daily = json.loads(Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json").read_text())["data"]
    filters = {r["symbol"]: r for r in json.loads((cache / "exchange_filters.json").read_text())["symbols"]}
    results, curves = {}, {}
    for window, (filename, start, end) in WINDOWS.items():
        panel = load_hour_panel(Path("state/research_cache/position_flow_20261027") / filename,
                                marks[window], daily)
        f = features(panel)
        results[window] = {}
        for name in ("long3", "long5", "both3"):
            rule = Rule(**retained["rules"][name])
            original = original_curves[window + "_" + name]
            s = original["summary"]
            # A fixed original quantity/clock ledger is an algebraic diagnostic,
            # not a margin-feasible inverse account. Original paths here have
            # no liquidation or insolvency adjustments in price_pnl.
            assert not s["counts"].get("liquidations") and not s["counts"].get("ruin")
            same_quantity_equity = s["initial_usdt"] - sum(
                r["price_pnl"] + r["funding_pnl"] + r["costs"] for r in original["curve"])
            results[window][name] = dict(original=s,
                same_original_quantity_reverse=dict(final_usdt=same_quantity_equity,
                    return_pct=(same_quantity_equity / s["initial_usdt"] - 1) * 100,
                    margin_feasibility_verified=False), inverse={})
            # Re-run original once: the new switch must leave prior results intact.
            control = replay(panel, f, rule, start=start, end=end, capital=21.25, filters=filters)
            assert control["summary"] == s, "original_replay_changed"
            for label, cost, path in (("10bp", 10, "liquidation_first"),
                                      ("0bp", 0, "liquidation_first"),
                                      ("30bp", 30, "liquidation_first"),
                                      ("stop_first_10bp", 10, "stop_first")):
                run = replay(panel, f, rule, start=start, end=end, capital=21.25,
                    filters=filters, cost_bp=cost, ambiguous_path=path, reverse_execution=True)
                results[window][name]["inverse"][label] = run["summary"]
                if label == "10bp":
                    curves[window + "_" + name] = run
            a = results[window][name]
            print(window, name, "original", round(s["return_pct"], 2),
                "fixed_quantity_inverse", round(a["same_original_quantity_reverse"]["return_pct"], 2),
                "own_equity_inverse", round(a["inverse"]["10bp"]["return_pct"], 2),
                "MDD", round(a["inverse"]["10bp"]["mdd_pct"], 2),
                a["inverse"]["10bp"]["counts"])
    payload = dict(research_only=True, orders_authorized=False, independent_oos=False,
        initial_capital_usdt=21.25, windows=WINDOWS,
        original_result_path=str(original_root / "results.json"),
        source_hashes=retained["source_hashes"], rules={n: retained["rules"][n] for n in ("long3", "long5", "both3")},
        reversal="Opposite actual side; original model still controls winner, trend exit, trailing trigger and maximum hold. Original stop trigger becomes inverse profit-taking. Quantity is sized from inverse account equity.",
        limitations=retained["limitations"] + [
            "Fixed-original-quantity inversion is an algebraic diagnostic; its margin feasibility is not verified.",
            "Own-equity inverse may enter different trades due to minimum orders and liquidation. It preserves signal logic, not an identical quantity ledger.",
            "Reversal chosen after seeing original losses on these same historical windows; no independent validation."],
        results=results)
    (output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    (output / "curves.json").write_text(json.dumps(curves, ensure_ascii=False, allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
