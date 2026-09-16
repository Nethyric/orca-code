"""Project memory — ORCA.md files, auto-injected into the system prompt."""
from __future__ import annotations

from pathlib import Path

from .config import global_memory_path

MEMORY_FILENAME = "ORCA.md"
LOCAL_MEMORY_FILENAME = "ORCA.local.md"

TEMPLATE = """\
# Project memory

Guidance here is automatically loaded into every Orca session.

## What is this project?
(one paragraph)

## Conventions
- (languages, frameworks, style rules, test commands)

## Build & test
- `...`

## Gotchas
- ...
"""


def load_memory(root: Path) -> tuple[str, list[Path]]:
    """Merge global + project memory files. Returns (text, paths_loaded)."""
    parts: list[str] = []
    paths: list[Path] = []

    global_path = global_memory_path()
    if global_path.is_file():
        paths.append(global_path)
        parts.append(f"### Global memory ({global_path})\n\n{global_path.read_text(encoding='utf-8', errors='replace').strip()}")

    for name in (MEMORY_FILENAME, LOCAL_MEMORY_FILENAME):
        path = root / name
        if path.is_file():
            paths.append(path)
            parts.append(f"### {name}\n\n{path.read_text(encoding='utf-8', errors='replace').strip()}")

    return ("\n\n".join(parts), paths)


def init_memory(root: Path) -> Path:
    path = root / MEMORY_FILENAME
    if path.exists():
        return path
    path.write_text(TEMPLATE, encoding="utf-8")
    return path
