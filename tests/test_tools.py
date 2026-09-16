import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orca.tools import (ToolContext, ToolError, run_tool, glob_match, is_ignored,
                        load_gitignore, walk_files)


def ctx_with_files(files: dict) -> ToolContext:
    tmp = tempfile.mkdtemp(prefix="orca-test-")
    root = Path(tmp)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return ToolContext(root)


class TestReadFile(unittest.TestCase):
    def test_numbering_and_range(self):
        ctx = ctx_with_files({"a.txt": "\n".join(f"line{i}" for i in range(1, 11))})
        out = run_tool("read_file", {"path": "a.txt", "offset": 3, "limit": 2}, ctx)
        self.assertIn("3\tline3", out)
        self.assertIn("4\tline4", out)
        self.assertNotIn("line5", out)
        self.assertIn("more lines", out)

    def test_missing(self):
        ctx = ctx_with_files({})
        with self.assertRaises(ToolError):
            run_tool("read_file", {"path": "nope.txt"}, ctx)

    def test_directory(self):
        ctx = ctx_with_files({"a.txt": "x"})
        with self.assertRaises(ToolError):
            run_tool("read_file", {"path": "."}, ctx)


class TestWriteEdit(unittest.TestCase):
    def test_write_creates_and_undo_restores(self):
        ctx = ctx_with_files({})
        ctx.undo.begin_turn()
        out = run_tool("write_file", {"path": "src/deep/new.py", "content": "x = 1\n"}, ctx)
        self.assertIn("Wrote", out)
        self.assertTrue((ctx.root / "src/deep/new.py").is_file())
        restored = ctx.undo.undo()
        self.assertEqual(len(restored), 1)
        self.assertFalse((ctx.root / "src/deep/new.py").exists())

    def test_edit_exact(self):
        ctx = ctx_with_files({"f.py": "def hello():\n    return 1\n"})
        ctx.undo.begin_turn()
        out = run_tool("edit_file", {"path": "f.py", "old_string": "return 1",
                                     "new_string": "return 2"}, ctx)
        self.assertIn("Edited", out)
        self.assertIn("return 2", (ctx.root / "f.py").read_text())

    def test_edit_ambiguous(self):
        ctx = ctx_with_files({"f.py": "a\na\n"})
        with self.assertRaises(ToolError) as cm:
            run_tool("edit_file", {"path": "f.py", "old_string": "a", "new_string": "b"}, ctx)
        self.assertIn("2 times", str(cm.exception))

    def test_edit_replace_all(self):
        ctx = ctx_with_files({"f.py": "a\na\n"})
        run_tool("edit_file", {"path": "f.py", "old_string": "a", "new_string": "b",
                               "replace_all": True}, ctx)
        self.assertEqual((ctx.root / "f.py").read_text(), "b\nb\n")

    def test_edit_fuzzy_hint(self):
        ctx = ctx_with_files({"f.py": "def hello():\n    return one\n"})
        with self.assertRaises(ToolError) as cm:
            run_tool("edit_file", {"path": "f.py", "old_string": "def hello():\n    return 1",
                                   "new_string": "x"}, ctx)
        self.assertIn("closest match", str(cm.exception))

    def test_edit_missing_file(self):
        ctx = ctx_with_files({})
        with self.assertRaises(ToolError):
            run_tool("edit_file", {"path": "no.py", "old_string": "a", "new_string": "b"}, ctx)


class TestBash(unittest.TestCase):
    def test_echo(self):
        ctx = ctx_with_files({})
        out = run_tool("bash", {"command": "echo hello"}, ctx)
        self.assertIn("hello", out)
        self.assertNotIn("exit code", out)

    def test_nonzero_exit(self):
        ctx = ctx_with_files({})
        out = run_tool("bash", {"command": "exit 3"}, ctx)
        self.assertIn("[exit code: 3]", out)

    def test_timeout(self):
        ctx = ctx_with_files({})
        out = run_tool("bash", {"command": "sleep 5", "timeout": 1}, ctx)
        self.assertIn("timed out", out)

    def test_catastrophic_refused(self):
        ctx = ctx_with_files({})
        with self.assertRaises(ToolError):
            run_tool("bash", {"command": "rm -rf /"}, ctx)

    def test_truncation(self):
        ctx = ctx_with_files({})
        out = run_tool("bash", {"command": f"seq 1 100000"}, ctx)
        self.assertLess(len(out), 40000)
        self.assertIn("truncated", out)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.ctx = ctx_with_files({
            "app.py": "import os\n\ndef run():\n    return os.getcwd()\n",
            "pkg/util.py": "def helper():\n    return 'needle here'\n",
            "pkg/__pycache__/junk.py": "needle but ignored\n",
            "node_modules/lib.js": "needle ignored too\n",
            ".gitignore": "ignored_dir/\n*.log\n",
            "ignored_dir/x.txt": "needle inside ignored\n",
            "debug.log": "needle log\n",
            "binary.bin": "needle\x00binary\n",
        })

    def test_grep(self):
        out = run_tool("grep", {"pattern": "needle"}, self.ctx)
        self.assertIn("pkg/util.py:2", out)
        self.assertNotIn("node_modules", out)
        self.assertNotIn("junk.py", out)
        self.assertNotIn("ignored_dir", out)
        self.assertNotIn("debug.log", out)
        self.assertNotIn("binary.bin", out)

    def test_grep_ignore_case(self):
        out = run_tool("grep", {"pattern": "NEEDLE", "ignore_case": True}, self.ctx)
        self.assertIn("pkg/util.py", out)

    def test_grep_no_match(self):
        out = run_tool("grep", {"pattern": "zzzz"}, self.ctx)
        self.assertIn("No matches", out)

    def test_grep_bad_regex(self):
        with self.assertRaises(ToolError):
            run_tool("grep", {"pattern": "(unclosed"}, self.ctx)

    def test_glob(self):
        out = run_tool("glob", {"pattern": "**/*.py"}, self.ctx)
        self.assertIn("app.py", out)
        self.assertIn("pkg/util.py", out)
        self.assertNotIn("lib.js", out)
        self.assertNotIn("junk.py", out)

    def test_glob_match_unit(self):
        self.assertTrue(glob_match("**/*.py", "a/b/c.py"))
        self.assertTrue(glob_match("src/**/*.ts", "src/x/y/z.ts"))
        self.assertTrue(glob_match("*.md", "README.md"))
        self.assertFalse(glob_match("**/*.py", "a/b/c.js"))
        self.assertFalse(glob_match("src/**/*.ts", "other/x.ts"))

    def test_is_ignored(self):
        patterns = load_gitignore(self.ctx.root)
        self.assertTrue(is_ignored("ignored_dir/x.txt", patterns))
        self.assertTrue(is_ignored("debug.log", patterns))
        self.assertFalse(is_ignored("app.py", patterns))

    def test_walk_respects_ignores(self):
        patterns = load_gitignore(self.ctx.root)
        rels = [p.relative_to(self.ctx.root).as_posix() for p in walk_files(self.ctx.root, patterns)]
        self.assertNotIn("ignored_dir/x.txt", rels)
        self.assertIn("app.py", rels)


class TestLsTodo(unittest.TestCase):
    def test_ls(self):
        ctx = ctx_with_files({"dir/sub/f.txt": "hi", "top.txt": "x"})
        out = run_tool("ls", {"path": "."}, ctx)
        self.assertIn("dir/", out)
        self.assertIn("top.txt", out)

    def test_todo(self):
        ctx = ctx_with_files({})
        out = run_tool("todo", {"todos": [
            {"content": "step one", "status": "in_progress"},
            {"content": "step two", "status": "pending"},
        ]}, ctx)
        self.assertIn("2 items", out)
        self.assertEqual(len(ctx.todos), 2)

    def test_todo_bad(self):
        ctx = ctx_with_files({})
        with self.assertRaises(ToolError):
            run_tool("todo", {"todos": "not a list"}, ctx)


if __name__ == "__main__":
    unittest.main()


class TestRunToolValidation(unittest.TestCase):
    def test_bad_timeout_string(self):
        ctx = ctx_with_files({})
        with self.assertRaises(ToolError) as cm:
            run_tool("bash", {"command": "echo hi", "timeout": "not-a-number"}, ctx)
        self.assertIn("Invalid arguments", str(cm.exception))

    def test_non_dict_args(self):
        ctx = ctx_with_files({})
        with self.assertRaises(ToolError):
            run_tool("read_file", ["not", "a", "dict"], ctx)

    def test_unknown_tool(self):
        ctx = ctx_with_files({})
        with self.assertRaises(ToolError):
            run_tool("teleport", {}, ctx)


class TestWebTools(unittest.TestCase):
    def test_web_fetch_rejects_non_http(self):
        from orca.tools import ToolContext
        ctx = ToolContext(Path(tempfile.mkdtemp()))
        for bad in ("ftp://x", "javascript:alert(1)", "file:///etc/passwd", "not-a-url"):
            with self.assertRaises(ToolError):
                run_tool("web_fetch", {"url": bad}, ctx)

    def test_web_search_requires_query(self):
        from orca.tools import ToolContext
        ctx = ToolContext(Path(tempfile.mkdtemp()))
        with self.assertRaises(ToolError):
            run_tool("web_search", {"query": "  "}, ctx)

    def test_ddg_parser(self):
        from orca.tools import _parse_ddg
        sample = """
        <a rel="nofollow" class="result__a"
           href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs&amp;rut=abc">Example <b>Docs</b></a>
        <a class="result__snippet">The <b>best</b> docs &amp; guides</a>
        <a class="result__a" href="https://direct.link/page">Direct Link</a>
        <a class="result__snippet">second snippet</a>
        """
        results = _parse_ddg(sample)
        self.assertEqual(len(results), 2)
        title, url, snippet = results[0]
        self.assertEqual(title, "Example Docs")
        self.assertEqual(url, "https://example.com/docs")
        self.assertIn("best docs", snippet)
        self.assertEqual(results[1][1], "https://direct.link/page")

    def test_text_extractor(self):
        from orca.tools import _TextExtractor
        page = ("<html><head><title>My Page</title><style>x{}</style></head>"
                "<body><nav>menu</nav><script>evil()</script>"
                "<h1>Hello</h1><p>First para</p><p>Second para</p></body></html>")
        extractor = _TextExtractor()
        extractor.feed(page)
        text = extractor.text()
        self.assertEqual(extractor.title, "My Page")
        self.assertIn("Hello", text)
        self.assertIn("First para", text)
        self.assertNotIn("evil()", text)
        self.assertNotIn("menu", text)


class TestRewindStack(unittest.TestCase):
    def test_undo_only_last_turn(self):
        ctx = ctx_with_files({"a.txt": "one"})
        ctx.undo.begin_turn()          # turn 1
        run_tool("write_file", {"path": "a.txt", "content": "two"}, ctx)
        ctx.undo.begin_turn()          # turn 2
        run_tool("write_file", {"path": "a.txt", "content": "three"}, ctx)
        restored = ctx.undo.undo()
        self.assertEqual(len(restored), 1)
        self.assertEqual((ctx.root / "a.txt").read_text(), "two")

    def test_rewind_to_multiple_turns(self):
        ctx = ctx_with_files({"a.txt": "zero"})
        ctx.undo.begin_turn()
        run_tool("write_file", {"path": "a.txt", "content": "one"}, ctx)
        run_tool("write_file", {"path": "b.txt", "content": "b-one"}, ctx)
        ctx.undo.begin_turn()
        run_tool("write_file", {"path": "a.txt", "content": "two"}, ctx)
        marker = len(ctx.undo.entries)  # after turn 2's first change? no: use index
        # rewind everything recorded after the first entry (i.e. the 2nd change of turn 1 + turn 2)
        restored = ctx.undo.rewind_to(1)
        self.assertEqual((ctx.root / "a.txt").read_text(), "one")
        self.assertEqual(len(restored), 2)
        self.assertEqual(len(ctx.undo.entries), 1)

    def test_rewind_past_end_is_noop(self):
        ctx = ctx_with_files({})
        self.assertEqual(ctx.undo.rewind_to(5), [])


class TestEggInfoIgnored(unittest.TestCase):
    def test_egg_info_skipped(self):
        ctx = ctx_with_files({
            "src.egg-info/PKG-INFO": "needle",
            "keep.txt": "needle",
        })
        out = run_tool("grep", {"pattern": "needle"}, ctx)
        self.assertIn("keep.txt", out)
        self.assertNotIn("egg-info", out)
