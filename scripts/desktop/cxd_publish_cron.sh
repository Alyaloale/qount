#!/bin/bash
# read-only C×D dashboard publisher (no trading): live trend + carry -> cxd_live.json
set -u
REPO="${QOUNT_REPO:-/root/qount}"
LOG="$HOME/cxd_publish.log"
ENV_FILE="$HOME/.config/qount/x4_live.env"

# shellcheck disable=SC1091
source "$REPO/scripts/desktop/cron_guard.sh"
qount_cron_guard "$0" "cxd-publish" "${QOUNT_CXD_PUBLISH_TIMEOUT_SECONDS:-90}" "$LOG" "$@"

cd "$REPO" || exit 1
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
PYTHONPATH=src ./.venv/bin/python scripts/desktop/cxd_publish.py >> "$LOG" 2>&1
