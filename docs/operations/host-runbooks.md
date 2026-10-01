# Host runbooks

> **状态**：active｜**权威**：L3 host operations reference｜**最后更新**：2026-09-30
> **适用范围**：Mac, Windows external disk, WSL and VPS ownership boundaries.
> **TL;DR**：Mac owns code; Windows external disk owns large data/artifacts; WSL owns compute reruns; VPS owns runtime truth. No host may infer permission to turn on live, arm, orders, timers or production cron.

## Handoff paths

| Host | What it may do | What it must not do | Check |
| --- | --- | --- | --- |
| Mac `/Users/alyaloale/Code/qount` | Code, git, docs, light verification and orchestration | Long-term full data or production execution | `qount-run config-check --profile mac --env-file .env` |
| Windows external disk `E:\qount_data` | Datasets, immutable artifacts, locks and backup manifests | Store `.env`, active SQLite or virtual environments | Verify an artifact manifest with relative path/hash/source/command/retention before copying. |
| WSL `/home/alyaloale/Code/qount` | CPU/GPU reruns and scratch computation | Store secrets or claim paper/live truth | `scripts/hosts/qount-wsl.sh status`, then `qount-run config-check --profile wsl --env-file deploy/wsl/qount-compute.env` |
| VPS `/root/qount` | Existing paper/dashboard services and minimum runtime state | Research bulk storage or manual service alteration without owner approval | Static repo checks only in this task; remote inspection is read-only and separately authorized. |

## WSL compute: connection entry (canonical)

This is the single entry point for reaching the WSL compute node from the Mac. Other docs link here.

**Quick use**

```bash
scripts/hosts/qount-wsl.sh status   # read-only: Tailscale, WSL SSH, GPU, external disk, tmux, keepalive task
scripts/hosts/qount-wsl.sh          # ensure + interactive shell (same as `shell`)
scripts/hosts/qount-wsl.sh shell -- 'cd ~/Code/qount && nvidia-smi'
ssh qount-wsl                       # plain alias once `ensure` has passed
scripts/sync-to-wsl.sh              # explicit code sync (only when compute code changes)
scripts/run-wsl-tests.sh tests.test_x
```

**Path**: Mac Tailscale → WSL's own Tailscale node `100.105.105.56` → socket-activated `sshd` inside WSL (user `alyaloale`,
key `~/.ssh/id_ed25519_remote`). It no longer goes through Windows `wsl.exe`, so PowerShell quoting does not apply.
Windows is reached as `qount-win` (`100.86.117.34`, user `15470`, default shell PowerShell 7) only to wake WSL.

| Component | Where | Setting |
| --- | --- | --- |
| SSH aliases | Mac `~/.ssh/config` | `qount-wsl` (ControlMaster, `~/.ssh/cm/`, persist 10m), `qount-win`. Existing `home` / `wsl-vscode` kept. Pre-change backup `~/.ssh/config.bak-20260930`. |
| Keep WSL running | Windows scheduled task `qount-wsl-keepalive` | At logon, runs `wsl.exe -d Ubuntu -u root --exec /bin/sleep infinity`; no time limit, restarts 3×. Without it Windows stops the VM when the last `wsl.exe` exits. |
| sshd | WSL `ssh.socket` enabled (systemd=true in `/etc/wsl.conf`) | Password auth unchanged; pubkey from the Mac is in `authorized_keys`. |
| Self-heal | `scripts/hosts/qount-wsl.sh ensure` | Starts Mac Tailscale (keeps `--accept-routes`), drops a stale ControlMaster, wakes WSL via `qount-win` when the node is offline. |

**Failure signatures (observed 2026-09-30)**

| Symptom | Cause | Fix (automated by `ensure`) |
| --- | --- | --- |
| `kex_exchange_identification: Connection closed` right after TCP connect | Mac Tailscale stopped; `100.x` is routed into the proxy TUN (`utun1024`, 198.18.0.1) which accepts TCP then resets | `tailscale up --accept-routes` |
| `Operation timed out`; `tailscale status` shows WSL node `offline` | WSL VM stopped by Windows | `Start-ScheduledTask qount-wsl-keepalive` on `qount-win` |
| Hang with no output after a network change | Stale ControlMaster socket | `ssh -O exit qount-wsl` |

Measured: warm reconnect 0.03 s; first connect 0.4 s; recovery from a fully stopped WSL ≈ 20 s.
Enable "Launch Tailscale at login" in the Mac Tailscale app so the first case rarely occurs.

**Long jobs**: run them in `tmux` inside WSL (`ssh qount-wsl`, then `tmux new -s JOB`). Sessions survive SSH disconnects
while the keepalive task runs; verified 2026-09-30. The older `screen … ssh home wsl.exe …` pattern in
[storage-topology.md](../storage-topology.md#长任务) is only needed if the keepalive task is removed.

**External disk**: `/mnt/e/qount_data/qount` must exist before any data job. `status` prints `external_disk=missing`
when `E:` is not attached to Windows; jobs must fail closed rather than write elsewhere.

**Rollback**: `ssh qount-win 'Unregister-ScheduledTask -TaskName qount-wsl-keepalive -Confirm:$false'`;
restore `~/.ssh/config.bak-20260930`; set `QOUNT_WSL_HOST=home` only together with reverting the two WSL scripts to the `wsl.exe` transport.

Boundary: WSL remains compute only. No secrets, `.env`, paper/live truth or production state on WSL; this helper never touches the VPS.

## VPS boundary

VPS service environment files are `/etc/qount/*.env`, owned `root:root` with mode `0600`. The repository can statically validate that deployment units reference expected scripts; it must not echo, copy, create, change permissions on, or sync these files. `qount-run config-check --profile vps --env-file /etc/qount/<service>.env` is an operator-run local preflight, not an instruction to access the server from this checkout.

Current runtime truth and enabled-service facts are only in [current.md](../current.md). Read-only probes must never be converted into `systemctl enable`, `start`, deployment sync, order, arm or cron actions. In particular, legacy and production trading timers stay disabled unless a future owner decision explicitly changes `current.md`.

## Recovery limits

Use the existing package tests and static deployment-reference check before a host-specific change. Recover only an explicitly approved service from its documented release/provenance; do not use an archived script or a historical unit as a recovery shortcut. The present governance batch does not authorize any recovery action.

## SSH unavailable: bounded inspection

If public SSH and the cloud provider's private-network SSH both time out before authentication,
use the provider's VNC/serial console. A reachable TCP port alone does not prove that SSH is healthy.
At `login:`, enter the Linux username; enter the password only after `Password:` appears.
Do not copy login URLs, private keys, session credentials or passwords into diagnostics.

Start with these bounded, read-only commands inside the instance:

```bash
uptime
free -m
df -h /
systemctl is-active ssh sshd
journalctl -k -b -p err -n 15 --no-pager
```

Inspect only the relevant service and a bounded journal slice next. Avoid loading the entire boot
journal into Python: collector messages can contain large JSON payloads. Do not dump collector
metadata wholesale; select counters, heartbeat timestamps and guard booleans, omitting recent event IDs.
Likewise, summarize paper performance without printing full NAV histories or rebalance arrays.

The operations health probe preserves a blocking provenance failure while distinguishing fixed codes
for missing/unreadable files, invalid JSON/schema, manifest hash failures and source-tree mismatch.
An older deployed probe may report only `release_provenance_unavailable`; that does not establish
which of these conditions occurred. Verify the base manifest and documented overlay evidence before
repairing a release; regenerating a manifest from an unexplained current tree is not validation.
