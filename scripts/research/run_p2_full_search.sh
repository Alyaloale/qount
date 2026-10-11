#!/bin/bash
# P2 完整搜索启动脚本（测试通过后使用）
# 预计时间：2.5-3.5 小时

set -euo pipefail

ACCOUNT="${1:-us}"
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
OUT_DIR="/mnt/e/qount_data/qount/artifacts/experiments/p2_parallel_search_${TIMESTAMP}"

echo "=== P2 Parallel Capacity Search ==="
echo "Account: $ACCOUNT"
echo "Output: $OUT_DIR"
echo "Timestamp: $TIMESTAMP"
echo ""

# 检查环境
if [ ! -d "p2_train_venv" ]; then
    echo "Error: p2_train_venv not found"
    exit 1
fi

source p2_train_venv/bin/activate

# 检查 GPU
echo "GPU Status:"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader
echo ""

# 确认开始
read -p "Start full capacity search? This will take ~3 hours. (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# 运行搜索
echo ""
echo "Starting capacity search..."
echo "You can detach with Ctrl+b d and reattach with: tmux attach -t p2_$ACCOUNT"
echo ""

python3 scripts/research/etf_trader_parallel_search.py \
    --account "$ACCOUNT" \
    --out "$OUT_DIR" \
    --stage-a-episodes 30 \
    --stage-b-episodes 100 \
    --parallel 4 \
    --batch-worlds 256 \
    --workers 16 \
    --device cuda \
    --gpu-id 0

echo ""
echo "=== Search Complete ==="
echo "Results: $OUT_DIR"
echo ""
echo "Check results:"
echo "  cat $OUT_DIR/stage_a_results.json | jq '.[:5]'"
echo "  cat $OUT_DIR/selected_config.json | jq"
