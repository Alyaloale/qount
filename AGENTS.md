# qount agent guide

> **Status:** active repository guidance. **Current facts:** [docs/current.md](docs/current.md) is the only current source of truth.

`qount` is a multi-host AI decision, risk/execution, no-order simulation, and research repository. Work must preserve the public CLI (`qount-run`, `qount-monitor`), deployed/unit references and test-imported module paths. Compatibility comes before directory elegance.

## Read first

1. [docs/current.md](docs/current.md) — current operating facts, owner decisions and hard limits.
2. [docs/project-rules.md](docs/project-rules.md) — code/document/research placement rules.
3. [docs/operations/host-runbooks.md](docs/operations/host-runbooks.md) — host authority and recovery boundaries.
4. [docs/reference/configuration.md](docs/reference/configuration.md) and [docs/reference/cli-and-scripts.md](docs/reference/cli-and-scripts.md).
5. The active line's primary document, then [docs/archive/README.md](docs/archive/README.md) only for historical context.

Conflict order is: `docs/current.md` → `docs/project-rules.md` → runbooks/reference → active research document → archive. README, this guide, and research reports are navigation, never a substitute for current facts.

## Safety boundary

- Do not enable, restore, arm, schedule, or invoke live trading, orders, a trading timer, or production cron without an explicit owner decision reflected in `docs/current.md`.
- Do not change external accounts, strategy parameters, service state, or VPS configuration in ordinary repository work. Existing active public-data/paper services are facts to preserve, not authority to alter.
- Do not print, copy, commit, export, rotate, or synchronize credentials. Never put secrets on the Windows external disk or WSL.
- Treat all research and paper outputs as `research_only` / `orders_authorized=false` unless the current fact document says otherwise.
- Never revive a frozen legacy line because a historical script or result appears usable.

## Host responsibilities

| Host | Allowed responsibility | Prohibited boundary |
| --- | --- | --- |
| Mac `/Users/alyaloale/Code/qount` | Main code checkout, git, docs, lightweight verification and orchestration | Long-term bulk data and production execution. |
| Windows external disk `E:\qount_data` | Datasets, immutable artifacts, environment locks and backups | All secrets, active SQLite databases and virtual environments. |
| WSL `/home/alyaloale/Code/qount` | CPU/GPU computation and authoritative reruns | Secrets, live/paper truth or a persistent Mac mirror. |
| VPS `/root/qount` | Existing paper/dashboard runtime truth and minimum audit state | Bulk research storage and unapproved service changes. |

The environment contract is [config/environment-contract.toml](config/environment-contract.toml). Private Mac `.env` files containing secrets must be `0600`; VPS service files are `/etc/qount/*.env`, `root:root 0600`. `deploy/wsl/qount-compute.env` is non-secret topology only and must not be merged with `.env`.

## Code and archive boundaries

- Production control plane: `contracts`, `execution`, `governance`, `ledger`, `risk`, `operations`, `notifications`, `persistence`, `portfolio`, `reporting`, `venue`.
- Active research/no-order simulation: `mini_trend`, `dual_engine`, `small_account`, `alpha_agents`, `research_data`, `research/sleeves`.
- `src/qount/legacy/` and `scripts/archive/` are frozen. No new business logic belongs there.
- `scripts/research/` and `scripts/operations/` are thin adapters only: parse arguments, call testable package functions and write declared artifacts. Production packages must not import research scripts.
- Before moving anything, run a reference audit. `docs/archive/manifest.md` is preservation-first; only an explicitly `approved` entry may enter a later archive move. This batch does not approve any move or deletion.

## Local commands and verification

```bash
set -a
. ./.env  # only after manual trust/permission check
set +a
qount-run config-check --profile mac
qount-run --help
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
```

Use the narrowest owning `unittest` first. For package-structure changes, run:

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
```

Deployment changes receive static systemd/shell reference validation unless separately authorized for VPS work. Do not infer authorization from an SSH alias, a deployed unit template, a private `.env`, or a historical runbook.

## Documentation updates

- A current operating fact change updates `docs/current.md`; it does not get copied into README or this guide.
- A structural/configuration/CLI change updates the appropriate reference/runbook and repository map as needed.
- Research documents state `research_only`, result status, and whether they can affect production (normally: no).
- Archive documents state that they are historical, non-restorable evidence and point to their replacement entry.
- After a meaningful change, record which focused verification ran; never state an unrun test as passed.
