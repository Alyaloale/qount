#!/bin/bash
# read-only C×D dashboard publisher (no trading): live trend + carry -> cxd_live.json
set -u
cd "$HOME/qount" || exit 1
[ -f "$HOME/.config/qount/x4_live.env" ] && . "$HOME/.config/qount/x4_live.env"
PYTHONPATH=src ./.venv/bin/python scripts/desktop/cxd_publish.py >> "$HOME/cxd_publish.log" 2>&1
