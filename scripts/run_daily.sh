#!/usr/bin/env bash
set -e

# Change directory to the root of the project
cd "$(dirname "$0")/.."

echo "========================================================"
echo "🚀 QOUNT: DAILY AI QUANTITATIVE PIPELINE"
echo "========================================================"

echo "[1/3] Activating virtual environment..."
source .venv/bin/activate

echo "[2/3] Fetching latest market data & rebuilding features..."
# Note: In a production environment, you would use a delta-update script.
# For now, we rebuild the features to ensure MACD/Z-scores are perfectly updated.
python scripts/download_data.py
python scripts/build_features.py

echo "[3/3] Running Pure-Python NumPy AI Inference..."
python scripts/predict_numpy.py

echo "✅ Daily pipeline completed successfully."
echo "========================================================"
