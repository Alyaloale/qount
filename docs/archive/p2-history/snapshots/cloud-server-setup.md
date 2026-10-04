# 云服务器镜像选择和环境配置指南

> **归档状态**：historical / non-restorable evidence｜**归档日期**：2026-10-02
> **替代入口**：[当前架构与研究结果](../../../p2-project-summary-20261002.md)；运行事实及权限仅看 [current.md](../../../current.md)。
> 保留现存正文用于追溯，旧时点状态、预计完成时间和历史命令不是当前结论或重启授权。

**适用于**：P2 训练在云 GPU（RTX 3090/4090）上运行

---

## 🖼️ 推荐镜像

### 选项 1：PyTorch 官方镜像（推荐）

```
PyTorch 2.x + CUDA 11.x/12.x
- Ubuntu 22.04/24.04
- PyTorch 2.0+ 预装
- CUDA 11.8 或 12.x
```

**优点**：
- ✅ PyTorch 和 CUDA 已配置好
- ✅ 驱动兼容性好
- ✅ 开箱即用

**选择标准**：
- PyTorch ≥ 2.0（支持 torch.compile）
- CUDA ≥ 11.8（推荐 12.x）
- Python 3.10-3.12

### 选项 2：Ubuntu + CUDA 基础镜像

```
Ubuntu 22.04/24.04 + CUDA Toolkit
- Ubuntu Server 22.04 或 24.04
- NVIDIA CUDA 12.x
- 需要手动安装 PyTorch
```

**优点**：
- ✅ 干净的环境
- ✅ 完全控制
- ⚠️ 需要额外配置（10-15分钟）

### ❌ 不推荐

- Windows 系统（需要 WSL，复杂）
- 旧版 CUDA < 11（不支持 PyTorch 2.x）
- CentOS/RedHat（包管理不同）

---

## 📋 环境配置步骤

### 方案 A：PyTorch 预装镜像（5分钟）

```bash
# 1. 验证环境
python3 --version          # 应该 ≥ 3.10
nvidia-smi                 # 检查 GPU
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"

# 2. 安装系统依赖（torch.compile 需要）
sudo apt update
sudo apt install -y build-essential python3-dev git

# 3. 克隆代码
cd ~
git clone https://github.com/your-repo/qount.git
# 或上传代码：scp -r qount/ user@server:~/

# 4. 安装 qount
cd qount
pip install -e ".[research,research-neural]"

# 5. 验证
python3 -c "from qount.research.etf_trader.train import train; print('OK')"

# 完成！
```

### 方案 B：从零配置（15分钟）

```bash
# 1. 验证 CUDA
nvidia-smi
nvcc --version  # 应该显示 CUDA 版本

# 2. 安装 Python 3.12
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt install -y python3.12 python3.12-venv python3.12-dev

# 3. 安装系统依赖
sudo apt install -y build-essential git curl

# 4. 创建虚拟环境
cd ~
python3.12 -m venv p2_env
source p2_env/bin/activate

# 5. 安装 PyTorch（根据 CUDA 版本选择）
# CUDA 12.x:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# CUDA 11.8:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 6. 验证 PyTorch
python3 -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}')"

# 7. 克隆和安装 qount
git clone <repo_url> qount
cd qount
pip install -e ".[research,research-neural]"

# 8. 验证
python3 -c "from qount.research.etf_trader.train import train; print('OK')"

# 完成！
```

---

## 🔍 关键验证步骤

### 必须检查

```bash
# 1. GPU 可见
nvidia-smi
# 应该显示 RTX 3090，24GB 显存

# 2. CUDA 版本
nvcc --version
# 或
nvidia-smi | grep "CUDA Version"

# 3. PyTorch + CUDA
python3 -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.device_count())"
# 应该输出：
# 2.x.x
# True
# 1

# 4. torch.compile 支持
python3 -c "import torch; print(hasattr(torch, 'compile'))"
# 应该输出：True

# 5. qount 模块
python3 -c "from qount.research.etf_trader.train import train; print('OK')"
# 应该输出：OK

# 6. GCC（torch.compile 需要）
gcc --version
# 应该显示 GCC 9+
```

---

## 🚀 快速启动脚本

保存为 `setup_cloud.sh`：

```bash
#!/bin/bash
set -e

echo "=== 云服务器 P2 环境配置 ==="

# 检查 GPU
echo "检查 GPU..."
nvidia-smi || { echo "错误: 未检测到 GPU"; exit 1; }

# 安装依赖
echo "安装系统依赖..."
sudo apt update
sudo apt install -y build-essential python3-dev git

# 验证 Python
echo "检查 Python..."
python3 --version

# 安装 PyTorch（如果未安装）
if ! python3 -c "import torch" 2>/dev/null; then
    echo "安装 PyTorch..."
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
fi

# 验证 torch.compile
echo "验证 torch.compile..."
python3 -c "import torch; assert hasattr(torch, 'compile'); print('torch.compile OK')"

# 克隆代码（如果未克隆）
if [ ! -d "qount" ]; then
    echo "克隆代码..."
    git clone <your-repo-url> qount
fi

cd qount

# 安装 qount
echo "安装 qount..."
pip install -e ".[research,research-neural]"

# 最终验证
echo "最终验证..."
python3 -c "
import torch
from qount.research.etf_trader.train import train
print(f'PyTorch: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
print(f'GPU: {torch.cuda.get_device_name(0)}')
print('环境就绪！')
"

echo ""
echo "=== 配置完成 ==="
echo "运行训练："
echo "  python3 scripts/research/etf_trader_parallel_search.py --account us --out /tmp/p2_us ..."
```

---

## 📦 代码上传方式

### 方式 1：Git（推荐）

```bash
# 在云服务器上
git clone https://github.com/your/qount.git
cd qount
```

### 方式 2：SCP 上传

```bash
# 在本地 Mac 上
cd /Users/alyaloale/Code/qount
tar czf qount.tar.gz --exclude='.git' --exclude='.venv' --exclude='__pycache__' .
scp qount.tar.gz user@server:~/

# 在云服务器上
tar xzf qount.tar.gz
```

### 方式 3：rsync（增量同步）

```bash
# 在本地 Mac 上
rsync -avz --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
  /Users/alyaloale/Code/qount/ user@server:~/qount/
```

---

## ⚠️ 常见问题

### 问题 1：torch.compile 失败 "No C compiler"

```bash
sudo apt install -y build-essential
```

### 问题 2：torch.compile 失败 "Python.h not found"

```bash
# Python 3.10
sudo apt install -y python3.10-dev

# Python 3.12
sudo apt install -y python3.12-dev
```

### 问题 3：CUDA 版本不匹配

```bash
# 检查 CUDA 版本
nvidia-smi | grep "CUDA Version"

# 安装匹配的 PyTorch
# CUDA 11.8:
pip install torch --index-url https://download.pytorch.org/whl/cu118

# CUDA 12.1:
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

### 问题 4：显存不足

```bash
# 减少 batch_worlds
python3 ... --batch-worlds 64  # 而不是 128

# 或减少并行度
python3 ... --parallel 2  # 而不是 4
```

---

## 🎯 推荐配置总结

**镜像选择**：
- 首选：**PyTorch 2.x + CUDA 12.x + Ubuntu 22.04/24.04**
- 次选：**Ubuntu 22.04 + CUDA 12.x**（手动装 PyTorch）

**关键要求**：
- ✅ Python 3.10-3.12
- ✅ PyTorch ≥ 2.0
- ✅ CUDA ≥ 11.8
- ✅ GCC（torch.compile）
- ✅ python3-dev（torch.compile）

**配置时间**：
- PyTorch 镜像：5 分钟
- 基础镜像：15 分钟

---

**准备好后，直接运行训练命令即可！**
