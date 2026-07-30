from __future__ import annotations

import errno
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "research"
    / "prepare_l1_personal_carrier_tiingo_cache.py"
)
SPEC = importlib.util.spec_from_file_location("prepare_l1_tiingo_cache_test", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
PREPARER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARER)


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _Opener:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def open(self, _request: object, *, timeout: int) -> _Response:
        if timeout != 60:
            raise AssertionError("unexpected Tiingo timeout")
        return _Response(self._payload)


class PreparePersonalCarrierTiingoCacheTests(unittest.TestCase):
    def test_exfat_hard_link_fallback_publishes_complete_cache(self) -> None:
        payload = [{"date": "2020-01-01T00:00:00+00:00", "adjClose": 100.0}]
        with tempfile.TemporaryDirectory() as temporary_dir:
            cache_path = Path(temporary_dir) / "tiingo_SPY.json"
            with (
                patch.object(PREPARER.urllib.request, "build_opener", return_value=_Opener(payload)),
                patch.object(PREPARER.os, "link", side_effect=OSError(errno.EPERM, "unsupported")),
            ):
                PREPARER._download_missing_cache(
                    ticker="SPY",
                    cache_path=cache_path,
                    api_key="fixture-key",
                )

            self.assertTrue(cache_path.is_file())
            self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8")), payload)
            self.assertEqual(list(Path(temporary_dir).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
