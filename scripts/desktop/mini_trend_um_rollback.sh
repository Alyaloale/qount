#!/usr/bin/env bash
set -euo pipefail

STATE_ROOT="${QOUNT_MINI_TREND_STATE_ROOT:-/root/qount/state/mini_trend}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK_ROOT="$STATE_ROOT/rollback/$STAMP"

mkdir -p "$ROLLBACK_ROOT"
printf '%s\n' "$STAMP" >"$STATE_ROOT/HALT"

if command -v systemctl >/dev/null 2>&1; then
  systemctl stop \
    qount-mini-trend.timer \
    qount-mini-trend.service \
    qount-mini-trend-forward.timer \
    qount-mini-trend-forward.service \
    2>/dev/null || true
  systemctl disable \
    qount-mini-trend.timer \
    qount-mini-trend-forward.timer \
    2>/dev/null || true
fi

for name in live paper preflight rules forward dry arm; do
  source_path="$STATE_ROOT/$name"
  if [[ -e "$source_path" ]]; then
    tar -czf "$ROLLBACK_ROOT/$name.tgz" -C "$STATE_ROOT" "$name"
  fi
done

cat >"$ROLLBACK_ROOT/README.txt" <<'EOF'
MiniTrend runtime was halted locally.
No exchange order, cancellation, transfer, or automatic flatten was attempted.

Required manual sequence:
1. Run the read-only account preflight and export positions/open orders/fills.
2. Identify orders and positions owned by this strategy.
3. Cancel only confirmed strategy orders.
4. Decide manually whether and how to flatten confirmed strategy positions.
5. Record fills, fees, funding and the incident cause before any re-arm.
EOF

printf 'halt_file=%s\n' "$STATE_ROOT/HALT"
printf 'rollback_snapshot=%s\n' "$ROLLBACK_ROOT"
printf '%s\n' 'exchange_actions_attempted=false'
