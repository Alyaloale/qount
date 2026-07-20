"""Deterministic serialization helpers for auditable contract hashes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical_hash(value: Mapping[str, Any]) -> str:
    """Return the stable SHA-256 used by cross-domain audit artifacts."""

    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
