#!/bin/bash
# Fetch the X4 crypto paper holdings (as-of-today forward book) as one compact JSON line for the
# Übersicht widget (x4paper.jsx). Unlike line A's ctar_fetch.sh (ssh -> WSL), data is LOCAL on the
# Mac: read holdings_latest.json that x4_paper.py holdings writes. Read-only, never trades.
exec /Users/alyaloale/Code/qount/.venv/bin/python - <<'PY'
import json, os
PAPER = "/Users/alyaloale/Code/qount/state/x4/paper"
try:
    with open(os.path.join(PAPER, "holdings_latest.json")) as fh:
        print(json.dumps(json.load(fh), default=float))   # one compact line
except Exception as e:
    print(json.dumps({"error": str(e)}))
PY
