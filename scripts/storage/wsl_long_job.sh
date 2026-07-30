#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${QOUNT_WSL_PROJECT_ROOT:-/home/alyaloale/Code/qount}"
SCRATCH_ROOT="${QOUNT_WSL_SCRATCH_ROOT:-/home/alyaloale/.cache/qount-compute}"
JOB_ROOT="$SCRATCH_ROOT/jobs"

usage() {
  printf '%s\n' "Usage: wsl_long_job.sh JOB_NAME manifest ROOT SOURCE_NODE OUTPUT"
  printf '%s\n' "       wsl_long_job.sh JOB_NAME install-research-env"
  printf '%s\n' "       wsl_long_job.sh JOB_NAME stablecoin-native-events OUTPUT_ROOT START_AT END_EXCLUSIVE"
  printf '%s\n' "       wsl_long_job.sh JOB_NAME stablecoin-remediate PHASE RUN_ID INPUT_DIR OUTPUT_ROOT SCRATCH_ROOT [PROXY_URL_ENV]"
  printf '%s\n' "       wsl_long_job.sh JOB_NAME stablecoin-g0 PREREG SOURCE_CAPACITY BASELINE SOURCE1 SOURCE2 SOURCE3 OUTPUT_ROOT"
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

job_completed=0
finish() {
  local status="$?"
  if [[ "$job_completed" -ne 1 && "$status" -eq 0 ]]; then
    status=125
  fi
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
  stablecoin-native-events)
    if [[ "$#" -ne 3 ]]; then
      usage >&2
      exit 2
    fi
    output_root="$1"
    start_at="$2"
    end_exclusive="$3"
    env \
      -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
      -u http_proxy -u https_proxy -u all_proxy \
      PYTHONPATH=src \
      ./.venv/bin/python scripts/research/mini_trend/collect_stablecoin_chain_events.py \
      --output-root "$output_root" \
      --start-at "$start_at" \
      --end-exclusive "$end_exclusive"
    ;;
  stablecoin-remediate)
    if [[ "$#" -lt 5 || "$#" -gt 6 ]]; then
      usage >&2
      exit 2
    fi
    phase="$1"
    run_id="$2"
    input_directory="$3"
    output_root="$4"
    scratch_root="$5"
    proxy_url_env="${6:-}"
    remediation_args=(
      --phase "$phase"
      --run-id "$run_id"
      --input-directory "$input_directory"
      --output-root "$output_root"
      --scratch-root "$scratch_root"
    )
    if [[ -n "$proxy_url_env" ]]; then
      remediation_args+=(--proxy-url-env "$proxy_url_env")
    fi
    PYTHONPATH=src ./.venv/bin/python \
      scripts/research/mini_trend/remediate_stablecoin_chain_events.py \
      "${remediation_args[@]}"
    ;;
  stablecoin-g0)
    if [[ "$#" -ne 7 ]]; then
      usage >&2
      exit 2
    fi
    preregistration="$1"
    source_capacity="$2"
    baseline="$3"
    source_one="$4"
    source_two="$5"
    source_three="$6"
    output_root="$7"
    PYTHONPATH=src ./.venv/bin/python scripts/research/mini_trend/run_stablecoin_impulse_g0.py \
      --run \
      --preregistration-path "$preregistration" \
      --source-capacity-path "$source_capacity" \
      --aggregate-supply-path "$baseline" \
      --source-input "$source_one" \
      --source-input "$source_two" \
      --source-input "$source_three" \
      --output-root "$output_root"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
job_completed=1
