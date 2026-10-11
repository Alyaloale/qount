#!/bin/bash
# Check status of dual GPU pipeline tests

echo "======================================================================"
echo "Dual GPU Pipeline Test Status Check"
echo "======================================================================"
echo ""

echo "[3090 Server Status]"
sshpass -p 'uYBtc8pn9ond' ssh -p 41489 -o StrictHostKeyChecking=no root@connect.nmb2.seetacloud.com << 'EOF'
echo "Processes:"
ps aux | grep etf_trader | grep -v grep | wc -l

echo ""
echo "Latest test directory:"
ls -td /root/autodl-tmp/experiments/p2_pipeline_test_3090_* 2>/dev/null | head -1

echo ""
echo "Progress (last 5 lines):"
LATEST=$(ls -td /root/autodl-tmp/experiments/p2_pipeline_test_3090_* 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    tail -5 "$LATEST/test.log" 2>/dev/null || echo "No log yet"
fi

echo ""
echo "GPU usage:"
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
EOF

echo ""
echo "======================================================================"
echo ""

echo "[WSL 4060 Status]"
ssh qount-wsl << 'EOF'
echo "Processes:"
ps aux | grep etf_trader | grep -v grep | wc -l

echo ""
echo "Latest test directory:"
ls -td ~/Code/qount/experiments/p2_pipeline_test_wsl_* 2>/dev/null | head -1

echo ""
echo "Progress (last 5 lines):"
LATEST=$(ls -td ~/Code/qount/experiments/p2_pipeline_test_wsl_* 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    tail -5 "$LATEST/test.log" 2>/dev/null || echo "No log yet"
fi
EOF

echo ""
echo "======================================================================"
