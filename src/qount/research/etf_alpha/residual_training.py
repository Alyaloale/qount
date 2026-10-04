"""R3 fitting, callable only after a verified explicit owner start receipt."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from .artifacts import write_json
from .residual_models import ResidualPredictor


def residual_loss(pred,target,mask):
    counts = mask.sum(-1)
    if not torch.all(counts>0):
        raise ValueError("each date requires observed residual targets")
    values = F.huber_loss(pred,target,reduction="none")
    return ((values*mask).sum(-1)/counts).mean()


def predict(model,assets):
    model.eval()
    with torch.inference_mode():
        result = np.concatenate([model(assets[i:i+256]).cpu().numpy().copy() for i in range(0,len(assets),256)])
    if not np.isfinite(result).all():
        raise FloatingPointError("nonfinite residual predictions")
    return result


def numerical_probe(device="cuda"):
    """Forward/backward readiness probe; zero optimizer steps and no saved model."""
    torch.manual_seed(20261003)
    model = ResidualPredictor().to(device).eval()
    original = {k:v.detach().clone() for k,v in model.state_dict().items()}
    x = torch.linspace(-1,1,64*8*8,device=device).reshape(64,8,8)
    target = torch.zeros((64,8),device=device)
    loss = residual_loss(model(x),target,torch.ones_like(target,dtype=torch.bool))
    loss.backward()
    finite = bool(torch.isfinite(loss)) and all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters())
    unchanged = all(torch.equal(original[k],v) for k,v in model.state_dict().items())
    if not finite or not unchanged:
        raise FloatingPointError("finite gradients with unchanged weights required")
    result = {"finite_forward_and_gradients":True,"parameters":161,"optimizer_steps":0,
              "weights_unchanged":True,"device":str(device),"loss":float(loss.detach())}
    del model,x,target,loss
    if str(device).startswith("cuda"):
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
    return result


def fit(train_x,train_y,train_mask,checkpoint_x,checkpoint_y,checkpoint_mask,evaluation_x,
        *,seed,out:Path,options,expired,emit,permit=None,fixed_epochs=None):
    if not permit or permit.get("verified_explicit_start") is not True:
        raise PermissionError("residual model fitting requires the later owner training instruction")
    if fixed_epochs is not None and not 1<=fixed_epochs<=options["max_epochs"]:
        raise ValueError("fixed outer epoch count outside the frozen past-inner schedule")
    out.mkdir(parents=True,exist_ok=False)
    torch.manual_seed(seed)
    model = ResidualPredictor().to(train_x.device)
    matrices,vectors = [],[]
    for parameter in model.parameters():
        (matrices if parameter.ndim>=2 else vectors).append(parameter)
    optimizer = torch.optim.AdamW([{"params":matrices,"weight_decay":options["matrix_weight_decay"]},
        {"params":vectors,"weight_decay":0.}],lr=options["learning_rate"],betas=(.9,.999),eps=1e-8,
        fused=train_x.device.type=="cuda")
    best,patience_best,stale,best_epoch = float("inf"),float("inf"),0,-1
    history,status = [],"complete"
    begun = time.monotonic()
    maximum = fixed_epochs if fixed_epochs is not None else options["max_epochs"]

    def snapshot(epoch):
        return {"model":{k:v.detach().cpu().clone() for k,v in model.state_dict().items()},
                "architecture":"8-16-1-GELU-dropout0.1","parameters":161,"seed":seed,"epoch":epoch,
                "fixed_outer_epochs":fixed_epochs,"targets":"centered_market_asset_residual"}

    for epoch in range(maximum):
        if expired():
            status = "owner_or_signal_stopped"
            break
        model.train()
        order = torch.randperm(len(train_x),device=train_x.device)
        losses = []
        for first in range(0,len(order),options["batch_dates"]):
            if expired():
                status = "owner_or_signal_stopped"
                break
            idx = order[first:first+options["batch_dates"]]
            loss = residual_loss(model(train_x[idx]),train_y[idx],train_mask[idx])
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("nonfinite residual training loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True)
            optimizer.step()
            losses.append(loss.detach())
        if status != "complete":
            break
        validation = None
        model.eval()
        if fixed_epochs is None:
            values = []
            with torch.inference_mode():
                for first in range(0,len(checkpoint_x),256):
                    idx = slice(first,first+256)
                    per_asset = F.huber_loss(model(checkpoint_x[idx]),checkpoint_y[idx],reduction="none")
                    mask = checkpoint_mask[idx]
                    values.append((per_asset*mask).sum(-1)/mask.sum(-1).clamp_min(1))
            validation = float(torch.cat(values).mean())
            if not np.isfinite(validation):
                raise FloatingPointError("nonfinite preceding-year checkpoint loss")
            if validation<best:
                best,best_epoch = validation,epoch
                torch.save(snapshot(epoch),out/"best.pt")
            improvement = validation<patience_best-options["early_stopping_min_delta"]
            if improvement:
                patience_best = validation
            stale = 0 if improvement else stale+1
        else:
            best_epoch = epoch
        record = {"epoch":epoch,"train_huber":float(torch.stack(losses).mean()),"checkpoint_huber":validation,
                  "best_epoch":best_epoch,"elapsed_seconds":time.monotonic()-begun}
        history.append(record)
        emit("epoch",**record)
        if fixed_epochs is None and stale>=options["early_stopping_patience"]:
            break
    torch.save(snapshot(len(history)-1)|{"optimizer":optimizer.state_dict(),"epochs_completed":len(history)},out/"last.pt")
    write_json(out/"history.json",history)
    if status == "complete" and len(history) != maximum and fixed_epochs is not None:
        raise RuntimeError("outer fixed epochs were not completed")
    if status == "complete":
        if fixed_epochs is not None:
            torch.save(snapshot(best_epoch),out/"best.pt")
        else:
            model.load_state_dict(torch.load(out/"best.pt",map_location=train_x.device,weights_only=True)["model"],strict=True)
        prediction = predict(model,evaluation_x)
        np.savez_compressed(out/"evaluation-prediction.npz",standardized_residual=prediction)
    receipt = {"status":status,"parameters":161,"epochs":len(history),"best_epoch":best_epoch,
               "checkpoint_huber":best if np.isfinite(best) else None,"fixed_outer_epochs":fixed_epochs,
               "outer_labels_used":False,"seconds":time.monotonic()-begun}
    write_json(out/"fit.json",receipt)
    return receipt
