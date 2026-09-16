"""Tests for `orca auth login|logout|list` — fully offline (validation mocked)."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orca.cli import run_auth  # noqa: E402
from orca.config import Config  # noqa: E402


def ns(**kw):
    base = dict(auth_cmd="login", provider=None, token=None, no_default=True)
    base.update(kw)
    return SimpleNamespace(**base)


class AuthHarness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"ORCA_HOME": self._tmp.name})
        self._env.start()
        if os.environ.get("GROQ_API_KEY"):
            del os.environ["GROQ_API_KEY"]

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def run_auth_capture(self, args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run_auth(args)
        return code, buf.getvalue()


class TestAuthLogin(AuthHarness):
    def test_login_stores_validated_key(self):
        cfg = Config()
        cfg.set("api_keys", {})
        cfg.save()
        with mock.patch("orca.providers.list_remote_models",
                        return_value=["model-a", "model-b"]):
            code, out = self.run_auth_capture(ns(provider="groq", token="gsk_good"))
        self.assertEqual(code, 0)
        self.assertIn("✓ key works — 2 models available", out)
        self.assertEqual(Config().get("api_keys", {}).get("groq"), "gsk_good")

    def test_login_rejects_bad_key_and_stores_nothing(self):
        cfg = Config()
        cfg.set("api_keys", {})
        cfg.save()
        from orca.providers import ProviderError
        with mock.patch("orca.providers.list_remote_models",
                        side_effect=ProviderError("HTTP 401: invalid key")):
            code, out = self.run_auth_capture(ns(provider="openai", token="sk_bad"))
        self.assertEqual(code, 1)
        self.assertIn("rejected", out)
        self.assertNotIn("openai", Config().get("api_keys", {}))

    def test_login_network_error_stores_with_warning(self):
        cfg = Config()
        cfg.set("api_keys", {})
        cfg.save()
        with mock.patch("orca.providers.list_remote_models",
                        side_effect=OSError("connection refused")):
            code, out = self.run_auth_capture(ns(provider="deepseek", token="sk_x"))
        self.assertEqual(code, 0)
        self.assertIn("could not validate", out)
        self.assertEqual(Config().get("api_keys", {}).get("deepseek"), "sk_x")

    def test_login_local_provider_needs_no_key(self):
        code, out = self.run_auth_capture(ns(provider="ollama"))
        self.assertEqual(code, 0)
        self.assertIn("no API key needed", out)

    def test_login_unknown_provider(self):
        code, out = self.run_auth_capture(ns(provider="nope", token="x"))
        self.assertEqual(code, 2)
        self.assertIn("unknown provider", out)

    def test_login_noninteractive_without_token(self):
        # stdin is not a tty under unittest → must refuse, not hang
        code, out = self.run_auth_capture(ns(provider="groq"))
        self.assertEqual(code, 2)
        self.assertIn("-t", out)


class TestAuthListLogout(AuthHarness):
    def test_list_shows_stored_env_and_local(self):
        cfg = Config()
        cfg.set("api_keys", {"openai": "sk_stored"})
        cfg.set("provider", "openai")
        cfg.save()
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_env"}):
            code, out = self.run_auth_capture(ns(auth_cmd="list"))
        self.assertEqual(code, 0)
        self.assertIn("openai", out)
        self.assertIn("✓ stored", out)
        self.assertIn("← default", out)
        self.assertIn("✓ env GROQ_API_KEY", out)
        self.assertIn("ollama", out)  # local providers always listed

    def test_logout_removes_stored_key(self):
        cfg = Config()
        cfg.set("api_keys", {"openai": "sk_stored"})
        cfg.save()
        code, out = self.run_auth_capture(ns(auth_cmd="logout", provider="openai"))
        self.assertEqual(code, 0)
        self.assertIn("removed", out)
        self.assertNotIn("openai", Config().get("api_keys", {}))

    def test_logout_missing_key(self):
        Config().set("api_keys", {})
        code, out = self.run_auth_capture(ns(auth_cmd="logout", provider="openai"))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
