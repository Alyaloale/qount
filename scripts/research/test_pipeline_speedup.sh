#!/bin/bash
# 测试流水线优化的加速效果
# 运行 3 episodes 对比基线版和流水线版的时间

set -e

ACCOUNT="us"
EPISODES=3
BATCH=256
WORKERS=16
DEVICE="cuda"

echo "=== P2 流水线优化测试 ==="
echo "配置: $EPISODES episodes, $BATCH worlds/episode, $WORKERS workers"
echo ""

# 基线版本
echo "[1/2] 运行基线版本（无流水线）..."
BASE_OUT="/tmp/p2_baseline_$(date +%s)"
python scripts/research/etf_trader_train.py \
    --account $ACCOUNT \
    --out $BASE_OUT \
    --episodes $EPISODES \
    --batch-worlds $BATCH \
    --workers $WORKERS \
    --device $DEVICE \
    --d-phi 16 --hidden 16 --layers 1 \
    2>&1 | tee /tmp/baseline.log

BASE_TIME=$(jq -r '.history[-1].seconds' $BASE_OUT/history.json)
BASE_GEN=$(jq -r '[.history[].time_gen] | add / length' $BASE_OUT/history.json)
BASE_ROLLOUT=$(jq -r '[.history[].time_rollout] | add / length' $BASE_OUT/history.json)

echo ""
echo "基线版本完成: 平均 episode 时间 = ${BASE_TIME}s"
echo "  - 世界生成: ${BASE_GEN}s"
echo "  - GPU 训练: ${BASE_ROLLOUT}s"
echo ""

# 流水线版本
echo "[2/2] 运行流水线版本..."
PIPE_OUT="/tmp/p2_pipelined_$(date +%s)"
python scripts/research/etf_trader_train.py \
    --account $ACCOUNT \
    --out $PIPE_OUT \
    --episodes $EPISODES \
    --batch-worlds $BATCH \
    --workers $WORKERS \
    --device $DEVICE \
    --d-phi 16 --hidden 16 --layers 1 \
    --pipeline \
    2>&1 | tee /tmp/pipelined.log

PIPE_TIME=$(jq -r '.history[-1].seconds' $PIPE_OUT/history.json)
PIPE_GEN=$(jq -r '[.history[].time_gen] | add / length' $PIPE_OUT/history.json)
PIPE_ROLLOUT=$(jq -r '[.history[].time_rollout] | add / length' $PIPE_OUT/history.json)
PIPE_TRANSFER=$(jq -r '[.history[].time_transfer] | add / length' $PIPE_OUT/history.json)

echo ""
echo "流水线版本完成: 平均 episode 时间 = ${PIPE_TIME}s"
echo "  - 世界生成: ${PIPE_GEN}s (并行)"
echo "  - 数据传输: ${PIPE_TRANSFER}s (异步)"
echo "  - GPU 训练: ${PIPE_ROLLOUT}s"
echo ""

# 计算加速比
SPEEDUP=$(echo "scale=2; $BASE_TIME / $PIPE_TIME" | bc)
SAVED_PCT=$(echo "scale=1; ($BASE_TIME - $PIPE_TIME) / $BASE_TIME * 100" | bc)

echo "=== 结果对比 ==="
echo "基线:   ${BASE_TIME}s/episode"
echo "流水线: ${PIPE_TIME}s/episode"
echo "加速比: ${SPEEDUP}x"
echo "节省:   ${SAVED_PCT}%"
echo ""

if (( $(echo "$SPEEDUP > 1.3" | bc -l) )); then
    echo "✅ 优化成功！加速比超过 1.3x，建议部署到生产训练"
    exit 0
else
    echo "⚠️  加速比低于预期（目标 1.5x），需要进一步调试"
    exit 1
fi
