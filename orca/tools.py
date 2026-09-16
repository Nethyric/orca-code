"""The Orca Code tool system — the model's hands and eyes.

Standard terminal-agent tool surface (read/write/edit/bash/grep/glob/ls/
todo) with an undo safety net: every write/edit is snapshotted so `/undo`
can revert the agent's last changes.
"""
from __future__ import annotations

import fnmatch
import difflib
import html as html_mod
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_READ_BYTES = 5_000_000
MAX_GREP_RESULTS = 200
MAX_GLOB_RESULTS = 500
MAX_BASH_OUTPUT = 30_000
DEFAULT_BASH_TIMEOUT = 120
MAX_BASH_TIMEOUT = 600

IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "target",
    ".next", ".nuxt", ".turbo", ".idea", ".tox", ".eggs", "*.egg-info",
    ".DS_Store", ".cache",
}

# Commands that are refused outright, in any permission mode.
CATASTROPHIC_BASH = [
    re.compile(r"rm\s+(-[a-z]+\s+)*-?[rf][a-z]*\s+(/|~|\$HOME)(\s|/|$)"),
    re.compile(r"mkfs(\.\w+)?\s"),
    re.compile(r":\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;:"),
    re.compile(r"dd\s+[^\n]*of=/dev/(sd|nvme|hd)"),
    re.compile(r">\s*/dev/sd"),
    re.compile(r"chmod\s+-R\s+777\s+/(\s|$)"),
    re.compile(r"curl[^|]*\|\s*(sudo\s+)?(sh|bash|zsh)\b"),
    re.compile(r"wget[^|]*\|\s*(sudo\s+)?(sh|bash|zsh)\b"),
]


class ToolError(Exception):
    """User-visible tool failure (returned to the model as an error result)."""


# --------------------------------------------------------------------------
# Agent-side state
# --------------------------------------------------------------------------

class UndoStack:
    """Snapshots of file writes/edits, grouped by agent turn, plus the
    session-start originals used by /diff."""

    def __init__(self) -> None:
        self.entries: List[Dict[str, Any]] = []
        self.originals: Dict[str, Optional[str]] = {}
        self._turn = 0

    def begin_turn(self) -> None:
        self._turn += 1

    @property
    def turn(self) -> int:
        return self._turn

    def snapshot(self, path: Path, root: Path) -> None:
        key = str(self._rel(path, root))
        if key not in self.originals:
            self.originals[key] = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None

    def push(self, path: Path, root: Path) -> None:
        before = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
        self.snapshot(path, root)
        self.entries.append({"turn": self._turn, "path": str(path), "before": before})

    def undo(self) -> List[str]:
        """Revert the most recent turn's file changes (a contiguous suffix)."""
        if not self.entries:
            return []
        last = self.entries[-1]["turn"]
        first = next((i for i, e in enumerate(self.entries) if e["turn"] == last),
                     len(self.entries))
        return self._revert_range(first)

    def rewind_to(self, entry_index: int) -> List[str]:
        """Revert every change recorded from `entry_index` onward (newest first)."""
        if entry_index >= len(self.entries):
            return []
        return self._revert_range(entry_index)

    def _revert_range(self, start: int) -> List[str]:
        restored: List[str] = []
        for entry in reversed(self.entries[start:]):
            path = Path(entry["path"])
            if entry["before"] is None:
                try:
                    path.unlink()
                    restored.append(f"deleted {path.name} (was newly created)")
                except OSError:
                    pass
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(entry["before"], encoding="utf-8")
                restored.append(f"restored {path.name}")
        self.entries = self.entries[:start]
        return restored

    @staticmethod
    def _rel(path: Path, root: Path) -> Path:
        try:
            return path.relative_to(root)
        except ValueError:
            return path


class ToolContext:
    def __init__(self, root: Path):
        self.root = root
        self.todos: List[Dict[str, str]] = []
        self.undo = UndoStack()

    def resolve(self, path: str) -> Path:
        p = Path(os.path.expanduser(path))
        if not p.is_absolute():
            p = self.root / p
        return Path(os.path.normpath(str(p)))

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()


# --------------------------------------------------------------------------
# Ignore handling (.gitignore-lite)
# --------------------------------------------------------------------------

def load_gitignore(root: Path) -> List[str]:
    path = root / ".gitignore"
    if not path.is_file():
        return []
    patterns = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("!"):
            patterns.append(line.rstrip("/"))
    return patterns


def is_ignored(rel_posix: str, patterns: List[str]) -> bool:
    parts = rel_posix.split("/")
    for pattern in patterns:
        pat = pattern.rstrip("/")
        if pat.endswith("/**") or pat.startswith("**/"):
            if fnmatch.fnmatch(rel_posix, pat):
                return True
            continue
        if fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(parts[-1], pat):
            return True
        # directory pattern: ignore everything beneath it
        if any(fnmatch.fnmatch(part, pat) for part in parts[:-1]):
            return True
    return False


def walk_files(root: Path, patterns: List[str]) -> List[Path]:
    """Deterministic recursive listing of files, respecting ignores."""
    out: List[Path] = []
    stack = sorted([p for p in root.iterdir()], key=lambda p: (p.is_file(), p.name))
    count = 0
    while stack and count < 50_000:
        current = stack.pop(0)
        rel = current.relative_to(root).as_posix()
        if (current.name in IGNORED_DIRS
                or any(fnmatch.fnmatch(current.name, pat) for pat in IGNORED_DIRS)
                or is_ignored(rel, patterns)):
            continue
        if current.is_dir():
            stack = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name)) + stack
            continue
        if current.is_file():
            out.append(current)
            count += 1
    return out


def glob_match(pattern: str, rel_posix: str) -> bool:
    """fnmatch with `**` support."""
    pat_parts = pattern.strip("/").split("/")
    path_parts = rel_posix.split("/")

    def match(pi: int, si: int) -> bool:
        if si == len(pat_parts):
            return pi == len(path_parts)
        part = pat_parts[si]
        if part == "**":
            for skip in range(pi, len(path_parts) + 1):
                if match(skip, si + 1):
                    return True
            return False
        if pi >= len(path_parts):
            return False
        if not fnmatch.fnmatch(path_parts[pi], part):
            return False
        return match(pi + 1, si + 1)

    return match(0, 0)


# --------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------

def _readable(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" not in fh.read(8192)
    except OSError:
        return False


def tool_read_file(ctx: ToolContext, args: Dict[str, Any]) -> str:
    path = ctx.resolve(args.get("path", ""))
    if not path.exists():
        raise ToolError(f"File not found: {ctx.rel(path)}")
    if path.is_dir():
        raise ToolError(f"{ctx.rel(path)} is a directory (use ls)")
    if path.stat().st_size > MAX_READ_BYTES:
        raise ToolError(f"File too large ({path.stat().st_size} bytes): {ctx.rel(path)}")
    if not _readable(path):
        raise ToolError(f"Binary file: {ctx.rel(path)}")
    offset = max(1, int(args.get("offset") or 1))
    limit = int(args.get("limit") or 2000)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    selected = lines[offset - 1: offset - 1 + limit]
    if not selected:
        return f"(no lines at offset {offset}; file has {total} lines)"
    out = [f"{i + offset:>6}\t{line}" for i, line in enumerate(selected)]
    if offset - 1 + limit < total:
        out.append(f"⋯ {total - (offset - 1 + limit)} more lines (use offset={offset + limit} to continue)")
    if offset > 1:
        out.insert(0, f"⋯ showing lines {offset}–{offset + len(selected) - 1} of {total}")
    return "\n".join(out)


def tool_write_file(ctx: ToolContext, args: Dict[str, Any]) -> str:
    path = ctx.resolve(args.get("path", ""))
    content = args.get("content")
    if content is None:
        raise ToolError("write_file requires 'content'")
    ctx.undo.push(path, ctx.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    n = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    return f"Wrote {ctx.rel(path)} ({max(n, 0)} lines)"


def _fuzzy_hint(content: str, old: str) -> Optional[str]:
    """Find the closest window to `old` so the model can self-correct."""
    old_lines = old.splitlines()
    file_lines = content.splitlines()
    if not old_lines or not (1 <= len(old_lines) <= 60) or len(file_lines) > 200_000:
        return None
    matcher = difflib.SequenceMatcher(None, old_lines, file_lines, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size > 0]
    if not blocks:
        return None
    start = min(b.b for b in blocks)
    end = max(b.b + b.size for b in blocks)
    start = max(0, start - 2)
    end = min(len(file_lines), end + 2)
    window = file_lines[start:end]
    ratio = difflib.SequenceMatcher(None, old_lines, window).ratio()
    if ratio < 0.4:
        return None
    snippet = "\n".join(f"{start + i + 1:>6}\t{line}" for i, line in enumerate(window[:12]))
    more = f"\n      ⋯ {len(window) - 12} more lines" if len(window) > 12 else ""
    return (f"old_string was not found, but the closest match is at lines "
            f"{start + 1}–{end} (similarity {ratio:.0%}):\n{snippet}{more}\n"
            f"Adjust old_string to match the file exactly (whitespace matters).")


def tool_edit_file(ctx: ToolContext, args: Dict[str, Any]) -> str:
    path = ctx.resolve(args.get("path", ""))
    old = args.get("old_string")
    new = args.get("new_string")
    if old is None or new is None:
        raise ToolError("edit_file requires 'old_string' and 'new_string'")
    if old == "":
        raise ToolError("old_string must be non-empty (use write_file to create files)")
    if not path.is_file():
        raise ToolError(f"File not found: {ctx.rel(path)}")
    content = path.read_text(encoding="utf-8", errors="replace")
    count = content.count(old)
    if count == 0:
        hint = _fuzzy_hint(content, old)
        raise ToolError(hint or f"old_string not found in {ctx.rel(path)}")
    replace_all = bool(args.get("replace_all"))
    if count > 1 and not replace_all:
        raise ToolError(
            f"old_string appears {count} times in {ctx.rel(path)}. "
            f"Provide more surrounding context to make it unique, or set replace_all=true."
        )
    ctx.undo.push(path, ctx.root)
    new_content = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    path.write_text(new_content, encoding="utf-8")
    line_no = new_content[: new_content.find(new) if new else 0].count("\n") + 1 if new in new_content else 1
    return (f"Edited {ctx.rel(path)} · {count if replace_all else 1} replacement(s) "
            f"· new text starts at line {line_no}")


def tool_bash(ctx: ToolContext, args: Dict[str, Any]) -> str:
    command = (args.get("command") or "").strip()
    if not command:
        raise ToolError("bash requires 'command'")
    timeout = min(int(args.get("timeout") or DEFAULT_BASH_TIMEOUT), MAX_BASH_TIMEOUT)
    for pattern in CATASTROPHIC_BASH:
        if pattern.search(command):
            raise ToolError(f"Refused: this command looks destructive ({pattern.pattern[:30]}…). "
                            f"Orca refuses catastrophic commands in every mode.")
    try:
        proc = subprocess.run(
            command, shell=True, cwd=str(ctx.root), capture_output=True,
            text=True, timeout=timeout,
        )
        output = proc.stdout or ""
        if proc.stderr:
            output += ("\n" if output else "") + proc.stderr
        tail = f"\n[exit code: {proc.returncode}]" if proc.returncode != 0 else ""
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        partial += (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return _truncate(f"{partial}\n[timed out after {timeout}s]")
    except OSError as exc:
        raise ToolError(f"Failed to run command: {exc}") from exc
    return _truncate(output + tail)


def _truncate(text: str) -> str:
    text = text.rstrip("\n")
    if len(text) <= MAX_BASH_OUTPUT:
        return text or "(no output)"
    head, tail = text[: MAX_BASH_OUTPUT // 2], text[-MAX_BASH_OUTPUT // 2:]
    dropped = len(text) - len(head) - len(tail)
    return f"{head}\n⋯ [truncated {dropped} characters] ⋯\n{tail}"


def tool_grep(ctx: ToolContext, args: Dict[str, Any]) -> str:
    pattern = args.get("pattern", "")
    if not pattern:
        raise ToolError("grep requires 'pattern' (a regular expression)")
    flags = re.IGNORECASE if args.get("ignore_case") else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise ToolError(f"Invalid regex: {exc}")
    search_root = ctx.resolve(args.get("path") or ".")
    if search_root.is_file():
        files = [search_root]
        base = search_root.parent
    else:
        if not search_root.exists():
            raise ToolError(f"Path not found: {ctx.rel(search_root)}")
        gitignore = load_gitignore(ctx.root)
        files = [f for f in walk_files(search_root, gitignore)
                 if f.stat().st_size <= 2_000_000 and _readable(f)]
        base = search_root
    glob_filter = args.get("glob")
    matches: List[str] = []
    scanned = 0
    for file in files:
        rel = _rel_to(base, file)
        if glob_filter and not glob_match(glob_filter, rel):
            continue
        scanned += 1
        try:
            for i, line in enumerate(
                file.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if regex.search(line):
                    matches.append(f"{rel}:{i}: {line.strip()[:400]}")
                    if len(matches) >= MAX_GREP_RESULTS:
                        matches.append(f"⋯ stopped after {MAX_GREP_RESULTS} matches")
                        return "\n".join(matches)
        except OSError:
            continue
    if not matches:
        return f"No matches for /{pattern}/ in {scanned} file(s)."
    return "\n".join(matches)


def _rel_to(base: Path, path: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def tool_glob(ctx: ToolContext, args: Dict[str, Any]) -> str:
    pattern = args.get("pattern", "")
    if not pattern:
        raise ToolError("glob requires 'pattern' (e.g. '**/*.py')")
    search_root = ctx.resolve(args.get("path") or ".")
    gitignore = load_gitignore(ctx.root)
    files = walk_files(search_root if search_root.is_dir() else ctx.root, gitignore)
    hits = [f for f in files if glob_match(pattern, _rel_to(ctx.root, f))]
    hits.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    if not hits:
        return f"No files matching {pattern}"
    shown = [ctx.rel(f) for f in hits[:MAX_GLOB_RESULTS]]
    if len(hits) > MAX_GLOB_RESULTS:
        shown.append(f"⋯ and {len(hits) - MAX_GLOB_RESULTS} more")
    return "\n".join(shown)


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n / 1:.1f}{unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n}B"


def tool_ls(ctx: ToolContext, args: Dict[str, Any]) -> str:
    path = ctx.resolve(args.get("path") or ".")
    if not path.exists():
        raise ToolError(f"Path not found: {ctx.rel(path)}")
    if path.is_file():
        return f"{ctx.rel(path)} · {_human(path.stat().st_size)}"
    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    out: List[str] = []
    for entry in entries:
        if entry.name in IGNORED_DIRS or entry.name.startswith(".orca"):
            if not args.get("all"):
                continue
        try:
            if entry.is_dir():
                out.append(f"{entry.name}/")
            else:
                out.append(f"{entry.name} · {_human(entry.stat().st_size)}")
        except OSError:
            continue
    return "\n".join(out) or "(empty directory)"


def tool_todo(ctx: ToolContext, args: Dict[str, Any]) -> str:
    todos = args.get("todos")
    if not isinstance(todos, list):
        raise ToolError("todo requires 'todos': a list of {content, status}")
    clean = []
    for item in todos[:50]:
        if isinstance(item, dict) and item.get("content"):
            status = item.get("status", "pending")
            if status not in ("pending", "in_progress", "completed"):
                status = "pending"
            clean.append({"content": str(item["content"]), "status": status})
    ctx.todos = clean
    return f"Todo list updated ({len(clean)} items)"


# --------------------------------------------------------------------------
# Web tools (zero-dependency: stdlib urllib + DuckDuckGo HTML, no API key)
# --------------------------------------------------------------------------

_WEB_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_MAX_WEB_BYTES = 2_000_000

_DDG_RESULT = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DDG_SNIPPET = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(fragment: str) -> str:
    return html_mod.unescape(_TAG_RE.sub("", fragment)).strip()


def _clean_ddg_url(href: str) -> str:
    href = html_mod.unescape(href)
    if "uddg=" in href:
        try:
            query = href.split("uddg=", 1)[1].split("&", 1)[0]
            return urllib.parse.unquote(query)
        except Exception:
            pass
    if href.startswith("//"):
        href = "https:" + href
    return href


def _parse_ddg(page: str):
    links = _DDG_RESULT.findall(page)
    snippets = _DDG_SNIPPET.findall(page) + [""] * len(links)
    results = []
    for (href, title), snippet in zip(links, snippets):
        url = _clean_ddg_url(href)
        title = _strip_tags(title)
        if not title or not url.startswith("http"):
            continue
        results.append((title, url, _strip_tags(snippet)))
    return results


def tool_web_search(ctx: ToolContext, args: Dict[str, Any]) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        raise ToolError("web_search requires 'query'")
    try:
        max_results = max(1, min(int(args.get("max_results") or 5), 8))
    except (TypeError, ValueError):
        max_results = 5
    endpoints = (
        "https://html.duckduckgo.com/html/?q=",
        "https://lite.duckduckgo.com/lite/?q=",
    )
    last_error = ""
    for endpoint in endpoints:
        try:
            request = urllib.request.Request(
                endpoint + urllib.parse.quote_plus(query),
                headers={"User-Agent": _WEB_UA, "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(request, timeout=15) as response:
                page = response.read(_MAX_WEB_BYTES).decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = str(exc)
            continue
        results = _parse_ddg(page)
        if not results:
            last_error = "no results parsed"
            continue
        lines = [f"Web results for: {query}"]
        for title, url, snippet in results[:max_results]:
            lines.append(f"\n{title}\n{url}\n{snippet[:400]}")
        return "\n".join(lines)
    raise ToolError(f"web_search failed ({last_error}). "
                    f"Network may be offline or the endpoint blocked.")


class _TextExtractor(HTMLParser):
    """Readable text + title out of an HTML page (readability-lite)."""
    _SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "pre"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def tool_web_fetch(ctx: ToolContext, args: Dict[str, Any]) -> str:
    url = (args.get("url") or "").strip()
    if not url:
        raise ToolError("web_fetch requires 'url'")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolError(f"Invalid URL: {url!r} (only http/https)")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": _WEB_UA, "Accept": "text/html,text/plain,*/*"})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(_MAX_WEB_BYTES)
            content_type = (response.headers.get("Content-Type") or "").lower()
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        raise ToolError(f"HTTP {exc.code} {exc.reason} for {url}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ToolError(f"web_fetch failed: {exc}") from exc
    text = raw.decode("utf-8", "replace")
    header = f"url: {final_url or url}"
    if "html" in content_type or "<html" in text[:2000].lower():
        extractor = _TextExtractor()
        try:
            extractor.feed(text)
            body = extractor.text()
            if extractor.title:
                header += f"\ntitle: {extractor.title.strip()[:200]}"
        except Exception:
            body = _strip_tags(text)
    else:
        body = text
    body = body.strip()
    if len(body) > 8000:
        body = body[:8000] + "\n\u22ef [truncated at 8000 of " + str(len(body)) + " chars]"
    if not body:
        raise ToolError(f"Empty response from {url}")
    return f"{header}\n\n{body}"


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

def _schema(props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "read_file",
        "perm": "read",
        "description": "Read a text file with 1-based line numbers. Use offset/limit for "
                       "slices of long files. Output is truncated with ⋯ markers.",
        "input_schema": _schema({
            "path": {"type": "string", "description": "File path (relative to the project root or absolute)"},
            "offset": {"type": "integer", "description": "Line number to start from (1-based)"},
            "limit": {"type": "integer", "description": "Max lines to return (default 2000)"},
        }, ["path"]),
        "fn": tool_read_file,
    },
    {
        "name": "write_file",
        "perm": "write",
        "description": "Create or overwrite a file with full content. Parent directories "
                       "are created automatically. Prefer edit_file for existing files.",
        "input_schema": _schema({
            "path": {"type": "string"},
            "content": {"type": "string", "description": "The complete file content"},
        }, ["path", "content"]),
        "fn": tool_write_file,
    },
    {
        "name": "edit_file",
        "perm": "write",
        "description": "Replace an exact string in a file. old_string must match exactly "
                       "(whitespace included) and be unique unless replace_all=true. "
                       "On mismatch a closest-match hint is returned.",
        "input_schema": _schema({
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence"},
        }, ["path", "old_string", "new_string"]),
        "fn": tool_edit_file,
    },
    {
        "name": "bash",
        "perm": "bash",
        "description": "Run a shell command in the project root. Output (stdout+stderr) is "
                       "combined and truncated to 30k chars. Non-zero exit codes are reported. "
                       "Use for builds, tests, git, and inspection.",
        "input_schema": _schema({
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "Seconds (default 120, max 600)"},
        }, ["command"]),
        "fn": tool_bash,
    },
    {
        "name": "grep",
        "perm": "read",
        "description": "Search file contents with a regular expression. Respects .gitignore "
                       "and skips binary/vendor directories. Returns path:line: text, max 200 matches.",
        "input_schema": _schema({
            "pattern": {"type": "string", "description": "Regular expression"},
            "path": {"type": "string", "description": "File or directory to search (default .)"},
            "glob": {"type": "string", "description": "Only search files matching this glob, e.g. '*.py'"},
            "ignore_case": {"type": "boolean"},
        }, ["pattern"]),
        "fn": tool_grep,
    },
    {
        "name": "glob",
        "perm": "read",
        "description": "Find files by glob pattern (supports **). Results sorted by modification time.",
        "input_schema": _schema({
            "pattern": {"type": "string", "description": "e.g. '**/*.py' or 'src/**/*.ts'"},
            "path": {"type": "string"},
        }, ["pattern"]),
        "fn": tool_glob,
    },
    {
        "name": "ls",
        "perm": "read",
        "description": "List a directory (dirs first). Use all=true to include dotfiles.",
        "input_schema": _schema({
            "path": {"type": "string"},
            "all": {"type": "boolean"},
        }, []),
        "fn": tool_ls,
    },
    {
        "name": "todo",
        "perm": "none",
        "description": "Update the task list for multi-step work. Pass the full list each time; "
                       "statuses: pending | in_progress | completed.",
        "input_schema": _schema({
            "todos": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                },
                "required": ["content", "status"],
            }},
        }, ["todos"]),
        "fn": tool_todo,
    },
    {
        "name": "web_search",
        "perm": "web",
        "description": "Search the web with DuckDuckGo (no API key). Returns titles, "
                       "URLs and snippets. Use for current documentation, error messages "
                       "and library APIs. Follow up with web_fetch for page contents.",
        "input_schema": _schema({
            "query": {"type": "string"},
            "max_results": {"type": "integer", "description": "1-8, default 5"},
        }, ["query"]),
        "fn": tool_web_search,
    },
    {
        "name": "task",
        "perm": "task",
        "description": "Spawn a subagent with a fresh context for one scoped, "
                       "self-contained sub-task (explore unfamiliar code, research an "
                       "approach, gather evidence) and return its final report. Keeps "
                       "the main conversation clean. The subagent cannot spawn further "
                       "subagents.",
        "input_schema": _schema({
            "prompt": {"type": "string",
                       "description": "Complete, self-contained instructions for the subagent"},
            "profile": {"type": "string", "enum": ["explore", "general"],
                        "description": "explore (default): read-only tools; general: full tool access"},
        }, ["prompt"]),
        "fn": None,   # executed by the Agent loop (needs agent state)
    },
    {
        "name": "web_fetch",
        "perm": "web",
        "description": "Fetch a web page by URL and return readable text (HTML is stripped). "
                       "Truncated to 8000 chars. Use for docs pages found via web_search.",
        "input_schema": _schema({
            "url": {"type": "string", "description": "Full http(s) URL"},
        }, ["url"]),
        "fn": tool_web_fetch,
    },
]

TOOL_BY_NAME: Dict[str, Dict[str, Any]] = {t["name"]: t for t in TOOLS}
ALL_TOOL_NAMES = {t["name"] for t in TOOLS}
# read-only toolset for explore-profile subagents
EXPLORE_TOOLS = {"read_file", "grep", "glob", "ls", "web_search", "web_fetch"}


def tool_specs() -> List[Dict[str, Any]]:
    """Schemas sent to the model (perm/fn stripped)."""
    return [{"name": t["name"], "description": t["description"],
             "input_schema": t["input_schema"]} for t in TOOLS]


def run_tool(name: str, args: Dict[str, Any], ctx: ToolContext) -> str:
    tool = TOOL_BY_NAME.get(name)
    if tool is None:
        raise ToolError(f"Unknown tool '{name}'. Available: {', '.join(TOOL_BY_NAME)}")
    if tool.get("fn") is None:
        raise ToolError(f"'{name}' is executed by the agent loop, not run_tool")
    if not isinstance(args, dict):
        raise ToolError(f"Invalid arguments for {name}: expected an object, "
                        f"got {type(args).__name__}")
    try:
        result = tool["fn"](ctx, args)
    except ToolError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ToolError(f"Invalid arguments for {name}: {exc}") from exc
    return result if isinstance(result, str) else str(result)
