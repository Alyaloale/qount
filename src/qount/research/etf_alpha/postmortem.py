"""Frozen-prediction attribution and selector sensitivity; never fit a model.

All counterfactuals are retrospective diagnostics. Resampling an observed ledger
does not produce an executable path or a probability of backtest overfitting.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from qount.research.etf_trader.costs import cost_params_for
from qount.research.etf_trader.env import Decision
from qount.research.etf_trader.scorer import percentile_rank
from qount.research.etf_trader.universe import US_ACCOUNT

from .artifacts import GUARDS, finish_manifest, new_directory, read_json, sha256, write_json
from .diagnostics import bridge_targets, correlation, ic_series, mean_finite, portfolio_report
from .execution import execution_inputs, simulate
from .expanded_selection import BASELINES, NEGATIVE, select_v2, utility
from .expanded_data import load_panel
from .training_data import load_folds, load_training_data


def guard_output_location(run, out):
    """A diagnostic artifact must never be written inside its frozen source."""
    if Path(out).resolve().is_relative_to(Path(run).resolve()):
        raise ValueError("analysis output must be separate from the immutable source run")


def prediction_components(mu):
    """Orthogonal two-way ANOVA of a complete dates-by-assets prediction panel."""
    mu = np.asarray(mu, float)
    if mu.ndim != 2 or not mu.size or not np.isfinite(mu).all():
        raise ValueError("a finite nonempty prediction panel is required")
    mean = float(mu.mean())
    asset = mu.mean(0) - mean
    date = mu.mean(1) - mean
    interaction = mu - mean - asset[None] - date[:, None]
    total = float(np.mean((mu - mean) ** 2))
    parts = {"asset": float(np.mean(asset ** 2)), "date": float(np.mean(date ** 2)),
             "interaction": float(np.mean(interaction ** 2))}
    return {"mean": mean, "asset_means": mu.mean(0).tolist(), "variance": total,
            "variance_fractions": {k: v / total if total > 1e-24 else 0. for k, v in parts.items()},
            "reconstruction_error": float(np.max(np.abs(mu - (mean + asset[None] + date[:, None] + interaction)))),
            "test_means_are_attribution_only": True}


def ledger_components(panel, ledger, stop):
    """Exact close-to-close profit identity, including splits and next-open fills."""
    rows = np.arange(ledger.start + 1, stop + 1)
    previous = ledger.shares[rows - 1]
    price = previous * (panel.splits[rows] * panel.close[rows] - panel.close[rows - 1])
    fill = ledger.executed_shares[rows] * (panel.close[rows] - panel.open[rows])
    dividend = previous * panel.splits[rows] * panel.dividends[rows]
    carry, costs = ledger.cash_carry[rows], -ledger.costs[rows]
    identity = (price + fill + dividend).sum(1) + carry + costs
    change = ledger.equity[rows] - ledger.equity[rows - 1]
    error = float(np.max(np.abs(identity - change)))
    if not np.allclose(identity, change, rtol=1e-10, atol=1e-6):
        raise ValueError("profit attribution does not reconcile to ledger equity")
    return {"rows": rows, "price": price, "fill": fill, "dividend": dividend,
            "cash_carry": carry, "costs": costs, "maximum_identity_error": error}


def _path_utility(returns, cash, penalty):
    returns, cash = np.asarray(returns), np.asarray(cash)
    if returns.ndim == 1:
        returns, cash = returns[None], cash[None]
    excess = returns - cash
    sd = excess.std(1, ddof=1)
    sharpe = np.divide(excess.mean(1) * np.sqrt(252), sd, out=np.zeros(len(sd)), where=sd > 1e-14)
    equity = np.c_[np.ones(len(returns)), np.cumprod(1 + returns, axis=1)]
    drawdown = np.max(1 - equity / np.maximum.accumulate(equity, axis=1), axis=1)
    return sharpe - 2 * drawdown - penalty


def selector_sensitivity(records, series, *, seed=20261003, samples=400, blocks=(20, 40, 60)):
    """Synchronous past-validation date perturbations, with and without IC gates.

    Executed returns are resampled, not refilled. Hard risk eligibility and the
    turnover penalty remain the originally observed values. This intentionally
    isolates instability of the validation score and prediction gates.
    """
    selection = select_v2(records)
    names = list(series)
    lengths = {len(v[0]["returns"]) for v in series.values()}
    if len(lengths) != 1:
        raise ValueError("all validation series must share the execution calendar")
    length = lengths.pop()
    if length < max(blocks):
        raise ValueError("validation window too short for registered block lengths")
    for name in names:
        if len(series[name]) != len(records[name]):
            raise ValueError("prediction and diagnostic seed counts disagree")
        for item, record in zip(series[name], records[name]):
            if any(len(item[k]) != length for k in ("returns", "cash", "rank", "huber")):
                raise ValueError("synchronous validation dates required")
            b = record["bridge"]["2x"]
            penalty = .025 * b["max_rolling_voluntary"] / 4
            reconstructed = float(_path_utility(item["returns"], item["cash"], penalty)[0])
            expected = (b["sharpe_excess_cash"] or 0) - 2*b["max_drawdown"] - penalty
            if not np.isclose(reconstructed, expected, atol=1e-8, rtol=1e-8):
                raise ValueError(f"validation utility mismatch: {name}")

    def evaluate(indices):
        scores, ranks, losses = {}, {}, {}
        for name in names:
            items = series[name]
            penalties = np.array([.025*r["bridge"]["2x"]["max_rolling_voluntary"]/4 for r in records[name]])
            r = np.stack([s["returns"][indices] for s in items])
            cash = np.stack([s["cash"][indices] for s in items])
            scores[name] = float(_path_utility(r, cash, penalties).mean())
            ranks[name] = [mean_finite(s["rank"][indices]) for s in items]
            losses[name] = float(np.mean([mean_finite(s["huber"][indices]) for s in items]))
        rank_ref = max(0., ranks["train-asset-mean"][0] or 0.,
                       float(np.mean([r or 0. for r in ranks[NEGATIVE]])))
        loss_ref = min(losses[k] for k in ("E3-ridge-raw", "train-asset-mean"))
        eligible = [k for k in selection["eligible"] if k in BASELINES]
        for name, decision in selection["decisions"].items():
            if (decision["complete_five_seeds"] and decision["hard_constraints"]
                and sum(v is not None and v > rank_ref+.01 for v in ranks[name]) >= 3
                and losses[name] <= 1.05*loss_ref):
                eligible.append(name)
        choose = lambda options: min(options, key=lambda k: (-scores[k], records[k][0]["parameters"], k))
        return choose(selection["eligible"]), choose(eligible), scores

    output = {"original_selected": selection["selected"], "original_eligible": selection["eligible"],
              "original_utilities": {k: utility(records[k]) for k in selection["eligible"]},
              "samples_per_block": samples, "execution_dates": length,
              "risk_and_turnover_penalty_fixed": True, "bootstrap": {}, "window_slices": {}}
    rng = np.random.default_rng(seed)
    for block in blocks:
        fixed, gates = {k: 0 for k in names}, {k: 0 for k in names}
        for _ in range(samples):
            starts = rng.integers(0, length-block+1, int(np.ceil(length/block)))
            indices = (starts[:, None] + np.arange(block)).ravel()[:length]
            a, b, _ = evaluate(indices)
            fixed[a] += 1
            gates[b] += 1
        output["bootstrap"][str(block)] = {"fixed_eligibility_win_frequency": {k: v/samples for k, v in fixed.items() if v},
            "recomputed_signal_gates_win_frequency": {k: v/samples for k, v in gates.items() if v},
            "original_winner_retained_fixed": fixed[selection["selected"]]/samples,
            "original_winner_retained_gates": gates[selection["selected"]]/samples}
    for label, indices in (("first_half", np.arange(length//2)), ("second_half", np.arange(length//2, length)),
                           *((f"leave_quarter_{i+1}_out", np.setdiff1d(np.arange(length), q))
                             for i, q in enumerate(np.array_split(np.arange(length), 4)))):
        a, b, scores = evaluate(indices)
        output["window_slices"][label] = {"fixed_eligibility_selected": a, "recomputed_signal_gates_selected": b,
                                         "utilities": {k: scores[k] for k in selection["eligible"]}}
    return output


def analyze_run(run: Path, out: Path, *, samples=400, emit=print):
    """Analyze a completed immutable v2 run on external storage, CPU only."""
    guard_output_location(run, out)
    config, summary = read_json(run/"run-contract.json"), read_json(run/"summary.json")
    if summary["status"] != "complete" or summary["outer_test_status"] != "complete":
        raise ValueError("a completed run with frozen outer results is required")
    new_directory(out)
    source_manifest = read_json(run/"manifest.json")
    consumed = {}

    def checked(path):
        relative = str(path.relative_to(run))
        entry = source_manifest["files"][relative]
        expected = entry["sha256"] if isinstance(entry, dict) else entry
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"frozen analysis input changed: {relative}")
        consumed[relative] = actual
        return path

    def arrays(path):
        with np.load(checked(path), allow_pickle=False) as saved:
            return {k: saved[k].copy() for k in saved.files}

    checked(run/"run-contract.json")
    checked(run/"summary.json")
    root = Path(config["data_root"])
    data = load_training_data(root, config["dataset_manifest_sha256"])
    panel = load_panel(root)
    folds = load_folds(Path(config["fold_contract"]), read_json(root/"dataset-contract.json"))
    prepared = execution_inputs(panel, cost_params_for(US_ACCOUNT))
    names = list(summary["outer_test"]["continuous"])
    report = GUARDS | {"analysis_kind": "post_test_diagnostic_no_new_fits", "source_run": str(run),
        "source_manifest_sha256": sha256(run/"manifest.json"), "dataset_manifest_sha256": config["dataset_manifest_sha256"],
        "method": {"cost_multiplier": 2., "selector_samples": samples, "selector_block_sessions": [20,40,60],
                   "static_template": "mean of previous full validation-year frozen predictions, per asset",
                   "counterfactuals_do_not_establish_alpha": True, "formal_PBO_or_DSR_computed": False},
        "selector": {}, "predictions": {}, "training": {}, "portfolios": {}, "counterfactuals": {},
        "validation_to_test_ranks": {}}
    predictions, templates, validation_utilities = {}, {}, {}

    for fold in folds:
        f = fold.fold_id
        records = read_json(checked(run/f/"screening-diagnostics.json"))
        validation_utilities[f] = {k: utility(v) for k, v in records.items()}
        scale = np.std(data.targets["mu20"][fold.train_rows][data.masks["mu20"][fold.train_rows]], ddof=1)
        series, templates[f] = {}, {}
        train_mean = np.nanmean(np.where(data.masks["mu20"][fold.train_rows], data.targets["mu20"][fold.train_rows], np.nan), axis=0)
        for name, values in records.items():
            series[name], family_templates = [], []
            for record in values:
                job = (run/"prepared"/f/name if name in ("E3-ridge-raw", "negative-ridge-shuffle") else
                       run/f/name/f"seed_{record['seed']}" if len(values) == 5 else run/f/name)
                curve, pred = arrays(job/"validation_curve.npz"), arrays(job/"validation.npz")
                ic = arrays(job/"validation_ic.npz")
                rows = curve["rows"][1:]
                if not np.array_equal(pred["rows"], ic["rows"]):
                    raise ValueError("validation prediction/IC date mismatch")
                rank, hub = np.full(len(rows), np.nan), np.full(len(rows), np.nan)
                positions = np.searchsorted(rows, pred["rows"])
                # The first bridge date is an initial mark and has no executed return.
                use = (positions < len(rows)) & (pred["rows"] >= rows[0])
                if not np.array_equal(rows[positions[use]], pred["rows"][use]):
                    raise ValueError("purged label dates do not match execution dates")
                rank[positions[use]] = ic["rank_ic"][use]
                truth, mask = data.targets["mu20"][pred["rows"]], data.masks["mu20"][pred["rows"]]
                error = np.abs((pred["mu20"]-truth)/scale)
                loss = np.where(error <= 1, .5*error**2, error-.5)
                per_date = np.where(mask, loss, 0).sum(1)/np.maximum(mask.sum(1),1)
                hub[positions[use]] = per_date[use]
                series[name].append({"returns": curve["returns_2x"][1:], "cash": prepared.cash_returns[rows],
                                     "rank": rank, "huber": hub})
                bridge = arrays(job/"validation_bridge.npz")
                family_templates.append(bridge["mu20"].mean(0))
            templates[f][name] = np.mean(family_templates, axis=0)
        report["selector"][f] = selector_sensitivity(records, series, samples=samples)
        report["predictions"][f] = {}
        for name in names:
            pred = arrays(run/"outer_test"/name/f/"predictions.npz")
            if not np.array_equal(pred["rows"], fold.test_rows):
                raise ValueError("outer predictions disagree with frozen fold dates")
            predictions[f,name] = pred["mu20"]
            component = prediction_components(pred["mu20"])
            component["asset_prior_rank_correlation"] = mean_finite([correlation(
                percentile_rank(pred["mu20"].mean(0)[None])[0], percentile_rank(train_mean[None])[0])])
            component["validation_asset_template"] = templates[f].get(name, templates[f][summary["selections"][f]["selected"]]).tolist()
            component["train_asset_mean"] = train_mean.tolist()
            _, ranks = ic_series(pred["mu20"] - train_mean[None], data.targets["mu20"][fold.test_rows] - train_mean[None],
                                 data.masks["mu20"][fold.test_rows])
            component["train_prior_centered_rank_ic"] = mean_finite(ranks)
            report["predictions"][f][name] = component
        emit(json.dumps({"event": "fold_prediction_and_selector_complete", "fold": f}), flush=True)

    for name in ("E3-mlp-mtr", "E3-mlp-raw", "v2-levels", "v2-levels-id", "v2-rank-id", NEGATIVE, "v2-bootstrap-rank-id"):
        fits = [read_json(checked(run/f.fold_id/name/f"seed_{seed}"/"fit.json")) for f in folds for seed in config["seeds"]]
        report["training"][name] = {"fits": len(fits), "best_epoch_zero_count": sum(v["best_epoch"] == 0 for v in fits),
            "best_epoch_median": float(np.median([v["best_epoch"] for v in fits])),
            "best_epoch_range": [int(min(v["best_epoch"] for v in fits)), int(max(v["best_epoch"] for v in fits))],
            "epochs_median": float(np.median([v["epochs"] for v in fits]))}

    def replay(name, mode="original", reset=False):
        state, all_parts, all_curves, all_weights, all_caps, yearly = None, [], [], [], [], {}
        anchor = int(folds[0].test_rows[0])
        for index, fold in enumerate(folds):
            f, rows = fold.fold_id, fold.test_rows
            mu = predictions[f,name]
            family = summary["selections"][f]["selected"] if name == "selected" else name
            template = templates[f][family]
            if mode == "validation_static":
                mu = np.broadcast_to(template, mu.shape)
            elif mode == "remove_asset_template":
                mu = mu-template[None]+template.mean()
            targets = bridge_targets(panel, rows, mu, prepared)
            first, stop = int(rows[0]), int(rows[-1])
            # Reset is deliberately a non-executable diagnostic; preserve the same
            # rebalance calendar and start at the preceding close for later folds.
            start = first if index == 0 else first-1
            def policy(obs):
                if obs.t < first or (obs.t-anchor)%21:
                    return Decision(None)
                return Decision(targets[obs.t], band=0, kappa=1)
            result = simulate(panel, policy, start=start, stop=stop, inputs=prepared, cost_multiplier=2.,
                              state=None if reset else state)
            state = result.state
            if mode == "original" and not reset:
                saved = arrays(run/"outer_test"/name/f/"curve.npz")
                if not np.array_equal(saved["rows"], np.arange(start,stop+1)) or not np.allclose(
                    saved["equity_2x"], result.equity[start:stop+1], rtol=1e-10, atol=1e-5):
                    raise ValueError(f"frozen portfolio replay mismatch: {name}/{f}")
            parts = ledger_components(panel, result, stop)
            all_parts.append(parts)
            keep = slice(start if index == 0 else start+1, stop+1)
            all_curves.append({"rows": np.arange(start,stop+1)[0 if index == 0 else 1:],
                               "equity": result.equity[keep], "returns": result.returns[keep]})
            all_weights.append(result.weights[start+1:stop+1])
            all_caps.append(result.gross_cap[start+1:stop+1])
            yearly[f] = portfolio_report(result, prepared.cash_returns, stop) | {
                "total_return": float(result.equity[stop]/result.equity[start]-1),
                "derisk_fraction": float(np.mean(result.gross_cap[start:stop] < 1)),
                "mean_cash_weight": float(np.mean(1-result.weights[start+1:stop+1].sum(1)))}
        returns = np.concatenate([c["returns"] for c in all_curves])[1:]
        rrows = np.concatenate([c["rows"] for c in all_curves])[1:]
        equity = np.r_[1., np.cumprod(1+returns)]
        excess = returns-prepared.cash_returns[rrows]
        sd = excess.std(ddof=1)
        metric = {"cagr": float(equity[-1]**(252/len(returns))-1),
                  "sharpe_excess_cash": float(excess.mean()*np.sqrt(252)/sd) if sd > 1e-14 else 0.,
                  "max_drawdown": float(np.max(1-equity/np.maximum.accumulate(equity))),
                  "total_return": float(equity[-1]-1), "years": yearly,
                  "derisk_fraction": float(np.mean(np.concatenate(all_caps)<1))}
        if not reset:
            initial = float(all_curves[0]["equity"][0])
            total = {k: np.concatenate([p[k] for p in all_parts]) for k in ("price","fill","dividend","cash_carry","costs")}
            weights = np.concatenate(all_weights)
            metric["attribution"] = {s: {"price_profit": float(total["price"][:,i].sum()),
                "next_open_fill_profit": float(total["fill"][:,i].sum()), "dividend_profit": float(total["dividend"][:,i].sum()),
                "total_profit": float(sum(total[k][:,i].sum() for k in ("price","fill","dividend"))),
                "profit_per_initial_equity": float(sum(total[k][:,i].sum() for k in ("price","fill","dividend"))/initial),
                "mean_close_weight": float(weights[:,i].mean())} for i,s in enumerate(panel.symbols)}
            metric["cash_carry_profit"] = float(total["cash_carry"].sum())
            metric["cost_profit"] = float(total["costs"].sum())
            metric["initial_equity"] = initial
            metric["maximum_identity_error"] = max(p["maximum_identity_error"] for p in all_parts)
            if not np.isclose(sum(v["total_profit"] for v in metric["attribution"].values())+
                              metric["cash_carry_profit"]+metric["cost_profit"], initial*metric["total_return"], atol=1e-5):
                raise ValueError("continuous attribution identity failed")
        return metric

    for name in ("selected", "momentum120", "train-asset-mean", "E3-ridge-raw", NEGATIVE, "v2-rank-id", "v2-bootstrap-rank-id"):
        report["portfolios"][name] = replay(name)
        report["counterfactuals"][name] = {"fresh_each_test_year": replay(name, reset=True)}
        if name in (NEGATIVE, "v2-rank-id", "v2-bootstrap-rank-id"):
            for mode in ("validation_static", "remove_asset_template"):
                report["counterfactuals"][name][mode] = replay(name, mode)
        emit(json.dumps({"event": "portfolio_replay_complete", "family": name}), flush=True)

    for fold in folds:
        f = fold.fold_id
        eligible = summary["selections"][f]["eligible"]
        # Comparable fresh-account test scores, conditional on already frozen eligibility.
        test_scores = {}
        for name in eligible:
            if name not in report["counterfactuals"]:
                report["counterfactuals"][name] = {"fresh_each_test_year": replay(name, reset=True)}
            b = report["counterfactuals"][name]["fresh_each_test_year"]["years"][f]
            test_scores[name] = b["sharpe_excess_cash"]-2*b["max_drawdown"]-.025*b["max_rolling_voluntary"]/4
        vr = percentile_rank(np.array([validation_utilities[f][n] for n in eligible])[None])[0]
        tr = percentile_rank(np.array([test_scores[n] for n in eligible])[None])[0]
        selected = summary["selections"][f]["selected"]
        report["validation_to_test_ranks"][f] = {"eligible": eligible, "spearman": mean_finite([correlation(vr,tr)]),
            "selected_fresh_test_rank": int(1+sum(v > test_scores[selected] for v in test_scores.values())),
            "test_utilities": test_scores, "validation_utilities": {n: validation_utilities[f][n] for n in eligible}}
    report["consumed_source_files"] = consumed
    write_json(out/"analysis.json", report)
    (out/"postmortem.py").write_text(Path(__file__).read_text(), encoding="utf-8")
    finish_manifest(out, source_run=str(run), source_manifest_sha256=report["source_manifest_sha256"],
                    phase="frozen_prediction_postmortem_complete", no_model_fits=True)
    return report


def probe_identity(run: Path, out: Path, *, emit=print):
    """CPU inference intervention on frozen embeddings, never a retraining ablation."""
    guard_output_location(run, out)
    import torch
    from .diagnostics import bridge_report
    from .expanded_data import representation
    from .expanded_models import ExpandedPredictor, ExpandedSpec
    from .ridge import block_permutation

    config, source = read_json(run/"run-contract.json"), read_json(run/"manifest.json")
    if read_json(run/"summary.json")["status"] != "complete":
        raise ValueError("completed frozen checkpoints required")
    new_directory(out)
    root = Path(config["data_root"])
    data = load_training_data(root, config["dataset_manifest_sha256"])
    panel = load_panel(root)
    folds = load_folds(Path(config["fold_contract"]), read_json(root/"dataset-contract.json"))
    with np.load(root/"features.npz", allow_pickle=False) as values:
        assets = representation(values["raw"], data.assets, data.names)
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("highest")
    report = GUARDS | {"kind": "frozen_embedding_input_intervention", "device": "cpu", "new_fits": 0,
        "source_run": str(run), "source_manifest_sha256": sha256(run/"manifest.json"),
        "embedding_intervention": "replace each asset embedding by the mean of the nine frozen embeddings",
        "limitations": "out-of-distribution input intervention; not a model retrained without identity",
        "shuffle": {}, "families": {}, "ensemble_validation": {}, "consumed_source_files": {}}

    def checked(path):
        key = str(path.relative_to(run))
        expected = source["files"][key]
        actual = sha256(path)
        if actual != (expected["sha256"] if isinstance(expected, dict) else expected):
            raise ValueError(f"frozen checkpoint/probe input changed: {key}")
        report["consumed_source_files"][key] = actual
        return path

    for fold in folds:
        report["shuffle"][fold.fold_id] = {"train_dates": len(fold.train_rows),
            "identity_preserved": True, "within_asset_label_distribution_preserved": True,
            "unaltered_date_pairs_by_seed": {str(s): int(np.sum(block_permutation(len(fold.train_rows),seed=s)
                                                                          == np.arange(len(fold.train_rows))))
                                            for s in config["seeds"]},
            "checkpoint_selection_uses_unshuffled_validation_labels": True}
        records = read_json(checked(run/fold.fold_id/"screening-diagnostics.json"))
        selection = select_v2(records)
        ensemble_scores = {name: utility(records[name]) for name in selection["eligible"]}
        scores = {}
        for name in selection["eligible"]:
            if len(records[name]) != 5:
                continue
            values = []
            for record in records[name]:
                path = run/fold.fold_id/name/f"seed_{record['seed']}"/"validation_bridge.npz"
                with np.load(checked(path),allow_pickle=False) as stored:
                    rows = stored["rows"].copy()
                    values.append(stored["mu20"].copy())
            metrics, _, _ = bridge_report(panel,rows,np.mean(values,axis=0),multipliers=(2.,))
            b = metrics["2x"]
            score = b["sharpe_excess_cash"]-2*b["max_drawdown"]-.025*b["max_rolling_voluntary"]/4
            scores[name] = {"mean_individual_seed_utility": ensemble_scores[name],
                            "utility_of_mean_prediction_ledger": score}
            ensemble_scores[name] = score
        chosen = min(ensemble_scores,key=lambda n:(-ensemble_scores[n],records[n][0]["parameters"],n))
        report["ensemble_validation"][fold.fold_id] = {"original_selected":selection["selected"],
            "mean_prediction_selected_fixed_signal_eligibility":chosen,"neural_scores":scores}
    for name in (NEGATIVE, "v2-rank-id", "v2-bootstrap-rank-id"):
        details, curves, states = {}, [], None
        for fold in folds:
            rows = fold.test_rows
            x = torch.as_tensor(assets[rows], dtype=torch.float32)
            market = torch.as_tensor(data.market[rows], dtype=torch.float32)
            original, neutral, errors = [], [], []
            for seed in config["seeds"]:
                job = run/fold.fold_id/name/f"seed_{seed}"
                saved = torch.load(checked(job/"best.pt"), map_location="cpu", weights_only=True)
                spec = saved["spec"] | {"heads": tuple(saved["spec"]["heads"])}
                model = ExpandedPredictor(ExpandedSpec(**spec)).eval()
                model.load_state_dict(saved["model"], strict=True)
                scale = saved["scales"]["stats"]["mu20"]
                with torch.inference_mode():
                    mu = model(x,market)["mu20"].numpy()*scale["std"]+scale["mean"]
                    embedding = model.identity.weight.mean(0,keepdim=True)
                    model.identity.weight.copy_(embedding.expand_as(model.identity.weight))
                    changed = model(x,market)["mu20"].numpy()*scale["std"]+scale["mean"]
                with np.load(checked(job/"test.npz"), allow_pickle=False) as stored:
                    error = float(np.max(np.abs(mu-stored["mu20"])))
                    if not np.array_equal(rows,stored["rows"]) or error > 1e-6:
                        raise ValueError("original CPU predictions failed frozen GPU reproduction")
                original.append(mu);neutral.append(changed);errors.append(error)
            mu, changed = np.mean(original,0), np.mean(neutral,0)
            truth, masks = data.targets["mu20"][rows], data.masks["mu20"][rows]
            _, rank = ic_series(mu,truth,masks)
            _, altered_rank = ic_series(changed,truth,masks)
            details[fold.fold_id] = {"original_rank_ic": mean_finite(rank), "neutral_identity_rank_ic": mean_finite(altered_rank),
                "original_components": prediction_components(mu), "neutral_components": prediction_components(changed),
                "maximum_original_cpu_gpu_error": max(errors)}
            _, curve, states = bridge_report(panel,rows,changed,state_by_cost=states,
                anchor=int(folds[0].test_rows[0]),multipliers=(2.,))
            curves.append(curve)
            emit(json.dumps({"event":"identity_probe_fold_complete","family":name,"fold":fold.fold_id}),flush=True)
        returns = np.concatenate([c["returns_2x"] if i == 0 else c["returns_2x"][1:] for i,c in enumerate(curves)])[1:]
        eq = np.r_[1.,np.cumprod(1+returns)]
        rows = np.concatenate([c["rows"] if i == 0 else c["rows"][1:] for i,c in enumerate(curves)])[1:]
        cash = panel.cash_close[rows]/panel.cash_close[rows-1]-1
        excess = returns-cash
        report["families"][name] = {"folds":details, "neutral_identity_continuous_2x": {
            "cagr": float(eq[-1]**(252/len(returns))-1), "max_drawdown":float(np.max(1-eq/np.maximum.accumulate(eq))),
            "sharpe_excess_cash":float(excess.mean()*np.sqrt(252)/excess.std(ddof=1))}}
    write_json(out/"identity-probe.json",report)
    (out/"postmortem.py").write_text(Path(__file__).read_text(),encoding="utf-8")
    finish_manifest(out,phase="frozen_identity_probe_complete",source_run=str(run),no_model_fits=True)
    return report
