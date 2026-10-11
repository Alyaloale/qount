#!/bin/bash
# Run P2 capacity search on WSL (design §3.3, §11).
# research_only=true / orders_authorized=false / trial=false.
# Two-stage search: 16 structures × 2 seeds (stage A) → top 3 × 3 lr × 5 seeds (stage B).

set -euo pipefail

REPO_ROOT="$HOME/Code/qount"
VENV_NAME="p2_train_venv"
VENV_PATH="$REPO_ROOT/$VENV_NAME"

cd "$REPO_ROOT"

if [ ! -d "$VENV_PATH" ]; then
    echo "Error: Virtual environment not found at $VENV_PATH"
    echo "Run setup_wsl_p2_env.sh first"
    exit 1
fi

source "$VENV_PATH/bin/activate"

# Output to external disk (storage topology §2)
OUT_ROOT="/mnt/e/qount_data/qount/artifacts/experiments/p2_capacity_search_$(date +%Y%m%dT%H%M%S)"
mkdir -p "$OUT_ROOT"

ACCOUNT="${1:-us}"  # us or cn
STAGE="${2:-both}"   # a, b, or both
WORKERS="${3:-16}"   # CPU workers for world generation
DEVICE="${4:-cuda}"

echo "=== P2 Capacity Search ==="
echo "Account: $ACCOUNT"
echo "Stage: $STAGE"
echo "Workers: $WORKERS"
echo "Device: $DEVICE"
echo "Output: $OUT_ROOT"
echo ""

# Verify GPU
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader

echo ""
echo "Starting capacity search..."
time python3 scripts/research/etf_trader_capacity_search.py \
    --account "$ACCOUNT" \
    --out "$OUT_ROOT" \
    --workers "$WORKERS" \
    --device "$DEVICE" \
    --stage "$STAGE" \
    --batch-worlds 256 \
    --n-val 1000

echo ""
echo "=== Search complete ==="
echo "Results saved to: $OUT_ROOT"
ls -lh "$OUT_ROOT"/*.json 2>/dev/null || echo "No result files yet"
