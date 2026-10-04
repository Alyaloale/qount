"""Compatibility entry for the shared bounded-prefetch training runtime.

Saved datasets prefetch disk reads and CUDA transfers only. Existing online-generation
callers remain supported by train(); objective, checkpoints and result schema are shared.
"""

from __future__ import annotations

from pathlib import Path

from .train import TrainConfig, train
from .training_runtime import pin_tensors, transfer_tensors


def _pin_tensors(et):
    return pin_tensors(et)


def _pin_batch(batch):
    return pin_tensors(batch)


def _transfer_to_device(et, device, stream=None):
    return transfer_tensors(et, device, stream)


def _transfer_batch(batch, device, stream=None):
    return transfer_tensors(batch, device, stream)


def train_pipelined(cfg: TrainConfig, out_dir: Path, *, log_every: int = 1,
                   max_minutes: float | None = None, use_compile: bool = True,
                   checkpoint_every: int = 10, world_dataset: Path | None = None) -> dict:
    result = train(cfg, out_dir, log_every=log_every, max_minutes=max_minutes,
                   use_compile=use_compile, checkpoint_every=checkpoint_every, world_dataset=world_dataset)
    result["pipelined"] = True
    return result
