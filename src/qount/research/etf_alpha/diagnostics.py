"""Date-balanced prediction and fixed no-order portfolio diagnostics."""
from __future__ import annotations

import numpy as np

from qount.research.etf_trader.costs import cost_params_for
from qount.research.etf_trader.env import Decision, max_drawdown
from qount.research.etf_trader.scorer import construct_weights, percentile_rank, rolling_mean, daily_returns
from qount.research.etf_trader.universe import US_ACCOUNT

from .data import total_return_index
from .execution import execution_inputs, simulate


def correlation(x, y):
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = np.asarray(x)[valid], np.asarray(y)[valid]
    if len(x) < 3 or x.std() < 1e-12 or y.std() < 1e-12:
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])


def mean_finite(x):
    values = np.asarray(x, float)
    return float(values[np.isfinite(values)].mean()) if np.isfinite(values).any() else None


def ic_series(pred, truth, masks):
    p, y = np.where(masks, pred, np.nan), np.where(masks, truth, np.nan)
    rp, ry = percentile_rank(p), percentile_rank(y)
    return np.asarray([correlation(a, b) for a, b in zip(p, y)]), np.asarray(
        [correlation(a, b) for a, b in zip(rp, ry)])


def huber(pred, truth, mask, scale):
    error = np.abs((pred - truth) / scale)
    value = np.where(error <= 1, .5 * error ** 2, error - .5)
    # NaN placeholders are excluded before multiplication.
    per_date = np.where(mask, value, 0).sum(1) / np.maximum(mask.sum(1), 1)
    return mean_finite(per_date[mask.any(1)])


def block_interval(series, *, block=60, seed=1000, samples=500):
    """Moving synchronous date blocks; missing IC stays missing within its date."""
    series = np.asarray(series, float)
    if len(series) < block or np.isfinite(series).sum() < 3:
        return {"status": "insufficient", "block_sessions": block}
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(samples):
        starts = rng.integers(0, len(series) - block + 1, int(np.ceil(len(series) / block)))
        indices = (starts[:, None] + np.arange(block)).ravel()[:len(series)]
        value = mean_finite(series[indices])
        if value is not None:
            draws.append(value)
    return {"status": "diagnostic", "block_sessions": block, "samples": len(draws),
            "lower": float(np.quantile(draws, .025)), "upper": float(np.quantile(draws, .975))}


def lagged_beta(panel):
    returns = daily_returns(total_return_index(panel.close, panel.dividends, panel.splits))
    cash = daily_returns(panel.cash_close)
    excess = returns - cash[:, None]
    benchmark = excess[:, panel.symbols.index("SPY")]
    cov = rolling_mean(excess * benchmark[:, None], 252) - rolling_mean(excess, 252) * rolling_mean(benchmark, 252)[:, None]
    var = rolling_mean(benchmark ** 2, 252) - rolling_mean(benchmark, 252) ** 2
    return np.divide(cov, var[:, None], out=np.full_like(cov, np.nan), where=var[:, None] > 1e-12)


def prediction_report(data, rows, pred, scales, panel, beta):
    rows = np.asarray(rows)
    truth, mask = data.targets["mu20"][rows], data.masks["mu20"][rows]
    mu = pred["mu20"]
    if mu.shape != truth.shape or not np.isfinite(mu).all():
        raise ValueError("finite date-aligned mu20 predictions required")
    ic, rank = ic_series(mu, truth, mask)
    end, start = data.end_rows[20][rows], data.start_rows[rows]
    realised_cash = np.full(len(rows), np.nan)
    valid = (end >= 0) & (start >= 0)
    realised_cash[valid] = panel.cash_open[end[valid]] / panel.cash_open[start[valid]] - 1
    # Forecasts are strictly trailing; realised cash is only a diagnostic target.
    forecast = panel.cash_close[rows] / panel.cash_close[rows - 20] - 1
    cash_ic, cash_rank = ic_series(mu - forecast[:, None], truth - realised_cash[:, None], mask)
    sp = panel.symbols.index("SPY")
    residual_y = truth - realised_cash[:, None] - beta[rows] * (truth[:, sp] - realised_cash)[:, None]
    residual_p = mu - forecast[:, None] - beta[rows] * (mu[:, sp] - forecast)[:, None]
    residual_mask = mask & mask[:, sp, None] & np.isfinite(beta[rows])
    residual_ic, residual_rank = ic_series(residual_p, residual_y, residual_mask)
    report = {"dates": int(mask.any(1).sum()), "asset_observations": int(mask.sum()),
              "assets": len(data.symbols), "mu20_huber": huber(mu, truth, mask, scales.stats["mu20"]["std"]),
              "rank_ic": mean_finite(rank), "ic": mean_finite(ic),
              "cash_excess_ic": mean_finite(cash_ic), "cash_excess_rank_ic": mean_finite(cash_rank),
              "lagged_beta_residual_ic": mean_finite(residual_ic), "lagged_beta_residual_rank_ic": mean_finite(residual_rank),
              "direction_accuracy": float(((mu > 0) == (truth > 0))[mask].mean()),
              "train_majority_direction_accuracy": float(((scales.stats["mu20"]["mean"] > 0) == (truth > 0))[mask].mean()),
              "time_series_ic": {s: mean_finite([correlation(np.where(mask[:, i], mu[:, i], np.nan),
                                                               np.where(mask[:, i], truth[:, i], np.nan))])
                                 for i, s in enumerate(data.symbols)},
              "rank_ic_intervals": {str(b): block_interval(rank, block=b) for b in (40, 60, 120)}}
    if "p_up" in pred:
        p, y = pred["p_up"], (truth > 0).astype(float)
        report["brier"] = float(((p - y) ** 2)[mask].mean())
        report["probability_calibration"] = []
        for low in np.arange(0, 1, .1):
            selected = mask & (p >= low) & (p < low + .1 + (1e-12 if low > .89 else 0))
            report["probability_calibration"].append({"lower": float(low), "count": int(selected.sum()),
                "forecast": mean_finite(p[selected]), "observed": mean_finite(y[selected])})
    if "q10" in pred:
        report["q10_violation_rate"] = float((truth < pred["q10"])[mask].mean())
    if "sigma20" in pred:
        sm = data.masks["sigma20"][rows]
        report["sigma_realised_to_forecast"] = mean_finite(data.targets["sigma20"][rows][sm] / pred["sigma20"][sm])
    return report, {"rows": rows, "ic": ic, "rank_ic": rank, "residual_rank_ic": residual_rank}


def bridge_targets(panel, rows, mu, prepared):
    if np.shape(mu) != (len(rows), len(panel.symbols)) or not np.isfinite(mu).all():
        raise ValueError("finite bridge predictions required")
    targets = np.zeros_like(panel.close)
    for row, prediction in zip(rows, mu):
        cash_forecast = panel.cash_close[row] / panel.cash_close[row - 20] - 1
        eligible = (prediction > cash_forecast + (1.005 ** (20 / 252) - 1)) & ~prepared.reduce_only[row]
        scores = percentile_rank(np.where(eligible, prediction, np.nan)[None])[0]
        targets[row] = construct_weights(scores, prepared.sigma[row], .3, 1.0, US_ACCOUNT, eligible)
    return targets


def portfolio_report(result, cash_returns, stop):
    start = result.start
    r = result.returns[start + 1:stop + 1]
    excess = r - cash_returns[start + 1:stop + 1]
    sd = excess.std(ddof=1)
    return {"cagr": float((result.equity[stop] / result.equity[start]) ** (252 / len(r)) - 1),
            "sharpe_excess_cash": float(excess.mean() * np.sqrt(252) / sd) if sd > 1e-14 else 0.0,
            "max_drawdown": max_drawdown(result.equity[start:stop + 1]),
            "forced_breaches": int(result.forced_breach[start:stop + 1].sum()),
            "minimum_cash": float(np.nanmin(result.cash[start:stop + 1])),
            "max_rolling_voluntary": float(np.max(np.convolve(result.voluntary_turnover[start + 1:stop + 1],
                                                          np.ones(min(252, len(r))), "valid"))),
            "trading_days": len(r), "total_costs": float(result.costs[start:stop + 1].sum())}


def bridge_report(panel, rows, mu, *, state_by_cost=None, anchor=None, multipliers=(1., 2., 3.)):
    prepared = execution_inputs(panel, cost_params_for(US_ACCOUNT))
    targets = bridge_targets(panel, rows, mu, prepared)
    first, stop = int(rows[0]), int(rows[-1])
    states, scores, curves = {}, {}, {}
    for multiplier in multipliers:
        state = None if state_by_cost is None else state_by_cost.get(multiplier)
        start = first if state is None else first - 1
        origin = first if anchor is None else anchor
        def policy(obs):
            if obs.t < first or (obs.t - origin) % 21:
                return Decision(None)
            return Decision(targets[obs.t], band=0, kappa=1)
        result = simulate(panel, policy, start=start, stop=stop, inputs=prepared,
                          cost_multiplier=multiplier, state=state)
        states[multiplier] = result.state
        scores[f"{multiplier:g}x"] = portfolio_report(result, prepared.cash_returns, stop)
        interval = slice(start, stop + 1)
        curves[f"equity_{multiplier:g}x"] = result.equity[interval]
        curves[f"returns_{multiplier:g}x"] = result.returns[interval]
        curves[f"cash_{multiplier:g}x"] = result.cash[interval]
    curves["rows"] = np.arange(start, stop + 1)
    return scores, curves, states


def retention(candidate: list[dict], parent: list[dict], *, turnover_rule="hard_budget") -> dict:
    """Paired seeds and actual hard budget; v1's stricter interpretation is explicit."""
    if turnover_rule not in ("hard_budget", "parent_nonincrease_v1"):
        raise ValueError("unknown turnover retention rule")
    if len(candidate) != 5 or len(parent) != 5:
        return {"retained": False, "reason": "incomplete_five_seed_pairs"}
    if any(a["seed"] != b["seed"] for a, b in zip(candidate, parent)):
        raise ValueError("retention requires matching seed pairs")
    mean = lambda records, key: float(np.mean([r["bridge"]["2x"][key] for r in records]))
    deltas = {"sharpe_excess_cash": mean(candidate, "sharpe_excess_cash") - mean(parent, "sharpe_excess_cash"),
              "cagr": mean(candidate, "cagr") - mean(parent, "cagr"),
              "max_drawdown": mean(parent, "max_drawdown") - mean(candidate, "max_drawdown")}
    qualified = []
    for key, threshold in (("sharpe_excess_cash", .05), ("cagr", .005), ("max_drawdown", .02)):
        direction = -1 if key == "max_drawdown" else 1
        agreement = sum(direction * (a["bridge"]["2x"][key] - b["bridge"]["2x"][key]) > 0
                        for a, b in zip(candidate, parent))
        passes = deltas[key] >= threshold if key == "max_drawdown" else deltas[key] > threshold
        if passes and agreement >= 3:
            qualified.append(key)
    ranks = [[r["prediction"]["rank_ic"] for r in records] for records in (candidate, parent)]
    rank_ok = all(v is not None for group in ranks for v in group) and np.median(ranks[0]) >= np.median(ranks[1])
    loss_ok = np.mean([r["prediction"]["mu20_huber"] for r in candidate]) <= np.mean(
        [r["prediction"]["mu20_huber"] for r in parent])
    constraints_ok = all(a["bridge"]["2x"]["forced_breaches"] <= b["bridge"]["2x"]["forced_breaches"]
                         and a["bridge"]["2x"]["minimum_cash"] >= -1e-7
                         and a["bridge"]["2x"]["max_rolling_voluntary"] <= (
                             b["bridge"]["2x"]["max_rolling_voluntary"] + 1e-9
                             if turnover_rule == "parent_nonincrease_v1" else US_ACCOUNT.turnover_budget + 1e-7)
                         for a, b in zip(candidate, parent))
    return {"retained": bool(qualified and rank_ok and loss_ok and constraints_ok),
            "improvement_metrics": qualified, "deltas": deltas, "rank_ic_ok": bool(rank_ok),
            "huber_ok": bool(loss_ok), "constraints_ok": bool(constraints_ok), "turnover_rule": turnover_rule}


def select_candidate(candidates: dict[str, list[dict]]) -> str:
    complete = {name: records for name, records in candidates.items() if records}
    if not complete:
        raise ValueError("no eligible completed candidate")
    losses = {name: float(np.mean([r["prediction"]["mu20_huber"] for r in records]))
              for name, records in complete.items()}
    best = min(losses.values())
    tied = [name for name, loss in losses.items() if loss <= best + 1e-4]
    return min(tied, key=lambda name: (complete[name][0]["parameters"], name))
