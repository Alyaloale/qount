"""P2 training: world pipeline, rollout and the constrained objective (design §3.3, §4).

``max E[Σ log(1+r)] − λ_kl·E[KL(α‖prior)]  s.t.  P95(max DD) ≤ D,  CVaR5%(annual log r) ≥ C``

λ_dd and λ_cvar are dual variables (projected dual ascent per segment); only λ_kl is a
fixed coefficient (to be set by the §4 null-world calibration).  Truncated BPTT over
252-day segments, hidden and env state carried across segments, Adam, grad-norm clip 1.0.
Constraint surrogates per segment: tail mean of the worst 5% segment drawdowns (≥ the P95)
and of the worst 5% segment log returns (one segment ≈ one year).

Worlds come only from the structural generator (no real data, no trial).  Train / val /
test seeds are disjoint ``SeedSequence`` branches.  research_only=true / orders_authorized=false.
"""

from __future__ import annotations

import json
import math
import time
from contextlib import closing
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch

from . import constraints as C
from .costs import cost_params_for
from .policy import PolicyConfig, Trader, construct, kl_to_prior, n_params
from .torch_env import Batch, TorchEnv
from .training_runtime import COMPILE_MODES, PolicyRunner, episode_tensors, load_training_dataset
from .universe import ACCOUNTS, Account
from .worlds import SPLITS, WorldArrays, _gen, generate_world, world_seed


@dataclass(frozen=True)
class TrainConfig:
    account: str = "us"
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    lr: float = 3e-4
    batch_worlds: int = 256
    episodes: int = 600  # × 8 segments ≈ 4,800 updates (§3.4: 3,000–5,000)
    years: float = 8.0
    warmup_years: float = 10.0
    segment: int = 252
    grad_clip: float = 1.0
    dd_target: float = 0.15  # §12.2 suggestion; owner to confirm
    cvar_floor: float = -0.10  # placeholder until the owner sets C_floor (§4)
    lambda_kl: float = 0.01  # placeholder until the §4 null-world calibration
    dual_lr: float = 0.5
    turnover_soft_start: float = 0.9  # soft penalty on used/U above this
    lambda_turnover: float = 1.0
    seed: int = 20260930
    workers: int = 8
    device: str = "cuda"
    plausibility_years: float = 100.0
    compile_mode: str = "default"  # recurrent BPTT uses compilation without CUDA Graph output reuse


# ---------------------------------------------------------------------------
# WorldArrays/generate_world remain re-exported for existing imports.


@dataclass
class EpisodeTensors:
    batch: Batch
    static: torch.Tensor  # (B, T, n, 8)
    eligible: torch.Tensor  # (B, T, n) bool
    market: torch.Tensor  # (B, T, 6)
    sigma_c: torch.Tensor  # (B, T, n) construction σ
    tradable: torch.Tensor  # (B, T, n)
    spread_mult: torch.Tensor
    impact_mult: torch.Tensor


def to_tensors(worlds: list[WorldArrays], device, dtype=torch.float32) -> EpisodeTensors:
    def st(get, dt=dtype):
        return torch.as_tensor(np.stack([get(w) for w in worlds]), dtype=dt, device=device)

    T = min(w.close.shape[0] for w in worlds)
    cut = lambda a: a[:T]  # noqa: E731
    batch = Batch(
        close_adj=st(lambda w: cut(w.close_adj)), close=st(lambda w: cut(w.close)), open=st(lambda w: cut(w.open)),
        adv=st(lambda w: cut(w.adv)), sigma=st(lambda w: cut(w.sigma)), cash_return=st(lambda w: cut(w.cash_return)),
        spread=st(lambda w: cut(w.spread)), reduce_only=st(lambda w: cut(w.features.reduce_only), torch.bool),
        buy_blocked=st(lambda w: cut(w.buy_blocked), torch.bool),
        suspended=torch.zeros((len(worlds), T, worlds[0].close.shape[1]), dtype=torch.bool, device=device),
    )
    return EpisodeTensors(
        batch=batch,
        static=st(lambda w: cut(w.features.asset)),
        eligible=st(lambda w: cut(w.features.eligible), torch.bool),
        market=st(lambda w: cut(w.features.market)),
        sigma_c=st(lambda w: cut(w.features.sigma)),
        tradable=st(lambda w: cut(w.features.tradable)),
        spread_mult=st(lambda w: w.spread_mult),
        impact_mult=st(lambda w: w.impact_mult),
    )


# ---------------------------------------------------------------------------
# Rollout


def policy_inputs(env: TorchEnv, ep: EpisodeTensors, obs, account: Account):
    t = obs.t
    w = obs.weights.to(ep.static.dtype)
    eq = obs.equity.to(ep.static.dtype)
    adv_cap = torch.log1p(C.MAX_ADV_FRACTION * torch.nan_to_num(ep.batch.adv[:, t], nan=0.0).clamp_min(0) / eq[:, None])
    asset = torch.cat([ep.static[:, t], w[..., None], (account.single_cap - w)[..., None],
                       ep.tradable[:, t, :, None], adv_cap[..., None]], dim=-1)
    U = env.U
    dd = torch.nan_to_num(obs.drawdown.to(w.dtype))
    used = obs.used_voluntary.to(w.dtype) / U
    acc = torch.stack([used, 1.0 - used, dd, env.d1 - dd, env.d2 - dd, obs.derisked.to(w.dtype)], dim=-1)
    return asset, ep.market[:, t], acc


def run_segment(env: TorchEnv, model: Trader, ep: EpisodeTensors, h: torch.Tensor, days: int, account: Account):
    """Advance ``days`` (or to the end); returns per-day stacked outputs, KL and the new state."""
    rets, kls, used, eqs = [], [], [], []
    for _ in range(days):
        if env.t >= env.T - 1:
            break
        obs = env.observe()
        asset, market, acc = policy_inputs(env, ep, obs, account)
        act, h = model(asset, market, acc, h)
        t = obs.t
        weights = model.construct if isinstance(model, PolicyRunner) else construct
        target = weights(ep.static[:, t, :, :4], ep.sigma_c[:, t], ep.eligible[:, t], act, account)
        out = env.step(target.to(env.dtype), act.band.to(env.dtype), act.kappa.to(env.dtype))
        rets.append(out["ret"])
        eqs.append(out["equity"])
        kls.append(kl_to_prior(act.alpha, model.log_prior))
        used.append(env.used_voluntary / env.U)
    if not rets:
        return None, h
    return {"ret": torch.stack(rets, 1), "equity": torch.stack(eqs, 1), "kl": torch.stack(kls, 1),
            "used": torch.stack(used, 1)}, h


def tail_mean(x: torch.Tensor, q: float, largest: bool) -> torch.Tensor:
    k = max(1, int(math.ceil(q * x.numel())))
    return torch.topk(x, k, largest=largest).values.mean()


# ---------------------------------------------------------------------------
# Training


def train(cfg: TrainConfig, out_dir: Path, *, log_every: int = 1, max_minutes: float | None = None,
          use_compile: bool = True, checkpoint_every: int = 10, world_dataset: Path | None = None) -> dict:
    if min(cfg.episodes, cfg.batch_worlds, cfg.segment, log_every, checkpoint_every) < 1:
        raise ValueError("episodes, batch size, segment and logging/checkpoint intervals must be positive")
    if cfg.compile_mode not in COMPILE_MODES:
        raise ValueError("unknown compile mode")
    dataset = load_training_dataset(cfg, world_dataset) if world_dataset is not None else None
    if dataset is not None and str(cfg.device).startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable; use device=cpu explicitly for fixture verification")
    if dataset is not None and out_dir.exists():
        raise FileExistsError("saved-dataset training requires a new output directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device(cfg.device if torch.cuda.is_available() or cfg.device == "cpu" else "cpu")
    torch.manual_seed(cfg.seed)
    acct = ACCOUNTS[cfg.account]
    model = Trader(cfg.policy).to(device)

    runner = PolicyRunner(model, enabled=use_compile and device.type == "cuda", mode=cfg.compile_mode)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr, fused=device.type == "cuda")
    costs = cost_params_for(acct)
    lam = {"dd": 0.0, "cvar": 0.0}
    hist: list[dict] = []
    t_start = time.time()
    meta = {"config": asdict(cfg), "n_params": n_params(model), "device": str(device),
            "compiled": False, "compilation": runner.status, "research_only": True, "orders_authorized": False, "trial": False}
    meta["world_source"] = "saved_dataset" if dataset is not None else "online_generator"
    if dataset is not None:
        meta["dataset"] = {"path": str(dataset.root), "manifest_sha256": dataset.manifest_sha256,
                           "contract_sha256": dataset.manifest["contract_sha256"],
                           "seed": dataset.cfg.seed, "start_index": dataset.cfg.start_index,
                           "worlds_used": cfg.episodes * cfg.batch_worlds}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))

    with closing(episode_tensors(cfg, device, to_tensors, dataset)) as batches:
        update = 0
        t_ep_start = time.time()
        for ep, (et, timing) in enumerate(batches):
            t_env_start = time.time()
            env = TorchEnv(et.batch, acct, costs, exact=False, spread_mult=et.spread_mult, impact_mult=et.impact_mult)
            env.cost_fn = runner.cost
            t_env = time.time() - t_env_start
            h = model.initial_state(env.B, device=device)
            peak = torch.ones(env.B, device=device)  # running peak relative to initial equity
            ep_dd = torch.zeros(env.B, device=device)
            e0 = env.equity.detach().clone()
            seg_stats = []
            t_rollout_start = time.time()
            while env.t < env.T - 1:
                out, h = run_segment(env, runner, et, h, cfg.segment, acct)
                if out is None:
                    break
                logr = torch.log1p(out["ret"].clamp_min(-0.999)).sum(dim=1)
                rel = out["equity"] / e0[:, None]
                run_peak = torch.maximum(torch.cummax(rel, dim=1).values, peak[:, None])
                dd = (1.0 - rel / run_peak).amax(dim=1)
                g_dd = tail_mean(dd, 0.05, largest=True) - cfg.dd_target
                g_cv = cfg.cvar_floor - tail_mean(logr, 0.05, largest=False)
                to_pen = torch.relu(out["used"] - cfg.turnover_soft_start).pow(2).mean()
                kl = out["kl"].mean()
                loss = (-logr.mean() + cfg.lambda_kl * kl + lam["dd"] * g_dd + lam["cvar"] * g_cv
                        + cfg.lambda_turnover * to_pen)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                gn = torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip, error_if_nonfinite=True)
                opt.step()
                update += 1
                lam["dd"] = max(0.0, lam["dd"] + cfg.dual_lr * float(g_dd.detach()))
                lam["cvar"] = max(0.0, lam["cvar"] + cfg.dual_lr * float(g_cv.detach()))
                peak = run_peak[:, -1].detach()
                ep_dd = torch.maximum(ep_dd, dd.detach())
                h = h.detach()
                env.detach_()
                seg_stats.append({"logr": float(logr.detach().mean()), "kl": float(kl.detach()),
                                  "g_dd": float(g_dd.detach()), "g_cvar": float(g_cv.detach()),
                                  "grad_norm": float(gn.detach()), "turnover_pen": float(to_pen.detach())})
            t_rollout = time.time() - t_rollout_start
            years = (env.t) / 252.0
            t_ep_total = time.time() - t_ep_start
            rec = {
                "episode": ep, "updates": update, "seconds": round(t_ep_total, 2),
                **{k: round(v, 4) for k, v in timing.items()},
                "time_env": round(t_env, 2), "time_rollout": round(t_rollout, 2),
                "ann_log_return": float(np.mean([s["logr"] for s in seg_stats])),
                "p95_max_dd": float(torch.quantile(ep_dd, 0.95)), "lambda_dd": lam["dd"], "lambda_cvar": lam["cvar"],
                "kl": float(np.mean([s["kl"] for s in seg_stats])), "years": years,
                "grad_norm": float(np.mean([s["grad_norm"] for s in seg_stats])),
            }
            hist.append(rec)
            if ep % log_every == 0:
                print(json.dumps(rec), flush=True)

            # Checkpoint every N episodes
            if ep > 0 and ep % checkpoint_every == 0:
                checkpoint_path = out_dir / f"checkpoint_ep{ep}.pt"
                torch.save({"model": model.state_dict(), "config": asdict(cfg), "lambda": lam, "episode": ep},
                          checkpoint_path)
                (out_dir / f"history_ep{ep}.json").write_text(json.dumps(hist, indent=2))

            meta["compiled"] = runner.status["state"] == "active"
            if max_minutes is not None and (time.time() - t_start) / 60 > max_minutes:
                break
            t_ep_start = time.time()
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    torch.save({"model": model.state_dict(), "config": asdict(cfg), "lambda": lam}, out_dir / "model.pt")
    (out_dir / "history.json").write_text(json.dumps(hist, indent=2))
    return {"meta": meta, "history": hist, "lambda": lam}
