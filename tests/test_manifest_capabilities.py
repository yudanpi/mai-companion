import json
import importlib.util
import sys
import unittest
from pathlib import Path


class ManifestCapabilityTests(unittest.TestCase):
    def test_declares_model_inventory_capability_used_by_diagnostic(self):
        manifest_path = Path(__file__).resolve().parents[1] / "_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("llm.get_available_models", manifest["capabilities"])

    def test_voice_reply_config_defaults_to_private_whitelist(self):
        config_path = Path(__file__).resolve().parents[1] / "config.py"
        spec = importlib.util.spec_from_file_location("mai_companion_config_test", config_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        config = module.MaiCompanionConfig()

        self.assertTrue(config.voice_reply_enabled)
        self.assertEqual(config.voice_private_whitelist, [])

    def test_plugin_declares_outbound_voice_hook(self):
        plugin_path = Path(__file__).resolve().parents[1] / "plugin.py"
        source = plugin_path.read_text(encoding="utf-8")
        self.assertIn('"send_service.outbound_transform"', source)


if __name__ == "__main__":
    unittest.main()

