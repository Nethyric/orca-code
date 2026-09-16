"""Deep Ocean v2: the visual identity.

256-color only — renders correctly in every terminal, including the
integrated ones IDEs ship with. Honors NO_COLOR and non-tty streams.
"""
import os
import sys
from typing import Optional


class Theme:
    # palette (fg, 256-color)
    WHALE = "38;5;81"      # deep-sea cyan — brand
    ACCENT = "38;5;81"
    SEAFOAM = "38;5;72"    # success
    CORAL = "38;5;203"     # errors
    SAND = "38;5;179"      # warnings
    LAVENDER = "38;5;139"  # tool names
    META = "38;5;245"      # secondary text
    FILE = "38;5;80"       # paths
    THINK = "38;5;102"     # reasoning, dim

    BANNER = r"""
     .-------------.
    |  🌊  ORCA     |  code, deeply.
     '-------------'
"""

    def __init__(self, enabled: Optional[bool] = None):
        if enabled is None:
            enabled = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self.enabled = bool(enabled)

    def paint(self, text: str, code: str, bold: bool = False) -> str:
        if not self.enabled or not code:
            return text
        prefix = "\x1b[1m" if bold else ""
        return f"\x1b[{code}m{prefix}{text}\x1b[0m"

    def dim(self, text: str) -> str:
        return self.paint(text, "2") if self.enabled else text

    def italic_dim(self, text: str) -> str:
        return f"\x1b[2;3m{text}\x1b[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self.paint(text, "1")

    # semantic helpers
    def whale(self, text: str) -> str:
        return self.paint(text, self.WHALE, bold=True)

    def ok(self, text: str) -> str:
        return self.paint(text, self.SEAFOAM)

    def err(self, text: str) -> str:
        return self.paint(text, self.CORAL)

    def warn(self, text: str) -> str:
        return self.paint(text, self.SAND)

    def tool(self, text: str) -> str:
        return self.paint(text, self.LAVENDER)

    def meta(self, text: str) -> str:
        return self.paint(text, self.META)

    def file(self, text: str) -> str:
        return self.paint(text, self.FILE)

    def banner(self, version: str) -> str:
        if not self.enabled:
            return f"Orca Code {version}"
        lines = [
            self.whale("     ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄"),
            self.whale("   ▄█████████████████▄   ") + self.paint("ORCA", self.WHALE, bold=True),
            self.paint("   ███████████████████   ", self.WHALE) + self.meta(f"code, deeply · v{version}"),
            self.whale("   ▀█████████████████▀"),
            self.whale("     ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀"),
        ]
        return "\n".join(lines)
