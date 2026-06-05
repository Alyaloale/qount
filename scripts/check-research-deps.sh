#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"

"$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import importlib
import json
import os
import sys

required_packages = ("numpy", "sklearn")
optional_packages = ("lightgbm",)
result: dict[str, object] = {
    "python": sys.version.split()[0],
    "executable": sys.executable,
    "packages": {},
}

missing: list[str] = []
optional_failures: list[str] = []
for package in required_packages + optional_packages:
    try:
        module = importlib.import_module(package)
    except Exception as exc:
        result["packages"][package] = {
            "ok": False,
            "version": None,
            "optional": package in optional_packages,
            "error": f"{type(exc).__name__}: {exc}",
        }
        if package in optional_packages:
            optional_failures.append(package)
        else:
            missing.append(package)
    else:
        result["packages"][package] = {
            "ok": True,
            "version": getattr(module, "__version__", "unknown"),
            "optional": package in optional_packages,
        }

print(json.dumps(result, indent=2, sort_keys=True))
if missing:
    print(
        "Missing research dependencies: "
        + ", ".join(missing)
        + ". Install with: python -m pip install -e '.[research]'",
        file=sys.stderr,
    )
    raise SystemExit(1)
if optional_failures and os.environ.get("QOUNT_REQUIRE_LIGHTGBM") == "1":
    print(
        "LightGBM is required but not importable. Install libomp or use the sklearn HistGradientBoosting fallback.",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
