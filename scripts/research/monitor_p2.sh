#!/bin/bash
# Monitor P2 parallel training progress

echo "=== P2 Training Monitor ==="
echo "Time: $(date)"
echo ""

# Check GPU utilization
echo "GPU Status:"
nvidia-smi --query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "  (nvidia-smi not available)"
echo ""

# Check running processes
echo "Training Processes:"
ps aux | grep "etf_trader" | grep -v grep | wc -l | xargs echo "  Active training processes:"
echo ""

# Check recent output files
if [ -d "/tmp/p2_test" ]; then
    echo "Test Output:"
    find /tmp/p2_test -name "meta.json" -o -name "history.json" | head -5
    echo ""
fi

if [ -d "/mnt/e/qount_data/qount/artifacts/experiments" ]; then
    echo "Recent Experiments:"
    ls -lht /mnt/e/qount_data/qount/artifacts/experiments | grep p2 | head -3
fi
