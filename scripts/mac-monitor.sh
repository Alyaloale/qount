#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${QOUNT_ALLOW_LEGACY_WSL:-0}" != "1" ]]; then
  cat >&2 <<'EOF'
scripts/mac-monitor.sh is deprecated.

Current crypto live state is on the VPS dashboard and VPS state files:
  https://qount.alyaloale.com
  ssh qount-vps 'cd /root/qount && tail -n 120 ~/cxd_live.log'
  ssh qount-vps 'cd /root/qount && python3 -m json.tool state/x4/live/latest.json'

To run the old WSL monitor for historical line A only, set:
  QOUNT_ALLOW_LEGACY_WSL=1
EOF
  exit 1
fi

exec "${ROOT_DIR}/.venv/bin/python" -m qount.mac_monitor "$@"
