"""Resident CUDA bootstrap pretraining followed by real-date fine tuning."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F

from .artifacts import read_json, verify_files
from .expanded_models import ExpandedPredictor, ExpandedSpec
from .training import TensorPartition, _prediction, inverse_predictions


def balanced_mean(loss, mask):
    count = mask.sum(-1)
    valid = count > 0
    return (((loss * mask).sum(-1) / count.clamp_min(1)) * valid).sum() / valid.sum().clamp_min(1)


def rank_loss(prediction, target, mask, minimum_gap=.1):
    """Date-balanced RankNet pairs; near-tied train-standardized labels excluded."""
    pair = torch.triu_indices(prediction.shape[-1], prediction.shape[-1], 1, device=prediction.device)
    a, b = pair[0], pair[1]
    difference = target[:, a] - target[:, b]
    valid = mask[:, a] & mask[:, b] & (difference.abs() >= minimum_gap)
    value = F.softplus(-difference.sign() * (prediction[:, a] - prediction[:, b]))
    return balanced_mean(value, valid)


def losses(prediction, target, mask, weight):
    huber = balanced_mean(F.huber_loss(prediction, target, reduction="none"), mask)
    ranking = rank_loss(prediction, target, mask)
    return huber + weight * ranking, huber, ranking


def load_bootstrap(root, scales, device="cuda"):
    """Preallocate once per fold; reuse resident tensors across all declared seeds."""
    shards = sorted(root.glob("shard_*"))
    counts = [np.load(p / "mu20.npy", mmap_mode="r").shape[0:2] for p in shards]
    count = sum(a * b for a, b in counts)
    if not count:
        raise ValueError("completed bootstrap shards required")
    assets = torch.empty((count, 9, 84), dtype=torch.float32, device=device)
    market = torch.empty((count, 17), dtype=torch.float32, device=device)
    target = torch.empty((count, 9), dtype=torch.float32, device=device)
    mask = torch.empty((count, 9), dtype=torch.bool, device=device)
    first = 0
    for path, shape in zip(shards, counts):
        verify_files(path, read_json(path / "receipt.json")["files"])
        size = shape[0] * shape[1]
        for name, destination, tail in (("assets", assets, (9, 84)), ("market", market, (17,)),
                                       ("mu20", target, (9,)), ("mask", mask, (9,))):
            array = np.load(path / f"{name}.npy", mmap_mode="r")
            value = np.array(array.reshape((size,) + tail), copy=True)
            if name == "mu20":
                value = scales.transform("mu20", value).astype(np.float32)
            destination[first:first + size].copy_(torch.from_numpy(value))
        first += size
    return TensorPartition(np.arange(count), assets, market, {"mu20": target}, {"mu20": mask})


def optimizer_for(model, options):
    matrices, vectors = [], []
    for p in model.parameters():
        (matrices if p.ndim >= 2 else vectors).append(p)
    return torch.optim.AdamW([{"params": matrices, "weight_decay": options["matrix_weight_decay"]},
                             {"params": vectors, "weight_decay": 0}], lr=options["learning_rate"],
                            fused=next(model.parameters()).is_cuda)


def compiled_forward(model, emit, *, enabled=True):
    device = next(model.parameters()).device
    # Avoid retaining separate CUDA Graph input pools for the many large seed fits.
    compile_cuda = device.type == "cuda" and enabled
    forward = torch.compile(model.forward, mode="default", dynamic=True) if compile_cuda else model.forward
    state = {"state": "pending" if compile_cuda else "disabled", "error": None}
    def predict(assets, market):
        nonlocal forward
        if device.type == "cuda":
            torch.compiler.cudagraph_mark_step_begin()
        try:
            value = forward(assets, market)
        except torch._dynamo.exc.TorchDynamoException as exc:
            state.update(state="fallback", error=f"{type(exc).__name__}: {str(exc)[:1000]}")
            emit("compile_fallback", **state)
            forward = model.forward
            value = forward(assets, market)
        if state["state"] == "pending":
            state["state"] = "active"
        return value
    return predict, state


def checkpoint(model, optimizer, spec, scales, seed, **extra):
    device = next(model.parameters()).device
    return {"model": model.state_dict(), "optimizer": optimizer.state_dict(), "spec": asdict(spec),
            "scales": asdict(scales), "seed": seed, "cpu_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state(device) if device.type == "cuda" else None, **extra}


def pretrain(model, predict, loss_fn, data, spec, scales, seed, out, options, *, expired, emit):
    optimizer = optimizer_for(model, options)
    begun, last_save = time.monotonic(), time.monotonic()
    steps, dates, epoch, cursor, order = 0, 0, 0, 0, None
    reason = "epoch_limit"
    model.train()
    last_loss = None
    for epoch in range(options["pretrain_max_epochs"]):
        order = torch.randperm(len(data.rows), device=data.assets.device)
        for cursor in range(0, len(data.rows), options["pretrain_batch_dates"]):
            if expired():
                reason = "global_deadline"
                break
            if time.monotonic() - begun >= options["pretrain_max_seconds_per_fit"]:
                reason = "declared_pretrain_time_limit"
                break
            idx = order[cursor:cursor + options["pretrain_batch_dates"]]
            prediction = predict(data.assets[idx], data.market[idx])["mu20"]
            loss, _, _ = loss_fn(prediction, data.targets["mu20"][idx], data.masks["mu20"][idx], spec.rank_weight)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1, error_if_nonfinite=True)
            optimizer.step()
            steps += 1
            dates += len(idx)
            if steps % 100 == 0:
                last_loss = float(loss.detach())
                emit("pretrain_progress", epoch=epoch, steps=steps, sampled_dates=dates,
                     loss=last_loss, grad_norm=float(norm), seconds=time.monotonic() - begun,
                     dates_per_second=dates / (time.monotonic() - begun),
                     allocated_bytes=torch.cuda.memory_allocated() if data.assets.is_cuda else 0)
            if time.monotonic() - last_save >= 60:
                torch.save(checkpoint(model, optimizer, spec, scales, seed, stage="bootstrap_pretrain",
                    epoch=epoch, next_cursor=cursor + len(idx), permutation=order, steps=steps,
                    sampled_dates=dates), out / "pretrain-last.pt")
                last_save = time.monotonic()
        if reason != "epoch_limit":
            break
    torch.save(checkpoint(model, optimizer, spec, scales, seed, stage="bootstrap_pretrain", epoch=epoch,
        next_cursor=cursor if reason != "epoch_limit" else len(data.rows), permutation=order, steps=steps,
        sampled_dates=dates, stop_reason=reason), out / "pretrain-last.pt")
    receipt = {"stop_reason": reason, "steps": steps, "sampled_dates": dates,
               "unique_augmented_dates": len(data.rows), "new_independent_dates": 0,
               "seconds": time.monotonic() - begun, "last_logged_loss": last_loss}
    (out / "pretraining.json").write_text(json.dumps(receipt, indent=2, allow_nan=False))
    emit("pretrain_finished", **receipt)
    return receipt


def fit_expanded(spec: ExpandedSpec, train, validation, scales, seed, out, options, *, expired, emit,
                 bootstrap=None, inference=None, compile_enabled=True):
    out.mkdir(parents=True, exist_ok=False)
    device = train.assets.device
    torch.manual_seed(seed)
    model = ExpandedPredictor(spec).to(device)
    predict, compilation = compiled_forward(model, emit, enabled=compile_enabled)
    # Fuse pair construction, masked reductions and Huber kernels separately from the forward graph.
    loss_fn = torch.compile(losses, dynamic=True, fullgraph=True) if device.type == "cuda" and compile_enabled else losses
    begun = time.monotonic()
    pt = pretrain(model, predict, loss_fn, bootstrap, spec, scales, seed, out, options,
                  expired=expired, emit=emit) if bootstrap is not None else None
    optimizer = optimizer_for(model, options)  # Independent real-date fine-tuning optimizer.
    best, best_epoch, stale, patience_best = float("inf"), -1, 0, float("inf")
    history, status = [], "complete"
    for epoch in range(options["max_epochs"]):
        if expired():
            status = "budget_stopped"
            break
        t0 = time.monotonic()
        model.train()
        order = torch.randperm(len(train.rows), device=device)
        batch_losses = []
        for first in range(0, len(train.rows), options["batch_dates"]):
            if expired():
                status = "budget_stopped"
                break
            idx = order[first:first + options["batch_dates"]]
            p = predict(train.assets[idx], train.market[idx])["mu20"]
            loss, _, _ = loss_fn(p, train.targets["mu20"][idx], train.masks["mu20"][idx], spec.rank_weight)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1, error_if_nonfinite=True)
            optimizer.step()
            batch_losses.append(loss.detach())
        if status != "complete":
            break
        model.eval()
        with torch.no_grad():
            # Real validation is small and date-balanced; checkpoint criterion identical in all v2 ablations.
            p = predict(validation.assets, validation.market)["mu20"]
            score, huber, ranking = loss_fn(p, validation.targets["mu20"], validation.masks["mu20"], .3)
            score, huber, ranking = float(score), float(huber), float(ranking)
        if not np.isfinite(score):
            raise FloatingPointError("nonfinite validation score")
        improved = score < patience_best - options["early_stopping_min_delta"]
        if improved:
            patience_best = score
        stale = 0 if improved else stale + 1
        if score < best:
            best, best_epoch = score, epoch
            torch.save({"model": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                        "spec": asdict(spec), "scales": asdict(scales), "seed": seed, "epoch": epoch,
                        "validation_score": score}, out / "best.pt")
        rec = {"epoch": epoch, "train_loss": float(torch.stack(batch_losses).mean()),
               "validation_score": score, "validation_mu20_huber": huber,
               "validation_rank_loss": ranking, "best_epoch": best_epoch, "grad_norm": float(norm),
               "seconds": time.monotonic() - t0, "compile_state": compilation["state"]}
        history.append(rec)
        emit("epoch", **rec)
        if epoch % 5 == 0:
            torch.save(checkpoint(model, optimizer, spec, scales, seed, stage="real_finetune", epoch=epoch), out / "last.pt")
        if stale >= options["early_stopping_patience"]:
            break
    torch.save(checkpoint(model, optimizer, spec, scales, seed, stage="real_finetune", epochs_completed=len(history)), out / "last.pt")
    (out / "history.json").write_text(json.dumps(history, indent=2, allow_nan=False))
    result = {"status": status, "epochs": len(history), "best_epoch": best_epoch,
              "validation_score": best if np.isfinite(best) else None, "compilation": compilation,
              "seconds": time.monotonic() - begun, "parameters": spec.parameters, "pretraining": pt}
    if status == "complete":
        model.load_state_dict(torch.load(out / "best.pt", map_location=device, weights_only=True)["model"])
        for name, partition in {"validation": validation, **(inference or {})}.items():
            if expired():
                result["status"] = "budget_stopped"
                break
            pred = inverse_predictions(_prediction(model, predict, partition), scales)
            np.savez_compressed(out / f"{name}.npz", rows=partition.rows, **pred)
    (out / "fit.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    return result
