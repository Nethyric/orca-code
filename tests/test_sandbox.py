"""Sandbox tests: the root is the only world."""
import os
import tempfile
import unittest
from pathlib import Path

from orca.tools.sandbox import Sandbox, SandboxError


class TestSandbox(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="orca-sbx-"))
        self.sbx = Sandbox(self.root)

    def test_relative_path_resolves_inside(self):
        target = self.sbx.resolve("src/app.py")
        self.assertEqual(target, (self.root / "src" / "app.py").resolve())

    def test_dotdot_escape_is_rejected(self):
        with self.assertRaises(SandboxError):
            self.sbx.resolve("../../etc/passwd")

    def test_absolute_path_outside_is_rejected(self):
        with self.assertRaises(SandboxError):
            self.sbx.resolve("/etc/passwd")

    def test_absolute_path_inside_root_is_allowed(self):
        inside = self.root / "notes.txt"
        with self.assertRaises(SandboxError):
            self.sbx.resolve("/etc/passwd")  # sanity: outside still blocked
        self.assertEqual(self.sbx.resolve(str(inside)), inside.resolve())

    def test_root_itself_is_allowed(self):
        self.assertEqual(self.sbx.resolve("."), self.root)

    def test_symlink_pointing_outside_is_rejected(self):
        outside = Path(tempfile.mkdtemp(prefix="orca-out-"))
        link = self.root / "escape"
        os.symlink(outside, link)
        with self.assertRaises(SandboxError):
            self.sbx.resolve("escape/secret.txt")

    def test_inside_predicate(self):
        self.assertTrue(self.sbx.inside("ok.txt"))
        self.assertFalse(self.sbx.inside("../nope.txt"))


if __name__ == "__main__":
    unittest.main()
