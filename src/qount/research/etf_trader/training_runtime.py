"""Batched training runtime: bounded disk prefetch, CUDA transfer and policy compilation.

The raw Trader owns parameters and checkpoint keys. Compiled callables are disposable;
compilation is reported successful only after a forward call actually succeeds.
"""

from __future__ import annotations

import multiprocessing as mp
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

import torch

from .policy import construct
from .torch_env import fill_cost
from .worlds import WorldDataset, _gen, cpu_workers, init_cpu_worker

COMPILE_MODES = ("default", "reduce-overhead", "max-autotune", "max-autotune-no-cudagraphs")


def map_tensors(value, fn):
    if isinstance(value, torch.Tensor):
        return fn(value)
    if is_dataclass(value):
        return replace(value, **{f.name: map_tensors(getattr(value, f.name), fn) for f in fields(value)})
    return value


def pin_tensors(ep):
    return map_tensors(ep, lambda t: t.pin_memory())


def transfer_tensors(ep, device, stream=None):
    device = torch.device(device)
    if device.type != "cuda":
        return map_tensors(ep, lambda t: t.to(device))
    if stream is None:
        return map_tensors(ep, lambda t: t.to(device, non_blocking=True))
    with torch.cuda.stream(stream):
        result = map_tensors(ep, lambda t: t.to(device, non_blocking=True))
    consumer = torch.cuda.current_stream(device)
    consumer.wait_stream(stream)
    # Allocations made on the copy stream stay alive until the consumer finishes.
    map_tensors(result, lambda t: t.record_stream(consumer))
    return result


def load_training_dataset(cfg, path: Path) -> WorldDataset:
    dataset = WorldDataset(path)
    dc = dataset.cfg
    if dc.account != cfg.account or dc.split != "train":
        raise ValueError("training requires a train-split dataset for the same account")
    if (dc.years, dc.warmup_years, dc.plausibility_years) != (cfg.years, cfg.warmup_years, cfg.plausibility_years):
        raise ValueError("dataset durations/plausibility differ from the training config")
    if dc.worlds < cfg.episodes * cfg.batch_worlds:
        raise ValueError("dataset has too few worlds; implicit reuse/regeneration is disabled")
    return dataset


def episode_tensors(cfg, device, to_tensors, dataset: WorldDataset | None = None):
    """At most one next episode is prefetched. Exceptions propagate through futures."""
    device = torch.device(device)
    stream = torch.cuda.Stream(device=device) if device.type == "cuda" else None

    def prepare(ep):
        t0 = time.perf_counter()
        worlds = dataset.batch(ep * cfg.batch_worlds, cfg.batch_worlds)
        loaded = time.perf_counter() - t0
        t0 = time.perf_counter()
        cpu = to_tensors(worlds, "cpu")
        if device.type == "cuda":
            cpu = pin_tensors(cpu)
        return cpu, {"time_gen": 0.0, "time_load": loaded, "time_tensor": time.perf_counter() - t0}

    if dataset is not None:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="world-dataset") as loader:
            pending = loader.submit(prepare, 0)
            try:
                for ep in range(cfg.episodes):
                    cpu, timing = pending.result()
                    if ep + 1 < cfg.episodes:
                        pending = loader.submit(prepare, ep + 1)
                    t0 = time.perf_counter()
                    tensors = transfer_tensors(cpu, device, stream)
                    timing["time_transfer_enqueue"] = time.perf_counter() - t0
                    yield tensors, timing  # retain the pinned source while the GPU consumes it
            finally:
                pending.cancel()
        return

    # Compatibility path for existing callers. Spawn never inherits a CUDA context.
    from .generator import native
    native.available()  # warm the C++ cache once in the parent

    def jobs(ep):
        base = ep * cfg.batch_worlds
        return [(cfg.account, cfg.seed, "train", base + i, cfg.years, cfg.warmup_years, cfg.plausibility_years)
                for i in range(cfg.batch_worlds)]

    pool = ProcessPoolExecutor(max_workers=cpu_workers(cfg.workers), mp_context=mp.get_context("spawn"),
                               initializer=init_cpu_worker)
    pending = [pool.submit(_gen, j) for j in jobs(0)]
    try:
        for ep in range(cfg.episodes):
            t0 = time.perf_counter()
            worlds = [f.result() for f in pending]
            generated = time.perf_counter() - t0
            if ep + 1 < cfg.episodes:
                pending = [pool.submit(_gen, j) for j in jobs(ep + 1)]
            t0 = time.perf_counter()
            cpu = to_tensors(worlds, "cpu")
            if device.type == "cuda":
                cpu = pin_tensors(cpu)
            stacked = time.perf_counter() - t0
            t0 = time.perf_counter()
            tensors = transfer_tensors(cpu, device, stream)
            yield tensors, {"time_gen": generated, "time_load": 0.0, "time_tensor": stacked,
                            "time_transfer_enqueue": time.perf_counter() - t0}
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)


class PolicyRunner:
    """Compile forward without wrapping the module or changing its state_dict schema."""

    def __init__(self, model, *, enabled: bool, mode: str):
        if mode not in COMPILE_MODES:
            raise ValueError(f"unknown compile mode: {mode}")
        self.model = model
        # BPTT keeps forward tensors alive across recurrent calls. CUDA Graph output
        # reuse is unsafe here; do not use reduce-overhead's graph capture.
        effective = {"reduce-overhead": "default", "max-autotune": "max-autotune-no-cudagraphs"}.get(mode, mode)
        self.status = {"requested": enabled, "requested_mode": mode, "effective_mode": effective,
                       "cudagraphs": False, "state": "disabled", "error": None}
        self.kernels = {}
        self.forward = model.forward
        if enabled:
            from torch._dynamo.exc import TorchDynamoException
            self.compiler_errors = (TorchDynamoException,)
            try:
                self.forward = torch.compile(model.forward, mode=effective, fullgraph=False, dynamic=False)
                self.status["state"] = "pending"
            except self.compiler_errors as exc:
                self._fallback(exc)
        for name, function in (("construction", construct), ("cost", fill_cost)):
            status = {"state": "disabled", "error": None}
            compiled = function
            if enabled:
                try:
                    compiled = torch.compile(function, mode=effective, fullgraph=True, dynamic=False)
                    status["state"] = "pending"
                except self.compiler_errors as exc:
                    status.update(state="fallback", error=f"{type(exc).__name__}: {str(exc)[:1000]}")
            self.kernels[name] = [function, compiled, status]
            self.status[name] = status

    def _kernel(self, name, *args):
        eager, compiled, status = self.kernels[name]
        if status["state"] in ("pending", "active"):
            try:
                result = compiled(*args)
            except self.compiler_errors as exc:
                status.update(state="fallback", error=f"{type(exc).__name__}: {str(exc)[:1000]}")
                warnings.warn(f"{name} compilation failed; using eager kernel", RuntimeWarning, stacklevel=2)
                return eager(*args)
            status["state"] = "active"
            return result
        return eager(*args)

    def construct(self, *args):
        return self._kernel("construction", *args)

    def cost(self, *args):
        return self._kernel("cost", *args)

    def _fallback(self, exc):
        self.forward = self.model.forward
        self.status.update(state="fallback", error=f"{type(exc).__name__}: {str(exc)[:1000]}")
        warnings.warn("policy compilation failed; using eager forward", RuntimeWarning, stacklevel=2)

    def __call__(self, *args):
        if self.status["state"] in ("pending", "active"):
            try:
                result = self.forward(*args)
            except self.compiler_errors as exc:
                self._fallback(exc)
                return self.forward(*args)
            self.status["state"] = "active"
            return result
        return self.forward(*args)

    @property
    def log_prior(self):
        return self.model.log_prior
