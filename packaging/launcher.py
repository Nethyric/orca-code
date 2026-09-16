"""PyInstaller entry point for Orca Code.

The package's own ``orca/__main__.py`` uses a relative import, which cannot
be frozen directly; this launcher uses absolute imports instead. Build from
the repository root:

    pyinstaller --onefile --clean --name orca --paths . packaging/launcher.py
"""
import sys

from orca.cli import main

if __name__ == "__main__":
    sys.exit(main())
