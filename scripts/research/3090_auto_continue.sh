#!/bin/bash
# 3090 Auto-Continue Training Script
# 监控当前训练，完成后自动启动Stage B或完整重训练

set -e

echo "======================================================================"
echo "3090 Auto-Continue Training Monitor"
echo "======================================================================"
echo "监控当前训练: p2_us_optimized_20261002_040315"
echo "主进程PID: 61653"
echo "配置: parallel=5, workers=6"
echo "======================================================================"
echo ""

# 当前训练配置
CURRENT_PID=61653
CURRENT_EXP="p2_us_optimized_20261002_040315"

# 检查训练是否还在运行
check_training_running() {
    ps -p $CURRENT_PID > /dev/null 2>&1
    return $?
}

echo "步骤1: 监控当前Stage A训练..."
echo "预计完成时间: 08:33 (约4.5小时)"
echo ""

# 循环检查训练状态
WAIT_COUNT=0
while check_training_running; do
    WAIT_COUNT=$((WAIT_COUNT + 1))

    # 每30分钟报告一次
    if [ $((WAIT_COUNT % 180)) -eq 0 ]; then
        HOURS=$((WAIT_COUNT / 360))
        MINUTES=$(((WAIT_COUNT % 360) / 6))
        echo "[等待 ${HOURS}h ${MINUTES}m] Stage A训练仍在运行..."

        # 显示GPU状态
        echo "  GPU状态:"
        nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv,noheader | sed 's/^/    /'

        # 统计完成的配置数
        COMPLETED=$(find /root/autodl-tmp/experiments/${CURRENT_EXP}/stage_a -type d -name "phi*" 2>/dev/null | wc -l)
        echo "  已启动配置: ${COMPLETED}/32"
    fi

    sleep 10
done

echo ""
echo "======================================================================"
echo "✓ Stage A训练已完成！"
echo "======================================================================"
COMPLETION_TIME=$(date '+%Y-%m-%d %H:%M:%S')
echo "完成时间: $COMPLETION_TIME"
echo ""

# 统计Stage A结果
echo "正在统计Stage A结果..."
STAGE_A_CONFIGS=$(find /root/autodl-tmp/experiments/${CURRENT_EXP}/stage_a -name 'train.log' 2>/dev/null | wc -l)
echo "  完成配置数: $STAGE_A_CONFIGS"

# 检查约束满足率
echo "  检查约束满足率..."
CONSTRAINT_CHECK=$(find /root/autodl-tmp/experiments/${CURRENT_EXP}/stage_a -name 'train.log' -exec grep -l 'p95_max_dd' {} \; 2>/dev/null | wc -l)
echo "  有约束数据的配置: $CONSTRAINT_CHECK"

echo ""
echo "等待30秒后启动Stage B训练..."
sleep 30

# 生成新的输出目录
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NEW_EXP="p2_us_stage_b_${TIMESTAMP}"
NEW_OUT="/root/autodl-tmp/experiments/${NEW_EXP}"
LOG_DIR="${NEW_OUT}/monitoring"

echo ""
echo "======================================================================"
echo "步骤2: 启动Stage B训练"
echo "======================================================================"
echo "输出目录: $NEW_OUT"
echo "配置: parallel=5, workers=6 (优化配置)"
echo "Stage B: 45配置 × 100 episodes"
echo "预计时间: 2-3小时"
echo "======================================================================"
echo ""

cd /root/autodl-tmp

# 创建目录
mkdir -p $NEW_OUT
mkdir -p $LOG_DIR

# 启动GPU监控
echo "Starting GPU monitoring..."
nohup bash -c "
while true; do
    nvidia-smi --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw \
        --format=csv >> ${LOG_DIR}/gpu_monitor.csv
    sleep 10
done
" > ${LOG_DIR}/gpu_monitor.log 2>&1 &
GPU_MON_PID=$!
echo $GPU_MON_PID > ${LOG_DIR}/gpu_monitor.pid
echo "GPU monitoring started (PID: $GPU_MON_PID)"

# 启动CPU/内存监控
echo "Starting CPU/Memory monitoring..."
nohup bash -c "
echo 'timestamp,cpu_percent,mem_used_gb,mem_total_gb,mem_percent' > ${LOG_DIR}/system_monitor.csv
while true; do
    TIMESTAMP=\$(date '+%Y-%m-%d %H:%M:%S')
    CPU=\$(top -bn1 | grep 'Cpu(s)' | awk '{print \$2}' | cut -d'%' -f1)
    MEM=\$(free -g | grep Mem | awk '{print \$3\",\"\$2\",\"\$3/\$2*100}')
    echo \"\$TIMESTAMP,\$CPU,\$MEM\" >> ${LOG_DIR}/system_monitor.csv
    sleep 30
done
" > ${LOG_DIR}/system_monitor.log 2>&1 &
SYS_MON_PID=$!
echo $SYS_MON_PID > ${LOG_DIR}/system_monitor.pid
echo "System monitoring started (PID: $SYS_MON_PID)"

echo ""
echo "Launching Stage B training..."

# 启动Stage B训练（仅Stage B，跳过Stage A）
nohup /root/miniconda3/bin/python3.12 scripts/research/etf_trader_parallel_search_optimized.py \
    --account us \
    --out $NEW_OUT \
    --stage-a-episodes 0 \
    --stage-b-episodes 100 \
    --batch-worlds 256 \
    --parallel 5 \
    --workers-factor 6.0 \
    --device cuda \
    --gpu-id 0 \
    > ${NEW_OUT}/training.log 2>&1 &

NEW_PID=$!
echo $NEW_PID > ${NEW_OUT}/train.pid

echo ""
echo "✓ Stage B训练已启动！"
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
echo "  nvidia-smi"
echo ""
echo "预计完成时间: $(date -d '+3 hours' '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"
echo ""
echo "脚本执行完成。Stage B训练将在后台继续运行。"
echo ""
