#!/bin/bash
# Minimal Scale Validation Test - Single config, 3 episodes
# Purpose: Verify optimized code works before full training

set -e

echo "======================================================================"
echo "P2 Minimal Scale Validation (Optimized Code)"
echo "======================================================================"
echo "Test: 1 config × 1 seed × 3 episodes"
echo "Purpose: Verify code correctness before full training"
echo "Time: ~10 minutes per GPU"
echo "======================================================================"
echo ""

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Stop all existing training
echo "[0/3] Stopping all existing training..."
sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com "pkill -f etf_trader 2>/dev/null || true"
ssh qount-wsl "pkill -f etf_trader 2>/dev/null || true"
sleep 3
echo "✓ All training stopped"
echo ""

# ============================================================
# 3090 Test: Direct train.py call
# ============================================================
echo "[1/3] Starting 3090 minimal test..."

sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com << EOF
cd /root/autodl-tmp

# Create test directory
mkdir -p experiments/p2_minimal_test_3090_${TIMESTAMP}

# Run single training directly
nohup python3 scripts/research/etf_trader_train.py \
    --account us \
    --out experiments/p2_minimal_test_3090_${TIMESTAMP} \
    --d-phi 16 \
    --hidden 32 \
    --layers 1 \
    --lr 3e-4 \
    --episodes 3 \
    --batch-worlds 128 \
    --seed 20260930 \
    --workers 4 \
    --device cuda \
    > experiments/p2_minimal_test_3090_${TIMESTAMP}/test.log 2>&1 &

echo "3090 test PID: \$!"
sleep 2
ps aux | grep python3 | grep etf_trader_train | grep -v grep | head -1
EOF

echo "✓ 3090 test launched (direct train.py)"
echo ""

# ============================================================
# WSL Test: Direct train.py call with PYTHONPATH
# ============================================================
echo "[2/3] Starting WSL minimal test..."

ssh qount-wsl << 'EOF'
cd ~/Code/qount

# Set PYTHONPATH to include venv_upper packages
export PYTHONPATH=~/venv_upper/lib/python3.12/site-packages:~/Code/qount

# Create test directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p experiments/p2_minimal_test_wsl_${TIMESTAMP}

# Run single training directly
nohup python3 scripts/research/etf_trader_train.py \
    --account us \
    --out experiments/p2_minimal_test_wsl_${TIMESTAMP} \
    --d-phi 16 \
    --hidden 32 \
    --layers 1 \
    --lr 3e-4 \
    --episodes 3 \
    --batch-worlds 128 \
    --seed 20260930 \
    --workers 4 \
    --device cuda \
    > experiments/p2_minimal_test_wsl_${TIMESTAMP}/test.log 2>&1 &

echo "WSL test PID: \$!"
sleep 2
ps aux | grep python3 | grep etf_trader_train | grep -v grep | head -1
EOF

echo "✓ WSL test launched (direct train.py)"
echo ""

# ============================================================
# Verification
# ============================================================
echo "[3/3] Verifying processes started..."
echo ""

echo "3090 processes:"
sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com \
    "ps aux | grep etf_trader_train | grep -v grep | wc -l"

echo ""
echo "WSL processes:"
ssh qount-wsl "ps aux | grep etf_trader_train | grep -v grep | wc -l"

echo ""
echo "======================================================================"
echo "✓ Minimal tests launched on both GPUs"
echo "======================================================================"
echo ""
echo "Expected: ~10 minutes to complete (3 episodes)"
echo ""
echo "Monitor 3090:"
echo "  sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com \\"
echo "    'tail -f /root/autodl-tmp/experiments/p2_minimal_test_3090_*/test.log'"
echo ""
echo "Monitor WSL:"
echo "  ssh qount-wsl 'tail -f ~/Code/qount/experiments/p2_minimal_test_wsl_*/test.log'"
echo ""
echo "Success criteria:"
echo "  ✓ No crashes or OOM"
echo "  ✓ 3 episodes complete"
echo "  ✓ Enhanced logging visible (g_dd, g_cvar, turnover)"
echo "  ✓ Resource monitoring working"
echo ""
