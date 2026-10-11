#!/bin/bash
# P2 Training Deployment Script - Optimized Version
#
# This script deploys the optimized P2 training to 3090 server
# with all Phase 1+2 fixes applied.

set -e

SERVER="root@connect.nmb2.seetacloud.com"
PORT="41489"
PASSWORD="uYBtc8pn9ond"
REMOTE_DIR="/root/autodl-tmp"

echo "======================================================================"
echo "P2 Optimized Training Deployment"
echo "======================================================================"
echo "Target: 3090 GPU Server"
echo "Optimizations: P0-1, P0-2, P1-3, P1-4, P1-5, P1-8, P2-8, P2-11"
echo "======================================================================"
echo ""

# Configuration
PARALLEL=14          # P0-2: Reduced from 16 to avoid OOM
WORKERS=28           # P1-3: 14 × 2 for optimal world generation
BATCH_WORLDS=256
STAGE_A_EP=30
STAGE_B_EP=100
ACCOUNT="us"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/p2_us_optimized_${TIMESTAMP}"

echo "Configuration:"
echo "  Parallel: $PARALLEL (reduced to avoid OOM)"
echo "  Workers: $WORKERS (optimized for $PARALLEL processes)"
echo "  Batch worlds: $BATCH_WORLDS"
echo "  Stage A episodes: $STAGE_A_EP"
echo "  Stage B episodes: $STAGE_B_EP"
echo "  Output: $OUT_DIR"
echo ""

# Step 1: Copy optimized code to server
echo "[1/4] Uploading optimized code..."
sshpass -p "$PASSWORD" scp -P $PORT \
    src/qount/research/etf_trader/train_optimized.py \
    ${SERVER}:${REMOTE_DIR}/src/qount/research/etf_trader/ || {
    echo "ERROR: Failed to upload train_optimized.py"
    exit 1
}

sshpass -p "$PASSWORD" scp -P $PORT \
    scripts/research/etf_trader_parallel_search_optimized.py \
    ${SERVER}:${REMOTE_DIR}/scripts/research/ || {
    echo "ERROR: Failed to upload parallel search script"
    exit 1
}

echo "✓ Code uploaded successfully"
echo ""

# Step 2: Verify environment
echo "[2/4] Verifying server environment..."
sshpass -p "$PASSWORD" ssh -p $PORT $SERVER << 'EOF'
echo "Checking GPU..."
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo "Checking Python environment..."
python -c "import torch; print(f'PyTorch: {torch.__version__}, CUDA: {torch.cuda.is_available()}')"

echo "Checking qount package..."
python -c "from qount.research.etf_trader.train_optimized import train; print('✓ train_optimized imported')"
EOF

if [ $? -ne 0 ]; then
    echo "ERROR: Environment verification failed"
    exit 1
fi

echo "✓ Environment verified"
echo ""

# Step 3: Stop any running training
echo "[3/4] Stopping existing training processes..."
sshpass -p "$PASSWORD" ssh -p $PORT $SERVER << EOF
pkill -f etf_trader_parallel_search 2>/dev/null || true
sleep 2
RUNNING=\$(ps aux | grep etf_trader | grep -v grep | wc -l)
if [ \$RUNNING -gt 0 ]; then
    echo "WARNING: \$RUNNING processes still running"
    ps aux | grep etf_trader | grep -v grep
else
    echo "✓ All training processes stopped"
fi
EOF

echo ""

# Step 4: Start optimized training
echo "[4/4] Starting optimized training..."
sshpass -p "$PASSWORD" ssh -p $PORT $SERVER << EOF
cd $REMOTE_DIR

# Create output directory
mkdir -p $OUT_DIR

# Launch training in background with nohup
nohup python scripts/research/etf_trader_parallel_search_optimized.py \
    --account $ACCOUNT \
    --out $OUT_DIR \
    --stage-a-episodes $STAGE_A_EP \
    --stage-b-episodes $STAGE_B_EP \
    --batch-worlds $BATCH_WORLDS \
    --parallel $PARALLEL \
    --workers-factor 2.0 \
    --device cuda \
    --gpu-id 0 \
    > ${OUT_DIR}/training.log 2>&1 &

TRAIN_PID=\$!
echo "Training started with PID: \$TRAIN_PID"
echo \$TRAIN_PID > ${OUT_DIR}/train.pid

# Wait a moment and check if it's still running
sleep 5
if ps -p \$TRAIN_PID > /dev/null; then
    echo "✓ Training process confirmed running"
    echo ""
    echo "Monitor with:"
    echo "  tail -f ${REMOTE_DIR}/${OUT_DIR}/training.log"
else
    echo "ERROR: Training process died immediately"
    echo "Check logs:"
    echo "  cat ${REMOTE_DIR}/${OUT_DIR}/training.log"
    exit 1
fi
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "======================================================================"
    echo "✓ Optimized training deployed and started successfully!"
    echo "======================================================================"
    echo ""
    echo "Monitoring commands:"
    echo "  # View training log"
    echo "  sshpass -p '$PASSWORD' ssh -p $PORT $SERVER 'tail -f ${REMOTE_DIR}/${OUT_DIR}/training.log'"
    echo ""
    echo "  # Check GPU usage"
    echo "  sshpass -p '$PASSWORD' ssh -p $PORT $SERVER 'watch -n 10 nvidia-smi'"
    echo ""
    echo "  # Check training progress"
    echo "  sshpass -p '$PASSWORD' ssh -p $PORT $SERVER 'find ${REMOTE_DIR}/${OUT_DIR} -name \"train.log\" | head -5 | xargs tail -1'"
    echo ""
    echo "Expected improvements:"
    echo "  - No 10-minute batch gaps (P0-1 fixed)"
    echo "  - No OOM errors (P0-2: parallel=14)"
    echo "  - Episode speed: ~6.5 minutes (P1-3: workers=28)"
    echo "  - Enhanced logging with g_dd, g_cvar, turnover"
    echo "  - Resource monitoring every 60 seconds"
    echo ""
else
    echo "ERROR: Deployment failed"
    exit 1
fi
