"""Tool tests: behavior, validation, and sandbox enforcement."""
import unittest

from orca.tools.builtin import register_builtins
from orca.tools.registry import Registry, UnknownToolError
from orca.tools.sandbox import Sandbox

from tests.helpers import tmp_root


def make_tools(root=None, timeout=120):
    root = root or tmp_root("orca-tools-")
    sbx = Sandbox(root)
    reg = Registry()
    register_builtins(reg, sbx, bash_timeout=timeout)
    return reg, root


def run(reg, name, **args):
    return reg.dispatch(name, args)


class TestFileTools(unittest.TestCase):
    def setUp(self):
        self.reg, self.root = make_tools()
        (self.root / "app.py").write_text("x = 1\ny = 2\nx = 1\n",
                                          encoding="utf-8")

    def test_read_file_numbers_lines(self):
        res = run(self.reg, "read_file", path="app.py")
        self.assertFalse(res.is_error)
        self.assertIn("1 │ x = 1", res.output)

    def test_read_file_offset_and_limit(self):
        res = run(self.reg, "read_file", path="app.py", offset=2, limit=1)
        self.assertIn("y = 2", res.output)
        self.assertNotIn("x = 1", res.output)

    def test_read_missing_file_is_an_error_result(self):
        res = run(self.reg, "read_file", path="nope.py")
        self.assertTrue(res.is_error)
        self.assertIn("not a file", res.output)

    def test_read_requires_path(self):
        res = run(self.reg, "read_file")
        self.assertTrue(res.is_error)
        self.assertIn("missing required", res.output)

    def test_write_file_creates_and_reports(self):
        res = run(self.reg, "write_file", path="new/dir/f.py",
                  content="print(1)\n")
        self.assertFalse(res.is_error)
        self.assertTrue((self.root / "new" / "dir" / "f.py").is_file())

    def test_write_outside_root_is_blocked(self):
        res = run(self.reg, "write_file", path="../escape.txt", content="x")
        self.assertTrue(res.is_error)
        self.assertIn("escapes", res.output)

    def test_edit_file_requires_unique_match(self):
        res = run(self.reg, "edit_file", path="app.py",
                  old_string="x = 1", new_string="x = 42")
        self.assertTrue(res.is_error)
        self.assertIn("2 places", res.output)

    def test_edit_file_miss_gives_clean_error(self):
        res = run(self.reg, "edit_file", path="app.py",
                  old_string="zzz-not-there", new_string="x")
        self.assertTrue(res.is_error)
        self.assertIn("not found", res.output)

    def test_edit_file_success(self):
        res = run(self.reg, "edit_file", path="app.py",
                  old_string="y = 2", new_string="y = 20")
        self.assertFalse(res.is_error)
        self.assertIn("y = 20",
                      (self.root / "app.py").read_text(encoding="utf-8"))


class TestBashTool(unittest.TestCase):
    def setUp(self):
        self.reg, self.root = make_tools()

    def test_echo_roundtrip(self):
        res = run(self.reg, "bash", command="echo hello-orca")
        self.assertFalse(res.is_error)
        self.assertIn("hello-orca", res.output)

    def test_nonzero_exit_is_error_result(self):
        res = run(self.reg, "bash", command="exit 3")
        self.assertTrue(res.is_error)

    def test_hard_timeout(self):
        res = run(self.reg, "bash", command="sleep 30", timeout=5)
        self.assertTrue(res.is_error)
        self.assertIn("timed out", res.output)

    def test_cwd_outside_root_is_blocked(self):
        res = run(self.reg, "bash", command="pwd", cwd="../..")
        self.assertTrue(res.is_error)
        self.assertIn("escapes", res.output)


class TestSearchTools(unittest.TestCase):
    def setUp(self):
        self.reg, self.root = make_tools()
        (self.root / "a.py").write_text("def alpha():\n    return 1\n",
                                        encoding="utf-8")
        (self.root / "b.txt").write_text("alpha mentioned in prose\n",
                                         encoding="utf-8")
        skip = self.root / ".git"
        skip.mkdir()
        (skip / "config").write_text("alpha should not appear",
                                     encoding="utf-8")

    def test_grep_finds_and_respects_skip_dirs(self):
        res = run(self.reg, "grep", pattern=r"alpha")
        self.assertFalse(res.is_error)
        self.assertIn("a.py:1:", res.output)
        self.assertIn("b.txt:1:", res.output)
        self.assertNotIn(".git", res.output)

    def test_grep_glob_filter(self):
        res = run(self.reg, "grep", pattern="alpha", glob="*.py")
        self.assertIn("a.py", res.output)
        self.assertNotIn("b.txt:", res.output)

    def test_grep_bad_regex_is_clean_error(self):
        res = run(self.reg, "grep", pattern="(unclosed")
        self.assertTrue(res.is_error)

    def test_glob_newest_first(self):
        (self.root / "z.py").write_text("", encoding="utf-8")
        res = run(self.reg, "glob", pattern="*.py")
        lines = res.output.splitlines()
        self.assertEqual(lines[0], "z.py")

    def test_ls_dirs_first(self):
        (self.root / "sub").mkdir()
        (self.root / "file.txt").write_text("", encoding="utf-8")
        res = run(self.reg, "ls", path=".")
        lines = res.output.splitlines()
        self.assertLess([l.endswith("sub/") for l in lines].index(True),
                        [l.endswith("file.txt") for l in lines].index(True))


class TestTodoAndTaskSpecs(unittest.TestCase):
    def setUp(self):
        self.reg, _ = make_tools()

    def test_todo_add_list_done(self):
        run(self.reg, "todo", action="add", item="write tests")
        res = run(self.reg, "todo", action="list")
        self.assertIn("[ ] write tests", res.output)
        run(self.reg, "todo", action="done", item="write tests")
        res = run(self.reg, "todo", action="list")
        self.assertIn("[x] write tests", res.output)

    def test_task_is_registered_but_not_directly_executable(self):
        res = run(self.reg, "task", prompt="x")
        self.assertTrue(res.is_error)
        self.assertIn("cannot be called directly", res.output)

    def test_registry_unknown_tool_raises(self):
        with self.assertRaises(UnknownToolError):
            run(self.reg, "no_such_tool")

    def test_nine_tools_registered(self):
        names = self.reg.names()
        for expected in ("read_file", "write_file", "edit_file", "bash",
                         "grep", "glob", "ls", "todo", "task"):
            self.assertIn(expected, names)
        self.assertEqual(len(names), 9)

    def test_bad_arguments_become_error_results(self):
        res = run(self.reg, "write_file", content="no path")
        self.assertTrue(res.is_error)


if __name__ == "__main__":
    unittest.main()
