#!/usr/bin/env bash
# Re-ETL the ETF universe from the preserved ETF L2 archives, producing daily
# panels that now include `day_open` (added to daily_flow_features) — the input
# the L6 close_auction × ETF T+0 execution line needs to split the next-day
# reversal into overnight (T close -> T+1 open) vs intraday (T+1 open -> close).
#
# Reads $QOUNT_L2_ARCHIVE/l6_etf_l2_<date>.tar.{xz,zst}; writes
# state/research_runs_etfopen/l6_daily_<date>/l6_daily_<date>.json (a SEPARATE
# root so the all-symbol D0 panels are left untouched). Idempotent: a date whose
# panel already exists is skipped. .tar.zst is skipped if zstd is unavailable.
# research-only; no network, no orders, single-day-at-a-time disk peak.
#
# Run on WSL:  nohup bash scripts/research/l6_etf_reetl.sh > /tmp/l6_reetl.log 2>&1 &
set -uo pipefail
REPO=/home/alyaloale/Code/qount
ARCHIVE="${QOUNT_L2_ARCHIVE:-/mnt/e/qount_data/qount/datasets/l6_l2_archive}"
WORK="${QOUNT_L2_WORK_DIR:-$HOME/l2work}/reetl"
OUT="$REPO/state/research_runs_etfopen"
PY="$REPO/.venv/bin/python"
WORKERS=32
mkdir -p "$WORK" "$OUT"
cd "$REPO"
ts() { date +%H:%M:%S; }

for arch in "$ARCHIVE"/l6_etf_l2_*.tar.*; do
  [ -e "$arch" ] || continue
  base="$(basename "$arch")"
  date="$(echo "$base" | grep -oE '[0-9]{8}')"
  outdir="$OUT/l6_daily_$date"; outjson="$outdir/l6_daily_$date.json"
  if [ -f "$outjson" ]; then echo "[$(ts)] SKIP $date (panel exists)"; continue; fi
  rm -rf "${WORK:?}/$date"
  echo "[$(ts)] === $date extract ($base) ==="
  case "$arch" in
    *.tar.xz)
      tar -C "$WORK" -xJf "$arch" || { echo "[$(ts)] FAIL extract $date"; rm -rf "${WORK:?}/$date"; continue; } ;;
    *.tar.zst)
      if ! command -v zstd >/dev/null 2>&1; then echo "[$(ts)] SKIP $date (.tar.zst, no zstd)"; continue; fi
      tar -C "$WORK" --zstd -xf "$arch" || { echo "[$(ts)] FAIL extract $date"; rm -rf "${WORK:?}/$date"; continue; } ;;
    *) echo "[$(ts)] SKIP $date (unknown ext)"; continue ;;
  esac
  mkdir -p "$outdir"
  if "$PY" scripts/research/l6_parallel_etl.py "$WORK/$date" "$outjson" "$WORKERS"; then
    : # ok
  else
    echo "[$(ts)] FAIL etl $date"; rm -f "$outjson"
  fi
  rm -rf "${WORK:?}/$date"
done
echo "[$(ts)] reetl complete -> $OUT"
