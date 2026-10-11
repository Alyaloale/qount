#!/bin/bash
# WSL 4060 - Hardware-Optimized Pipeline Training
# Hardware: 32 CPU cores, 64GB RAM, RTX 4060 8GB

set -e

ACCOUNT="us"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/p2_wsl_pipeline_${TIMESTAMP}"

# ============================================================
# WSL 4060 Hardware-Optimized Configuration
# ============================================================
# GPU: RTX 4060 8GB
PARALLEL=4               # 4 parallel training processes (2GB each = 8GB)
WORKERS=32               # 32 CPU workers (32 cores available)
BATCH_WORLDS=256         # Batch size per episode

# Pipeline mode: world generation (CPU) || GPU training
# Expected speedup: 2.5-3x vs sequential

echo "======================================================================"
echo "WSL 4060 Pipeline Training (Hardware-Optimized)"
echo "======================================================================"
echo "Hardware:"
echo "  CPU: 32 cores"
echo "  GPU: RTX 4060 8GB"
echo "  RAM: 64GB"
echo ""
echo "Configuration:"
echo "  Parallel: $PARALLEL (4 × 2GB = 8GB GPU)"
echo "  Workers: $WORKERS (all 32 cores)"
echo "  Batch: $BATCH_WORLDS"
echo "  Mode: Pipeline (world gen || GPU training)"
echo ""
echo "Test: 1 config × 3 episodes"
echo "Expected: ~3-4 min/episode with pipeline"
echo "======================================================================"
echo ""

cd ~/Code/qount

# Set PYTHONPATH for venv_upper
export PYTHONPATH=~/venv_upper/lib/python3.12/site-packages:~/Code/qount

# Stop existing training
pkill -9 -f etf_trader 2>/dev/null || true
sleep 2

# Create output directory
mkdir -p $OUT_DIR

# Launch pipeline training
nohup python3 scripts/research/etf_trader_train.py \
    --account $ACCOUNT \
    --out $OUT_DIR \
    --d-phi 16 \
    --hidden 32 \
    --layers 1 \
    --lr 3e-4 \
    --episodes 3 \
    --batch-worlds $BATCH_WORLDS \
    --seed 20260930 \
    --workers $WORKERS \
    --device cuda \
    --pipeline \
    > $OUT_DIR/train.log 2>&1 &

TRAIN_PID=$!
echo "Training started (PID: $TRAIN_PID)"
echo ""
echo "Monitor with:"
echo "  tail -f ~/Code/qount/$OUT_DIR/train.log"
echo ""
echo "Check progress:"
echo "  tail -1 ~/Code/qount/$OUT_DIR/train.log | grep episode"
