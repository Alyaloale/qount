#!/usr/bin/env bash
# Reliable Mac -> WSL compute connection (research/compute only).
#
# Path: Mac Tailscale -> WSL Tailscale node -> sshd inside WSL (socket-activated).
# The Windows logon task "qount-wsl-keepalive" keeps the WSL VM running so sshd
# and tmux sessions survive after SSH disconnects.
#
# Self-heals the three failures seen on 2026-09-30:
#   1. Mac Tailscale stopped -> 100.x traffic falls into the proxy TUN and is reset.
#   2. WSL VM stopped by Windows -> Tailscale node offline.
#   3. Stale ControlMaster socket after a network change -> hangs.
#
# Never reads, prints or copies credentials. Does not touch VPS or production hosts.
set -euo pipefail

WSL_SSH="${QOUNT_WSL_HOST:-qount-wsl}"
WIN_SSH="${QOUNT_WIN_HOST:-qount-win}"
TASK_NAME="qount-wsl-keepalive"

usage() {
  cat <<'EOF'
Usage: scripts/hosts/qount-wsl.sh [status|ensure|shell] [-- REMOTE_COMMAND...]
  status   Report Tailscale, WSL reachability, keepalive task and GPU (read-only).
  ensure   Start local Tailscale / wake WSL as needed; exit 0 when SSH works.
  shell    ensure, then open an SSH session (default). Extra args after -- run remotely.
EOF
}

log() { printf '[qount-wsl] %s\n' "$*" >&2; }

tailscale_bin() {
  if command -v tailscale >/dev/null 2>&1; then
    command -v tailscale
  elif [[ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
    printf '%s\n' /Applications/Tailscale.app/Contents/MacOS/Tailscale
  else
    return 1
  fi
}

wsl_ip() { ssh -G "$WSL_SSH" 2>/dev/null | awk '/^hostname /{print $2; exit}'; }
win_ip() { ssh -G "$WIN_SSH" 2>/dev/null | awk '/^hostname /{print $2; exit}'; }

# `exit 0` is valid in both bash (WSL) and PowerShell (Windows default shell).
ssh_probe() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$1" 'exit 0' >/dev/null 2>&1
}

drop_stale_master() {
  if ssh -O check "$WSL_SSH" >/dev/null 2>&1 && ! ssh_probe "$WSL_SSH"; then
    ssh -O exit "$WSL_SSH" >/dev/null 2>&1 || true
  fi
}

ensure_tailscale() {
  local ts
  ts="$(tailscale_bin)" || { log "tailscale CLI not found"; return 1; }
  if "$ts" status >/dev/null 2>&1; then
    return 0
  fi
  log "local Tailscale is stopped; starting it"
  local args=(up --timeout=30s)
  # Preserve the existing accept-routes preference; `tailscale up` refuses to
  # silently drop non-default settings.
  if "$ts" debug prefs 2>/dev/null | grep -q '"RouteAll": true'; then
    args+=(--accept-routes)
  fi
  "$ts" "${args[@]}" >/dev/null
}

wait_peer() {
  local ts ip="$1" i
  ts="$(tailscale_bin)" || return 1
  for i in 1 2 3 4 5 6; do
    if "$ts" ping -c 1 --timeout=5s "$ip" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wake_wsl() {
  log "WSL unreachable; waking it through $WIN_SSH"
  wait_peer "$(win_ip)" || { log "Windows host is offline on Tailscale"; return 1; }
  # Windows default shell is PowerShell. Start the keepalive task; fall back to
  # a one-shot boot if the task has not been registered on this machine.
  ssh -o BatchMode=yes "$WIN_SSH" \
    "Start-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue; if (-not \$?) { wsl.exe -d Ubuntu --exec /bin/true }" \
    >/dev/null 2>&1 || true
}

peer_offline() {
  local ts
  ts="$(tailscale_bin)" || return 1
  "$ts" status 2>/dev/null | awk -v ip="$1" '$1==ip' | grep -q offline
}

ensure() {
  ensure_tailscale
  drop_stale_master
  if ssh_probe "$WSL_SSH"; then
    return 0
  fi
  # A node Tailscale already marks offline is a stopped WSL VM: wake immediately.
  if peer_offline "$(wsl_ip)" || ! wait_peer "$(wsl_ip)"; then
    wake_wsl
    wait_peer "$(wsl_ip)" || { log "WSL Tailscale node did not come online"; return 1; }
  fi
  local i
  for i in 1 2 3 4 5; do
    if ssh_probe "$WSL_SSH"; then
      return 0
    fi
    sleep 3
  done
  log "WSL Tailscale node is online but sshd did not answer"
  return 1
}

status() {
  local ts
  ts="$(tailscale_bin)" || true
  if [[ -n "${ts:-}" ]] && "$ts" status >/dev/null 2>&1; then
    printf 'tailscale_local=running\n'
    "$ts" status | awk -v w="$(wsl_ip)" -v h="$(win_ip)" '$1==w{print "wsl_node=" $0} $1==h{print "win_node=" $0}'
  else
    printf 'tailscale_local=stopped\n'
  fi
  if ssh_probe "$WSL_SSH"; then
    printf 'wsl_ssh=ok\n'
    ssh -o BatchMode=yes "$WSL_SSH" \
      '/usr/lib/wsl/lib/nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null | sed "s/^/gpu=/"; test -d /mnt/e/qount_data/qount && echo external_disk=mounted || echo external_disk=missing; tmux ls 2>/dev/null | sed "s/^/tmux=/" || true'
  else
    printf 'wsl_ssh=unreachable\n'
  fi
  if ssh_probe "$WIN_SSH"; then
    printf 'keepalive_task=%s\n' "$(ssh -o BatchMode=yes "$WIN_SSH" "(Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue).State" 2>/dev/null | tr -d '\r' | tail -1)"
  else
    printf 'win_ssh=unreachable\n'
  fi
}

cmd="${1:-shell}"
case "$cmd" in
  -h|--help) usage ;;
  status) status ;;
  ensure) ensure ;;
  shell|--)
    [[ "$cmd" == shell ]] && shift || true
    [[ "${1:-}" == "--" ]] && shift
    ensure
    exec ssh "$WSL_SSH" "$@"
    ;;
  *) usage >&2; exit 2 ;;
esac
