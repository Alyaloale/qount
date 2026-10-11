#!/bin/bash
# Check dual GPU pipeline test status

echo "======================================================================"
echo "Dual GPU Pipeline Test Status"
echo "======================================================================"
echo ""

echo "[3090 Status]"
sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com << 'EOF'
echo "Processes: $(ps aux | grep python3 | grep etf_trader_train | grep -v grep | wc -l)"
echo ""
echo "Latest test:"
LATEST=$(ls -td /root/autodl-tmp/experiments/p2_3090_pipeline_* 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    echo "$LATEST"
    echo ""
    echo "Progress (last 3 lines):"
    tail -3 "$LATEST/train.log" 2>/dev/null || echo "No log yet"
fi
echo ""
echo "GPU:"
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader
EOF

echo ""
echo "======================================================================"
echo ""

echo "[WSL Status]"
ssh qount-wsl << 'EOF'
echo "Processes: $(ps aux | grep python3 | grep etf_trader_train | grep -v grep | wc -l)"
echo ""
echo "Latest test:"
LATEST=$(ls -td ~/Code/qount/experiments/p2_wsl_pipeline_* 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    echo "$LATEST"
    echo ""
    echo "Progress (last 3 lines):"
    tail -3 "$LATEST/train.log" 2>/dev/null || echo "No log yet"
fi
EOF

echo ""
echo "======================================================================"
