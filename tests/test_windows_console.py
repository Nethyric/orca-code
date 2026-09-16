"""Windows console detection & fallback logic (runs on any OS, Windows mocked)."""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orca import winconsole  # noqa: E402
from orca.ui import UI, _encoding_ok, glyph  # noqa: E402


class TestWinConsoleCaps(unittest.TestCase):
    def test_setup_on_this_platform_is_safe(self):
        caps = winconsole.setup()
        self.assertIn("windows", caps)
        self.assertIn("vt", caps)
        self.assertIn("utf8", caps)
        self.assertIn("modern", caps)
        self.assertEqual(caps["windows"], os.name == "nt")
        # idempotent
        self.assertEqual(winconsole.setup(), caps)

    def test_ascii_only_legacy_cmd(self):
        with mock.patch.dict(winconsole._CAPS,
                             {"windows": True, "vt": True, "utf8": True,
                              "modern": False}):
            self.assertTrue(winconsole.ascii_only())   # plain cmd.exe

    def test_ascii_only_windows_terminal(self):
        with mock.patch.dict(winconsole._CAPS,
                             {"windows": True, "vt": True, "utf8": True,
                              "modern": True}):
            self.assertFalse(winconsole.ascii_only())  # Windows Terminal

    def test_ascii_only_posix(self):
        with mock.patch.dict(winconsole._CAPS,
                             {"windows": False, "vt": True, "utf8": True,
                              "modern": False}):
            self.assertFalse(winconsole.ascii_only())


class TestEncodingGate(unittest.TestCase):
    def test_legacy_cmd_disables_fancy_glyphs(self):
        with mock.patch.dict(winconsole._CAPS,
                             {"windows": True, "vt": True, "utf8": True,
                              "modern": False}):
            self.assertFalse(_encoding_ok())

    def test_windows_terminal_allows_fancy_glyphs(self):
        buf = io.StringIO()  # utf-8-capable stream, like a real WT session
        with mock.patch.dict(winconsole._CAPS,
                             {"windows": True, "vt": True, "utf8": True,
                              "modern": True}), redirect_stdout(buf):
            self.assertTrue(_encoding_ok())

    def test_glyph_falls_back_on_legacy_cmd(self):
        with mock.patch.dict(winconsole._CAPS,
                             {"windows": True, "vt": True, "utf8": True,
                              "modern": False}):
            self.assertEqual(glyph("🐋"), "<O>")
            self.assertEqual(glyph("◆"), "*")
        buf = io.StringIO()
        with mock.patch.dict(winconsole._CAPS,
                             {"windows": True, "vt": True, "utf8": True,
                              "modern": True}), redirect_stdout(buf):
            self.assertEqual(glyph("🐋"), "🐋")


class TestUIConsoleBehavior(unittest.TestCase):
    ENV = {"NO_COLOR": "", "ORCA_COLOR": "", "ORCA_NO_COLOR": "",
           "TERM": "xterm"}

    def _make_ui(self, caps):
        env = dict(self.ENV)
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch("orca.ui.os_name", return_value="nt"), \
             mock.patch.dict(winconsole._CAPS, caps), \
             redirect_stdout(io.StringIO()):
            ui = UI(interactive=True)
        return ui

    def test_color_off_when_vt_unavailable(self):
        ui = self._make_ui({"windows": True, "vt": False, "utf8": True,
                            "modern": False})
        self.assertFalse(ui.color)   # no raw ESC garbage in old consoles
        self.assertFalse(ui.fancy)   # ASCII glyph set
        self.assertEqual(ui.sym("◆"), "*")

    def test_color_on_when_vt_available(self):
        ui = self._make_ui({"windows": True, "vt": True, "utf8": True,
                            "modern": False})
        self.assertTrue(ui.color)
        self.assertFalse(ui.fancy)   # still ASCII glyphs in legacy conhost
        self.assertEqual(ui.sym("🐋"), "<O>")

    def test_full_fancy_in_windows_terminal(self):
        ui = self._make_ui({"windows": True, "vt": True, "utf8": True,
                            "modern": True})
        self.assertTrue(ui.color)
        self.assertTrue(ui.fancy)
        self.assertEqual(ui.sym("◆"), "◆")


if __name__ == "__main__":
    unittest.main()
