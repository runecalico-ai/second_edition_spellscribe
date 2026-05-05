from __future__ import annotations

import importlib
import os
import unittest
from unittest.mock import patch


class BuildConfigTests(unittest.TestCase):
    def _reload_build_config(self):
        import app.build_config

        return importlib.reload(app.build_config)

    def test_standard_is_default_build_flavor(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            module = self._reload_build_config()
            self.assertEqual(module.BUILD_FLAVOR, "standard")
            self.assertFalse(module.is_pro_build())
            self.assertEqual(module.edition_label(), "Standard Edition")

    def test_pro_build_flavor_uses_pro_label(self) -> None:
        with patch.dict(os.environ, {"SPELLSCRIBE_BUILD_FLAVOR": "pro"}, clear=True):
            module = self._reload_build_config()
            self.assertEqual(module.BUILD_FLAVOR, "pro")
            self.assertTrue(module.is_pro_build())
            self.assertEqual(module.edition_label(), "Pro Edition")
