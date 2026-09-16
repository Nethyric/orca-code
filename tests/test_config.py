"""Config tests: layering, env, provider detection."""
import json
import os
import unittest
from unittest import mock

from orca.runtime.config import Config

from tests.helpers import tmp_root


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.root = tmp_root("orca-cfg-")
        self.home = tmp_root("orca-home-")
        self._env = mock.patch.dict(os.environ,
                                    {k: "" for k in list(os.environ)
                                     if k.startswith("ORCA_")})
        self._env.start()
        self.addCleanup(self._env.stop)

    def make(self, user=None, project=None):
        if user is not None:
            (self.home / "config.json").write_text(
                json.dumps(user), encoding="utf-8")
        if project is not None:
            (self.root / ".orca").mkdir(exist_ok=True)
            (self.root / ".orca" / "config.json").write_text(
                json.dumps(project), encoding="utf-8")
        return Config(root=self.root, home=self.home)

    def test_defaults(self):
        cfg = self.make()
        self.assertEqual(cfg.get("max_turns"), 40)
        self.assertIsNone(cfg.get("max_cost_usd"))
        self.assertEqual(cfg.get("hooks"), {})

    def test_user_file_overrides_defaults(self):
        cfg = self.make(user={"max_turns": 12})
        self.assertEqual(cfg.get("max_turns"), 12)

    def test_project_file_beats_user_file(self):
        cfg = self.make(user={"model": "user-model"},
                        project={"model": "project-model"})
        self.assertEqual(cfg.get("model"), "project-model")

    def test_deep_merge_keeps_siblings(self):
        cfg = self.make(user={"permissions": {"mode": "yolo"}})
        self.assertEqual(cfg.permission_mode(), "yolo")

    def test_env_beats_files(self):
        self.make(user={"provider": "openai"})
        with mock.patch.dict(os.environ, {"ORCA_PROVIDER": "groq"}):
            cfg = self.make(user={"provider": "openai"})
            self.assertEqual(cfg.detect_provider(), "groq")

    def test_detect_provider_falls_back_to_keyed(self):
        cfg = self.make(user={"api_keys": {"deepseek": "sk-x"}})
        self.assertEqual(cfg.detect_provider(), "deepseek")

    def test_detect_provider_defaults_to_ollama(self):
        self.assertEqual(self.make().detect_provider(), "ollama")

    def test_api_key_env_beats_stored(self):
        cfg = self.make(user={"api_keys": {"deepseek": "stored"}})
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "from-env"}):
            self.assertEqual(cfg.api_key("deepseek"), "from-env")

    def test_bad_config_file_raises_configerror(self):
        (self.home / "config.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(Exception):
            Config(root=self.root, home=self.home)

    def test_set_and_save_user(self):
        cfg = self.make()
        cfg.set("max_cost_usd", 5)
        cfg.save_user()
        reloaded = Config(root=self.root, home=self.home)
        self.assertEqual(reloaded.get("max_cost_usd"), 5)


if __name__ == "__main__":
    unittest.main()
