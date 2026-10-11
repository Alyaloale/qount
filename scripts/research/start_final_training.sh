#!/bin/bash
# P2 最终训练脚本 - 基于完整分析和优化

set -e

echo "============================================================"
echo "P2 模仿学习训练 - 最终配置"
echo "============================================================"
echo
echo "配置："
echo "  - 并行进程: 16（充分利用 24GB 显存）"
echo "  - compile_mode: max-autotune（2% 加速）"
echo "  - Stage A: 30 episodes（文档配置）"
echo "  - Stage B: 100 episodes（文档配置）"
echo
echo "预期时间："
echo "  - Stage A: ~1.8 小时"
echo "  - Stage B: ~8.6 小时"
echo "  - 总计: ~10.4 小时"
echo "============================================================"
echo

# 检查环境
if ! nvidia-smi &>/dev/null; then
    echo "错误: 未检测到 GPU"
    exit 1
fi

# 显示 GPU 信息
echo "GPU 状态:"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader
echo

# 询问确认
read -p "开始训练? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# 创建输出目录
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/p2_us_final_${TIMESTAMP}"
mkdir -p "$OUT_DIR"

echo
echo "输出目录: $OUT_DIR"
echo "开始时间: $(date)"
echo

# 运行训练
source /root/miniconda3/bin/activate
cd /root/autodl-tmp

python scripts/research/etf_trader_parallel_search.py \
    --account us \
    --out "$OUT_DIR" \
    --stage-a-episodes 30 \
    --stage-b-episodes 100 \
    --parallel 16 \
    --workers 20 \
    --batch-worlds 256 \
    2>&1 | tee "${OUT_DIR}/training.log"

EXIT_CODE=$?

echo
echo "============================================================"
echo "训练完成"
echo "============================================================"
echo "结束时间: $(date)"
echo "退出码: $EXIT_CODE"
echo "结果目录: $OUT_DIR"
echo

if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ 训练成功完成"
    echo
    echo "查看结果:"
    echo "  cd $OUT_DIR"
    echo "  cat stage_a_results.json"
    echo "  cat selected_config.json"
else
    echo "✗ 训练失败"
    echo
    echo "检查日志:"
    echo "  tail -100 ${OUT_DIR}/training.log"
fi

exit $EXIT_CODE
