#!/bin/bash
# 双端最小规模验证 - 不使用pipeline参数（使用默认train.py）

set -e

echo "======================================================================"
echo "双端最小规模验证"
echo "======================================================================"
echo "测试：1配置 × 3 episodes"
echo "3090: 10并行 × 30 workers"
echo "WSL:  4并行 × 32 workers"
echo "======================================================================"
echo ""

# ============================================================
# 3090启动
# ============================================================
echo "[1/2] 启动3090测试..."
sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com << 'EOF'
cd /root/autodl-tmp
pkill -9 -f etf_trader 2>/dev/null || true
sleep 2

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/p2_3090_test_${TIMESTAMP}"
mkdir -p $OUT_DIR

# 找到Python
PYTHON=$(which python3.12 || which python3 || which python)
echo "使用Python: $PYTHON"

# 启动训练（不使用--pipeline参数）
nohup $PYTHON scripts/research/etf_trader_train.py \
    --account us \
    --out $OUT_DIR \
    --d-phi 16 \
    --hidden 32 \
    --layers 1 \
    --lr 3e-4 \
    --episodes 3 \
    --batch-worlds 256 \
    --seed 20260930 \
    --workers 30 \
    --device cuda \
    > $OUT_DIR/train.log 2>&1 &

echo "✓ 3090训练启动 (PID: $!)"
EOF

echo ""

# ============================================================
# WSL启动
# ============================================================
echo "[2/2] 启动WSL测试..."
ssh qount-wsl << 'EOF'
cd ~/Code/qount
export PYTHONPATH=~/venv_upper/lib/python3.12/site-packages:~/Code/qount/src

pkill -9 -f etf_trader 2>/dev/null || true
sleep 2

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/p2_wsl_test_${TIMESTAMP}"
mkdir -p $OUT_DIR

# 启动训练（不使用--pipeline参数）
nohup python3 scripts/research/etf_trader_train.py \
    --account us \
    --out $OUT_DIR \
    --d-phi 16 \
    --hidden 32 \
    --layers 1 \
    --lr 3e-4 \
    --episodes 3 \
    --batch-worlds 256 \
    --seed 20260930 \
    --workers 32 \
    --device cuda \
    > $OUT_DIR/train.log 2>&1 &

echo "✓ WSL训练启动 (PID: $!)"
EOF

echo ""
echo "======================================================================"
echo "✓ 双端测试已启动"
echo "======================================================================"
echo ""
echo "预计完成时间：~20分钟（3 episodes × 6-7分钟）"
echo ""
echo "监控命令："
echo "  3090: sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com 'tail -f /root/autodl-tmp/experiments/p2_3090_test_*/train.log'"
echo "  WSL:  ssh qount-wsl 'tail -f ~/Code/qount/experiments/p2_wsl_test_*/train.log'"
echo ""
