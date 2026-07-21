#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${QOUNT_VPS_HOST:-qount-vps}"
REMOTE_DIR="${QOUNT_VPS_DIR:-/root/qount}"

usage() {
  printf '%s\n' "Usage: scripts/sync-to-vps.sh [--install] [--delete] [--dry-run]"
}

install=false
delete=false
dry_run=false
while (($#)); do
  case "$1" in
    --install)
      install=true
      shift
      ;;
    --delete)
      delete=true
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

cd "$(dirname "$0")/.."

if [[ "$dry_run" != true ]]; then
  if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    printf '%s\n' "refusing VPS sync from a dirty worktree; commit the release first" >&2
    exit 3
  fi
  release_python="${QOUNT_SYNC_PYTHON:-./.venv/bin/python}"
  if [[ ! -x "$release_python" ]]; then
    printf 'release_provenance_python_not_executable=%s\n' "$release_python" >&2
    exit 4
  fi
  PYTHONPATH=src "$release_python" scripts/operations/write_release_provenance.py \
    --repo-root . \
    --output-path .qount-release-provenance.json
fi

ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_DIR'"

rsync_args=(
  -az
  --relative
  --exclude='__pycache__'
  --exclude='*.pyc'
  --exclude='.DS_Store'
)
if [[ "$delete" == true ]]; then
  rsync_args+=(--delete)
fi
if [[ "$dry_run" == true ]]; then
  rsync_args+=(--dry-run)
fi

items=(
  ./README.md
  ./pyproject.toml
  ./deploy
  ./docs
  ./prompts
  ./scripts
  ./src/qount
  ./tests
  ./web
  ./.qount-release-provenance.json
)

rsync "${rsync_args[@]}" "${items[@]}" "$REMOTE_HOST:$REMOTE_DIR/"

if [[ "$install" == true && "$dry_run" != true ]]; then
  ssh "$REMOTE_HOST" "cd '$REMOTE_DIR' && ./.venv/bin/python -m pip install -e '.[test]'"
fi

printf '%s\n' "synced to ${REMOTE_HOST}:${REMOTE_DIR}"
