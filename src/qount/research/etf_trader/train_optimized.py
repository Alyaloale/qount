"""P2 training: OPTIMIZED VERSION with all Phase 1+2 fixes.

Changes from original train.py:
- P0-3: dd_target relaxed 0.15 → 0.20
- P1-5: Dual variable upper bounds (MAX_LAMBDA)
- P1-8: Resource monitoring thread
- P2-8: Enhanced episode logging (g_dd, g_cvar, turnover)
- P2-11: Complete random seed management
- Display memory fraction setting for multi-process safety

research_only=true / orders_authorized=false / trial=false.
"""

from __future__ import annotations

import json
import math
import threading
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch

from . import constraints as C
from .costs import RANDOMIZATION_RANGE, cost_params_for
from .features import WorldFeatures, world_features
from .generator.params import sample_world
from .generator.plausibility import check
from .generator.specs import ACCOUNT_SPECS
from .generator.structural import simulate_world
from .policy import PolicyConfig, Trader, construct, kl_to_prior, n_params
from .torch_env import Batch, TorchEnv
from .universe import ACCOUNTS, Account

SPLITS = {"train": 0, "val": 1, "test": 2}

# P1-5: Dual variable upper bounds
MAX_LAMBDA_DD = 50.0
MAX_LAMBDA_CVAR = 50.0


@dataclass(frozen=True)
class TrainConfig:
    account: str = "us"
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    lr: float = 3e-4
    batch_worlds: int = 256
    episodes: int = 600
    years: float = 8.0
    warmup_years: float = 10.0
    segment: int = 252
    grad_clip: float = 1.0
    dd_target: float = 0.20  # P0-3: relaxed from 0.15 to 0.20
    cvar_floor: float = -0.10
    lambda_kl: float = 0.01
    dual_lr: float = 0.5
    turnover_soft_start: float = 0.9
    lambda_turnover: float = 1.0
    seed: int = 20260930
    workers: int = 8
    device: str = "cuda"
    plausibility_years: float = 100.0
    compile_mode: str = "reduce-overhead"


# ---------------------------------------------------------------------------
# World pipeline (CPU workers)


@dataclass
class WorldArrays:
    close_adj: np.ndarray
    close: np.ndarray
    open: np.ndarray
    adv: np.ndarray
    sigma: np.ndarray
    cash_return: np.ndarray
    spread: np.ndarray
    buy_blocked: np.ndarray
    features: WorldFeatures
    spread_mult: float
    impact_mult: float
    params_seed: int


def world_seed(root: int, split: str, index: int) -> np.random.SeedSequence:
    return np.random.SeedSequence((root, SPLITS[split], index))


def generate_world(account: str, root: int, split: str, index: int, years: float, warmup_years: float,
                   plausibility_years: float = 100.0, max_draws: int = 50) -> WorldArrays:
    """Draw accepted (§7.2) parameters, simulate, compute features; return trading rows only."""
    rng = np.random.default_rng(world_seed(root, split, index))
    spec, acct = ACCOUNT_SPECS[account], ACCOUNTS[account]
    for _ in range(max_draws):
        params = sample_world(account, rng)
        if plausibility_years <= 0 or not check(simulate_world(spec, params, years=plausibility_years))[1]:
            break
    else:
        raise RuntimeError(f"no plausible world in {max_draws} draws ({split}/{index})")
    w = simulate_world(spec, params, years=years, warmup_years=warmup_years)
    d = w.data
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        f = world_features(d.close_adj, acct, w.valuation, d.adv, d.spread)
    s = w.start
    lo, hi = RANDOMIZATION_RANGE
    return WorldArrays(
        close_adj=d.close_adj[s:], close=d.close[s:], open=d.open[s:], adv=d.adv[s:], sigma=d.sigma[s:],
        cash_return=d.cash_return[s:], spread=d.spread[s:], buy_blocked=d.buy_blocked[s:], features=f.sliced(s),
        spread_mult=float(rng.uniform(lo, hi)), impact_mult=float(rng.uniform(lo, hi)), params_seed=params.seed,
    )


def _gen(args):
    return generate_world(*args)


@dataclass
class EpisodeTensors:
    batch: Batch
    static: torch.Tensor
    eligible: torch.Tensor
    market: torch.Tensor
    sigma_c: torch.Tensor
    tradable: torch.Tensor
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
        target = construct(ep.static[:, t, :, :4], ep.sigma_c[:, t], ep.eligible[:, t], act, account)
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


# P2-11: Complete random seed management
def set_all_seeds(seed: int):
    """Set all random sources for reproducibility."""
    import random
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)
    # Enable deterministic mode (slight performance cost)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


# P1-8: Resource monitoring
def monitor_resources(interval: int, stop_event: threading.Event):
    """Background thread to monitor GPU/CPU/Memory usage."""
    try:
        import psutil
    except ImportError:
        print("[Monitor] psutil not available, skipping resource monitoring", flush=True)
        return

    while not stop_event.is_set():
        try:
            if torch.cuda.is_available():
                gpu_mem = torch.cuda.memory_allocated() / 1e9
                gpu_total = torch.cuda.get_device_properties(0).total_memory / 1e9
                print(f"[Monitor] GPU Memory: {gpu_mem:.2f}/{gpu_total:.2f} GB ({gpu_mem/gpu_total*100:.1f}%)",
                      flush=True)

            cpu_pct = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            print(f"[Monitor] CPU: {cpu_pct:.1f}%, RAM: {mem.percent:.1f}%", flush=True)
        except Exception as e:
            print(f"[Monitor] Error: {e}", flush=True)

        time.sleep(interval)


# ---------------------------------------------------------------------------
# Training


def train(cfg: TrainConfig, out_dir: Path, *, log_every: int = 1, max_minutes: float | None = None,
          use_compile: bool = True, checkpoint_every: int = 10, parallel: int = 1) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device(cfg.device if torch.cuda.is_available() or cfg.device == "cpu" else "cpu")

    # P2-11: Set all random seeds
    set_all_seeds(cfg.seed)

    # P0-2: Memory management for multi-process safety
    if device.type == "cuda" and parallel > 1:
        fraction = 0.95 / parallel
        torch.cuda.set_per_process_memory_fraction(fraction)
        print(f"[Memory] Set per-process memory fraction: {fraction:.2%} ({parallel} parallel)", flush=True)

    acct = ACCOUNTS[cfg.account]
    model = Trader(cfg.policy).to(device)

    # torch.compile
    compile_mode = getattr(cfg, 'compile_mode', 'reduce-overhead')
    if use_compile and device.type == "cuda":
        try:
            if compile_mode == 'max-autotune':
                model = torch.compile(model, mode='max-autotune', fullgraph=False)
            elif compile_mode == 'default':
                model = torch.compile(model, mode='default', fullgraph=False)
            else:
                model = torch.compile(model, mode='reduce-overhead', fullgraph=False)
            compiled = True
            print(f"torch.compile enabled with mode={compile_mode}", flush=True)
        except Exception as e:
            print(f"Warning: torch.compile failed ({e}), falling back to eager mode", flush=True)
            compiled = False
    else:
        compiled = False

    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr)
    costs = cost_params_for(acct)
    lam = {"dd": 0.0, "cvar": 0.0}
    hist: list[dict] = []
    t_start = time.time()
    meta = {"config": asdict(cfg), "n_params": n_params(model), "device": str(device),
            "compiled": compiled, "research_only": True, "orders_authorized": False, "trial": False,
            "optimized": True, "dd_target": cfg.dd_target}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))

    # P1-8: Start resource monitoring thread
    stop_monitor = threading.Event()
    monitor_thread = threading.Thread(target=monitor_resources, args=(60, stop_monitor), daemon=True)
    monitor_thread.start()

    def jobs(ep):
        base = ep * cfg.batch_worlds
        return [(cfg.account, cfg.seed, "train", base + i, cfg.years, cfg.warmup_years, cfg.plausibility_years)
                for i in range(cfg.batch_worlds)]

    with ProcessPoolExecutor(max_workers=cfg.workers) as pool:
        pending = [pool.submit(_gen, j) for j in jobs(0)]
        update = 0
        for ep in range(cfg.episodes):
            t_ep_start = time.time()
            worlds = [f.result() for f in pending]
            t_gen = time.time() - t_ep_start
            if ep + 1 < cfg.episodes:
                pending = [pool.submit(_gen, j) for j in jobs(ep + 1)]
            t_tensor_start = time.time()
            et = to_tensors(worlds, device)
            t_tensor = time.time() - t_tensor_start
            t_env_start = time.time()
            env = TorchEnv(et.batch, acct, costs, exact=False, spread_mult=et.spread_mult, impact_mult=et.impact_mult)
            t_env = time.time() - t_env_start
            h = model.initial_state(env.B, device=device)
            peak = torch.ones(env.B, device=device)
            ep_dd = torch.zeros(env.B, device=device)
            e0 = env.equity.detach().clone()
            seg_stats = []
            t_rollout_start = time.time()
            while env.t < env.T - 1:
                out, h = run_segment(env, model, et, h, cfg.segment, acct)
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
                gn = torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
                opt.step()
                update += 1

                # P1-5: Dual variable updates with upper bounds
                lam["dd"] = float(np.clip(lam["dd"] + cfg.dual_lr * float(g_dd.detach()), 0.0, MAX_LAMBDA_DD))
                lam["cvar"] = float(np.clip(lam["cvar"] + cfg.dual_lr * float(g_cv.detach()), 0.0, MAX_LAMBDA_CVAR))

                # P1-5: Warning if approaching limits
                if lam["dd"] >= MAX_LAMBDA_DD * 0.9:
                    print(f"[WARNING] lambda_dd approaching limit: {lam['dd']:.2f}/{MAX_LAMBDA_DD}", flush=True)
                if lam["cvar"] >= MAX_LAMBDA_CVAR * 0.9:
                    print(f"[WARNING] lambda_cvar approaching limit: {lam['cvar']:.2f}/{MAX_LAMBDA_CVAR}", flush=True)

                peak = run_peak[:, -1].detach()
                ep_dd = torch.maximum(ep_dd, dd.detach())
                h = h.detach()
                env.detach_()

                # P2-8: Enhanced segment stats
                seg_stats.append({
                    "logr": float(logr.mean()),
                    "kl": float(kl),
                    "g_dd": float(g_dd),
                    "g_cvar": float(g_cv),
                    "grad_norm": float(gn),
                    "turnover_pen": float(to_pen),
                    "turnover": float(out["used"].mean()),
                })

            t_rollout = time.time() - t_rollout_start
            years = (env.t) / 252.0
            t_ep_total = time.time() - t_ep_start

            # P2-8: Enhanced episode logging
            rec = {
                "episode": ep,
                "updates": update,
                "seconds": round(t_ep_total, 2),
                "time_gen": round(t_gen, 2),
                "time_tensor": round(t_tensor, 2),
                "time_env": round(t_env, 2),
                "time_rollout": round(t_rollout, 2),
                "ann_log_return": float(np.mean([s["logr"] for s in seg_stats])),
                "p95_max_dd": float(torch.quantile(ep_dd, 0.95)),
                "lambda_dd": lam["dd"],
                "lambda_cvar": lam["cvar"],
                "g_dd": float(np.mean([s["g_dd"] for s in seg_stats])),
                "g_cvar": float(np.mean([s["g_cvar"] for s in seg_stats])),
                "kl": float(np.mean([s["kl"] for s in seg_stats])),
                "mean_turnover": float(np.mean([s["turnover"] for s in seg_stats])),
                "turnover_penalty": float(np.mean([s["turnover_pen"] for s in seg_stats])),
                "years": years,
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

            if max_minutes is not None and (time.time() - t_start) / 60 > max_minutes:
                break

    # Stop monitoring
    stop_monitor.set()
    monitor_thread.join(timeout=2.0)

    torch.save({"model": model.state_dict(), "config": asdict(cfg), "lambda": lam}, out_dir / "model.pt")
    (out_dir / "history.json").write_text(json.dumps(hist, indent=2))
    return {"meta": meta, "history": hist, "lambda": lam}
