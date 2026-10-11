#!/bin/bash
# 3090 GPU Server - Fixed Pipeline Training Script

set -e

ACCOUNT="us"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/p2_3090_pipeline_${TIMESTAMP}"

# Hardware-Optimized Configuration
PARALLEL=10
WORKERS=30
BATCH_WORLDS=256

echo "======================================================================"
echo "3090 Pipeline Training (Hardware-Optimized)"
echo "======================================================================"
echo "Configuration: parallel=$PARALLEL, workers=$WORKERS"
echo "Mode: Pipeline"
echo "======================================================================"
echo ""

cd /root/autodl-tmp

# Stop existing training
pkill -9 -f etf_trader 2>/dev/null || true
sleep 2

# Create output directory
mkdir -p $OUT_DIR

# Find correct python command
PYTHON_CMD=$(which python || which python3 || echo "/usr/bin/python3")
echo "Using Python: $PYTHON_CMD"

# Launch pipeline training
nohup $PYTHON_CMD scripts/research/etf_trader_train.py \
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
echo "Monitor: tail -f /root/autodl-tmp/$OUT_DIR/train.log"
