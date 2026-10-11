#!/bin/bash
# Dual GPU Minimal Pipeline Validation
# Hardware-optimized for 3090 (28 cores, 24GB) and WSL 4060 (32 cores, 8GB)

set -e

echo "======================================================================"
echo "Dual GPU Minimal Pipeline Validation"
echo "======================================================================"
echo "Mode: Pipeline (world gen CPU || GPU training)"
echo "Test: 1 config × 3 episodes per GPU"
echo "Expected: ~3-4 min/episode with pipeline"
echo ""
echo "3090: 10 parallel × 30 workers"
echo "WSL:  4 parallel × 32 workers"
echo "======================================================================"
echo ""

# Upload scripts to both servers
echo "[1/4] Uploading optimized scripts..."

# Upload to 3090
sshpass -p 'uYBtc8pn9ond' scp -P 41489 \
    scripts/research/start_3090_pipeline_test.sh \
    root@connect.nmb2.seetacloud.com:/root/autodl-tmp/scripts/research/

# Upload to WSL
scp scripts/research/start_wsl_pipeline_test.sh \
    qount-wsl:~/Code/qount/scripts/research/

echo "✓ Scripts uploaded"
echo ""

# Make scripts executable and launch
echo "[2/4] Starting 3090 pipeline test..."
sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com \
    "chmod +x /root/autodl-tmp/scripts/research/start_3090_pipeline_test.sh && bash /root/autodl-tmp/scripts/research/start_3090_pipeline_test.sh"

echo ""
echo "[3/4] Starting WSL pipeline test..."
ssh qount-wsl \
    "chmod +x ~/Code/qount/scripts/research/start_wsl_pipeline_test.sh && bash ~/Code/qount/scripts/research/start_wsl_pipeline_test.sh"

echo ""
echo "[4/4] Both tests launched!"
echo ""
echo "======================================================================"
echo "✓ Dual GPU pipeline tests running"
echo "======================================================================"
echo ""
echo "Expected completion: ~10-12 minutes"
echo ""
echo "Monitor 3090:"
echo "  sshpass -p 'uYBtc8pn9ond' ssh -p 41489 root@connect.nmb2.seetacloud.com \\"
echo "    'tail -f /root/autodl-tmp/experiments/p2_3090_pipeline_*/train.log'"
echo ""
echo "Monitor WSL:"
echo "  ssh qount-wsl 'tail -f ~/Code/qount/experiments/p2_wsl_pipeline_*/train.log'"
echo ""
echo "Check status:"
echo "  ./scripts/research/check_pipeline_status.sh"
echo ""
