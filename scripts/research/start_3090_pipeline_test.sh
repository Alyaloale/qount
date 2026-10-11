#!/bin/bash
# 3090 GPU Server - Hardware-Optimized Pipeline Training
# Hardware: 28 CPU cores, 64GB RAM, RTX 3090 24GB

set -e

ACCOUNT="us"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/p2_3090_pipeline_${TIMESTAMP}"

# ============================================================
# 3090 Hardware-Optimized Configuration
# ============================================================
# GPU: RTX 3090 24GB
PARALLEL=10              # 10 parallel training processes (2.4GB each = 24GB)
WORKERS=30               # 30 CPU workers (28 cores, leave 2 for system)
BATCH_WORLDS=256         # Batch size per episode

# Pipeline mode: world generation (CPU) || GPU training
# Expected speedup: 2.5-3x vs sequential

echo "======================================================================"
echo "3090 Pipeline Training (Hardware-Optimized)"
echo "======================================================================"
echo "Hardware:"
echo "  CPU: 28 cores"
echo "  GPU: RTX 3090 24GB"
echo "  RAM: 64GB"
echo ""
echo "Configuration:"
echo "  Parallel: $PARALLEL (10 × 2.4GB = 24GB GPU)"
echo "  Workers: $WORKERS (28 cores - 2 system)"
echo "  Batch: $BATCH_WORLDS"
echo "  Mode: Pipeline (world gen || GPU training)"
echo ""
echo "Test: 1 config × 3 episodes"
echo "Expected: ~3-4 min/episode with pipeline"
echo "======================================================================"
echo ""

cd /root/autodl-tmp

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
echo "  tail -f /root/autodl-tmp/$OUT_DIR/train.log"
echo ""
echo "Check progress:"
echo "  tail -1 /root/autodl-tmp/$OUT_DIR/train.log | grep episode"
