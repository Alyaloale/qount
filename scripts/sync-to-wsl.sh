#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${QOUNT_WSL_HOST:-home}"
REMOTE_DIR="${QOUNT_WSL_DIR:-/home/alyaloale/Code/qount}"

usage() {
  printf '%s\n' "Usage: scripts/sync-to-wsl.sh [--install] [--clean-code]"
  printf '%s\n' "Explicitly update the independent WSL compute workspace."
}

install=false
clean_code=false
while (($#)); do
  case "$1" in
    --install)
      install=true
      shift
      ;;
    --clean-code)
      clean_code=true
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

if [[ "$clean_code" == true ]]; then
  ssh -o ClearAllForwardings=yes "$REMOTE_HOST" 'wsl.exe bash -s' -- "$REMOTE_DIR" <<'EOF'
set -euo pipefail
REMOTE_DIR="$1"
cd "$REMOTE_DIR"
rm -rf deploy docs prompts scripts src tests
EOF
fi

COPYFILE_DISABLE=1 tar \
  --no-xattrs \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  -cf - \
  README.md \
  pyproject.toml \
  deploy \
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
printf '%s\n' "WSL is an independent compute workspace; sync only when its compute code changes."
