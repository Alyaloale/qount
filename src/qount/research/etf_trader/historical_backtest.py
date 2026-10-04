"""Frozen exploratory checkpoint evaluation through the authoritative numpy engine.

This is not P3 certification: the final P2 model and second-family acceptance are
not available. Evaluate the declared checkpoint set once, without selecting a
winner on historical returns. research_only=true / orders_authorized=false.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import torch

from . import baselines, constraints as C
from .costs import cost_params_for
from .env import Decision, MarketData, Observation, SimResult, max_drawdown, max_rolling_turnover, simulate, summarize
from .features import WorldFeatures, world_features
from .historical_data import file_hash, load_panel
from .policy import PolicyConfig, Trader, construct
from .universe import ACCOUNTS, Account


class HistoricalPolicy:
    """Match train.policy_inputs exactly, including all holdings-dependent inputs."""

    def __init__(self, model: Trader, features: WorldFeatures, data: MarketData, account: Account):
        self.model, self.features, self.data, self.account = model, features, data, account
        self.h = model.initial_state(1, device="cpu")
        self.actions: list[dict] = []

    def __call__(self, obs: Observation) -> Decision:
        t, w = obs.t, obs.weights
        capacity = np.log1p(C.MAX_ADV_FRACTION * np.maximum(self.data.adv[t], 0) / obs.equity)
        asset = np.column_stack([self.features.asset[t], w, self.account.single_cap - w,
                                 self.features.tradable[t], capacity])
        used = obs.used_voluntary / obs.budget
        acc = [used, 1 - used, obs.drawdown, C.DEFAULT_D1 - obs.drawdown,
               C.DEFAULT_D2 - obs.drawdown, float(obs.derisked)]
        tensor = lambda x: torch.as_tensor(x, dtype=torch.float32).unsqueeze(0)
        with torch.inference_mode():
            action, self.h = self.model(tensor(asset), tensor(self.features.market[t]), tensor(acc), self.h)
            target = construct(tensor(self.features.asset[t, :, :4]), tensor(self.features.sigma[t]),
                               torch.as_tensor(self.features.eligible[t]).unsqueeze(0), action, self.account)
        weights = target[0].numpy().astype(float)
        if not np.isfinite(weights).all():
            raise ValueError(f"non-finite model target at row {t}")
        self.actions.append({"row": t, "alpha": action.alpha[0].tolist(), "gross": action.gross.item(),
                             "tau": action.tau.item(), "band": action.band.item(), "kappa": action.kappa.item()})
        return Decision(weights, action.band.item(), action.kappa.item())


def load_checkpoint(path: Path) -> tuple[Trader, dict]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    cfg = checkpoint["config"]
    if "episode" in checkpoint:
        cfg = cfg | {"checkpoint_episode": checkpoint["episode"]}
    model = Trader(PolicyConfig(**cfg["policy"]))
    state = {k.removeprefix("_orig_mod."): v for k, v in checkpoint["model"].items()}
    model.load_state_dict(state, strict=True)
    model.eval()
    return model, cfg


def metrics(result: SimResult, data: MarketData, dates: list[str]) -> dict:
    summary = summarize(result)
    start = result.start
    equity = result.equity[start:]
    returns = result.returns[start + 1:]
    cash = data.cash_return[start + 1:]
    excess = returns - cash
    sd = float(np.std(excess, ddof=1)) if len(excess) > 1 else 0.0
    summary.update(total_return=float(equity[-1] / equity[0] - 1), final_equity=float(equity[-1]),
                   ann_log_return=float(np.log(equity[-1] / equity[0]) * 252 / len(returns)),
                   sharpe_excess_cash=float(np.mean(excess) / sd * np.sqrt(252)) if sd else 0.0,
                   sharpe_definition="sharpe: arithmetic net returns vs zero; sharpe_excess_cash: vs BIL",
                   trading_days=len(returns), total_costs=float(result.costs.sum()),
                   max_rolling_voluntary=max_rolling_turnover(result.voluntary_turnover[start + 1:]),
                   max_rolling_total=max_rolling_turnover((result.voluntary_turnover + result.forced_turnover)[start + 1:]),
                   mean_cash_weight=float(np.mean(1 - result.weights[start + 1:].sum(axis=1))),
                   mean_asset_weights=np.mean(result.weights[start + 1:], axis=0).tolist(),
                   annual={})
    day_dates = dates[start + 1:]
    for year in sorted({d[:4] for d in day_dates}):
        r = returns[np.array([d.startswith(year) for d in day_dates])]
        summary["annual"][year] = {"return": float(np.prod(1 + r) - 1), "days": len(r),
                                   "max_drawdown": max_drawdown(np.r_[1.0, np.cumprod(1 + r)])}
    return summary


def _without_year(result: SimResult, dates: list[str], year: str) -> tuple[float, float]:
    r = result.returns[result.start + 1:]
    keep = np.array([not d.startswith(year) for d in dates[result.start + 1:]])
    r = r[keep]
    sd = float(np.std(r, ddof=1))
    return float(r.mean() / sd * np.sqrt(252)) if sd else 0.0, max_drawdown(np.r_[1, np.cumprod(1 + r)])


def exploratory_gates(model: SimResult, fixed: SimResult, reference: SimResult,
                      data: MarketData, dates: list[str], account: Account) -> dict:
    m, f, b = [metrics(r, data, dates) for r in (model, fixed, reference)]
    full_years = {y: v for y, v in m["annual"].items() if v["days"] >= 240}
    best = max(full_years, key=lambda y: full_years[y]["return"]) if full_years else None
    g5 = None
    if best:
        ms, md = _without_year(model, dates, best)
        bs, bd = _without_year(reference, dates, best)
        g5 = ms >= bs - 0.10 and md <= 0.7 * bd
    return {"G1": m["sharpe"] >= b["sharpe"] - 0.10 and m["max_drawdown"] <= 0.7 * b["max_drawdown"],
            "G2": m["sharpe"] >= f["sharpe"] and m["max_drawdown"] <= f["max_drawdown"] + 0.03,
            "G3": m["max_drawdown"] <= 0.20,
            "G4": m["max_rolling_voluntary"] <= account.turnover_budget + 1e-6
                  and m["max_rolling_total"] <= 1.5 * account.turnover_budget + 1e-6,
            "G5": g5, "excluded_best_full_year": best, "promotion_authorized": False}


def _curve(path: Path, result: SimResult, dates: list[str], symbols: tuple[str, ...]) -> None:
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["date", "equity", "net_return", "cost", "voluntary_turnover", "forced_turnover", *symbols, "cash"])
        for t in range(result.start, len(dates)):
            w = result.weights[t]
            writer.writerow([dates[t], result.equity[t], result.returns[t], result.costs[t],
                             result.voluntary_turnover[t], result.forced_turnover[t], *w, 1 - w.sum()])


def evaluate(checkpoints: list[Path], data_root: Path, out: Path, start: str, end: str,
             initial_equity: float = 1_000_000.0) -> dict:
    """Freeze hashes and copies before model inference, then evaluate every declared model."""
    if not checkpoints or initial_equity <= 0 or start >= end:
        raise ValueError("checkpoints, positive equity and increasing ISO dates required")
    torch.set_num_threads(1)
    account = ACCOUNTS["us"]
    data, dates, audit = load_panel(data_root, account, end)
    first = int(np.searchsorted(dates, start))
    # Longest factor lookback plus PIT standardization: 756+257 rows.
    if first < 1013 or first >= data.T - 1:
        raise ValueError("evaluation requires at least 1013 prior common bars and a fill day")
    features = world_features(data.close_adj, account, adv=data.adv, spread=data.spread)
    if not features.eligible[first:].any(axis=1).all():
        raise ValueError("no eligible risk assets on an evaluation date")
    out.mkdir(parents=True, exist_ok=False)
    frozen = out / "checkpoints"
    frozen.mkdir()
    declared = []
    for i, checkpoint in enumerate(checkpoints):
        dest = frozen / f"model_{i}.pt"
        shutil.copyfile(checkpoint, dest)
        declared.append({"id": f"model_{i}", "source": str(checkpoint), "sha256": file_hash(dest)})
    source_root = Path(__file__).parent
    code_hashes = {str(p.relative_to(source_root)): file_hash(p) for p in sorted(source_root.glob("*.py"))}
    contract = {"schema": "etf-historical-exploratory-v1", "frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "research_only": True, "orders_authorized": False, "result_status": "exploratory_weak_holdout",
                "account": asdict(account) | {"t_plus_one": sorted(account.t_plus_one)},
                "requested_start": start, "requested_end": end, "decision_start": dates[first],
                "first_fill": dates[first + 1], "last": dates[-1], "warmup_bars": first,
                "initial_equity": initial_equity, "cost_multipliers": [1.0, 2.0, 3.0],
                "checkpoints": declared, "data": audit, "code_hashes": code_hashes,
                "model_selection": "caller-declared checkpoints, no historical selection or parameter tuning",
                "baselines": ["fixed_scorer", "sixty_forty", "cash"],
                "sixty_forty_convention": "monthly 60% SPY/40% IEF; same costs/budget; no risk caps or drawdown de-risk",
                "limitations": ["P2 capacity selection and bootstrap-family acceptance incomplete; not P3",
                                "public Yahoo alternative to uncompleted P0 data audit", "valuation unavailable; Value neutral",
                                "static spread/impact/regulatory fee estimates", "no DSR/PBO or bootstrap confidence intervals",
                                "history already exposed in previous research; not independent OOS"],
                "historical_model_exposures": len(declared), "global_trial_count": "not reconciled; no P3 trial number claimed"}
    (out / "contract.json").write_text(json.dumps(contract, indent=2) + "\n")
    report = {"contract_sha256": file_hash(out / "contract.json"), "research_only": True,
              "orders_authorized": False, "result_status": contract["result_status"], "period": {
                  "decision_start": dates[first], "first_fill": dates[first + 1], "end": dates[-1]},
              "data_audit": audit, "costs": {}}
    costs = cost_params_for(account)
    fixed_targets = baselines.fixed_scorer(data.close_adj, account)
    reference_targets = baselines.sixty_forty(data.close_adj, account)
    for multiplier in contract["cost_multipliers"]:
        label = f"{multiplier:g}x"
        run = lambda policy, acct=account, dr=None: simulate(data, acct, policy, costs, start=first,
            initial_equity=initial_equity, cost_multiplier=multiplier, derisk=dr)
        fixed = run(baselines.scheduled_policy(fixed_targets, first))
        reference = run(baselines.scheduled_policy(reference_targets, first),
                        replace(account, single_cap=1.0, group_cap=1.0), C.DeRisk(d1=0.99, d2=0.999))
        cash = run(lambda obs: Decision(None))
        section = {"baselines": {name: metrics(res, data, dates) for name, res in
                                  (("fixed_scorer", fixed), ("sixty_forty", reference), ("cash", cash))}, "models": {}}
        for name, res in (("fixed_scorer", fixed), ("sixty_forty", reference), ("cash", cash)):
            _curve(out / f"{name}_{label}.csv", res, dates, account.symbols)
        for declaration in declared:
            name = declaration["id"]
            model, cfg = load_checkpoint(frozen / f"{name}.pt")
            if cfg["account"] != account.name:
                raise ValueError("checkpoint account does not match the US data panel")
            policy = HistoricalPolicy(model, features, data, account)
            res = run(policy)
            stats = metrics(res, data, dates)
            stats.update(config=cfg, checkpoint_sha256=declaration["sha256"], source=declaration["source"],
                         mean_action={k: np.mean([a[k] for a in policy.actions], axis=0).tolist()
                                      for k in ("alpha", "gross", "tau", "band", "kappa")})
            if multiplier == 2:
                stats["exploratory_gates"] = exploratory_gates(res, fixed, reference, data, dates, account)
            section["models"][name] = stats
            _curve(out / f"{name}_{label}.csv", res, dates, account.symbols)
            (out / f"{name}_{label}_actions.json").write_text(json.dumps(policy.actions) + "\n")
            print(f"{label} {name}: CAGR={stats['cagr']:.4%}, Sharpe={stats['sharpe']:.3f}, DD={stats['max_drawdown']:.4%}", flush=True)
        report["costs"][label] = section
    (out / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    manifest = {"research_only": True, "orders_authorized": False,
                "files": {str(p.relative_to(out)): file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()},
                "command": "see contract.json for frozen inputs; invoked via etf_trader_backtest.py",
                "retention": "immutable research evidence; no production eligibility"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return report
