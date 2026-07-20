from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qount.research_compute import _memory_total_bytes, _os_release, _sha256_file


class ResearchComputeManifestTest(unittest.TestCase):
    def test_manifest_helpers_parse_stable_system_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload.bin"
            payload.write_bytes(b"qount")
            os_release = root / "os-release"
            os_release.write_text('NAME="Research Linux"\nVERSION_ID=1\n', encoding="utf-8")
            meminfo = root / "meminfo"
            meminfo.write_text("MemTotal:       1024 kB\n", encoding="utf-8")

            self.assertEqual(
                _sha256_file(payload),
                "82ecccdefa3c69c641211493a1bcd29d1a769d070f21da54f3c89ee64f36497b",
            )
            self.assertEqual(
                _os_release(os_release),
                {"NAME": "Research Linux", "VERSION_ID": "1"},
            )
            self.assertEqual(_memory_total_bytes(meminfo), 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
