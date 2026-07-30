#!/usr/bin/env bash
# L6 WSL batch: per-day serial pipeline for A-share L2 .7z archives.
#   .7z (py7zr) -> unpack to ext4 -> parallel ETL (all cores) -> daily panel
#   -> extract ETF subset, xz-compress to external archive -> verify -> delete unpacked + .7z
#
# Single-day-at-a-time bounds the ext4/VHDX peak to one day (~40-50G). Each .7z is
# deleted ONLY after: ETL scored >= 6000 AND the xz archive passes `xz -t`.
# research-only; no network beyond local disk, no orders.
#
# Usage:  l6_wsl_batch.sh DATE [DATE ...]
set -uo pipefail

REPO=/home/alyaloale/Code/qount
SRCDIR="${QOUNT_L2_SOURCE_DIR:-/mnt/e/qount_data/qount/scratch/l6-incoming}"
ARCHIVE="${QOUNT_L2_ARCHIVE:-/mnt/e/qount_data/qount/datasets/l6_l2_archive}"
WORK="${QOUNT_L2_WORK_DIR:-$HOME/l2work}"
PY="$REPO/.venv/bin/python"
WORKERS="${WORKERS:-32}"

cd "$REPO"
mkdir -p "$WORK" "$ARCHIVE"

for DATE in "$@"; do
  SRC="$SRCDIR/$DATE.7z"
  if [ ! -f "$SRC" ]; then
    echo "SKIP $DATE (no .7z — still downloading?)"
    continue
  fi
  echo "=== $DATE start $(date +%H:%M:%S) ==="
  rm -rf "${WORK:?}/$DATE"

  # 1. unpack (py7zr) to ext4
  if ! "$PY" -c 'import py7zr,sys; py7zr.SevenZipFile(sys.argv[1]).extractall(sys.argv[2])' "$SRC" "$WORK/"; then
    echo "FAIL extract $DATE — keep .7z"; rm -rf "${WORK:?}/$DATE"; continue
  fi
  DD="$WORK/$DATE"

  # 2. parallel ETL across all cores
  if ! "$PY" scripts/research/l6_parallel_etl.py "$DD" "/tmp/l6_daily_$DATE.json" "$WORKERS"; then
    echo "FAIL etl $DATE — keep .7z"; rm -rf "$DD"; continue
  fi
  scored=$("$PY" -c "import json;print(json.load(open('/tmp/l6_daily_$DATE.json'))['n_symbols_scored'])")
  if [ "$scored" -lt 6000 ]; then
    echo "WARN $DATE scored=$scored too low — keep .7z, skip"; rm -rf "$DD"; continue
  fi
  mkdir -p "state/research_runs/l6_daily_$DATE"
  cp "/tmp/l6_daily_$DATE.json" "state/research_runs/l6_daily_$DATE/"

  # 3. ETF subset -> xz archive on external storage
  ls "$DD" | grep -E '^(159|51[0-8]|56[0-3]|588)[0-9]' | sed "s#^#$DATE/#" > "/tmp/etflist_$DATE.txt"
  etf=$(wc -l < "/tmp/etflist_$DATE.txt" | tr -d ' ')
  tar -C "$WORK" -cf - -T "/tmp/etflist_$DATE.txt" | xz -T0 -6 > "$ARCHIVE/l6_etf_l2_$DATE.tar.xz"

  # 4. verify archive, then delete unpacked + .7z
  if xz -t "$ARCHIVE/l6_etf_l2_$DATE.tar.xz" >/dev/null 2>&1; then
    rm -rf "$DD"
    rm -f "$SRC"
    echo "DONE $DATE: scored=$scored etf=$etf size=$(du -h "$ARCHIVE/l6_etf_l2_$DATE.tar.xz" | cut -f1) .7z DELETED $(date +%H:%M:%S)"
  else
    echo "FAIL xz verify $DATE — keep .7z"; rm -rf "$DD"
  fi
done
echo "=== BATCH DONE $(date +%H:%M:%S) ==="
