#!/bin/bash
# Dual GPU Ultra-Small Scale Validation with Pipeline Mode
# Tests optimized code on both 3090 and WSL 4060 with minimal episodes

set -e

echo "======================================================================"
echo "P2 Dual GPU Ultra-Small Scale Validation (Pipeline Mode)"
echo "======================================================================"
echo "Test: 2 configs × 1 seed × 5 episodes"
echo "Mode: Pipeline (world gen + GPU training parallel)"
echo "GPUs: 3090 (parallel=2) + WSL 4060 (parallel=2)"
echo "======================================================================"
echo ""

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# ============================================================
# 3090 Server Test
# ============================================================
echo "[1/2] Starting 3090 pipeline test..."

sshpass -p 'uYBtc8pn9ond' ssh -p 41489 -o StrictHostKeyChecking=no root@connect.nmb2.seetacloud.com << 'EOF'
cd /root/autodl-tmp

# Stop any existing training
pkill -f etf_trader 2>/dev/null || true
sleep 2

# Launch pipeline test
nohup python scripts/research/etf_trader_parallel_search_optimized.py \
    --account us \
    --out experiments/p2_pipeline_test_3090_${TIMESTAMP} \
    --stage-a-episodes 5 \
    --stage b \
    --parallel 2 \
    --workers-factor 2.0 \
    --test \
    > experiments/p2_pipeline_test_3090_${TIMESTAMP}/test.log 2>&1 &

echo "3090 test started (PID: $!)"
sleep 3
ps aux | grep etf_trader | grep -v grep | head -1
EOF

echo "✓ 3090 test launched"
echo ""

# ============================================================
# WSL 4060 Test
# ============================================================
echo "[2/2] Starting WSL 4060 pipeline test..."

ssh qount-wsl << 'EOF'
cd ~/Code/qount

# Set Python path to use venv_upper packages
export PYTHONPATH=~/venv_upper/lib/python3.12/site-packages:~/Code/qount

# Stop any existing training
pkill -f etf_trader 2>/dev/null || true
sleep 2

# Create test directory
mkdir -p experiments/p2_pipeline_test_wsl_${TIMESTAMP}

# Launch pipeline test
nohup python3 scripts/research/etf_trader_parallel_search_optimized.py \
    --account us \
    --out experiments/p2_pipeline_test_wsl_${TIMESTAMP} \
    --stage-a-episodes 5 \
    --stage b \
    --parallel 2 \
    --workers-factor 2.0 \
    --test \
    > experiments/p2_pipeline_test_wsl_${TIMESTAMP}/test.log 2>&1 &

echo "WSL test started (PID: $!)"
sleep 3
ps aux | grep etf_trader | grep -v grep | head -1
EOF

echo "✓ WSL test launched"
echo ""

# ============================================================
# Monitoring
# ============================================================
echo "======================================================================"
echo "Both tests launched successfully!"
echo "======================================================================"
echo ""
echo "Expected duration: ~15-20 minutes per test"
echo ""
echo "Monitoring commands:"
echo ""
echo "# 3090 progress:"
echo "sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com \\"
echo "  'tail -f /root/autodl-tmp/experiments/p2_pipeline_test_3090_*/test.log'"
echo ""
echo "# WSL progress:"
echo "ssh qount-wsl 'tail -f ~/Code/qount/experiments/p2_pipeline_test_wsl_*/test.log'"
echo ""
echo "# Check both:"
echo "./scripts/research/check_dual_test_status.sh"
echo ""
echo "Key metrics to verify:"
echo "  - Pipeline mode enabled"
echo "  - No OOM errors"
echo "  - Episode speed ~3-4 minutes (with pipeline)"
echo "  - Enhanced logging (g_dd, g_cvar, turnover)"
echo ""
