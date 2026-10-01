from __future__ import annotations

import unittest

from qount.main import build_parser


class CliRegistryCompatibilityTests(unittest.TestCase):
    def test_frozen_research_commands_remain_available_from_public_parser(self) -> None:
        parser = build_parser()

        l3 = parser.parse_args(["l3-stablecoin-fetch"])
        l1 = parser.parse_args(
            [
                "l1-cross-asset-breadth-scan",
                "--start",
                "2026-01-01",
                "--end",
                "2026-02-01",
            ]
        )
        l4 = parser.parse_args(
            [
                "l4-cross-exchange-funding-scan",
                "--start",
                "2026-01-01",
                "--end",
                "2026-02-01",
            ]
        )
        l6 = parser.parse_args(
            [
                "l6-microstructure-ic-scan",
                "--data-dir",
                "fixtures",
                "--symbols",
                "159919.SZ",
            ]
        )

        self.assertEqual(l3.command, "l3-stablecoin-fetch")
        self.assertEqual(l1.command, "l1-cross-asset-breadth-scan")
        self.assertEqual(l4.command, "l4-cross-exchange-funding-scan")
        self.assertEqual(l6.command, "l6-microstructure-ic-scan")

    def test_cta_compatibility_stub_stays_visible_to_parser(self) -> None:
        args = build_parser().parse_args(["cta-paper-sim"])
        self.assertEqual(args.command, "cta-paper-sim")


if __name__ == "__main__":
    unittest.main()
