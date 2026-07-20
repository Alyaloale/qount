#!/usr/bin/env bash

# Shared fail-closed guard for cron entrypoints. The outer invocation owns the
# wall-clock timeout; the inner invocation owns the non-blocking flock.
qount_cron_guard() {
  if [ "$#" -lt 4 ]; then
    printf '%s\n' "qount_cron_guard: expected script job timeout_seconds log_file" >&2
    exit 64
  fi

  local script="$1"
  local job="$2"
  local timeout_seconds="$3"
  local log_file="$4"
  shift 4

  case "$job" in
    ''|*[!A-Za-z0-9._-]*)
      printf '%s\n' "qount_cron_guard: invalid job name: $job" >&2
      exit 64
      ;;
  esac
  case "$timeout_seconds" in
    ''|*[!0-9]*|0)
      printf '%s\n' "qount_cron_guard: invalid timeout: $timeout_seconds" >&2
      exit 64
      ;;
  esac

  mkdir -p "$(dirname "$log_file")" 2>/dev/null || true

  if [ "${QOUNT_CRON_GUARDED_JOB:-}" != "$job" ]; then
    local timeout_bin="${QOUNT_TIMEOUT_BIN:-}"
    if [ -z "$timeout_bin" ]; then
      timeout_bin=$(command -v timeout 2>/dev/null || true)
    fi
    if [ -z "$timeout_bin" ]; then
      printf '[ALERT] %s missing timeout command; refusing to run\n' "$job" >> "$log_file"
      exit 78
    fi

    QOUNT_CRON_GUARDED_JOB="$job" "$timeout_bin" \
      --signal=TERM --kill-after=10s "${timeout_seconds}s" \
      /bin/bash "$script" "$@"
    local rc=$?
    if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
      printf '[ALERT] %s exceeded %ss runtime limit; process group terminated rc=%s at %s\n' \
        "$job" "$timeout_seconds" "$rc" "$(date '+%F %T %Z')" >> "$log_file"
    elif [ "$rc" -eq 125 ] || [ "$rc" -eq 126 ] || [ "$rc" -eq 127 ]; then
      printf '[ALERT] %s timeout wrapper failed rc=%s at %s\n' \
        "$job" "$rc" "$(date '+%F %T %Z')" >> "$log_file"
    fi
    exit "$rc"
  fi

  local flock_bin="${QOUNT_FLOCK_BIN:-}"
  if [ -z "$flock_bin" ]; then
    flock_bin=$(command -v flock 2>/dev/null || true)
  fi
  if [ -z "$flock_bin" ]; then
    printf '[ALERT] %s missing flock command; refusing to run\n' "$job" >> "$log_file"
    exit 78
  fi

  local lock_dir="${QOUNT_CRON_LOCK_DIR:-/run/lock/qount}"
  if ! mkdir -p "$lock_dir"; then
    printf '[ALERT] %s cannot create lock dir %s; refusing to run\n' "$job" "$lock_dir" >> "$log_file"
    exit 78
  fi
  local lock_file="$lock_dir/$job.lock"
  exec 9>"$lock_file"
  if ! "$flock_bin" -n 9; then
    printf '[SKIP] %s previous run still active at %s\n' \
      "$job" "$(date '+%F %T %Z')" >> "$log_file"
    exit 0
  fi
}
