"""Hook tests: veto, append, and visible failures."""
import unittest

from orca.runtime.hooks import HookRunner

from tests.helpers import tmp_root


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.root = tmp_root("orca-hooks-")

    def test_noop_when_unconfigured(self):
        runner = HookRunner({}, root=self.root)
        result = runner.run("before_bash", command="ls")
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "")

    def test_before_bash_can_veto(self):
        runner = HookRunner({"before_bash": "exit 1"}, root=self.root)
        result = runner.run("before_bash", command="rm tmp")
        self.assertTrue(result.blocked)
        self.assertFalse(result.ok)

    def test_before_bash_pass_and_substitution(self):
        runner = HookRunner({"before_bash": "echo guard:%command"},
                            root=self.root)
        result = runner.run("before_bash", command="pytest -q")
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "guard:pytest -q")

    def test_after_edit_output_with_file_substitution(self):
        (self.root / "a.py").write_text("x=1\n", encoding="utf-8")
        runner = HookRunner({"after_edit": "echo fmt:%file"}, root=self.root)
        result = runner.run("after_edit", file="a.py")
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "fmt:a.py")

    def test_timeout_blocks_and_reports(self):
        runner = HookRunner({"before_bash": "sleep 60"}, root=self.root,
                            )
        runner.TIMEOUT = 1
        result = runner.run("before_bash", command="x")
        self.assertTrue(result.blocked)
        self.assertIn("timed out", result.output)

    def test_hook_stderr_is_captured(self):
        runner = HookRunner({"after_bash": "echo oops >&2"}, root=self.root)
        result = runner.run("after_bash", command="ls")
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "oops")


if __name__ == "__main__":
    unittest.main()
