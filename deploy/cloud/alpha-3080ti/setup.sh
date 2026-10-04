#!/usr/bin/env bash
# Provision an isolated research environment; never source an .env or change drivers.
set -euo pipefail
task_python="${1:-/root/miniconda3/bin/python}"
task_venv="${2:-/root/qount-envs/alpha-3080ti-20261003}"
test "$(uname -s)" = Linux
if [[ -e "$task_venv" ]]; then
  printf '%s\n' 'Environment already exists; validate it explicitly instead of overwriting.' >&2
  exit 2
fi
"$task_python" -m venv "$task_venv"
"$task_venv/bin/python" -m pip install --no-cache-dir 'torch==2.13.0' --index-url https://download.pytorch.org/whl/cu130
"$task_venv/bin/python" -m pip install --no-cache-dir 'numpy==2.5.1' 'threadpoolctl==3.6.0'
"$task_venv/bin/python" -m pip check
"$task_venv/bin/python" -c 'import torch,numpy; assert torch.cuda.is_available(); assert torch.cuda.get_device_capability(0)==(8,6); print({"torch":torch.__version__,"numpy":numpy.__version__,"cuda":torch.version.cuda,"gpu":torch.cuda.get_device_name(0)})'
