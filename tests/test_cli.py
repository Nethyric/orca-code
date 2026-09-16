"""CLI end-to-end tests with the mock provider (offline)."""
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from orca import __version__
from orca.cli import main

from tests.helpers import tmp_root


def run_main(argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    env = env or {}
    base = {k: v for k, v in os.environ.items()
            if not k.startswith("ORCA_") and not k.endswith("_API_KEY")}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True), \
            redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue() + err.getvalue()


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.root = tmp_root("orca-cli-")
        self.home = tmp_root("orca-clihome-")

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as ctx:
            run_main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_providers_listing(self):
        code, out = run_main(["--providers"])
        self.assertEqual(code, 0)
        self.assertIn("deepseek", out)
        self.assertIn("ollama", out)

    def test_print_mode_with_mock_provider(self):
        code, out = run_main(
            ["-p", "say something", "--root", str(self.root)],
            env={"ORCA_PROVIDER": "mock", "ORCA_HOME": str(self.home)})
        self.assertEqual(code, 0)
        self.assertIn("done", out)

    def test_print_mode_prints_banner_events(self):
        code, out = run_main(
            ["-p", "hi", "--root", str(self.root)],
            env={"ORCA_PROVIDER": "mock", "ORCA_HOME": str(self.home)})
        self.assertIn("Orca Code", out)

    def test_missing_key_exits_with_error(self):
        code, out = run_main(
            ["-p", "hi", "--root", str(self.root), "--provider", "openai"],
            env={"ORCA_HOME": str(self.home)})
        self.assertEqual(code, 1)
        self.assertIn("OPENAI_API_KEY", out)

    def test_root_flag_controls_sandbox(self):
        code, out = run_main(
            ["-p", "hi", "--root", str(self.root)],
            env={"ORCA_PROVIDER": "mock", "ORCA_HOME": str(self.home)})
        self.assertEqual(code, 0)
        self.assertTrue(self.root.is_dir())


if __name__ == "__main__":
    unittest.main()
