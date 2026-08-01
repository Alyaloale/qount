# Host runbooks

> **状态**：active｜**权威**：L3 host operations reference｜**最后更新**：2026-08-02
> **适用范围**：Mac, Windows external disk, WSL and VPS ownership boundaries.
> **TL;DR**：Mac owns code; Windows external disk owns large data/artifacts; WSL owns compute reruns; VPS owns runtime truth. No host may infer permission to turn on live, arm, orders, timers or production cron.

## Handoff paths

| Host | What it may do | What it must not do | Check |
| --- | --- | --- | --- |
| Mac `/Users/alyaloale/Code/qount` | Code, git, docs, light verification and orchestration | Long-term full data or production execution | `qount-run config-check --profile mac --env-file .env` |
| Windows external disk `E:\qount_data` | Datasets, immutable artifacts, locks and backup manifests | Store `.env`, active SQLite or virtual environments | Verify an artifact manifest with relative path/hash/source/command/retention before copying. |
| WSL `/home/alyaloale/Code/qount` | CPU/GPU reruns and scratch computation | Store secrets or claim paper/live truth | `qount-run config-check --profile wsl --env-file deploy/wsl/qount-compute.env` |
| VPS `/root/qount` | Existing paper/dashboard services and minimum runtime state | Research bulk storage or manual service alteration without owner approval | Static repo checks only in this task; remote inspection is read-only and separately authorized. |

## VPS boundary

VPS service environment files are `/etc/qount/*.env`, owned `root:root` with mode `0600`. The repository can statically validate that deployment units reference expected scripts; it must not echo, copy, create, change permissions on, or sync these files. `qount-run config-check --profile vps --env-file /etc/qount/<service>.env` is an operator-run local preflight, not an instruction to access the server from this checkout.

Current runtime truth and enabled-service facts are only in [current.md](../current.md). Read-only probes must never be converted into `systemctl enable`, `start`, deployment sync, order, arm or cron actions. In particular, legacy and production trading timers stay disabled unless a future owner decision explicitly changes `current.md`.

## Recovery limits

Use the existing package tests and static deployment-reference check before a host-specific change. Recover only an explicitly approved service from its documented release/provenance; do not use an archived script or a historical unit as a recovery shortcut. The present governance batch does not authorize any recovery action.
