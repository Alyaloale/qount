#!/usr/bin/env bash
set -euo pipefail

EXTERNAL_ROOT="${QOUNT_EXTERNAL_DATA_ROOT:-/mnt/e/qount_data/qount}"
SCRATCH_ROOT="${QOUNT_WSL_SCRATCH_ROOT:-/home/alyaloale/.cache/qount-compute}"
PROJECT_ROOT="${QOUNT_WSL_PROJECT_ROOT:-/home/alyaloale/Code/qount}"
COMPUTE_STATE_ROOT="$SCRATCH_ROOT/state"
STATE_LINK="$PROJECT_ROOT/state"
MARKER="$SCRATCH_ROOT/.qount-compute-scratch"

usage() {
  printf '%s\n' "Usage: scripts/storage/wsl_compute_storage.sh <check|init|clean-scratch|status>"
}

require_wsl() {
  if ! grep -qi microsoft /proc/sys/kernel/osrelease; then
    printf '%s\n' "This command must run inside WSL." >&2
    exit 1
  fi
}

check_external() {
  local mount_target
  mount_target="$(findmnt -T "$EXTERNAL_ROOT" -n -o TARGET 2>/dev/null || true)"
  if [[ "$mount_target" != "/mnt/e" ]]; then
    printf '%s\n' "External data root is not on the expected E: mount: $EXTERNAL_ROOT" >&2
    exit 1
  fi
  if [[ ! -d "$EXTERNAL_ROOT" || ! -w "$EXTERNAL_ROOT" ]]; then
    printf '%s\n' "External data root is missing or not writable: $EXTERNAL_ROOT" >&2
    exit 1
  fi
}

initialize() {
  mkdir -p \
    "$EXTERNAL_ROOT/datasets" \
    "$EXTERNAL_ROOT/artifacts" \
    "$EXTERNAL_ROOT/environments" \
    "$EXTERNAL_ROOT/manifests" \
    "$EXTERNAL_ROOT/migrations" \
    "$EXTERNAL_ROOT/runtime-backups/vps" \
    "$EXTERNAL_ROOT/scratch"
  mkdir -p "$SCRATCH_ROOT"
  mkdir -p "$COMPUTE_STATE_ROOT"
  printf '%s\n' "$SCRATCH_ROOT" >"$MARKER"
  if [[ -L "$STATE_LINK" ]]; then
    if [[ "$(readlink -f "$STATE_LINK")" != "$COMPUTE_STATE_ROOT" ]]; then
      printf '%s\n' "State link points outside compute scratch: $STATE_LINK" >&2
      exit 1
    fi
  elif [[ -e "$STATE_LINK" ]]; then
    printf '%s\n' "Refusing to replace an existing non-link state path: $STATE_LINK" >&2
    exit 1
  else
    ln -s "$COMPUTE_STATE_ROOT" "$STATE_LINK"
  fi
}

status() {
  printf 'external_root=%s\n' "$EXTERNAL_ROOT"
  findmnt -T "$EXTERNAL_ROOT" -o TARGET,SOURCE,FSTYPE,OPTIONS -n
  df -hT "$EXTERNAL_ROOT"
  printf 'scratch_root=%s\n' "$SCRATCH_ROOT"
  df -hT "$SCRATCH_ROOT"
  if [[ -f "$MARKER" ]]; then
    printf '%s\n' "scratch_marker=present"
  else
    printf '%s\n' "scratch_marker=missing"
  fi
  printf 'state_link=%s\n' "$(readlink "$STATE_LINK" 2>/dev/null || printf 'missing')"
}

clean_scratch() {
  if [[ ! -f "$MARKER" ]] || [[ "$(<"$MARKER")" != "$SCRATCH_ROOT" ]]; then
    printf '%s\n' "Refusing cleanup without the exact scratch marker: $MARKER" >&2
    exit 1
  fi
  find "$SCRATCH_ROOT" -mindepth 1 -maxdepth 1 ! -name '.qount-compute-scratch' \
    -exec rm -rf -- {} +
  mkdir -p "$COMPUTE_STATE_ROOT"
}

require_wsl
command="${1:-}"
case "$command" in
  check)
    check_external
    ;;
  init)
    check_external
    initialize
    status
    ;;
  clean-scratch)
    check_external
    clean_scratch
    status
    ;;
  status)
    check_external
    status
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
