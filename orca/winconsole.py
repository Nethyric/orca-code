"""Windows console initialization — stdlib-only, no-op on other platforms.

A plain cmd.exe window (conhost) ships with three defaults that wreck rich
terminal UIs:

1. a legacy code page (cp437 / cp1252) — UTF-8 bytes render as mojibake
2. VT processing disabled — ANSI color codes print as literal ``←[36m`` garbage
3. no ``WT_SESSION`` env var — conhost, often with a font that lacks the glyphs

``setup()`` fixes 1 and 2 (UTF-8 code page + ENABLE_VIRTUAL_TERMINAL_PROCESSING)
and reports capabilities so the UI can choose its look: full Deep Ocean glyphs
in Windows Terminal, a clean ASCII set in legacy consoles.
"""
from __future__ import annotations

import os
from typing import Dict

# populated once by setup(); tests may patch this dict directly
_CAPS: Dict[str, bool] = {}

_ENABLE_VT = 0x0004            # ENABLE_VIRTUAL_TERMINAL_PROCESSING
_STD_OUTPUT_HANDLE = -11


def setup() -> Dict[str, bool]:
    """Initialize the console (Windows) or return platform caps. Idempotent."""
    if _CAPS:
        return caps()
    info = {
        "windows": os.name == "nt",
        "vt": False,        # ANSI escape sequences processed?
        "utf8": False,      # console code page set to 65001?
        "modern": False,    # Windows Terminal (full glyph support)?
    }
    if info["windows"]:
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            # 1) UTF-8 output code page so UTF-8 bytes decode correctly
            info["utf8"] = bool(k32.SetConsoleOutputCP(65001))
            # 2) enable VT processing, preserving the existing console flags
            handle = k32.GetStdHandle(_STD_OUTPUT_HANDLE)
            mode = ctypes.c_uint32()
            if handle and k32.GetConsoleMode(handle, ctypes.byref(mode)):
                if (mode.value & _ENABLE_VT) or k32.SetConsoleMode(
                        handle, mode.value | _ENABLE_VT):
                    info["vt"] = True
        except Exception:
            pass            # non-console stream or restricted environment
        # 3) Windows Terminal announces itself; plain conhost does not
        info["modern"] = bool(os.environ.get("WT_SESSION"))
    _CAPS.update(info)
    return caps()


def caps() -> Dict[str, bool]:
    """Cached capability dict (calls setup() if it hasn't run yet)."""
    if not _CAPS:
        return setup()
    return dict(_CAPS)


def ascii_only() -> bool:
    """True when the console can't be trusted with Unicode UI glyphs."""
    c = caps()
    return c["windows"] and not c["modern"]
