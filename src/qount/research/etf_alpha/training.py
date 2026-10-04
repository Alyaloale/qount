"""Supervised Stage 1 fitting on frozen, date-level partitions; no orders or live state."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from .models import ModelSpec, SharedPredictor
from .training_data import Partition, TargetScales


@dataclass
class TensorPartition:
    rows: np.ndarray
    assets: torch.Tensor
    market: torch.Tensor | None
    targets: dict[str, torch.Tensor]
    masks: dict[str, torch.Tensor]

    @classmethod
    def from_partition(cls, p: Partition, device):
        return cls(p.rows, torch.as_tensor(p.assets, device=device),
                   None if p.market is None else torch.as_tensor(p.market, device=device),
                   {k: torch.as_tensor(np.nan_to_num(v, nan=0), device=device) for k, v in p.targets.items()},
                   {k: torch.as_tensor(v, device=device) for k, v in p.masks.items()})


def date_mean(loss, mask):
    counts = mask.sum(-1)
    return ((loss * mask).sum(-1) / counts.clamp_min(1))[counts > 0].mean()


def objective(pred, targets, masks, scales: TargetScales):
    returns = [date_mean(F.huber_loss(pred[k], targets[k], reduction="none"), masks[k])
               for k in ("mu5", "mu20", "mu60") if k in pred]
    loss = torch.stack(returns).mean()
    if "p_up" in pred:
        loss = loss + .2 * date_mean(F.binary_cross_entropy_with_logits(pred["p_up"], targets["p_up"],
                                                                       reduction="none"), masks["p_up"])
    if "q10" in pred:
        error = targets["q10"] - pred["q10"]
        loss = loss + .5 * date_mean(torch.maximum(.1 * error, -.9 * error), masks["q10"])
    if "sigma20" in pred:
        stats = scales.stats["sigma20"]
        sigma = (torch.log(F.softplus(pred["sigma20"]) + 1e-6) - stats["mean"]) / stats["std"]
        loss = loss + .2 * date_mean(F.huber_loss(sigma, targets["sigma20"], reduction="none"), masks["sigma20"])
    return loss


def _prediction(model, forward, part: TensorPartition, *, batch=256):
    model.eval()
    outputs = {h: [] for h in model.spec.heads}
    with torch.no_grad():
        for start in range(0, len(part.rows), batch):
            idx = slice(start, start + batch)
            pred = forward(part.assets[idx], None if part.market is None else part.market[idx])
            for name in outputs:
                outputs[name].append(pred[name].detach().cpu().numpy().copy())
    return {k: np.concatenate(v) for k, v in outputs.items()}


def inverse_predictions(pred, scales):
    result = {}
    for k, value in pred.items():
        if k == "p_up":
            result[k] = 1 / (1 + np.exp(-np.clip(value, -80, 80)))
        elif k == "sigma20":
            result[k] = np.logaddexp(0, value) + 1e-6
        else:
            result[k] = scales.inverse(k, value)
    return result


def fit(spec: ModelSpec, train: TensorPartition, validation: TensorPartition, scales: TargetScales,
        seed: int, out: Path, options: dict, *, expired, emit, compile_mode="reduce-overhead",
        inference: dict[str, TensorPartition] | None = None) -> dict:
    """One declared fit. A deadline saves a partial receipt, never an eligible final model."""
    out.mkdir(parents=True, exist_ok=False)
    device = train.assets.device
    torch.manual_seed(seed)
    model = SharedPredictor(spec).to(device)
    model.initialize_head_biases(scales.initial_biases)
    matrices, vectors = [], []
    for p in model.parameters():
        (matrices if p.ndim >= 2 else vectors).append(p)
    optimizer = torch.optim.AdamW(
        [{"params": matrices, "weight_decay": options["matrix_weight_decay"]},
         {"params": vectors, "weight_decay": 0}], lr=options["learning_rate"],
        betas=tuple(options["betas"]), eps=options["epsilon"], fused=device.type == "cuda")
    forward = model.forward
    compile_status = {"state": "disabled", "mode": compile_mode, "error": None}
    if device.type == "cuda" and compile_mode is not None:
        forward = torch.compile(model.forward, mode=compile_mode, dynamic=True, fullgraph=False)
        compile_status["state"] = "pending"
    def predict(assets, market):
        nonlocal forward
        if device.type == "cuda":
            torch.compiler.cudagraph_mark_step_begin()
        try:
            output = forward(assets, market)
        except torch._dynamo.exc.TorchDynamoException as exc:
            compile_status.update(state="fallback", error=f"{type(exc).__name__}: {str(exc)[:1000]}")
            emit("compile_fallback", error=compile_status["error"])
            forward = model.forward
            output = forward(assets, market)
        if compile_status["state"] == "pending":
            compile_status["state"] = "active"
        return output

    start = time.perf_counter()
    best, patience_best, stale, history, best_epoch = float("inf"), float("inf"), 0, [], -1
    maximum = options["max_epochs"]
    status = "complete"
    for epoch in range(maximum):
        if expired():
            status = "budget_stopped"
            break
        t0 = time.perf_counter()
        model.train()
        permutation = torch.randperm(len(train.rows), device=device)
        losses, norms = [], []
        for first in range(0, len(train.rows), options["batch_dates"]):
            if expired():
                status = "budget_stopped"
                break
            idx = permutation[first:first + options["batch_dates"]]
            pred = predict(train.assets[idx], None if train.market is None else train.market[idx])
            loss = objective(pred, {k: train.targets[k][idx] for k in spec.heads},
                             {k: train.masks[k][idx] for k in spec.heads}, scales)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), options["gradient_clip_norm"],
                                                  error_if_nonfinite=True)
            optimizer.step()
            losses.append(loss.detach())
            norms.append(norm.detach())
        if status == "budget_stopped":
            break
        model.eval()
        # Equal date weighting, including the final partial batch.
        vals = []
        with torch.no_grad():
            for first in range(0, len(validation.rows), 256):
                idx = slice(first, first + 256)
                pred = predict(validation.assets[idx], None if validation.market is None else validation.market[idx])
                mask = validation.masks["mu20"][idx]
                loss = F.huber_loss(pred["mu20"], validation.targets["mu20"][idx], reduction="none")
                vals.append(((loss * mask).sum(-1) / mask.sum(-1).clamp_min(1)))
        val = float(torch.cat(vals).mean())
        if not np.isfinite(val):
            raise FloatingPointError("nonfinite validation loss")
        # Save any lower score; patience improvement uses the separately frozen delta.
        improvement = val < patience_best - options["early_stopping_min_delta"]
        if improvement:
            patience_best = val
        if val < best:
            best, best_epoch = val, epoch
            torch.save({"model": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                        "spec": asdict(spec), "scales": asdict(scales), "seed": seed, "epoch": epoch,
                        "validation_mu20_huber": val}, out / "best.pt")
        stale = 0 if improvement else stale + 1
        rec = {"epoch": epoch, "train_loss": float(torch.stack(losses).mean()), "validation_mu20_huber": val,
               "grad_norm": float(torch.stack(norms).mean()), "best_epoch": best_epoch,
               "seconds": time.perf_counter() - t0, "dates_per_second": len(train.rows) / (time.perf_counter() - t0),
               "compile_state": compile_status["state"], "elapsed_seconds": time.perf_counter() - start,
               "allocated_bytes": torch.cuda.memory_allocated(device) if device.type == "cuda" else 0}
        history.append(rec)
        emit("epoch", **rec)
        if epoch % 5 == 0:
            torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(), "epoch": epoch,
                        "spec": asdict(spec), "scales": asdict(scales), "seed": seed,
                        "cpu_rng": torch.get_rng_state(),
                        "cuda_rng": torch.cuda.get_rng_state(device) if device.type == "cuda" else None}, out / "last.pt")
        if stale >= options["early_stopping_patience"]:
            break
    torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(), "spec": asdict(spec),
                "scales": asdict(scales), "seed": seed, "epochs_completed": len(history),
                "cpu_rng": torch.get_rng_state(),
                "cuda_rng": torch.cuda.get_rng_state(device) if device.type == "cuda" else None}, out / "last.pt")
    (out / "history.json").write_text(json.dumps(history, indent=2))
    result = {"status": status, "epochs": len(history), "best_epoch": best_epoch,
              "validation_mu20_huber": best if np.isfinite(best) else None, "compilation": compile_status,
              "seconds": time.perf_counter() - start, "parameters": spec.parameters}
    if status == "complete":
        model.load_state_dict(torch.load(out / "best.pt", map_location=device, weights_only=True)["model"])
        pred = inverse_predictions(_prediction(model, predict, validation), scales)
        np.savez_compressed(out / "validation.npz", rows=validation.rows, **pred)
        for name, partition in (inference or {}).items():
            if not name.replace("_", "").isalnum():
                raise ValueError("safe inference artifact name required")
            if expired():
                result["status"] = "budget_stopped"
                break
            pred = inverse_predictions(_prediction(model, predict, partition), scales)
            np.savez_compressed(out / f"{name}.npz", rows=partition.rows, **pred)
    (out / "fit.json").write_text(json.dumps(result, indent=2))
    return result
