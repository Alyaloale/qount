from __future__ import annotations

import json
from pathlib import Path
import stat
import tempfile
import unittest

from qount.config_contract import check_environment
from qount.config_contract import load_contract
from qount.main import build_parser


class EnvironmentContractTests(unittest.TestCase):
    def test_contract_has_required_metadata_for_each_variable(self) -> None:
        contract = load_contract()
        self.assertGreater(len(contract), 80)
        for variable in contract.values():
            self.assertTrue(variable.name)
            self.assertTrue(variable.domain)
            self.assertTrue(variable.value_type)
            self.assertTrue(variable.allowed_hosts)
            self.assertTrue(variable.default_policy)
            self.assertTrue(variable.consumers)

    def test_value_free_report_never_echoes_secret(self) -> None:
        secret = "not-for-output-7c9854"
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(f"QOUNT_OPENAI_API_KEY={secret}\n", encoding="utf-8")
            env_file.chmod(0o600)
            report = check_environment(profile="mac", env_file=env_file)

        rendered = json.dumps(report)
        self.assertNotIn(secret, rendered)
        self.assertTrue(report["values_redacted"])
        self.assertTrue(report["ok"])

    def test_sensitive_file_with_open_permissions_is_reported_without_value(self) -> None:
        secret = "not-for-output-15dd"
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(f"QOUNT_OPENAI_API_KEY={secret}\n", encoding="utf-8")
            env_file.chmod(0o644)
            report = check_environment(profile="mac", env_file=env_file)

        self.assertFalse(report["ok"])
        self.assertEqual(report["unsafe_permissions"], ["environment_file_permissions"])
        self.assertNotIn(secret, json.dumps(report))

    def test_wsl_rejects_secret_and_live_request_is_always_unsafe(self) -> None:
        report = check_environment(
            profile="wsl",
            environ={
                "QOUNT_OPENAI_API_KEY": "not-printed",
                "QOUNT_LIVE_ENABLE": "true",
            },
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["host_not_allowed"], ["QOUNT_OPENAI_API_KEY"])
        self.assertEqual(report["mutually_exclusive_or_unsafe"], ["live_enable_requested"])

    def test_config_check_is_registered_as_a_read_only_cli_command(self) -> None:
        args = build_parser().parse_args(["config-check", "--profile", "mac"])
        self.assertEqual(args.command, "config-check")
        self.assertEqual(args.profile, "mac")
        self.assertIsNone(args.env_file)


if __name__ == "__main__":
    unittest.main()
