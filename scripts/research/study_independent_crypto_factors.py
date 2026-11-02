#!/usr/bin/env python3
"""Independent, offline factor falsification on a fixed seven-perpetual universe.

This exploratory script never imports exchange execution code. Daily signals
wait a full extra day before trading; funding uses actual timestamps and
reported settlement marks. Missing early marks use that day's trade open as
an explicit approximation. Fixed factors and one chronological ridge learner
are evaluated without a hyperparameter search.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

DAY = 86_400_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT", "LINKUSDT")


def rolling(x, window, operation="mean"):
    out = np.full_like(x, np.nan, dtype=float)
    for t in range(window - 1, len(x)):
        a = x[t - window + 1:t + 1]
        if operation == "mean":
            out[t] = np.mean(a, axis=0)
        elif operation == "std":
            out[t] = np.std(a, axis=0, ddof=1)
        elif operation == "median":
            out[t] = np.median(a, axis=0)
    return out


def zscore(x, window=60):
    return (x - rolling(x, window)) / np.maximum(rolling(x, window, "std"), 1e-8)


def change(x, days):
    out = np.full_like(x, np.nan)
    out[days:] = np.log(x[days:] / x[:-days])
    return out


def load_panel(path):
    raw = json.loads(Path(path).read_text())
    data = raw["data"]
    bars = [np.asarray(data[s + "_klines"], dtype=float) for s in SYMBOLS]
    times = bars[0][:, 0].astype(np.int64)
    cutoff = np.datetime64(raw["cutoff"].replace("Z", ""), "ms").astype(np.int64)
    for b in bars:
        assert b.shape == bars[0].shape and b.shape[1] == 12
        assert np.array_equal(b[:, 0], times)
        assert np.all(np.diff(b[:, 0]) == DAY), "missing_or_duplicate_daily_bar"
        assert np.all(b[:, 6] < cutoff), "incomplete_daily_bar"
        assert np.all(np.isfinite(b)) and np.all(b[:, 1:6] > 0)
        assert np.all(b[:, 2] >= np.maximum(b[:, 1], b[:, 4]))
        assert np.all(b[:, 3] <= np.minimum(b[:, 1], b[:, 4]))
        assert np.all((b[:, 10] >= 0) & (b[:, 10] <= b[:, 7]))
    cube = np.stack(bars, axis=2)
    daily_rate = np.zeros((len(times), len(SYMBOLS)))
    funding_value = np.zeros_like(daily_rate)
    funding_counts, approximate_marks = [], {}
    for j, s in enumerate(SYMBOLS):
        rows = data[s + "_funding"]
        stamps = np.asarray([r["fundingTime"] for r in rows], np.int64)
        assert len(np.unique(stamps)) == len(stamps)
        assert np.all(np.diff(stamps) > 0)
        assert stamps[0] <= times[0] + 8 * 3_600_000
        assert stamps[-1] >= times[-1] + 16 * 3_600_000
        assert np.max(np.diff(stamps)) < 8.01 * 3_600_000, "funding_gap"
        funding_counts.append(len(rows))
        approximate_marks[s] = 0
        for r in rows:
            t, rate = int(r["fundingTime"]), float(r["fundingRate"])
            # Signal day owns its completed [00:00,24:00) settlements.
            d = int((t - times[0]) // DAY)
            if r.get("markPrice"):
                mark = float(r["markPrice"])
            else:
                assert 0 <= d < len(times)
                mark = cube[d, 1, j]
                approximate_marks[s] += 1
            assert np.isfinite(rate) and np.isfinite(mark) and mark > 0
            if 0 <= d < len(times):
                daily_rate[d, j] += rate
            # Holding interval owns (entry open, following open] settlements.
            k = int(np.searchsorted(times, t, side="left") - 1)
            if 0 <= k < len(times) - 1:
                funding_value[k, j] += rate * mark
    return dict(times=times, dates=times.astype("datetime64[ms]").astype("datetime64[D]").astype(str),
                open=cube[:, 1], close=cube[:, 4], quote=cube[:, 7], taker=cube[:, 10],
                daily_rate=daily_rate, funding_value=funding_value,
                funding_counts=funding_counts, approximate_marks=approximate_marks,
                downloaded_at=raw["downloaded_at"])


def make_factors(p):
    close, quote = p["close"], p["quote"]
    r = change(close, 1)
    vol = rolling(r, 20, "std")
    mr, mb = rolling(r, 60), rolling(r[:, :1], 60)
    covariance = rolling(r * r[:, :1], 60) - mr * mb
    variance = rolling(r[:, :1] ** 2, 60) - mb ** 2
    beta = covariance / np.maximum(variance, 1e-10)
    flow3 = 2 * rolling(p["taker"], 3) / rolling(quote, 3) - 1
    r3, r20 = change(close, 3), change(close, 20)
    residual3 = r3 - beta * r3[:, :1]
    residual20 = r20 - beta * r20[:, :1]
    shock = np.clip(quote / rolling(quote, 30, "median") - 1, 0, 3)
    factors = {
        "carry_7d": -rolling(p["daily_rate"], 7),
        "taker_pressure_3d": flow3,
        "passive_absorption_3d": np.clip(zscore(r3), -3, 3) - np.clip(zscore(flow3), -3, 3),
        "residual_momentum_20d": residual20 / np.maximum(vol, 1e-8),
        "residual_reversal_3d": -residual3 / np.maximum(vol, 1e-8),
        "volume_shock_reversal": -np.clip(r / np.maximum(vol, 1e-8), -3, 3) * shock,
        "low_volatility_20d": -vol,
        "momentum_20d_control": r20,
    }
    return factors, beta


def factor_weights(score, beta=None):
    if not np.all(np.isfinite(score)):
        return np.zeros(len(score))
    w = rankdata(score) - (len(score) + 1) / 2
    if beta is not None:
        if not np.all(np.isfinite(beta)):
            return np.zeros(len(score))
        constraints = np.stack([np.ones(len(score)), beta])
        w -= constraints.T @ np.linalg.pinv(constraints @ constraints.T) @ (constraints @ w)
    gross = np.abs(w).sum()
    return w / gross if gross > 1e-10 else np.zeros(len(score))


def simulate(p, score, *, start="2021-05-01", end=None, cost_bp=10, cadence=7,
             beta=None, initial=10000.0, neutral=True):
    """Fixed quantities between scheduled rebalances, timestamped funding ledger.

    Equity at each open includes previous interval PnL and funding. Execution at
    open t uses signal t-2 (signal t-1 is deliberately not used). Funding at t
    is settled on old quantities before a rebalance. Final open is liquidated.
    """
    eligible = np.flatnonzero((p["dates"] >= start) & (p["dates"] < (end or "9999")))
    left, right = int(eligible[0]), min(int(eligible[-1]), len(p["times"]) - 1)
    q = np.zeros(len(SYMBOLS))
    equity = initial
    nav, rets, gross_pnl, funding_pnl, costs, turnovers, dates, betas, exposure = [], [], [], [], [], [], [], [], []
    for t in range(left, right):
        before = equity
        cost = turnover = 0.0
        if (t - left) % cadence == 0:
            if neutral:
                w = factor_weights(score[t - 2], None if beta is None else beta[t - 2])
            else:
                w = np.full(len(SYMBOLS), 1 / len(SYMBOLS))
            target = equity * w / p["open"][t]
            turnover = np.sum(np.abs(target - q) * p["open"][t])
            cost = turnover * cost_bp / 10000
            equity -= cost
            q = target
        exante_beta = np.sum(q * p["open"][t] / before * p["beta"][t - 2])
        price_pnl = np.sum(q * (p["open"][t + 1] - p["open"][t]))
        funding = -np.sum(q * p["funding_value"][t])
        equity += price_pnl + funding
        if t == right - 1:
            closing_turnover = np.sum(np.abs(q) * p["open"][t + 1])
            closing_cost = closing_turnover * cost_bp / 10000
            equity -= closing_cost
            cost += closing_cost
            turnover += closing_turnover
        assert equity > 0, "bankrupt_research_account"
        dates.append(p["dates"][t])
        nav.append(equity / initial)
        rets.append(equity / before - 1)
        gross_pnl.append(float(price_pnl))
        funding_pnl.append(float(funding))
        costs.append(float(cost))
        turnovers.append(float(turnover / before))
        betas.append(float(exante_beta))
        exposure.append(float(np.sum(np.abs(q) * p["open"][t]) / before))
    return {k: np.asarray(v) for k, v in dict(dates=dates, nav=nav, returns=rets,
                price_pnl=gross_pnl, funding_pnl=funding_pnl, costs=costs,
                turnover=turnovers, exante_beta=betas, gross_exposure=exposure).items()}


def metrics(run, start="0000", end="9999"):
    mask = (run["dates"] >= start) & (run["dates"] < end)
    r = run["returns"][mask]
    if not len(r):
        return None
    nav = np.r_[1., np.cumprod(1 + r)]
    mdd = np.max(1 - nav / np.maximum.accumulate(nav))
    cagr = nav[-1] ** (365.25 / len(r)) - 1
    return dict(start=str(run["dates"][mask][0]), last_return_start=str(run["dates"][mask][-1]),
                days=len(r), return_pct=(nav[-1] - 1) * 100, cagr_pct=cagr * 100,
                mdd_pct=mdd * 100, calmar=cagr / mdd if mdd else None,
                sharpe=float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(365.25)) if np.std(r, ddof=1) > 0 else None,
                price_pnl=float(run["price_pnl"][mask].sum()),
                funding_pnl=float(run["funding_pnl"][mask].sum()),
                costs=float(run["costs"][mask].sum()),
                annual_one_way_turnover=float(run["turnover"][mask].mean() * 365.25),
                mean_exante_beta=float(run["exante_beta"][mask].mean()),
                active_days=int(np.sum(run["gross_exposure"][mask] > 1e-8)),
                mean_gross_exposure=float(run["gross_exposure"][mask].mean()))


def block_ci(x, block=30, draws=2000, seed=271026):
    """Moving calendar-block bootstrap, before filtering missing observations."""
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, max(1, len(x) - block + 1), size=(draws, int(np.ceil(len(x) / block))))
    idx = (starts[:, :, None] + np.arange(block)).reshape(draws, -1)[:, :len(x)]
    estimates = np.nanmean(x[np.minimum(idx, len(x) - 1)], axis=1)
    return np.nanquantile(estimates, [0.025, 0.975]).tolist()


def information_coefficient(p, score, horizon):
    ic = np.full(len(score), np.nan)
    # t close signal -> t+2 open execution -> t+2+h open outcome.
    for t in range(len(score) - horizon - 2):
        if np.all(np.isfinite(score[t])):
            target = np.log(p["open"][t + 2 + horizon] / p["open"][t + 2])
            a, b = rankdata(score[t]), rankdata(target)
            if np.std(a) > 0 and np.std(b) > 0:
                ic[t] = np.corrcoef(a, b)[0, 1]
    result = {}
    for label, start, end in [("development", "2021-05-01", "2024-01-01"),
                              ("validation_2024", "2024-01-01", "2025-01-01"),
                              ("evaluation_2025", "2025-01-01", "2026-01-01"),
                              ("evaluation_2026", "2026-01-01", "2026-10-27")]:
        # Purge labels that would cross each window boundary.
        outcome_date = np.full(len(score), "9999-99-99", dtype="U10")
        outcome_date[:-horizon - 2] = p["dates"][horizon + 2:]
        mask = (p["dates"] >= start) & (outcome_date < end)
        values = ic[mask]
        result[label] = dict(mean=float(np.nanmean(values)), count=int(np.isfinite(values).sum()),
                             block30_ci95=block_ci(values))
    return result


def online_ridge_scores(p, factors, beta):
    """One fixed walk-forward learner; no tuning against evaluation outcomes.

    Cross-sectional ranks enter a rolling 365-day ridge (lambda=.1), refit
    every 28 days. Seven-day labels mature nine days after their signal.
    The optional gate requires forecast net alpha to cover a 60bp round trip.
    """
    names = [n for n in factors if not n.endswith("control") and n != "equal_six_factor_ensemble"]
    x = np.full((len(beta), len(SYMBOLS), len(names)), np.nan)
    for k, name in enumerate(names):
        for t, row in enumerate(factors[name]):
            if np.all(np.isfinite(row)):
                x[t, :, k] = (rankdata(row) - 4) / 3
    target = np.full(beta.shape, np.nan)
    for t in range(len(beta) - 9):
        r = p["open"][t + 9] / p["open"][t + 2] - 1
        target[t] = r - beta[t] * r[0]
        target[t] -= np.mean(target[t])
    score = np.zeros_like(beta)
    gated = np.zeros_like(beta)
    coefficients, fits = None, []
    last_fit = -100
    for t in range(365 + 100, len(beta)):
        if t - last_fit >= 28:
            # A signal from t-9 ends at open t, already observable at close t.
            left, right = t - 9 - 365 + 1, t - 9 + 1
            a, y = x[left:right].reshape(-1, len(names)), target[left:right].reshape(-1)
            good = np.all(np.isfinite(a), axis=1) & np.isfinite(y)
            a, y = a[good], y[good]
            coefficients = np.linalg.solve(a.T @ a / len(y) + .1 * np.eye(len(names)), a.T @ y / len(y))
            fits.append(dict(signal_date=str(p["dates"][t]), last_training_signal=str(p["dates"][right - 1]),
                             last_training_outcome=str(p["dates"][right - 1 + 9]),
                             coefficients=dict(zip(names, coefficients.tolist()))))
            last_fit = t
        prediction = x[t] @ coefficients
        score[t] = prediction
        w = factor_weights(prediction, beta[t])
        expected_funding = w @ np.sum(p["daily_rate"][t - 6:t + 1], axis=0)
        if w @ prediction - expected_funding > .006:
            gated[t] = prediction
    return score, gated, fits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json"))
    parser.add_argument("--output", type=Path, default=Path("state/research_runs/independent_crypto_factors_20261027"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    p = load_panel(args.input)
    factors, beta = make_factors(p)
    p["beta"] = beta
    windows = {"development": ("2021-05-01", "2024-01-01"),
               "validation_2024": ("2024-01-01", "2025-01-01"),
               "evaluation_2025": ("2025-01-01", "2026-01-01"),
               "evaluation_2026": ("2026-01-01", "2026-10-27"),
               "evaluation_2025_2026": ("2025-01-01", "2026-10-27")}
    results, curves = {}, {}
    for name, score in factors.items():
        result = {"ic_1d": information_coefficient(p, score, 1),
                  "ic_5d": information_coefficient(p, score, 5), "accounts": {}}
        for mode in ("dollar_neutral", "beta_neutral"):
            for cost in (10, 30, 60):
                run = simulate(p, score, cost_bp=cost, beta=beta if mode == "beta_neutral" else None)
                label = f"{mode}_{cost}bp"
                result["accounts"][label] = {k: metrics(run, *v) for k, v in windows.items()}
                curves[name + "_" + label] = run
        results[name] = result
    baseline = simulate(p, next(iter(factors.values())), neutral=False)
    results["equal_weight_long_control"] = {k: metrics(baseline, *v) for k, v in windows.items()}
    # Predefined equal-weight ensemble, independent of observed factor outcomes.
    names = [n for n in factors if not n.endswith("control") and n != "low_volatility_20d"]
    ranked = []
    for name in names:
        a = np.array([factor_weights(row) for row in factors[name]])
        ranked.append(a)
    ensemble = np.mean(ranked, axis=0)
    factors["equal_six_factor_ensemble"] = ensemble
    results["equal_six_factor_ensemble"] = {"accounts": {}}
    for cost in (10, 30, 60):
        run = simulate(p, ensemble, beta=beta, cost_bp=cost)
        label = f"beta_neutral_{cost}bp"
        results["equal_six_factor_ensemble"]["accounts"][label] = {k: metrics(run, *v) for k, v in windows.items()}
        curves["equal_six_factor_ensemble_" + label] = run
    learner, gated, fits = online_ridge_scores(p, factors, beta)
    for name, score in [("online_ridge", learner), ("online_ridge_cost_gate", gated)]:
        results[name] = {"accounts": {}, "training": "365d rolling, 28d refit, ridge .1, 9d label maturity"}
        for cost in (10, 30, 60):
            # Fresh start after learner warm-up; earlier windows are omitted.
            run = simulate(p, score, start="2024-01-01", beta=beta, cost_bp=cost)
            label = f"beta_neutral_{cost}bp"
            results[name]["accounts"][label] = {k: metrics(run, *v) for k, v in windows.items()}
            curves[name + "_" + label] = run
        results[name]["fits"] = fits
    uncertainty = {}
    for name in ("carry_7d", "residual_momentum_20d", "passive_absorption_3d",
                 "momentum_20d_control", "online_ridge_cost_gate"):
        run = curves[name + "_beta_neutral_10bp"]
        r = run["returns"][run["dates"] >= "2025-01-01"]
        bounds = block_ci(np.log1p(r))
        uncertainty[name] = dict(daily_mean_log_return_block30_ci95=bounds,
                                 cagr_pct_ci95=((np.exp(np.asarray(bounds) * 365.25) - 1) * 100).tolist())
    (args.output / "uncertainty.json").write_text(json.dumps(uncertainty, indent=2, allow_nan=False) + "\n")
    # Existing evaluation history is not an untouched test, regardless of new code.
    payload = dict(research_only=True, orders_authorized=False, universe=list(SYMBOLS),
                   bar_count=len(p["times"]), funding_counts=p["funding_counts"],
                   approximate_funding_marks=p["approximate_marks"],
                   funding_approximation="Missing marks through 2023-10-31 use same-day trade open; 2024+ marks complete",
                   first_bar=str(p["dates"][0]), last_bar=str(p["dates"][-1]),
                   downloaded_at=p["downloaded_at"], initial_equity_usdt=10000,
                   signal_to_execution="signal close t; execute open t+2; full extra day delay",
                   rebalance_days=7, gross_target=1, costs_one_way_bp=[10,30,60],
                   windows=windows, independent_oos=False, results=results)
    (args.output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    # Retain compact daily account series so later comparisons need no repeat API calls.
    np.savez_compressed(args.output / "curves.npz", **{f"{k}__{field}": v for k, run in curves.items()
                         for field, v in run.items() if field in ("dates", "returns", "nav")})
    print("factor | dev CAGR | 2024 CAGR | 2025 CAGR | 2026 CAGR | eval CAGR/MDD | stress30 CAGR | 5d IC eval2025/26")
    for name, result in results.items():
        if "accounts" not in result:
            continue
        a = result["accounts"]["beta_neutral_10bp"]
        b = result["accounts"]["beta_neutral_30bp"]["evaluation_2025_2026"]
        vals = [a[k]["cagr_pct"] if a[k] else None for k in windows if k != "evaluation_2025_2026"]
        m = a["evaluation_2025_2026"]
        ic = result.get("ic_5d", {})
        print(name, [round(v, 2) if v is not None else None for v in vals], round(m["cagr_pct"],2), round(m["mdd_pct"],2), round(b["cagr_pct"],2),
              {k:round(v["mean"],4) for k,v in ic.items() if k.startswith("evaluation")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
