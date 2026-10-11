#!/bin/bash
# Monitor dual GPU training progress

echo "======================================================================"
echo "Dual GPU Training Monitor"
echo "======================================================================"
echo ""

echo "[3090 Status]"
sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com << 'EOF'
LATEST=$(ls -td /root/autodl-tmp/experiments/p2_us_full_* 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    echo "Directory: $LATEST"
    echo ""

    # Training progress
    echo "=== Training Progress ==="
    tail -5 "$LATEST/training.log" 2>/dev/null | grep episode || echo "No episode data yet"

    echo ""
    echo "=== GPU Status (last 3 readings) ==="
    tail -3 "$LATEST/monitoring/gpu_monitor.csv" 2>/dev/null || echo "No GPU data yet"

    echo ""
    echo "=== System Status (last 3 readings) ==="
    tail -3 "$LATEST/monitoring/system_monitor.csv" 2>/dev/null || echo "No system data yet"

    echo ""
    echo "=== Process Count ==="
    ps aux | grep etf_trader | grep -v grep | wc -l
else
    echo "No training directory found"
fi
EOF

echo ""
echo "======================================================================"
echo ""

echo "[WSL Status]"
ssh qount-wsl << 'EOF'
LATEST=$(ls -td ~/Code/qount/experiments/p2_us_full_wsl_* 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    echo "Directory: $LATEST"
    echo ""

    # Training progress
    echo "=== Training Progress ==="
    tail -5 "$LATEST/training.log" 2>/dev/null | grep episode || echo "No episode data yet"

    echo ""
    echo "=== GPU Status (last 3 readings) ==="
    tail -3 "$LATEST/monitoring/gpu_monitor.csv" 2>/dev/null || echo "No GPU data yet"

    echo ""
    echo "=== System Status (last 3 readings) ==="
    tail -3 "$LATEST/monitoring/system_monitor.csv" 2>/dev/null || echo "No system data yet"

    echo ""
    echo "=== Process Count ==="
    ps aux | grep etf_trader | grep -v grep | wc -l
else
    echo "No training directory found"
fi
EOF

echo ""
echo "======================================================================"
