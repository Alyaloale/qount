#!/bin/bash
# Fetch the X4 fixed-TOP7 LIVE status (线 D §21) as one compact JSON line for the Übersicht widget
# (x4live.jsx). Data is LOCAL on the Mac: state/x4/live/latest.json, written by x4_live.py. Read-only.
exec /Users/alyaloale/Code/qount/.venv/bin/python - <<'PY'
import json, os
LIVE = "/Users/alyaloale/Code/qount/state/x4/live"
try:
    with open(os.path.join(LIVE, "latest.json")) as fh:
        print(json.dumps(json.load(fh), default=float))   # one compact line
except Exception as e:
    print(json.dumps({"error": str(e)}))
PY
