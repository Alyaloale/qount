"""GPU engineering calibration on synthetic tensors, without market selection."""
from __future__ import annotations

import time

from .artifacts import GUARDS


def amortized_choice(records, expected_steps):
    usable = [r for r in records if r.get("status") == "complete" and r.get("parity_passed") is True]
    if not usable:
        raise ValueError("no numerically qualified runtime candidate")
    return min(usable, key=lambda r: r["startup_seconds"] + r["seconds_per_step"] * expected_steps)["compiled"]


def candidate(*, compiled, bootstrap, steps=50):
    import torch
    from .expanded_models import ExpandedPredictor, ExpandedSpec
    from .expanded_training import losses, optimizer_for
    torch.set_num_threads(2)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.manual_seed(20261003)
    batch = 4096 if bootstrap else 64
    assets = torch.randn(batch, 9, 84, device="cuda")
    market = torch.randn(batch, 17, device="cuda")
    target = torch.randn(batch, 9, device="cuda")
    mask = torch.rand(batch, 9, device="cuda") > .1
    # Reserve the real fold's resident input allocation when calibrating pretraining.
    resident = torch.empty(4_047_298_560, dtype=torch.uint8, device="cuda") if bootstrap else None
    model = ExpandedPredictor(ExpandedSpec(identity=True, rank_weight=.3)).cuda()
    model.eval()
    eager = model(assets, market)["mu20"]
    reference = losses(eager, target, mask, .3)[0]
    reference.backward()
    gradients = [p.grad.detach().clone() for p in model.parameters()]
    model.zero_grad(set_to_none=True)
    forward = torch.compile(model.forward, mode="default", dynamic=True) if compiled else model.forward
    loss_fn = torch.compile(losses, dynamic=True, fullgraph=True) if compiled else losses
    torch.cuda.synchronize()
    begun = time.perf_counter()
    actual = forward(assets, market)["mu20"]
    loss = loss_fn(actual, target, mask, .3)[0]
    loss.backward()
    torch.cuda.synchronize()
    startup = time.perf_counter() - begun
    torch.testing.assert_close(actual, eager, rtol=1e-4, atol=5e-6)
    torch.testing.assert_close(loss, reference, rtol=1e-4, atol=5e-6)
    for parameter, expected in zip(model.parameters(), gradients):
        torch.testing.assert_close(parameter.grad, expected, rtol=2e-4, atol=5e-6)
    optimizer = optimizer_for(model, {"learning_rate": .0003, "matrix_weight_decay": .001})
    model.train()
    def step():
        optimizer.zero_grad(set_to_none=True)
        prediction = forward(assets, market)["mu20"]
        value = loss_fn(prediction, target, mask, .3)[0]
        value.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1, error_if_nonfinite=True)
        optimizer.step()
    begun = time.perf_counter()
    for _ in range(5):
        step()
    torch.cuda.synchronize()
    startup += time.perf_counter() - begun
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    begun = time.perf_counter()
    for _ in range(steps):
        step()
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - begun
    with torch.no_grad():
        if not all(torch.isfinite(p).all().item() for p in model.parameters()):
            raise FloatingPointError("calibration optimizer produced nonfinite weights")
    return GUARDS | {"status": "complete", "compiled": compiled, "bootstrap": bootstrap,
        "batch_dates": batch, "parity_passed": True, "startup_seconds": startup,
        "seconds_per_step": elapsed / steps, "dates_per_second": batch * steps / elapsed,
        "measured_steps": steps, "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "resident_reserve_bytes": 0 if resident is None else resident.numel(),
        "market_inputs_used": False, "precision": "float32_highest_no_amp_no_tf32"}
