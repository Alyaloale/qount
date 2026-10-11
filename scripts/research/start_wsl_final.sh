#!/bin/bash
# WSL 4060 - Final Fixed Pipeline Training Script

set -e

ACCOUNT="us"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/p2_wsl_pipeline_${TIMESTAMP}"

PARALLEL=4
WORKERS=32
BATCH_WORLDS=256

echo "======================================================================"
echo "WSL 4060 Pipeline Training"
echo "======================================================================"
echo "Configuration: parallel=$PARALLEL, workers=$WORKERS, pipeline=True"
echo "======================================================================"
echo ""

cd ~/Code/qount

# Critical: Use src directly in sys.path, not installed package
export PYTHONPATH=~/venv_upper/lib/python3.12/site-packages:~/Code/qount/src

# Stop existing training
pkill -9 -f etf_trader 2>/dev/null || true
sleep 2

# Create output directory
mkdir -p $OUT_DIR

echo "Verifying environment..."
python3 -c "import sys; sys.path.insert(0, 'src'); import torch; from qount.research.etf_trader.policy import PolicyConfig; print('✓ Environment OK')" || {
    echo "ERROR: Environment check failed"
    exit 1
}

echo "✓ Environment verified"
echo "Starting training..."
echo ""

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
echo "✓ Training started (PID: $TRAIN_PID)"
echo ""
echo "Monitor: tail -f ~/Code/qount/$OUT_DIR/train.log"
