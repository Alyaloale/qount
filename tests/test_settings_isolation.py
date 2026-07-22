from __future__ import annotations

import dataclasses
import unittest

from qount.settings import PRODUCTION_CRITICAL_FIELDS
from qount.settings import RESEARCH_ONLY_FIELDS
from qount.settings import ResearchSettings
from qount.settings import Settings
from qount.settings import safe_research_replace
from qount.settings import validate_no_production_override


class SettingsIsolationTest(unittest.TestCase):
    def test_production_critical_fields_not_in_research_only(self):
        overlap = PRODUCTION_CRITICAL_FIELDS & RESEARCH_ONLY_FIELDS
        self.assertEqual(
            overlap,
            set(),
            f"fields overlap: {overlap}",
        )

    def test_research_settings_has_only_research_fields(self):
        research_fields = {
            f.name for f in dataclasses.fields(ResearchSettings)
        }
        self.assertEqual(research_fields, RESEARCH_ONLY_FIELDS)

    def test_validate_no_production_override_allows_research_fields(self):
        settings = Settings.from_env()
        errors = validate_no_production_override(
            settings,
            research_shadow_candidate_tags=("test",),
        )
        self.assertEqual(errors, ())

    def test_validate_no_production_override_blocks_live_enable(self):
        settings = Settings.from_env()
        errors = validate_no_production_override(
            settings,
            live_enable=True,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("live_enable", errors[0])

    def test_validate_no_production_override_blocks_leverage(self):
        settings = Settings.from_env()
        errors = validate_no_production_override(
            settings,
            contract_leverage=10,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("contract_leverage", errors[0])

    def test_safe_research_replace_allows_research_fields(self):
        settings = Settings.from_env()
        new_settings = safe_research_replace(
            settings,
            research_shadow_candidate_tags=("tag1", "tag2"),
        )
        self.assertEqual(
            new_settings.research_shadow_candidate_tags,
            ("tag1", "tag2"),
        )

    def test_safe_research_replace_blocks_production_fields(self):
        settings = Settings.from_env()
        with self.assertRaises(ValueError) as cm:
            safe_research_replace(
                settings,
                live_enable=True,
            )
        self.assertIn("live_enable", str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            safe_research_replace(
                settings,
                contract_leverage=100,
            )
        self.assertIn("contract_leverage", str(cm.exception))

    def test_safe_research_replace_blocks_multiple_production_fields(self):
        settings = Settings.from_env()
        with self.assertRaises(ValueError) as cm:
            safe_research_replace(
                settings,
                live_enable=True,
                contract_leverage=10,
                binance_api_key="stolen",
            )
        message = str(cm.exception)
        self.assertIn("live_enable", message)
        self.assertIn("contract_leverage", message)
        self.assertIn("binance_api_key", message)

    def test_research_settings_from_settings(self):
        settings = Settings.from_env()
        research = ResearchSettings.from_settings(settings)
        self.assertEqual(
            research.research_shadow_candidate_tags,
            settings.research_shadow_candidate_tags,
        )
        self.assertEqual(
            research.hourly_model_enable,
            settings.hourly_model_enable,
        )

    def test_dataclasses_replace_still_works_but_unsafe(self):
        """Verify that raw dataclasses.replace is not blocked (it's the
        unsafe path that safe_research_replace replaces)."""
        settings = Settings.from_env()
        unsafe = dataclasses.replace(settings, live_enable=True)
        self.assertTrue(unsafe.live_enable)
        # This demonstrates why safe_research_replace is needed

    def test_production_fields_cannot_appear_in_research_settings(self):
        """ResearchSettings must not contain any production-critical field."""
        research_field_names = {
            f.name for f in dataclasses.fields(ResearchSettings)
        }
        for critical in PRODUCTION_CRITICAL_FIELDS:
            self.assertNotIn(
                critical,
                research_field_names,
                f"ResearchSettings must not contain {critical}",
            )


if __name__ == "__main__":
    unittest.main()
