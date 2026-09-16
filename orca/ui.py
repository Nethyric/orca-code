"""Terminal UI for Orca Code — themes, syntax highlighting, dialogs, meters.

Zero dependencies: everything degrades gracefully on dumb terminals and
Windows (VT sequences enabled at init; ASCII fallbacks for exotic glyphs).

Theme system (uses your terminal palette where possible; never assumes
24-bit truecolor is available):
    dark   — Deep Ocean: glacier-ice on dark water (Orca's signature)
    light  — Arctic Day: tuned for light backgrounds
    coral  — warm accents (soft contrast, low-glare)
    ansi   — pure 16-color: your terminal theme decides every color
    mono   — no color at all, glyphs preserved
Pick with `orca config`, `/theme <name>`, or ORCA_THEME. Force color for
pipes/screenshots with ORCA_COLOR=force; kill it with ORCA_COLOR=off.
"""
from __future__ import annotations

import re
import sys
import threading
import time
from contextlib import contextmanager
from typing import Iterator, List, Optional, Sequence

# --------------------------------------------------------------------------
# Themes
# --------------------------------------------------------------------------

# truecolor rgb, 256-color fallback, 16-color fallback
#
# Signature identity — "Deep Ocean": the orca's own world. Cold arctic
# water, glacier ice, seafoam. Precise, cold, fast.
_PALETTE = {
    "dark": {                                    # Deep Ocean — the default
        "brand": ("95;215;255", "81", "6"),      # glacier ice
        "teal": ("137;232;206", "86", "6"),      # seafoam
        "gray": ("124;138;150", "245", "8"),     # stormy slate
    },
    "light": {                                   # Arctic Day
        "brand": ("14;116;144", "74", "6"),
        "teal": ("16;122;101", "30", "6"),
        "gray": ("110;118;125", "242", "8"),
    },
    "coral": {                                   # warm, low-glare accents
        "brand": ("217;119;87", "173", "3"),
        "teal": ("125;211;192", "80", "6"),
        "gray": ("148;156;163", "245", "8"),
    },
}

_BASE = {
    "bold": "1",
    "dim": "2",
    "italic": "3",
    "underline": "4",
    "strike": "9",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
}

THEMES = ("dark", "light", "coral", "ansi", "mono")

_RESET = "\x1b[0m"


def _encoding_ok() -> bool:
    try:
        enc = sys.stdout.encoding or "utf-8"
        "⏺⎿•⋯❯🐋☒◐☐✢↻".encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# Fallbacks for terminals that cannot print the fancy glyphs.
_FALLBACK = {
    "⏺": "*", "⎿": "`", "•": "-", "⋯": "...", "❯": ">", "🐋": "<O>",
    "✔": "v", "✗": "x", "⚠": "!", "◐": "o", "█": "#", "░": ".",
    "╭": "+", "╮": "+", "╰": "+", "╯": "+", "─": "-", "│": "|",
    "┌": "+", "┐": "+", "└": "+", "┘": "+", "├": "+", "┤": "+",
    "☒": "[x]", "☐": "[ ]", "✢": "*", "✳": "*", "✶": "*", "✻": "*",
    "✽": "*", "↻": "R", "⏵": ">", "⏸": "||",
    "≈": "~", "≋": "~", "·": ".", "⌁": "~",
}


# --------------------------------------------------------------------------
# Syntax highlighting (tiny, stdlib-only, preview-grade)
# --------------------------------------------------------------------------

_PY_KW = {
    "def", "class", "return", "if", "elif", "else", "for", "while", "try",
    "except", "finally", "with", "as", "import", "from", "pass", "break",
    "continue", "raise", "yield", "lambda", "global", "nonlocal", "assert",
    "del", "in", "is", "not", "and", "or", "None", "True", "False", "async",
    "await", "self", "cls", "match", "case", "print",
}
_JS_KW = {
    "function", "const", "let", "var", "return", "if", "else", "for", "while",
    "do", "switch", "case", "default", "break", "continue", "new", "class",
    "extends", "import", "export", "from", "try", "catch", "finally", "throw",
    "typeof", "instanceof", "in", "of", "this", "super", "null", "undefined",
    "true", "false", "async", "await", "yield", "delete", "void", "static",
    "console",
}
_SH_KW = {
    "if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done",
    "case", "esac", "function", "return", "export", "local", "source", "echo",
    "cd", "set", "unset", "exit", "trap", "shift",
}
_YAML_KW = {"true", "false", "null", "yes", "no", "on", "off"}

_LANG_GROUPS = {
    "py": "py", "python": "py",
    "js": "js", "javascript": "js", "ts": "js", "typescript": "js",
    "jsx": "js", "tsx": "js", "mjs": "js", "cjs": "js",
    "json": "json",
    "sh": "sh", "bash": "sh", "zsh": "sh", "shell": "sh", "console": "sh",
    "yaml": "yaml", "yml": "yaml",
}

_STRING_PAT = r"""(?:[frbu]{0,2})(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)"""
_TOKEN = re.compile(
    r"(?P<comment>\#.*|//.*)"
    r"|(?P<string>%s)"
    r"|(?P<deco>@[A-Za-z_][\w.]*)"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<word>[A-Za-z_]\w*)"
    r"|(?P<other>\s+|.)"
    % _STRING_PAT,
)


class _Highlighter:
    """Token-at-a-time regex highlighter. Preview-grade, never raises."""

    def __init__(self, ui: "UI"):
        self.ui = ui

    def line(self, text: str, lang: Optional[str]) -> str:
        if not self.ui.color or not lang:
            return text
        group = _LANG_GROUPS.get((lang or "").lower())
        if group is None:
            return text
        out = []
        for m in _TOKEN.finditer(text):
            out.append(self._paint_token(m, text, m.end(), group))
        return "".join(out)

    def _paint_token(self, m: re.Match, line: str, pos: int, group: str) -> str:
        ui = self.ui
        if m.group("comment"):
            if group in ("py", "js", "sh"):
                return ui.paint(m.group("comment"), "gray", "italic")
            return m.group("comment")  # json/yaml have no comments
        if m.group("string"):
            s = m.group("string")
            if group == "json" and _json_is_key(line, pos):
                return ui.paint(s, "cyan")
            if group == "yaml" and _yaml_is_key(line, pos):
                return ui.paint(s, "cyan")
            return ui.paint(s, "green")
        if m.group("deco"):
            return ui.paint(m.group("deco"), "yellow", "italic")
        if m.group("number"):
            return ui.paint(m.group("number"), "brand")
        word = m.group("word")
        if word is not None:
            if group == "py":
                if word in _PY_KW:
                    return ui.paint(word, "magenta")
            elif group == "js":
                if word in _JS_KW:
                    return ui.paint(word, "magenta")
            elif group == "sh":
                if word in _SH_KW:
                    return ui.paint(word, "magenta")
                if _next_nonspace(line, pos) == "(":
                    return ui.paint(word, "cyan")
            elif group == "yaml":
                if word in _YAML_KW:
                    return ui.paint(word, "magenta")
                if _yaml_is_key(line, pos):
                    return ui.paint(word, "cyan")
            elif group == "json":
                if word in ("true", "false", "null"):
                    return ui.paint(word, "magenta")
            if _next_nonspace(line, pos) == "(" and word[0].isupper() is False:
                return ui.paint(word, "cyan")
        return m.group("word") or m.group("other")


def _next_nonspace(line: str, pos: int) -> str:
    for ch in line[pos:]:
        if not ch.isspace():
            return ch
    return ""


def _json_is_key(line: str, pos: int) -> bool:
    return _next_nonspace(line, pos) == ":"


def _yaml_is_key(line: str, pos: int) -> bool:
    rest = line[pos:]
    return ":" in rest.split("#", 1)[0]


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

class UI:
    """All printing goes through here so color/tty logic lives in one place."""

    def __init__(self, interactive: Optional[bool] = None, stderr: bool = False,
                 theme: Optional[str] = None):
        if interactive is None:
            interactive = sys.stdout.isatty()
        self.interactive = interactive
        self.stderr = stderr
        forced = (os_env("ORCA_COLOR") or "").lower()
        self.color = (
            (interactive or forced == "force")
            and not self._env_no_color()
            and forced != "off"
            and (os_env("TERM") != "dumb")
        )
        self.fancy = _encoding_ok()
        if os_name() == "nt":
            try:
                import ctypes  # noqa: F401
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                pass
        self._out = sys.stderr if stderr else sys.stdout
        self._streamed_newline = True
        self._reasoning_shown = False
        self._can_color = self.color
        self.set_theme(theme or os_env("ORCA_THEME") or "dark")
        self.highlight = _Highlighter(self)

    # -- theme ---------------------------------------------------------------

    def set_theme(self, name: str) -> None:
        if name not in THEMES:
            name = "dark"
        self.theme = name
        self.color = self._can_color and name != "mono"
        styles = dict(_BASE)
        if name in _PALETTE:
            pal = _PALETTE[name]
            truecolor = (
                self.color and "truecolor" in (os_env("COLORTERM") or "").lower()
            )
            for key, (rgb, c256, c16) in pal.items():
                styles[key] = (
                    f"38;2;{rgb}" if truecolor else f"38;5;{c256}"
                )
        elif name == "ansi":
            styles["brand"] = "36"   # let the terminal palette speak
            styles["teal"] = "32"
            styles["gray"] = "90"
        # "mono": no color styles — paint() returns text untouched
        self._styles = styles

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _env_no_color() -> bool:
        return bool(os_env("NO_COLOR") or os_env("ORCA_NO_COLOR"))

    def sym(self, s: str) -> str:
        return _FALLBACK.get(s, s) if not self.fancy else s

    def p(self, text: str = "", style: Optional[Sequence[str]] = None,
          file=None) -> None:
        out = file or self._out
        print(self.paint(text, *style) if style else text, file=out)

    def paint(self, text: str, *styles: str) -> str:
        if not self.color or not styles or self.theme == "mono":
            return text
        codes = ";".join(self._styles.get(s, "") for s in styles if s in self._styles)
        if not codes:
            return text
        return f"\x1b[{codes}m{text}{_RESET}"

    def width(self) -> int:
        try:
            import shutil
            return max(40, shutil.get_terminal_size((78, 24)).columns)
        except Exception:
            return 78

    def rule(self, label: str = "") -> None:
        w = min(self.width(), 100)
        if label:
            pad = max(0, w - len(label) - 4)
            self.p(f"{self.sym('─') * 2} {label} {self.sym('─') * pad}",
                   style=["gray"])
        else:
            self.p(self.sym("─") * w, style=["gray"])

    # -- streaming ------------------------------------------------------------

    def stream_text(self, delta: str) -> None:
        """Print assistant text as it arrives."""
        if self._reasoning_shown:
            print()            # close the thinking line before the answer
            self._reasoning_shown = False
        print(delta, end="", flush=True)
        self._streamed_newline = delta.endswith("\n")

    def reasoning(self, delta: str) -> None:
        """Stream a thinking model's reasoning — dim, italic, display-only."""
        if not self._reasoning_shown:
            self.end_stream()
            self.p(self.paint("  ⌁ thinking", "gray") if self.color
                   else "  - thinking", style=["gray"])
            self._reasoning_shown = True
        print(self.paint(delta, "gray", "italic") if self.color else delta,
              end="", flush=True)
        self._streamed_newline = delta.endswith("\n")

    def end_stream(self) -> None:
        if not self._streamed_newline:
            print()
        self._streamed_newline = True
        self._reasoning_shown = False

    # -- tool display ----------------------------------------------------------

    def tool_start(self, name: str, detail: str) -> None:
        self.end_stream()
        line = f"{self.paint(self.sym('⏺'), 'brand')} {self.paint(name, 'bold')}"
        if detail:
            line += self.paint(f"({self._short(detail)})", "gray")
        self.p(line)

    def tool_done(self, summary: str, is_error: bool = False) -> None:
        style = ["gray"] if not is_error else ["red"]
        mark = self.paint(self.sym("⎿"), *style)
        first, *rest = summary.splitlines() or [""]
        self.p(f"  {mark} {first}", style=style)
        for line in rest[:4]:
            self.p(f"    {line}", style=style)
        if len(rest) > 4:
            self.p(f"    {self.sym('⋯')} +{len(rest) - 4} more lines", style=["gray"])

    def file_preview(self, path: str, output: str, max_lines: int = 8) -> None:
        """Line-numbered, syntax-highlighted preview for read_file results."""
        lines = output.splitlines()
        if not lines:
            self.tool_done("(empty file)")
            return
        lang = path.rsplit(".", 1)[-1] if "." in path else ""
        mark = self.paint(self.sym("⎿"), "gray")
        gutter = self.paint(self.sym("│"), "gray")
        shown = lines[:max_lines]
        for raw in shown:
            num, _, code = raw.partition("\t")
            num = num.strip()
            if num.isdigit():
                self.p(f"  {mark} {self.paint(f'{num:>5} {gutter} ', 'gray')}"
                       f"{self.highlight.line(code, lang)}")
            else:
                self.p(f"  {mark} {self.paint(raw, 'gray')}")
        if len(lines) > max_lines:
            self.p(f"  {mark} {self.paint(self.sym('⋯') + f' +{len(lines) - max_lines} more lines', 'gray')}")

    @staticmethod
    def _short(s: str, limit: int = 78) -> str:
        s = " ".join(s.split())
        return s if len(s) <= limit else s[: limit - 1] + "…"

    # -- notices ---------------------------------------------------------------

    def ok(self, msg: str) -> None:
        self.p(f"{self.sym('✔')} {msg}", style=["green"])

    def warn(self, msg: str) -> None:
        self.p(f"{self.sym('⚠')} {msg}", style=["yellow"])

    def error(self, msg: str) -> None:
        self.p(f"{self.sym('✗')} {msg}", style=["red"])

    def notice(self, msg: str) -> None:
        self.p(f"{self.sym('•')} {msg}", style=["gray"])

    def print(self, *args, **kwargs) -> None:  # passthrough
        print(*args, **kwargs)

    # -- markdown-lite -----------------------------------------------------------

    _FENCE = re.compile(r"^```(\S*)\s*$")
    _HR = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
    _INLINE_CODE = re.compile(r"`([^`\n]+)`")
    _BOLD = re.compile(r"\*\*([^*\n]+)\*\*")

    def markdown(self, text: str) -> None:
        """Render a subset of markdown to the terminal."""
        self.end_stream()
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            fence = self._FENCE.match(line.strip())
            if fence:
                lang = fence.group(1)
                block = []
                i += 1
                while i < len(lines) and not self._FENCE.match(lines[i].strip()):
                    block.append(lines[i])
                    i += 1
                self.code_block(block, lang or None)
                i += 1
                continue
            if self._is_table_line(line) and i + 1 < len(lines) \
                    and self._is_table_line(lines[i + 1]) \
                    and set(lines[i + 1].replace("|", "").replace(" ", "")) <= {"-", ":"}:
                i = self._table(lines, i)
                continue
            i += 1
            stripped = line.strip()
            if not stripped:
                self.p()
                continue
            if self._HR.match(stripped):
                self.rule()
                continue
            if stripped.startswith("#"):
                head = stripped.lstrip("# ").strip()
                self.p(self.paint(head, "bold", "brand"))
                continue
            if stripped.startswith(("- ", "* ", "• ")):
                body = self._inline(stripped[2:])
                self.p(f"  {self.paint(self.sym('•'), 'brand')} {body}")
                continue
            if re.match(r"^\d+\. ", stripped):
                num, _, body = stripped.partition(". ")
                self.p(f"  {self.paint(num + '.', 'bold', 'brand')} {self._inline(body)}")
                continue
            if stripped.startswith(">"):
                self.p(f"  {self.paint(self.sym('│'), 'gray')} "
                       f"{self._inline(stripped.lstrip('> '))}", style=["gray"])
                continue
            self.p(self._inline(line.rstrip()))

    def code_block(self, block: List[str], lang: Optional[str],
                   max_lines: int = 30) -> None:
        self.p(f"  {self.paint(self.sym('┌') + (f' {lang}' if lang else ''), 'gray')}")
        for line in block[:max_lines]:
            self.p(f"  {self.paint(self.sym('│'), 'gray')} "
                   f"{self.highlight.line(line, lang)}")
        if len(block) > max_lines:
            self.p(f"  {self.paint(self.sym('│'), 'gray')} "
                   f"{self.paint(self.sym('⋯') + f' +{len(block) - max_lines} more', 'gray')}")
        self.p(f"  {self.paint(self.sym('└'), 'gray')}")

    @staticmethod
    def _is_table_line(line: str) -> bool:
        s = line.strip()
        return s.startswith("|") and s.endswith("|") and s.count("|") >= 2

    def _table(self, lines: List[str], i: int) -> int:
        rows = []
        while i < len(lines) and self._is_table_line(lines[i]):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows.append(cells)
            i += 1
        if len(rows) >= 2 and rows[1] and all(
                set(c) <= {"-", ":"} and c for c in rows[1] if c.strip()):
            rows.pop(1)  # drop the |---|---| separator
        if not rows:
            return i
        ncol = max(len(r) for r in rows)
        widths = [0] * ncol
        for r in rows:
            for c, cell in enumerate(r):
                widths[c] = max(widths[c], len(self._strip_inline(cell)))
        for ri, r in enumerate(rows):
            parts = []
            for c in range(ncol):
                cell = r[c] if c < len(r) else ""
                parts.append(self._inline(cell).ljust(widths[c]))
            row = "  " + "  ".join(parts)
            self.p(self.paint(row, "bold") if ri == 0 else row)
            if ri == 0:
                self.p("  " + "  ".join(self.paint(self.sym("─") * w, "gray")
                                        for w in widths))
        return i

    @staticmethod
    def _strip_inline(s: str) -> str:
        return re.sub(r"[`*]", "", s)

    def _inline(self, s: str) -> str:
        if not self.color:
            return s
        s = self._INLINE_CODE.sub(lambda m: self.paint(m.group(1), "teal"), s)
        s = self._BOLD.sub(lambda m: self.paint(m.group(1), "bold"), s)
        return s

    # -- status widgets -------------------------------------------------------

    def context_meter(self, used: int, window: int) -> None:
        if window <= 0:
            return
        frac = min(1.0, used / window)
        width = 18
        filled = int(round(frac * width))
        # the water level rises as the context fills — Orca's signature meter
        bar = "".join(
            self.paint(self.sym("≈"), "green") if (n + 1) / width < 0.6
            else (self.paint(self.sym("≈"), "yellow") if (n + 1) / width < 0.85
                  else self.paint(self.sym("≈"), "red"))
            for n in range(filled)
        ) + self.paint(self.sym("·") * (width - filled), "gray")
        style = "green" if frac < 0.6 else ("yellow" if frac < 0.85 else "red")
        pct = self.paint(f"{int(frac * 100):3d}%", style)
        left = self.paint(f"{fmt_tokens(max(0, window - used))} left", "gray")
        hint = self.paint(f" · {self.sym('↻')} /compact soon", "yellow") \
            if frac >= 0.8 else ""
        self.p(f"  context {self.sym('▏')}{bar}{self.sym('▏')} {pct} · "
               f"{fmt_tokens(used)}/{fmt_tokens(window)} · {left}{hint}",
               style=["gray"])

    def cost_line(self, text: str) -> None:
        whale = self.paint(self.sym("🐋"), "brand")
        self.p(f"  {whale} {self.paint(text, 'gray')}")

    def turn_footer(self, used: int, window: int, cost_text: str) -> None:
        self.end_stream()
        self.context_meter(used, window)
        self.cost_line(cost_text)

    # -- spinner -----------------------------------------------------------------

    _SPIN_FRAMES = "✢✳✶✻✽✻✶✳"
    _SPIN_VERBS = ("Pondering", "Echolocating", "Reading the currents",
                   "Swimming deeper", "Mulling it over", "Hunting",
                   "Porpoising", "Diving")

    @contextmanager
    def thinking(self, label: str = "Thinking") -> Iterator[None]:
        if not self.interactive or not sys.stderr.isatty():
            yield
            return
        state = {"stop": False}

        def spin() -> None:
            frames = self._SPIN_FRAMES if self.fancy else "*"
            colors = ["brand", "white", "teal", "cyan"] if self.color else [None]
            start = time.time()
            i = 0
            while not state["stop"]:
                elapsed = time.time() - start
                verb = self._SPIN_VERBS[int(elapsed / 2.4) % len(self._SPIN_VERBS)] \
                    if self.fancy else label
                frame = self.paint(frames[i % len(frames)], colors[(i // 3) % len(colors)])
                sys.stderr.write(f"\r\x1b[2m{frame} {verb}… ({elapsed:.1f}s)\x1b[0m")
                sys.stderr.flush()
                i += 1
                time.sleep(0.12)
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()

        thread = threading.Thread(target=spin, daemon=True)
        thread.start()
        try:
            yield
        finally:
            state["stop"] = True
            thread.join(timeout=1.0)

    # -- prompts -------------------------------------------------------------------

    def ask_permission(self, tool: str, detail: str, pattern: Optional[str] = None,
                       diff: Optional[str] = None) -> str:
        """Interactive permission prompt. Returns 'y', 'a' (session), 'A' (persist), 'n'."""
        if self.fancy and self.color:
            return self._permission_dialog(tool, detail, pattern, diff)
        return self._permission_plain(tool, detail, pattern, diff)

    def _permission_dialog(self, tool: str, detail: str,
                           pattern: Optional[str] = None,
                           diff: Optional[str] = None) -> str:
        def _clip(s: str, limit: int) -> str:
            return s if len(s) <= limit else s[: limit - 1] + "…"

        rows = []
        for line in detail.splitlines()[:10]:
            k, sep, v = line.partition(":")
            if sep and len(k.strip()) <= 8:
                rows.append((k.strip(), _clip(v.strip(), 46)))
            else:
                rows.append(("", _clip(line.strip(), 52)))
        title = f" {tool} "
        diff_lines = diff.splitlines()[:18] if diff else []
        diff_lines = [_clip(d, 58) for d in diff_lines]
        longest = max([len(title)] + [len(k) + len(v) + 8 for k, v in rows]
                      + [len(d) + 4 for d in diff_lines] + [34])
        w = min(longest + 5, 68)

        self.p()
        edge = self.paint(self.sym("─") * (w - len(title) - 3), "brand")
        self.p(f"{self.sym('╭')}{edge}"
               f"{self.paint(title, 'bold', 'brand')}"
               f"{self.paint(self.sym('─'), 'brand')}{self.sym('╮')}")
        for k, v in rows:
            if k:
                key_p = self.paint(k.ljust(7), "gray")
                pad = " " * max(0, w - 4 - 7 - len(v))
                self.p(f"{self.sym('│')} {key_p}{self.paint(v, 'cyan')}{pad}{self.sym('│')}")
            else:
                pad = " " * max(0, w - 4 - len(v))
                self.p(f"{self.sym('│')} {self.paint(v, 'cyan')}{pad}{self.sym('│')}")
        if diff_lines:
            label = " change "
            self.p(f"{self.sym('├')}{self.paint(self.sym('─') * 2 + label, 'brand')}"
                   f"{self.paint(self.sym('─') * (w - len(label) - 5), 'brand')}{self.sym('┤')}")
            for line in diff_lines:
                if line.startswith("+"):
                    painted, style = line, "green"
                elif line.startswith("-"):
                    painted, style = line, "red"
                elif line.startswith("@"):
                    painted, style = line, "cyan"
                else:
                    painted, style = line, "gray"
                pad = " " * max(0, w - 4 - len(line))
                self.p(f"{self.sym('│')}  {self.paint(painted, style)}{pad}{self.sym('│')}")
        self.p(f"{self.sym('╰')}{self.paint(self.sym('─') * (w - 2), 'brand')}{self.sym('╯')}")
        self.p(f"  {self.paint('1', 'bold')}. Yes   {self.paint('2', 'bold')}. Always this "
               f"session   {self.paint('3', 'bold')}. Always + save   "
               f"{self.paint('4', 'bold')}. No")
        while True:
            try:
                raw = input(self.paint(f"  {self.sym('❯')} ", "bold", "brand")).strip()
            except (EOFError, KeyboardInterrupt):
                return "n"
            answer = raw.lower()
            if answer in ("", "y", "yes", "1"):
                return "y"
            if answer in ("a", "2"):
                return "a"
            if raw == "A" or answer in ("3", "always+save"):
                return "A"
            if answer in ("n", "no", "4"):
                return "n"
            self.p("  1-4 or y / a / A / n", style=["gray"])

    def _permission_plain(self, tool: str, detail: str,
                           pattern: Optional[str] = None,
                          diff: Optional[str] = None) -> str:
        self.p()
        label = pattern or tool
        self.p(f"  {self.sym('⏺')} Orca wants to use {self.paint(tool, 'bold')}:")
        for line in detail.splitlines()[:12]:
            self.p(f"    {self.paint(self.sym('│'), 'yellow')} {line}")
        if diff:
            self.render_diff(diff, indent=6)
        hint = " [y]es · [a]lways this session · [A]lways+save · [n]o"
        if not self.fancy:
            hint = " [y]es / [a]lways session / [A]lways+save / [n]o"
        while True:
            try:
                answer = input(self.paint(f"  Allow {label}?{hint} ", "bold")).strip()
            except (EOFError, KeyboardInterrupt):
                return "n"
            if answer in ("", "y", "yes", "1"):
                return "y"
            if answer in ("a", "2"):
                return "a"
            if answer in ("A", "3"):
                return "A"
            if answer in ("n", "no", "4"):
                return "n"

    def render_diff(self, diff: str, indent: int = 2, max_lines: int = 40) -> None:
        """Render a unified diff with +/- coloring, capped to max_lines."""
        pad = " " * indent
        shown = 0
        for line in diff.splitlines():
            if shown >= max_lines:
                self.p(f"{pad}{self.sym('⋯')} (+{len(diff.splitlines()) - shown} more diff lines)",
                       style=["gray"])
                break
            shown += 1
            if line.startswith("+"):
                self.p(f"{pad}{self.paint(line, 'green')}")
            elif line.startswith("-"):
                self.p(f"{pad}{self.paint(line, 'red')}")
            elif line.startswith("@"):
                self.p(f"{pad}{self.paint(line, 'cyan')}")
            else:
                self.p(f"{pad}{self.paint(line, 'gray')}")

    def confirm(self, question: str, default: bool = True) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        try:
            answer = input(self.paint(f"{question} {suffix} ", "bold")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if not answer:
            return default
        return answer in ("y", "yes")

    # -- banner ----------------------------------------------------------------------

    _TIPS = (
        "/undo reverts the last file change — /rewind n also rewinds the chat.",
        "orca -p \"prompt\" runs one task non-interactively, exit code included.",
        "/cost shows your cache hit rate — cached tokens bill ~10%.",
        "/permissions acceptEdits stops the edit prompts without going full yolo.",
        "/system prints the exact system prompt you are paying for.",
        "Bash(git *) style rules live in .orca/settings.local.json.",
        "orca -c picks up your last session where it left off.",
        "/model switches mid-session — fast models for reads, big ones for writes.",
    )

    def banner(self, version: str, provider: str, model: str, root: str, mode: str) -> None:
        whale = self.sym("🐋")
        title = f" {whale}  ORCA CODE  v{version} "
        pad = max(1, 46 - len(title) - 1)  # -1: the whale renders 2 cols wide
        border = self.paint(self.sym("─") * 46, "brand")
        waves = self.paint(self.sym("≈") * 46, "brand")
        self.p()
        self.p(f"{self.sym('╭')}{border}{self.sym('╮')}")
        self.p(f"{self.sym('│')}{self.paint(title + ' ' * pad, 'bold')}{self.sym('│')}")
        self.p(f"{self.sym('╰')}{waves}{self.sym('╯')}")
        theme_note = f" · theme {self.theme}" if self.theme != "dark" else ""
        self.p(f"  provider  {self.paint(provider, 'teal')}"
               f"   model  {self.paint(model, 'teal')}{theme_note}", style=["gray"])
        self.p(f"  root      {root}", style=["gray"])
        self.p(f"  mode      {self.paint(mode, 'yellow')}", style=["gray"])
        tip = self._TIPS[int(time.time() // 86400) % len(self._TIPS)]
        self.p(f"  {self.paint('?', 'bold')} for hints · /help for commands · tip: {tip}",
               style=["gray"])
        self.p()

    def todos(self, items: List[dict]) -> None:
        """Compact todo list with strike-through on done items."""
        self.end_stream()
        if not items:
            return
        self.p(f"  {self.paint(self.sym('⏺'), 'bold')} {self.paint('Update Todos', 'bold')}")
        for item in items:
            status = item.get("status", "pending")
            if status == "completed":
                mark = self.paint(self.sym("☒"), "green")
                text = self.paint(item.get("content", ""), "gray", "strike")
            elif status == "in_progress":
                mark = self.paint(self.sym("◐"), "brand", "bold")
                text = self.paint(item.get("content", ""), "bold")
            else:
                mark = self.paint(self.sym("☐"), "gray")
                text = item.get("content", "")
            self.p(f"    {self.paint(self.sym('⎿'), 'gray')} {mark} {text}")
        self.p()


def fmt_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


def os_name() -> str:
    import os
    return os.name


def os_env(key: str) -> Optional[str]:
    import os
    return os.environ.get(key)
