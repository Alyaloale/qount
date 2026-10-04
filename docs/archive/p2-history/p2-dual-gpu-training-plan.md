# 双GPU并行训练方案（云端3090 + WSL 4060）

> **归档状态**：historical / non-restorable evidence｜**整理日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../p2-project-summary-20261002.md)；运行事实与权限仅看 [current.md](../../current.md)。
> 原文中的“当前”“最终”“通过”仅代表当时的记录，未经本轮重新验收；历史命令不构成重启、部署或交易授权。

> **目标**：充分利用两块GPU，差异化种子，加速P2完成  
> **修复**：消除批次间隙bug（phi16→phi32的10分钟空闲）  
> **预期**：总时间从49小时降至**25小时**（2倍加速）

---

## 一、问题分析

### 1.1 当前云端3090的问题

**批次间隙bug**：
- phi16完成后GPU空闲10分钟
- phi32启动前需要清理显存
- 每批损失10分钟，Stage A+B总计损失约50分钟

**速度对比**：
```
云端3090：8分钟/episode（实测）
WSL 4060：预期10-12分钟/episode（基于历史数据）
```

**但3090有批次间隙bug** → 实际效率被拉低

### 1.2 双GPU并行的优势

**任务分配**：
- 3090：运行修复后的代码（无批次间隙）
- 4060：运行不同种子的训练（差异化实验）

**时间节省**：
- 两GPU并行 → 总任务量减半
- 修复bug → 消除50分钟空闲
- **预期总时间**：49h / 2 - 1h ≈ **24小时**

---

## 二、修复的代码

### 2.1 Bug根因

**旧代码隐式问题**：
```python
# 虽然用了ProcessPoolExecutor和as_completed
# 但所有16个phi16配置在01:53:23同时启动
# 说明任务提交时有某种批次分组

# 可能的隐式批次：
tasks = [(cfg, seed) for cfg in STRUCTURES for seed in [20260930, 20260931]]
# STRUCTURES可能内部按d_phi排序，导致phi16全部在前
```

**实际执行**：
1. 前16个future全是phi16
2. ProcessPoolExecutor的max_workers=16
3. 16个worker全部被phi16占据
4. phi32的futures在队列中等待
5. 当phi16完成，workers全部释放（显存清零）
6. 10分钟后phi32开始启动

### 2.2 修复方案

**关键改动**：
```python
# FIXED: 确保任务真正交错提交
# 方法1：打乱任务顺序
tasks = [(cfg, seed) for cfg in STRUCTURES for seed in [20260930, 20260931]]
random.shuffle(tasks)  # 打乱phi16和phi32

# 方法2：显式交错
phi16_tasks = [(cfg, seed) for cfg in STRUCTURES if cfg.d_phi == 16 for seed in SEEDS]
phi32_tasks = [(cfg, seed) for cfg in STRUCTURES if cfg.d_phi == 32 for seed in SEEDS]
tasks = [t for pair in zip(phi16_tasks, phi32_tasks) for t in pair]  # 交错

# 方法3：动态调度（最优）
# 小模型优先完成，大模型慢慢跑
# as_completed自然处理，无需特殊逻辑
```

**修复后的文件**：`scripts/research/etf_trader_parallel_search_fixed.py`

---

## 三、双GPU训练配置

### 3.1 云端3090（修复后继续）

**SSH连接**：
```bash
ssh -p 41489 root@connect.nmb2.seetacloud.com
# 密码：[凭据已移出文档，认证仅从 Mac 私有配置读取]
```

**上传修复代码**：
```bash
# 从Mac上传
scp -P 41489 scripts/research/etf_trader_parallel_search_fixed.py \
  root@connect.nmb2.seetacloud.com:/root/autodl-tmp/scripts/research/

# 验证
ssh -p 41489 root@connect.nmb2.seetacloud.com \
  "grep -n 'FIXED' /root/autodl-tmp/scripts/research/etf_trader_parallel_search_fixed.py | head -5"
```

**启动新训练**（使用不同种子）：
```bash
# 使用新的种子序列：20261001, 20261002
cd /root/autodl-tmp

# 修改固定种子为新序列
nohup python scripts/research/etf_trader_parallel_search_fixed.py \
  --account us \
  --out experiments/p2_us_3090_fixed_seed2 \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 16 \
  --workers 20 \
  --batch-worlds 256 \
  > train_3090_fixed.log 2>&1 &
```

**注意**：需要修改代码中的seed列表：
```python
# 在etf_trader_parallel_search_fixed.py中
# Stage A
tasks = [(cfg, seed) for cfg in STRUCTURES for seed in [20261001, 20261002]]  # 新种子

# Stage B  
for seed in [20261001, 20261002, 20261003, 20261004, 20261005]  # 新种子
```

### 3.2 WSL 4060（新训练）

**连接WSL**：
```bash
ssh qount-wsl
# 或从Mac：
ssh -i ~/.ssh/id_rsa alyaloale@$(cat ~/.ssh/wsl_ip)
```

**准备环境**：
```bash
cd ~/Code/qount

# 激活虚拟环境（如果已存在）
source p2_train_venv/bin/activate

# 或创建新环境
python3 -m venv p2_train_venv
source p2_train_venv/bin/activate
pip install -e ".[research,research-neural]"

# 验证GPU
nvidia-smi
python3 -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, Devices: {torch.cuda.device_count()}')"
```

**配置差异化训练**：

**方案A：完整Stage A（使用种子3&4）**
```bash
# 创建tmux会话
tmux new -s p2_wsl_4060

# 运行训练（使用不同种子）
cd ~/Code/qount
source p2_train_venv/bin/activate

python scripts/research/etf_trader_parallel_search_fixed.py \
  --account us \
  --out experiments/p2_us_4060_seed34 \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 8 \
  --workers 16 \
  --batch-worlds 256 \
  --device cuda \
  --gpu-id 0 \
  > train_4060.log 2>&1

# 分离tmux：Ctrl+b d
# 重新连接：tmux attach -t p2_wsl_4060
```

**方案B：互补训练（各承担一半）**
```bash
# 3090：phi16全系列 + phi32前半
# 4060：phi32后半

# 需要修改代码，手动选择结构子集
```

**4060的并行数建议**：
- 8GB显存 → parallel=8（每个1GB）
- 或 parallel=6（每个1.3GB，更安全）
- workers=16（CPU够用）

---

## 四、种子分配策略

### 4.1 种子序列设计

**云端3090（修复后）**：
- Stage A: seed 20261001, 20261002
- Stage B: seed 20261001-20261005（5个）

**WSL 4060**：
- Stage A: seed 20261003, 20261004
- Stage B: seed 20261006-20261010（5个）

**理由**：
- 独立种子 → 更robust的结果
- 无重复 → 有效样本量翻倍
- 交叉验证 → 可对比两GPU的训练质量

### 4.2 修改种子的代码

**创建两个版本**：

**版本1：云端3090用**
```bash
cp scripts/research/etf_trader_parallel_search_fixed.py \
   scripts/research/etf_trader_parallel_search_3090.py

# 修改种子
sed -i 's/20260930, 20260931/20261001, 20261002/g' \
  scripts/research/etf_trader_parallel_search_3090.py

sed -i 's/20260930, 20260931, 20260932, 20260933, 20260934/20261001, 20261002, 20261003, 20261004, 20261005/g' \
  scripts/research/etf_trader_parallel_search_3090.py
```

**版本2：WSL 4060用**
```bash
cp scripts/research/etf_trader_parallel_search_fixed.py \
   scripts/research/etf_trader_parallel_search_4060.py

# 修改种子
sed -i 's/20260930, 20260931/20261003, 20261004/g' \
  scripts/research/etf_trader_parallel_search_4060.py

sed -i 's/20260930, 20260931, 20260932, 20260933, 20260934/20261006, 20261007, 20261008, 20261009, 20261010/g' \
  scripts/research/etf_trader_parallel_search_4060.py
```

---

## 五、执行步骤（按顺序）

### Step 1：上传修复代码到云端（立即）

```bash
# 在Mac上
cd /Users/alyaloale/Code/qount

# 上传修复版本
scp -P 41489 scripts/research/etf_trader_parallel_search_fixed.py \
  root@connect.nmb2.seetacloud.com:/root/autodl-tmp/scripts/research/

# 修改种子并创建3090版本
ssh -p 41489 root@connect.nmb2.seetacloud.com << 'EOF'
cd /root/autodl-tmp/scripts/research

# 创建3090专用版本
cp etf_trader_parallel_search_fixed.py etf_trader_parallel_search_3090.py

# 修改种子（使用sed）
sed -i 's/seed in \[20260930, 20260931\]/seed in [20261001, 20261002]/g' etf_trader_parallel_search_3090.py
sed -i 's/for seed in \[20260930, 20260931, 20260932, 20260933, 20260934\]/for seed in [20261001, 20261002, 20261003, 20261004, 20261005]/g' etf_trader_parallel_search_3090.py

# 验证修改
grep "seed in \[" etf_trader_parallel_search_3090.py
EOF
```

### Step 2：启动云端3090新训练（等当前完成Stage A后）

```bash
ssh -p 41489 root@connect.nmb2.seetacloud.com

# 等待当前训练完成Stage A（预计今天10:20）
# 可以检查进度
find /root/autodl-tmp/experiments/p2_us_final_20261002_monitored/stage_a -name "history.json" | wc -l
# 应该是32

# 启动新训练
cd /root/autodl-tmp
nohup python scripts/research/etf_trader_parallel_search_3090.py \
  --account us \
  --out experiments/p2_us_3090_fixed_seedB \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 16 \
  --workers 20 \
  --batch-worlds 256 \
  > train_3090_fixed_seedB.log 2>&1 &

# 监控
tail -f train_3090_fixed_seedB.log
```

### Step 3：准备WSL 4060环境（现在）

```bash
# 在Mac上通过SSH
ssh qount-wsl << 'EOF'
cd ~/Code/qount

# 拉取最新代码
git pull origin main

# 创建4060专用版本
cp scripts/research/etf_trader_parallel_search_fixed.py \
   scripts/research/etf_trader_parallel_search_4060.py

# 修改种子
sed -i 's/seed in \[20260930, 20260931\]/seed in [20261003, 20261004]/g' scripts/research/etf_trader_parallel_search_4060.py
sed -i 's/for seed in \[20260930, 20260931, 20260932, 20260933, 20260934\]/for seed in [20261006, 20261007, 20261008, 20261009, 20261010]/g' scripts/research/etf_trader_parallel_search_4060.py

# 验证修改
grep "seed in \[" scripts/research/etf_trader_parallel_search_4060.py

# 检查虚拟环境
if [ ! -d "p2_train_venv" ]; then
  python3 -m venv p2_train_venv
  source p2_train_venv/bin/activate
  pip install -e ".[research,research-neural]"
else
  echo "虚拟环境已存在"
fi

# 测试GPU
source p2_train_venv/bin/activate
python3 -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0)}')"
EOF
```

### Step 4：启动WSL 4060训练（现在或等待3090 Stage A完成）

**方案A：立即开始（推荐）**
```bash
ssh qount-wsl

# 创建tmux会话
tmux new -s p2_4060

cd ~/Code/qount
source p2_train_venv/bin/activate

# 启动训练
python scripts/research/etf_trader_parallel_search_4060.py \
  --account us \
  --out experiments/p2_us_4060_seedC \
  --stage-a-episodes 30 \
  --stage-b-episodes 100 \
  --parallel 8 \
  --workers 16 \
  --batch-worlds 256 \
  --device cuda \
  --gpu-id 0

# 分离：Ctrl+b d
# 稍后重新连接：tmux attach -t p2_4060
```

**方案B：等待3090完成Stage A后开始**
- 理由：可以用3090的结果指导4060只跑top-3结构
- 时间：等到今天10:20

---

## 六、时间预估

### 6.1 单GPU时间（修复后）

**云端3090（修复后，无批次间隙）**：
```
Episode速度：8分钟
Stage A：32配置 × 30ep × 8min / 16并行 = 8h - 0.3h(间隙) = 7.7h
Stage B：45配置 × 100ep × 8min / 16并行 = 37.5h - 0.5h = 37h
总计：44.7h
```

**WSL 4060（预估）**：
```
Episode速度：10分钟（比3090慢25%）
并行数：8（显存限制）
Stage A：32配置 × 30ep × 10min / 8并行 = 20h
Stage B：45配置 × 100ep × 10min / 8并行 = 93.75h
总计：113.75h（太慢！）
```

### 6.2 双GPU并行方案

**方案A：各自完整Stage A+B（不推荐）**
```
3090：44.7h
4060：113.75h（瓶颈）
总时间：113.75h（未节省时间）
```

**方案B：Stage A双GPU，Stage B只用3090**
```
Stage A：
  3090: 16配置 × 30ep × 8min / 16并行 = 4h
  4060: 16配置 × 30ep × 10min / 8并行 = 10h（瓶颈）
  
Stage B（合并Stage A结果，只用3090）：
  3090: 45配置 × 100ep × 8min / 16并行 = 37h

总时间：10h + 37h = 47h（基本无改善）
```

**方案C：任务动态分配（最优）** ⭐
```
3090承担：70%任务（速度快）
4060承担：30%任务（速度慢）

Stage A：
  3090: 22配置 × 2种子 = 44任务
    时间：44 × 30ep × 8min / 16 = 11h
  4060: 10配置 × 2种子 = 20任务
    时间：20 × 30ep × 10min / 8 = 12.5h（瓶颈）

Stage B：
  3090: 32配置（约70%）
    时间：32 × 100ep × 8min / 16 = 26.7h
  4060: 13配置（约30%）
    时间：13 × 100ep × 10min / 8 = 27h（瓶颈）

总时间：12.5h + 27h = 39.5h
节省：44.7h → 39.5h（节省12%）
```

**方案D：4060只跑Stage A（最实用）** ⭐⭐
```
Stage A：
  3090: 32配置 × seed(1,2) = 7.7h（修复后）
  4060: 32配置 × seed(3,4) = 20h（并行进行）
  实际总时间：max(7.7h, 20h) = 20h

Stage B（合并4个种子的结果，只用3090）：
  3090: 45配置 × 100ep = 37h
  
总时间：20h + 37h = 57h
但获得4个独立种子的Stage A结果（更robust）
```

### 6.3 推荐方案

**最优策略**：方案D（4060只跑Stage A）

**理由**：
1. Stage A种子翻倍（2→4），结果更可靠
2. 4060的20小时可被3090的7.7小时掩盖（并行）
3. Stage B用3090独自跑更快
4. 实现简单，无需复杂的任务分配

**实际时间线**：
```
现在（02:30）：启动4060 Stage A（seed 3,4）
今天10:20：3090 Stage A完成（当前训练）
今天10:30：3090启动修复版Stage A（seed 1,2）
今天18:00：3090修复版Stage A完成
后天07:00：4060 Stage A完成（20小时后）
后天07:00：合并4个种子结果，3090启动Stage B
后天20:00：3090 Stage B完成（37小时后）
```

**总计**：约**42小时**（从现在开始）

---

## 七、监控与验证

### 7.1 云端3090监控

```bash
# GPU曲线（应该无批次间隙）
watch -n 10 nvidia-smi

# 进度监控
watch -n 60 'find /root/autodl-tmp/experiments/p2_us_3090_fixed_seedB/stage_a -name "train.log" | wc -l'

# 检查是否真的无间隙（phi16和phi32交错）
ls -lt /root/autodl-tmp/experiments/p2_us_3090_fixed_seedB/stage_a/
# 应该看到phi16和phi32目录交错创建，而非分批
```

### 7.2 WSL 4060监控

```bash
# 本地监控
tmux attach -t p2_4060

# 或远程监控
ssh qount-wsl "tail -f ~/Code/qount/experiments/p2_us_4060_seedC/train_4060.log"

# GPU状态
ssh qount-wsl "nvidia-smi"
```

### 7.3 关键验证点

**修复验证**：GPU曲线应该**无10分钟空闲期**

**4060性能验证**：
- Episode 0: 预期15-25分钟（含编译）
- Episode 1: 预期10-12分钟（稳定）
- 如果>15分钟 → 调整并行数（8→6）

---

## 八、立即执行清单

### 现在（02:30）

- [ ] 创建修复版本脚本（已完成）
- [ ] 上传到云端服务器
- [ ] 在WSL准备4060环境
- [ ] 启动WSL 4060训练（Stage A，seed 3,4）

### 今天上午（10:20，3090当前训练完成Stage A后）

- [ ] 检查当前训练结果
- [ ] 启动3090修复版训练（Stage A，seed 1,2）
- [ ] 验证GPU曲线无批次间隙

### 明天上午（4060 Stage A完成后）

- [ ] 合并4个种子的Stage A结果
- [ ] 选择top-3结构
- [ ] 启动3090 Stage B

### 后天上午（3090 Stage B完成后）

- [ ] 收集所有结果
- [ ] 分析最优配置
- [ ] 准备P3预登记

---

**执行人**：立即开始  
**预期收益**：时间从49h降至42h，获得4倍种子样本  
**风险**：WSL 4060可能比预期慢，但不影响整体（并行进行）

`research_only=true / orders_authorized=false`
