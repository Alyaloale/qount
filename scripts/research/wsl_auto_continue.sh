#!/bin/bash
# WSL自动连续训练脚本
# 当前训练完成后，自动启动完整Stage A+B训练

set -e

echo "======================================================================"
echo "WSL Auto-Continue Training Script"
echo "======================================================================"
echo "监控当前训练，完成后自动启动完整训练"
echo "当前训练: ~/Code/qount/experiments/p2_us_full_wsl_20261002_033008"
echo "预计完成: 04:48 (43分钟后)"
echo "======================================================================"
echo ""

# 当前训练配置
CURRENT_EXP="p2_us_full_wsl_20261002_033008"
CURRENT_PID=2507

# 新训练配置
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NEW_EXP="p2_us_complete_auto_${TIMESTAMP}"
NEW_OUT="$HOME/Code/qount/experiments/${NEW_EXP}"

# 检查当前训练是否还在运行
check_training_running() {
    ps -p $CURRENT_PID > /dev/null 2>&1
    return $?
}

echo "步骤1: 等待当前训练完成..."
echo "监控进程: PID $CURRENT_PID"
echo ""

# 循环检查训练状态
WAIT_COUNT=0
while check_training_running; do
    WAIT_COUNT=$((WAIT_COUNT + 1))

    # 每10分钟报告一次
    if [ $((WAIT_COUNT % 60)) -eq 0 ]; then
        MINUTES=$((WAIT_COUNT / 60))
        echo "[等待 ${MINUTES} 分钟] 当前训练仍在运行..."

        # 获取最新进度
        LATEST_LOG=$(find ~/Code/qount/experiments/${CURRENT_EXP}/stage_a -name 'train.log' -exec tail -1 {} \; 2>/dev/null | grep episode | head -1)
        if [ ! -z "$LATEST_LOG" ]; then
            EPISODE=$(echo "$LATEST_LOG" | grep -o '"episode": [0-9]*' | cut -d' ' -f2)
            echo "  最新进度: Episode $EPISODE/30"
        fi
    fi

    sleep 10
done

echo ""
echo "======================================================================"
echo "✓ 当前训练已完成！"
echo "======================================================================"
echo ""
echo "等待5秒后启动完整训练..."
sleep 5

echo ""
echo "======================================================================"
echo "步骤2: 启动完整Stage A+B训练"
echo "======================================================================"
echo "输出目录: $NEW_OUT"
echo "Stage A: 32配置 × 30 episodes"
echo "Stage B: 45配置 × 100 episodes"
echo "预计时间: 8-10小时"
echo "======================================================================"
echo ""

# 创建输出目录
mkdir -p "$NEW_OUT"

# 启动新训练
cd ~/Code/qount

nohup python3 scripts/research/etf_trader_parallel_search_optimized.py \
    --account us \
    --out "experiments/${NEW_EXP}" \
    --stage-a-episodes 30 \
    --stage-b-episodes 100 \
    --batch-worlds 256 \
    --parallel 4 \
    --workers-factor 8.0 \
    --device cuda \
    --gpu-id 0 \
    > "${NEW_OUT}/training.log" 2>&1 &

NEW_PID=$!
echo $NEW_PID > "${NEW_OUT}/train.pid"

echo "✓ 完整训练已启动！"
echo ""
echo "======================================================================"
echo "训练信息"
echo "======================================================================"
echo "进程PID: $NEW_PID"
echo "输出目录: $NEW_OUT"
echo "训练日志: ${NEW_OUT}/training.log"
echo ""
echo "监控命令:"
echo "  tail -f ${NEW_OUT}/training.log"
echo "  ps -p $NEW_PID"
echo ""
echo "停止训练:"
echo "  kill $NEW_PID"
echo ""
echo "======================================================================"
echo "预计完成时间: $(date -d '+10 hours' '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"
echo ""
echo "脚本执行完成，训练将在后台继续运行。"
echo "您可以安心休息，训练会自动完成。"
echo ""
