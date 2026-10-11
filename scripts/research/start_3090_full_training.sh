#!/bin/bash
# 3090 Complete Training with Monitoring
# Stage A: 32 configs × 30 episodes
# Stage B: 45 configs × 100 episodes

set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/p2_us_full_${TIMESTAMP}"
LOG_DIR="${OUT_DIR}/monitoring"

echo "======================================================================"
echo "P2 Complete Training - 3090 Server"
echo "======================================================================"
echo "Stage A: 32 configs × 30 episodes"
echo "Stage B: 45 configs × 100 episodes"
echo "Estimated: 8-10 hours"
echo "======================================================================"
echo ""

cd /root/autodl-tmp

# Stop any existing training
pkill -9 -f etf_trader 2>/dev/null || true
sleep 3

# Create directories
mkdir -p $OUT_DIR
mkdir -p $LOG_DIR

# Start GPU monitoring in background
echo "Starting GPU monitoring..."
nohup bash -c "
while true; do
    nvidia-smi --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw \
        --format=csv >> ${LOG_DIR}/gpu_monitor.csv
    sleep 10
done
" > ${LOG_DIR}/gpu_monitor.log 2>&1 &
GPU_MON_PID=$!
echo "GPU monitoring started (PID: $GPU_MON_PID)"

# Start CPU/Memory monitoring in background
echo "Starting CPU/Memory monitoring..."
nohup bash -c "
echo 'timestamp,cpu_percent,mem_used_gb,mem_total_gb,mem_percent' > ${LOG_DIR}/system_monitor.csv
while true; do
    TIMESTAMP=\$(date '+%Y-%m-%d %H:%M:%S')
    CPU=\$(top -bn1 | grep 'Cpu(s)' | awk '{print \$2}' | cut -d'%' -f1)
    MEM=\$(free -g | grep Mem | awk '{print \$3\",\"\$2\",\"\$3/\$2*100}')
    echo \"\$TIMESTAMP,\$CPU,\$MEM\" >> ${LOG_DIR}/system_monitor.csv
    sleep 30
done
" > ${LOG_DIR}/system_monitor.log 2>&1 &
SYS_MON_PID=$!
echo "System monitoring started (PID: $SYS_MON_PID)"

# Save monitoring PIDs
echo $GPU_MON_PID > ${LOG_DIR}/gpu_monitor.pid
echo $SYS_MON_PID > ${LOG_DIR}/system_monitor.pid

echo ""
echo "Monitoring started, launching training..."
echo ""

# Launch complete training
nohup python3 scripts/research/etf_trader_parallel_search_optimized.py \
    --account us \
    --out $OUT_DIR \
    --stage-a-episodes 30 \
    --stage-b-episodes 100 \
    --batch-worlds 256 \
    --parallel 10 \
    --workers-factor 3.0 \
    --device cuda \
    --gpu-id 0 \
    > ${OUT_DIR}/training.log 2>&1 &

TRAIN_PID=$!
echo $TRAIN_PID > ${OUT_DIR}/train.pid

echo "✓ Training started (PID: $TRAIN_PID)"
echo ""
echo "======================================================================"
echo "Monitoring & Logs:"
echo "======================================================================"
echo "Training log:    tail -f /root/autodl-tmp/${OUT_DIR}/training.log"
echo "GPU monitor:     tail -f /root/autodl-tmp/${LOG_DIR}/gpu_monitor.csv"
echo "System monitor:  tail -f /root/autodl-tmp/${LOG_DIR}/system_monitor.csv"
echo ""
echo "Stop monitoring:"
echo "  kill \$(cat /root/autodl-tmp/${LOG_DIR}/gpu_monitor.pid)"
echo "  kill \$(cat /root/autodl-tmp/${LOG_DIR}/system_monitor.pid)"
echo ""
