#!/usr/bin/env bash
# L6 download->process pipeline (run on WSL, unattended/overnight).
#
# Producer (downloader, ~10MB/s network-bound) and consumer (extract -> parallel
# ETL -> xz archive -> delete) run CONCURRENTLY so the slow download overlaps with
# CPU processing — no stage blocks the other. Two space guards keep D: from filling:
#   * downloader pauses when D: free < MIN_FREE_GB OR pending .7z >= MAX_PENDING
#   * processor is single-day-serial (ext4/VHDX peak = one day), deletes .7z + the
#     unpacked dir right after the xz archive verifies, freeing D: immediately.
# IMPORTANT: the WSL ext4 VHDX lives on D: and does NOT shrink when files are
# deleted, so space is judged on `df /mnt/d` (real), never `df /home` (virtual).
#
# Idempotent: a date whose archive already exists (or whose .7z is gone) is skipped,
# so killing/restarting just resumes. research-only; no live, no orders.
# A .7z that can't be processed (corrupt extract / etl fail / scored<6000 incomplete
# source / xz verify fail) is MOVED to $SRCDIR/_bad/ so it leaves the *.7z glob — the
# processor never re-retries it and can exit cleanly. Re-download good copies to retry.
#
# ---- YOU EDIT THIS BLOCK, then: nohup bash scripts/research/l6_pipeline.sh > /tmp/l6_pipeline.log 2>&1 &
set -uo pipefail

# Remote files to fetch. Either list explicit .7z names (must be <YYYYMMDD>.7z) and
# a remote dir, OR replace download_one() below with your own tool entirely.
# 下载模式:
#   "cli"      = 脚本调用 BaiduPCS-Go 等命令行工具自动下载(全自动,需登录)
#   "external" = 你用网盘 GUI / 其他方式自己下到 $SRCDIR,脚本只做处理(消费者);
#                下完后在 WSL 执行  touch /mnt/d/BaiduNetdiskDownload/.l6_download_done  让脚本收尾
DOWNLOAD_MODE="external"
REMOTE_DIR="/your/baidu/netdisk/path"      # <-- (cli 模式)网盘里 .7z 所在目录
DATES="20250303 20250304 20250305"          # <-- (cli 模式)要下的交易日;external 模式可留空
DL_PARALLEL=16                               # 下载线程(网速 ~10MB/s 是硬上限,8-16 足够)

# ---- paths / knobs (usually no need to change) ----
REPO=/home/alyaloale/Code/qount
SRCDIR=/mnt/d/BaiduNetdiskDownload           # .7z 落地(D 盘 NTFS)
BAD="$SRCDIR/_bad"                           # 处理失败的坏 .7z 隔离区(移出 glob,processor 不再重试)
ARCHIVE=/mnt/d/qount_l2_archive              # ETF 压缩归档(D 盘 NTFS)
WORK="$HOME/l2work"                          # 解压工作区(ext4,VHDX 在 D 盘)
PY="$REPO/.venv/bin/python"
WORKERS=32                                   # ETL 并行核数
MIN_FREE_GB=70                               # D 盘可用低于此,暂停下载(留单天解压 + 余量)
MAX_PENDING=3                                # 未处理 .7z 缓冲上限(3×~5G=15G)
PROC_MIN_FREE_GB=55                          # 解压前要求的 D 盘可用(单天 VHDX 增长 ~40-50G)
ETF_RE='^(159|51[0-8]|56[0-3]|588)[0-9]'
# 已知合法的低标的交易日(源数据本身 <6000,非半包下载)——空格分隔;跳过 scored<6000 守卫。
LOW_OK_DATES="20260210"

mkdir -p "$SRCDIR" "$BAD" "$ARCHIVE" "$WORK"
cd "$REPO"
ts() { date +%H:%M:%S; }
free_gb() { df -BG "$SRCDIR" 2>/dev/null | awk 'NR==2{gsub(/G/,"",$4); print $4+0}'; }
pending_count() { ls "$SRCDIR"/*.7z 2>/dev/null | grep -vc 'downloading' || true; }

# ---------------------------------------------------------------------------
# Download one date's .7z. EDIT this to match your tool (BaiduPCS-Go shown).
# Must produce $SRCDIR/<date>.7z. Resumable downloads strongly preferred.
# ---------------------------------------------------------------------------
download_one() {
  local date="$1"
  # --- BaiduPCS-Go example (needs prior `BaiduPCS-Go login`): ---
  BaiduPCS-Go download "$REMOTE_DIR/$date.7z" --saveto "$SRCDIR" --p "$DL_PARALLEL"
  # --- or bypy: bypy downfile "$REMOTE_DIR/$date.7z" "$SRCDIR/$date.7z" ---
  # --- or any CLI that writes "$SRCDIR/$date.7z" ---
}

downloader() {
  for date in $DATES; do
    if [ -f "$ARCHIVE/l6_etf_l2_$date.tar.xz" ]; then
      echo "[dl $(ts)] SKIP $date (archive exists)"; continue
    fi
    if [ -f "$SRCDIR/$date.7z" ]; then
      echo "[dl $(ts)] SKIP $date (.7z already present)"; continue
    fi
    # space/buffer guard: wait until processor has drained enough
    while [ "$(free_gb)" -lt "$MIN_FREE_GB" ] || [ "$(pending_count)" -ge "$MAX_PENDING" ]; do
      echo "[dl $(ts)] hold: free=$(free_gb)G pending=$(pending_count) (waiting for processor)"; sleep 60
    done
    echo "[dl $(ts)] downloading $date (free=$(free_gb)G)"
    download_one "$date" || echo "[dl $(ts)] FAIL download $date (will retry next run)"
  done
  touch "$SRCDIR/.l6_download_done"
  echo "[dl $(ts)] all downloads issued"
}

# ---------------------------------------------------------------------------
process_one() {
  local src="$1"; local date; date="$(basename "$src" .7z)"
  while [ "$(free_gb)" -lt "$PROC_MIN_FREE_GB" ]; do
    echo "[proc $(ts)] low space $(free_gb)G < ${PROC_MIN_FREE_GB}G, waiting"; sleep 60
  done
  echo "[proc $(ts)] === $date start (free=$(free_gb)G) ==="
  rm -rf "${WORK:?}/$date"
  if ! "$PY" -c 'import py7zr,sys; py7zr.SevenZipFile(sys.argv[1]).extractall(sys.argv[2])' "$src" "$WORK/"; then
    echo "[proc $(ts)] FAIL extract $date — corrupt .7z, move to _bad/"; rm -rf "${WORK:?}/$date"; mv "$src" "$BAD/"; return
  fi
  local dd="$WORK/$date"
  if ! "$PY" scripts/research/l6_parallel_etl.py "$dd" "/tmp/l6_daily_$date.json" "$WORKERS"; then
    echo "[proc $(ts)] FAIL etl $date — move to _bad/"; rm -rf "$dd"; mv "$src" "$BAD/"; return
  fi
  local scored
  scored=$("$PY" -c "import json;print(json.load(open('/tmp/l6_daily_$date.json'))['n_symbols_scored'])")
  if [ "$scored" -lt 6000 ] && [[ " $LOW_OK_DATES " != *" $date "* ]]; then
    echo "[proc $(ts)] WARN $date scored=$scored low — incomplete source, move to _bad/"; rm -rf "$dd"; mv "$src" "$BAD/"; return
  fi
  [ "$scored" -lt 6000 ] && echo "[proc $(ts)] NOTE $date scored=$scored low but whitelisted (LOW_OK_DATES) — keep"
  mkdir -p "state/research_runs/l6_daily_$date"
  cp "/tmp/l6_daily_$date.json" "state/research_runs/l6_daily_$date/"
  ls "$dd" | grep -E "$ETF_RE" | sed "s#^#$date/#" > "/tmp/etflist_$date.txt"
  tar -C "$WORK" -cf - -T "/tmp/etflist_$date.txt" | xz -T0 -6 > "$ARCHIVE/l6_etf_l2_$date.tar.xz"
  if xz -t "$ARCHIVE/l6_etf_l2_$date.tar.xz" >/dev/null 2>&1; then
    rm -rf "$dd"; rm -f "$src"            # free D: immediately (unpacked + .7z)
    echo "[proc $(ts)] DONE $date scored=$scored etf_archive=$(du -h "$ARCHIVE/l6_etf_l2_$date.tar.xz" | cut -f1) (free=$(free_gb)G)"
  else
    echo "[proc $(ts)] FAIL xz verify $date — move to _bad/"; rm -rf "$dd"; mv "$src" "$BAD/"
  fi
}

processor() {
  while true; do
    local did_work=0
    for f in "$SRCDIR"/*.7z; do
      [ -f "$f" ] || continue
      case "$f" in *downloading*) continue;; esac
      # stability check: size unchanged across 5s => fully downloaded
      local s1 s2; s1=$(stat -c%s "$f"); sleep 5; s2=$(stat -c%s "$f")
      [ "$s1" = "$s2" ] || { echo "[proc $(ts)] $f still growing, skip this pass"; continue; }
      process_one "$f"; did_work=1
    done
    # exit when downloads finished AND nothing left to process
    if [ -f "$SRCDIR/.l6_download_done" ]; then
      local left; left=$(ls "$SRCDIR"/*.7z 2>/dev/null | grep -vc 'downloading' || true)
      [ "$left" -eq 0 ] && { echo "[proc $(ts)] all processed, exit"; break; }
    fi
    [ "$did_work" -eq 0 ] && sleep 30
  done
}

# ---- run ----
echo "[main $(ts)] start mode=$DOWNLOAD_MODE  D: free=$(free_gb)G"
if [ "$DOWNLOAD_MODE" = "cli" ]; then
  # producer + consumer concurrently (download overlaps processing)
  rm -f "$SRCDIR/.l6_download_done"
  processor & PROC_PID=$!
  downloader
  wait "$PROC_PID"
else
  # external: you download into $SRCDIR yourself; we just consume as files land.
  echo "[main $(ts)] external 模式:把 .7z 下到 $SRCDIR,脚本持续处理;下完后 touch $SRCDIR/.l6_download_done 收尾"
  processor
fi
echo "[main $(ts)] pipeline complete. archives in $ARCHIVE ; panels in state/research_runs/l6_daily_*"
