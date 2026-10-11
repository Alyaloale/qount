#!/bin/bash
# WSL Training Wrapper - Uses venv_upper environment
# This script ensures the correct Python environment is used

# Set Python to venv_upper's python3
export PYTHON_BIN="/home/alyaloale/venv_upper/bin/python3"

# Verify Python exists
if [ ! -f "$PYTHON_BIN" ]; then
    echo "ERROR: Python not found at $PYTHON_BIN"
    echo "Checking for python3 in venv_upper..."
    ls -la /home/alyaloale/venv_upper/bin/ | grep python
    exit 1
fi

# Run training with correct Python
cd ~/Code/qount
exec $PYTHON_BIN scripts/research/etf_trader_train.py "$@"
