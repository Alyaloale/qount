#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${QOUNT_WSL_PROJECT_ROOT:-/home/alyaloale/Code/qount}"
SCRATCH_ROOT="${QOUNT_WSL_SCRATCH_ROOT:-/home/alyaloale/.cache/qount-compute}"
JOB_ROOT="$SCRATCH_ROOT/jobs"

usage() {
  printf '%s\n' "Usage: wsl_long_job.sh JOB_NAME manifest ROOT SOURCE_NODE OUTPUT"
  printf '%s\n' "       wsl_long_job.sh JOB_NAME install-research-env"
}

job_name="${1:-}"
action="${2:-}"
if [[ ! "$job_name" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  printf '%s\n' "Invalid job name: $job_name" >&2
  exit 2
fi
shift 2 || true

mkdir -p "$JOB_ROOT"
log_path="$JOB_ROOT/$job_name.log"
exit_path="$JOB_ROOT/$job_name.exit"
lock_path="$JOB_ROOT/$job_name.lock"
rm -f "$exit_path"
exec >"$log_path" 2>&1
exec 9>"$lock_path"
if ! flock -n 9; then
  printf '%s\n' "Job is already active: $job_name" >&2
  exit 1
fi

finish() {
  local status="$?"
  printf '%s\n' "$status" >"$exit_path"
}
trap finish EXIT

cd "$PROJECT_ROOT"
case "$action" in
  manifest)
    if [[ "$#" -ne 3 ]]; then
      usage >&2
      exit 2
    fi
    root="$1"
    source_node="$2"
    output="$3"
    PYTHONPATH=src ./.venv/bin/python scripts/storage/state_manifest.py \
      --root "$root" \
      --source-node "$source_node" \
      --output "$output"
    ;;
  install-research-env)
    if [[ "$#" -ne 0 ]]; then
      usage >&2
      exit 2
    fi
    env \
      -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
      -u http_proxy -u https_proxy -u all_proxy \
      PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
      ./.venv/bin/python -m pip install -e '.[research-regime,research-neural]'
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
