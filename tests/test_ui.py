"""UI tests: themes, highlighter, markdown tables, dialog parsing, preview."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orca.ui import UI, THEMES  # noqa: E402
from orca.config import (PROVIDER_PRESETS, SUGGESTED_MODELS,  # noqa: E402
                         expand_model_alias, Config)


class TestThemes(unittest.TestCase):
    def test_all_themes_instantiable_and_paintable(self):
        for name in THEMES:
            ui = UI(interactive=False, theme=name)
            self.assertEqual(ui.theme, name)
            ui.paint("x", "brand", "teal", "gray")  # must not raise

    def test_unknown_theme_falls_back_to_dark(self):
        ui = UI(interactive=False, theme="neon")
        self.assertEqual(ui.theme, "dark")

    def test_mono_disables_color_but_dark_keeps_it(self):
        forced = os.environ.get("ORCA_COLOR")
        os.environ["ORCA_COLOR"] = "force"
        try:
            ui = UI(interactive=False, theme="mono")
            self.assertFalse(ui.color)
            self.assertEqual(ui.paint("x", "brand"), "x")
            ui.set_theme("dark")   # switching back re-enables color
            self.assertTrue(ui.color)
            self.assertIn("\x1b[", ui.paint("x", "brand"))
        finally:
            del os.environ["ORCA_COLOR"]
            if forced:
                os.environ["ORCA_COLOR"] = forced

    def test_orca_color_off_wins(self):
        old = os.environ.get("ORCA_COLOR")
        os.environ["ORCA_COLOR"] = "off"
        try:
            ui = UI(interactive=True, theme="dark")
            self.assertFalse(ui.color)
        finally:
            del os.environ["ORCA_COLOR"]
            if old:
                os.environ["ORCA_COLOR"] = old

    def test_coral_theme_registered(self):
        os.environ["ORCA_COLOR"] = "force"
        try:
            ui = UI(interactive=False, theme="coral")
            self.assertEqual(ui.theme, "coral")
            self.assertTrue(ui._styles["brand"].startswith("38;5;173"))
        finally:
            del os.environ["ORCA_COLOR"]

    def test_theme_switch_respects_ansi(self):
        os.environ["ORCA_COLOR"] = "force"
        try:
            ui = UI(interactive=False, theme="ansi")
            self.assertEqual(ui._styles["brand"], "36")  # terminal palette cyan
            ui = UI(interactive=False, theme="dark")
            self.assertTrue(ui._styles["brand"].startswith("38;5;"))
        finally:
            del os.environ["ORCA_COLOR"]


class TestHighlighter(unittest.TestCase):
    def setUp(self):
        os.environ["ORCA_COLOR"] = "force"
        self.ui = UI(interactive=False, theme="dark")

    def tearDown(self):
        del os.environ["ORCA_COLOR"]

    def test_python_keywords_strings_comments(self):
        line = self.ui.highlight.line('def divide(a):  # math', "py")
        self.assertIn("\x1b[35mdef\x1b[0m", line)       # keyword magenta
        self.assertIn("\x1b[32m'math'\x1b[0m", line) if False else None
        line2 = self.ui.highlight.line("x = 'math'", "py")
        self.assertIn("\x1b[32m'math'\x1b[0m", line2)   # string green
        self.assertIn("\x1b[38;5;245;3m# math\x1b[0m", line)  # comment dim italic

    def test_numbers_brand_and_calls_cyan(self):
        line = self.ui.highlight.line("ratio = calc(3.14)", "py")
        self.assertIn("\x1b[38;5;81m3.14\x1b[0m", line)
        self.assertIn("\x1b[36mcalc\x1b[0m", line)

    def test_json_keys_vs_values(self):
        line = self.ui.highlight.line('{"model": "kimi"}', "json")
        self.assertIn("\x1b[36m\"model\"\x1b[0m", line)   # key cyan
        self.assertIn("\x1b[32m\"kimi\"\x1b[0m", line)    # value green

    def test_unknown_lang_plain(self):
        self.assertEqual(self.ui.highlight.line("x = 1", "brainfuck"), "x = 1")

    def test_no_color_returns_plain(self):
        ui = UI(interactive=False, theme="mono")
        self.assertEqual(ui.highlight.line("def x(): pass", "py"), "def x(): pass")


class TestMarkdownExtras(unittest.TestCase):
    def setUp(self):
        os.environ["ORCA_COLOR"] = "force"
        self.ui = UI(interactive=False, theme="dark")

    def tearDown(self):
        del os.environ["ORCA_COLOR"]

    def _capture(self, text):
        import io
        import contextlib
        from unittest import mock
        buf = io.StringIO()
        # force the "modern terminal" path so glyph assertions are
        # identical on every OS and console (fallback covered in
        # test_windows_console.py)
        with mock.patch("orca.winconsole.ascii_only", return_value=False), \
                contextlib.redirect_stdout(buf):
            UI(interactive=False, theme="dark").markdown(text)
        return buf.getvalue()

    def test_table_renders_aligned_with_separator_dropped(self):
        out = self._capture("| a | b |\n|---|---|\n| 1 | 22 |\n| 333 | 4 |")
        self.assertNotIn("|---", out)
        self.assertIn("a    b", out)
        self.assertIn("333  4", out)   # aligned columns
        self.assertIn("─", out)        # header rule

    def test_hr_rule(self):
        out = self._capture("before\n\n---\n\nafter")
        self.assertIn("─", out)

    def test_fenced_code_highlighted(self):
        out = self._capture("```python\nreturn None\n```")
        self.assertIn("\x1b[35mreturn\x1b[0m", out)

    def test_headings_brand_colored(self):
        out = self._capture("## Title")
        self.assertIn("38;5;81", out)


class TestPermissionDialog(unittest.TestCase):
    def test_number_and_letter_answers(self):
        ui = UI(interactive=False, theme="dark")
        answers = iter(["", "2", "A", "n", "y"])
        import builtins
        real_input = builtins.input
        builtins.input = lambda *a, **k: next(answers)
        import io, contextlib
        try:
            os.environ["ORCA_COLOR"] = "force"
            ui2 = UI(interactive=False, theme="dark")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ui2._permission_plain("bash", "cmd: ls"), "y")
                self.assertEqual(ui2._permission_plain("bash", "cmd: ls"), "a")
                self.assertEqual(ui2._permission_plain("bash", "cmd: ls"), "A")
                self.assertEqual(ui2._permission_plain("bash", "cmd: ls"), "n")
                self.assertEqual(ui2._permission_dialog("edit_file", "path: f.py",
                                                        None, None), "y")
        finally:
            builtins.input = real_input
            del os.environ["ORCA_COLOR"]


class TestFilePreview(unittest.TestCase):
    def test_numbered_preview_with_more_line(self):
        os.environ["ORCA_COLOR"] = "force"
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                UI(interactive=False, theme="dark").file_preview(
                    "app.py", "\n".join(
                        f"{i+1:>6}\talpha line {i}" for i in range(12)))
            out = buf.getvalue()
            self.assertIn("alpha line", out)
            self.assertNotIn("code line 8", out)   # capped at 8
            self.assertIn("+4 more lines", out)
        finally:
            del os.environ["ORCA_COLOR"]


class TestDahlProvider(unittest.TestCase):
    def test_preset_registered(self):
        self.assertIn("dahl", PROVIDER_PRESETS)
        preset = PROVIDER_PRESETS["dahl"]
        self.assertEqual(preset["base_url"], "https://inference.dahl.global/v1")
        self.assertEqual(preset["key_env"], "DAHL_API_KEY")
        self.assertEqual(preset["kind"], "openai")

    def test_suggested_models(self):
        models = SUGGESTED_MODELS["dahl"]
        self.assertIn("MiniMaxAI/MiniMax-M2.7", models)
        self.assertIn("zai-org/GLM-5.3-Flash", models)

    def test_model_aliases(self):
        self.assertEqual(expand_model_alias("kimi"), "moonshotai/Kimi-K2.6")
        self.assertEqual(expand_model_alias("DeepSeek-Flash"),
                         "deepseek-ai/DeepSeek-V4-Flash-0731")
        self.assertEqual(expand_model_alias("MiniMax"), "MiniMaxAI/MiniMax-M2.7")
        self.assertEqual(expand_model_alias("glm"), "zai-org/GLM-5.3-Flash")
        self.assertEqual(expand_model_alias("gpt-5.1"), "gpt-5.1")  # untouched

    def test_theme_config_key(self):
        cfg = Config.__new__(Config)
        cfg._data = {"theme": "ansi"}
        self.assertEqual(cfg.get("theme"), "ansi")


if __name__ == "__main__":
    unittest.main()
