# Host runbooks

> **状态**：active｜**权威**：L3 host operations reference｜**最后更新**：2026-10-04
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

If Windows can read `E:` but SSH reports `No such device`, compare the mount namespaces: a Windows `wsl.exe` command may use a different namespace from the systemd SSH/training processes. An authorized remount must target the namespace used by training (systemd PID1 via `nsenter --target 1 --mount`), with no active data consumers. Verify the data path and input hashes from a new SSH session before starting a job; a successful read only inside the Windows command does not prove the training mount is usable.

**Rollback**: `ssh qount-win 'Unregister-ScheduledTask -TaskName qount-wsl-keepalive -Confirm:$false'`;
restore `~/.ssh/config.bak-20260930`; set `QOUNT_WSL_HOST=home` only together with reverting the two WSL scripts to the `wsl.exe` transport.

Boundary: WSL remains compute only. No secrets, `.env`, paper/live truth or production state on WSL; this helper never touches the VPS.

## P3 R3 residual readiness and later launch

The owner authorized deployment and preparation while explicitly waiting for a later training instruction. Follow the [standalone R3 reference](../../deploy/wsl/alpha-residual/README.md) and [current authority](../current.md). Use the immutable public bundle in a new WSL ext4 code directory and the existing isolated venv; E holds prepared slots, public source snapshot and numerical verification. `prepare/check/status` do not fit models. A new owner activation bound to the ready/code/data manifests is required by `launch/run` before any fitting or output run directory is created.

The R3 launcher supplies its own detached single-run supervisor and `.pid.json/.supervisor.log/.exit.json`; it needs no waiting tmux task, daemon, cron or keepalive modification. The shared `etf-alpha-cuda.lock` excludes duplicate GPU jobs. Fifty-one pilot fits run first; a failed increment gate exits normally with outer withheld. A passing pilot allows at most272 total registered fits. Signals preserve partial checkpoints and exit; interrupted/failed jobs never retry automatically. Read current readiness with `check` immediately before a future activation; mounted storage, input/source drift or an occupied lock fails closed without host repair or service changes.

Use the [reviewed schema-v2 contract](../../config/etf-alpha-residual-reviewed-20261003.json) and latest ready pointer. Its null controls require at least25-session date displacement, and the joined forecast ledger preserves a prior year's last-close decision through a next-year opening fill. Original proposals, earlier ready directories and their manifests remain immutable. A revised public delivery requires a new prepared root and a freshly verified source/data binding; do not modify an older ready directory in place. [Review rationale](../etf-p3-research-plan-2026-10.md#23-r3开训前复审修正与创新取舍2026-10-03).

For progress, read the current authority and the Mac `state/research_runs/etf_alpha_residual/latest-run.json` pointer, then query `status --path RUN` and the sibling `.exit.json`. The ready pointer and `READY.json` describe immutable preparation, not a trainer's current progress. A completed pilot with `pilot_no_increment/exit_code=0` has consumed its single-run activation; reconnecting or a retained ready directory does not restart it. Preserve completed output manifests and use a separate directory for later reviews. [Result interpretation](../etf-p3-research-plan-2026-10.md#24-r3残差pilot执行与结果2026-10-04).

## Owner-designated P3 RTX3080Ti cloud compute

The owner-designated `jn1f8a7n6z` machine is separate from the stopped3090/P2 host. Current permissions/state are in [current.md](../current.md); cloud computation/sending remains paused. The later WSL training instruction does not resume cloud work. Reconnection does not authorize resumption.

Only the non-secret P3 delivery and immutable public M0/M1 inputs may be sent. Use the [standalone deployment reference](../../deploy/cloud/alpha-3080ti/README.md) and [P3 §20](../etf-p3-research-plan-2026-10.md#20-3080-ti-付费云计算交付与性能策略2026-10-03). Never synchronize a private checkout/.env/SSH keys, or use a legacy cloud launch script.

The data root is `/root/autodl-tmp/qount`, on a verified real data mount. Environment lives in an isolated system-disk venv; compiler caches live in dedicated cloud data-disk paths. GPU visibility must expose exactly the allocated single3080Ti. CPU affinity80 does not override the actual20-core cgroup quota; memory is constrained by the30GiB container, not host128GiB.

The initial independent installer was interrupted when SSH closed during an owner-stop request. On a separately authorized recovery, first read the dedicated install log/owner-stop receipt and inspect only that task's process tree, then verify environment completeness. Do not overwrite a partial venv or automatically restart installation/training. This record does not prove platform shutdown or completed installation.

Completed/failed run manifests and lightweight result archives return to E for permanent retention; Mac retains code deliveries and summaries only. Do not automatically expand/release disks, rent/switch instances, invoke platform account APIs or shutdown; those actions require an explicit owner decision. A finished trainer and an offline SSH endpoint are not proof of billing termination.

## VPS boundary

VPS service environment files are `/etc/qount/*.env`, owned `root:root` with mode `0600`. The repository can statically validate that deployment units reference expected scripts; it must not echo, copy, create, change permissions on, or sync these files. `qount-run config-check --profile vps --env-file /etc/qount/<service>.env` is an operator-run local preflight, not an instruction to access the server from this checkout.

Current runtime truth and enabled-service facts are only in [current.md](../current.md). Read-only probes must never be converted into `systemctl enable`, `start`, deployment sync, order, arm or cron actions. In particular, legacy and production trading timers stay disabled unless a future owner decision explicitly changes `current.md`.

## Personal proxy and SSH entry

The owner's personal-proxy/SSH authorization and current operating facts are recorded in [current.md](../current.md#vps-个人代理与-ssh-恢复2026-10-10) and detailed in [network-proxy-and-anti-ban-guide.md](network-proxy-and-anti-ban-guide.md). This is separate from qount execution authority. Keep proxy UUIDs, residential credentials and private WebSocket paths out of repository files and diagnostic output.

Mac operational files are `~/.config/aliyun-manila-relay/ssh-client.json`, `~/Library/LaunchAgents/com.alyaloale.aliyun-manila-relay.plist` and the `qount-vps` entry in `~/.ssh/config`. Verify actual SSH authentication with `ssh -o BatchMode=yes -o ControlPath=none qount-vps 'uptime'`; a listening SOCKS port alone is insufficient. The private client config is `0600`. It is independent of the main Clash Verge mode/selection and must not fall back silently to Windows or a subscription exit.

Clash Verge client routing uses `mode: rule`, with `Aliyun-Manila-Relay` configured as the persistent overseas fallback selector (`良心云`) and US residential proxy chained for AI services (`AI-美国住宅`). Cloudflare trace domains (`cloudflare.com`, `www.cloudflare.com`) route to the AI residential group so CLI pre-flight checks (e.g. `claude-us`) pass. Local developer proxy environment variables for terminal tools (such as Codex CLI) are sourced via `~/.codex/proxy-env.zsh`.

The server's dedicated unit is `/etc/systemd/system/aliyun-relay.service`, with binary `/opt/aliyun-relay/xray` and root-only config/metadata in `/etc/aliyun-relay/`. Read only bounded health properties for this unit. Caddy's marked `owner-aliyun-relay` insertion wraps the original site handlers; metadata records the inserted prefix/suffix and original hash for targeted rollback. Do not dump the Caddyfile or private metadata, replace the entire Caddy configuration, or remove original authentication. Any future rollback must preserve all unrelated routes and validate the resulting Caddy configuration before reload; it is not authority to restart qount or trading services.

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
