"""Generator acceptance report: §7.2 rejection sampling + §7.3 stylized-fact gates.

The P1 acceptance run is 1,000 validation worlds per account (§7.3).  One draw costs a
100-year plausibility simulation (~3 s single-core numpy) plus, if accepted, a
``stylized_years`` simulation, so the acceptance run belongs on the WSL compute node with
``workers`` > 1.  Small ``n_worlds`` runs are diagnostics and are labelled as such.
With the native kernel (``backend="auto"``) a 100-year draw costs ~0.05 s, so the run is
bounded by worker count, not by the day loop.

CN autocorrelation is scored against the calibrated 2005–2014 index targets
(``targets.py``, :data:`DEFAULT_TARGETS`); the 5-year dividend-yield R² stays undecided until
the P0 Shiller target exists.

Draws are independent: worker ``k`` uses ``SeedSequence(seed).spawn()`` entry ``k``, so a
run is reproducible from ``(seed, n_draws)`` regardless of how many workers execute it.
"""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import stylized as SF
from .params import sample_world
from .plausibility import DEFAULT_YEARS, SamplingReport, check
from .specs import ACCOUNT_SPECS
from .structural import simulate_world
from .targets import CalibrationTargets

DEFAULT_TARGETS = {"cn": Path(__file__).with_name("data") / "cn_targets.json"}

ACCEPTANCE_WORLDS = 1000
STYLIZED_YEARS = 40.0
DRAW_BUDGET = 2.5  # draws attempted per requested world (≈45% rejection leaves headroom)


@dataclass(frozen=True)
class _Job:
    account: str
    entropy: tuple[int, ...]
    plausibility_years: float
    stylized_years: float
    backend: str = "auto"
    targets_json: str | None = None


def _evaluate(job: _Job):
    """One draw: plausibility check, and the stylized checks only if it is accepted.

    With the native kernel a stylized world costs ~0.03 s, so every accepted draw is scored
    and the gates use the first ``n_worlds`` in draw order (deterministic for any worker count).
    """
    rng = np.random.default_rng(np.random.SeedSequence(job.entropy))
    spec = ACCOUNT_SPECS[job.account]
    params = sample_world(job.account, rng)
    _, fails = check(simulate_world(spec, params, years=job.plausibility_years, backend=job.backend))
    if fails or job.stylized_years <= 0:
        return params, fails, None
    targets = _targets(job.targets_json)
    world = simulate_world(spec, params, years=job.stylized_years, backend=job.backend)
    return params, [], SF.world_checks(world.sample(), targets)


_TARGET_CACHE: dict[str, CalibrationTargets] = {}


def _targets(text: str | None) -> CalibrationTargets | None:
    if text is None:
        return None
    if text not in _TARGET_CACHE:
        _TARGET_CACHE[text] = CalibrationTargets.from_json(text)
    return _TARGET_CACHE[text]


def load_targets(account: str, path: Path | None = None) -> str | None:
    """Targets JSON for ``account`` (explicit path, else the committed default, else None)."""
    path = path or DEFAULT_TARGETS.get(account)
    if path is None:
        return None
    text = Path(path).read_text()
    if CalibrationTargets.from_json(text).account != account:
        raise ValueError(f"targets in {path} are not for account {account!r}")
    return text


def calibration_report(
    account: str,
    n_worlds: int,
    seed: int,
    plausibility_years: float = DEFAULT_YEARS,
    stylized_years: float = STYLIZED_YEARS,
    workers: int = 1,
    draw_budget: float = DRAW_BUDGET,
    backend: str = "auto",
    targets_path: Path | None = None,
) -> dict[str, object]:
    if account not in ACCOUNT_SPECS:
        raise ValueError(f"unknown account {account!r}")
    targets_json = load_targets(account, targets_path)
    if backend != "numpy":
        from . import native

        backend = "native" if native.available() else ("numpy" if backend == "auto" else backend)
        if backend == "native":
            native.load()  # build once in the parent so workers find the cached library
    n_draws = max(1, int(n_worlds * draw_budget))
    jobs = [_Job(account, (seed, i), plausibility_years, stylized_years, backend, targets_json)
            for i in range(n_draws)]

    report = SamplingReport(account)
    checks: list[dict[str, tuple[float, bool]]] = []
    workers = max(1, min(workers, len(jobs)))
    if workers == 1:
        results = map(_evaluate, jobs)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_evaluate, jobs, chunksize=4))
    for params, fails, world_checks in results:
        report.draws += 1
        if fails:
            for f in fails:
                report.fail_counts[f] = report.fail_counts.get(f, 0) + 1
        else:
            report.accepted.append(params)
            if world_checks is not None:
                checks.append(world_checks)

    gates = SF.gate_pass_rate(checks[:n_worlds])
    decidable = {k: v for k, v in gates.items() if not v.get("needs_calibration")}
    return {
        "account": account,
        "seed": seed,
        "n_worlds_requested": n_worlds,
        "n_worlds_accepted": len(report.accepted),
        "n_worlds_stylized": len(checks[:n_worlds]),
        "draw_budget": n_draws,
        "workers": workers,
        "backend": backend,
        "targets_sha256": hashlib.sha256(targets_json.encode()).hexdigest() if targets_json else None,
        "plausibility_years": plausibility_years,
        "stylized_years": stylized_years,
        "acceptance_run": len(report.accepted) >= ACCEPTANCE_WORLDS,
        "plausibility": report.summary(),
        "stylized": gates,
        "stylized_passed": bool(decidable) and all(v["passed"] for v in decidable.values()),
        "stylized_failed": sorted(k for k, v in decidable.items() if not v["passed"]),
        "stylized_undecided": sorted(k for k, v in gates.items() if v.get("needs_calibration")),
        "cpu_count": os.cpu_count(),
        "research_only": True,
        "orders_authorized": False,
        "trial": False,
    }
