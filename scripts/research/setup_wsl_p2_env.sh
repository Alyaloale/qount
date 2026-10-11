#!/bin/bash
# Setup WSL environment for P2 ETF trader training (design §3.3, §11).
# research_only=true / orders_authorized=false / trial=false.
# Must be run on WSL with RTX 4060 GPU.

set -euo pipefail

REPO_ROOT="$HOME/Code/qount"
VENV_NAME="p2_train_venv"
VENV_PATH="$REPO_ROOT/$VENV_NAME"

cd "$REPO_ROOT"

echo "=== Setting up P2 training environment on WSL ==="
echo "Python: $(python3 --version)"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
echo ""

# Create venv if it doesn't exist
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
else
    echo "Virtual environment already exists at $VENV_PATH"
fi

# Activate and install dependencies
source "$VENV_PATH/bin/activate"

echo "Installing core dependencies..."
pip install --upgrade pip setuptools wheel

echo "Installing qount package..."
pip install -e ".[research,research-neural]"

echo "Verifying installation..."
python3 -c "import torch; print(f'torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}')"
python3 -c "import numpy; print(f'numpy {numpy.__version__}')"
python3 -c "from qount.research.etf_trader.train import train; print('etf_trader.train OK')"

echo ""
echo "=== Environment ready ==="
echo "Activate with: source $VENV_PATH/bin/activate"
echo "Python: $(which python3)"
echo "Installed packages: $(pip list | wc -l) packages"
