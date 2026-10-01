"""Generator acceptance report: §7.2 rejection sampling + §7.3 stylized-fact gates.

The P1 acceptance run is 1,000 validation worlds per account (§7.3).  One draw costs a
100-year plausibility simulation (~3 s single-core numpy) plus, if accepted, a
``stylized_years`` simulation, so the acceptance run belongs on the WSL compute node with
``workers`` > 1.  Small ``n_worlds`` runs are diagnostics and are labelled as such.

Draws are independent: worker ``k`` uses ``SeedSequence(seed).spawn()`` entry ``k``, so a
run is reproducible from ``(seed, n_draws)`` regardless of how many workers execute it.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace

import numpy as np

from . import stylized as SF
from .params import sample_world
from .plausibility import DEFAULT_YEARS, SamplingReport, check
from .specs import ACCOUNT_SPECS
from .structural import simulate_world

ACCEPTANCE_WORLDS = 1000
STYLIZED_YEARS = 40.0
DRAW_BUDGET = 2.5  # draws attempted per requested world (≈45% rejection leaves headroom)


class _StylizedBudget:
    """Yield jobs, dropping the stylized simulation once ``limit`` worlds have been checked.

    With several workers the count is approximate (jobs are dispatched before their results
    return), so a few extra stylized simulations may run; the gate statistics use the first
    ``limit`` accepted worlds either way.
    """

    def __init__(self, limit: int, jobs: list["_Job"]):
        self.limit = limit
        self.jobs = jobs
        self.issued = 0

    def __len__(self) -> int:
        return len(self.jobs)

    def __iter__(self):
        for job in self.jobs:
            self.issued += 1
            yield job if self.issued <= self.limit * 2 else replace(job, stylized_years=0.0)


@dataclass(frozen=True)
class _Job:
    account: str
    entropy: tuple[int, ...]
    plausibility_years: float
    stylized_years: float


def _evaluate(job: _Job):
    """One draw: plausibility check, and the stylized checks only if it is accepted.

    Stylized checks are skipped once ``stylized_years`` is 0, which the caller uses to stop
    paying for them after the first ``n_worlds`` acceptances.
    """
    rng = np.random.default_rng(np.random.SeedSequence(job.entropy))
    spec = ACCOUNT_SPECS[job.account]
    params = sample_world(job.account, rng)
    _, fails = check(simulate_world(spec, params, years=job.plausibility_years))
    if fails or job.stylized_years <= 0:
        return params, fails, None
    checks = SF.world_checks(simulate_world(spec, params, years=job.stylized_years).sample())
    return params, [], checks


def calibration_report(
    account: str,
    n_worlds: int,
    seed: int,
    plausibility_years: float = DEFAULT_YEARS,
    stylized_years: float = STYLIZED_YEARS,
    workers: int = 1,
    draw_budget: float = DRAW_BUDGET,
) -> dict[str, object]:
    if account not in ACCOUNT_SPECS:
        raise ValueError(f"unknown account {account!r}")
    n_draws = max(1, int(n_worlds * draw_budget))
    jobs = [_Job(account, (seed, i), plausibility_years, stylized_years) for i in range(n_draws)]

    report = SamplingReport(account)
    checks: list[dict[str, tuple[float, bool]]] = []
    workers = max(1, min(workers, len(jobs)))
    stop_stylized = _StylizedBudget(n_worlds, jobs)
    if workers == 1:
        results = map(_evaluate, stop_stylized)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_evaluate, stop_stylized, chunksize=1))
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
