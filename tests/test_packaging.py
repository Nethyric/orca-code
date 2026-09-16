"""Packaging tests: `python -m orca`, the PyInstaller launcher, and the
zipapp builder — the three distribution formats shipped per release."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orca.config import VERSION                                    # noqa: E402

REPO = Path(__file__).resolve().parent.parent


class TestEntrypoints(unittest.TestCase):
    def test_python_dash_m_orca(self):
        out = subprocess.run(
            [sys.executable, "-m", "orca", "--version"],
            cwd=str(REPO), capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), f"orca-code {VERSION}")

    def test_pyinstaller_launcher_compiles(self):
        launcher = REPO / "packaging" / "launcher.py"
        self.assertTrue(launcher.is_file(), "packaging/launcher.py missing")
        # absolute imports only — it must survive bundling
        src = launcher.read_text(encoding="utf-8")
        self.assertNotIn("from .", src)
        compile(src, str(launcher), "exec")


class TestZipapp(unittest.TestCase):
    def test_build_pyz_runs_and_reports_version(self):
        sys.path.insert(0, str(REPO / "packaging"))
        import build_pyz
        with tempfile.TemporaryDirectory(prefix="orca-pyz-test-") as tmp:
            out = Path(tmp) / "orca.pyz"
            build_pyz.build(out)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 100_000)
            # runs under the current interpreter from an unrelated cwd
            res = subprocess.run(
                [sys.executable, str(out), "--version"],
                cwd=tmp, capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(res.stdout.strip(), f"orca-code {VERSION}")


if __name__ == "__main__":
    unittest.main()
