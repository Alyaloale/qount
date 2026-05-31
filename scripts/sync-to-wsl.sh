#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${QOUNT_WSL_HOST:-home}"
REMOTE_DIR="${QOUNT_WSL_DIR:-/home/alyaloale/Code/qount}"

usage() {
  printf '%s\n' "Usage: scripts/sync-to-wsl.sh [--install]"
}

install=false
while (($#)); do
  case "$1" in
    --install)
      install=true
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

tar \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  -cf - \
  README.md \
  pyproject.toml \
  docs \
  prompts \
  scripts \
  src/qount \
  tests \
  | ssh -o ClearAllForwardings=yes "$REMOTE_HOST" "wsl.exe bash -lc 'cd \"$REMOTE_DIR\" && tar -xf -'"

if [[ "$install" == true ]]; then
  ssh -o ClearAllForwardings=yes "$REMOTE_HOST" "wsl.exe bash -lc 'cd \"$REMOTE_DIR\" && ./.venv/bin/python -m pip install -e .'"
fi

printf '%s\n' "synced to ${REMOTE_HOST}:${REMOTE_DIR}"
