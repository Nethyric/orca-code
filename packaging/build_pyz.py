#!/usr/bin/env python3
"""Build orca.pyz — a single-file, zero-dependency distribution of Orca Code.

The zipapp runs anywhere Python 3.9+ is installed (``python orca.pyz``) and is
directly executable on Unix thanks to its shebang. Pure standard library:
``python3 packaging/build_pyz.py [--out dist/orca.pyz]``
"""
import argparse
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAIN = "import sys\nfrom orca.cli import main\nsys.exit(main())\n"


def build(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="orca-pyz-"))
    try:
        pkg = staging / "orca"
        shutil.copytree(REPO / "orca", pkg,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (staging / "__main__.py").write_text(MAIN, encoding="utf-8")
        if out.exists():
            out.unlink()
        zipapp.create_archive(staging, target=str(out),
                              interpreter="/usr/bin/env python3", main=None)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"built {out} ({out.stat().st_size:,} bytes)")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO / "dist" / "orca.pyz")
    args = ap.parse_args(argv)
    build(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
