"""Built-in tools. Filesystem access is sandboxed centrally; bash runs with
a hard timeout; every tool returns a ToolResult, never raises."""
import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .registry import Registry, ToolParam, ToolResult, ToolSpec
from .sandbox import Sandbox, SandboxError

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             ".mypy_cache", ".pytest_cache", "dist", "build"}


def _numbered(text: str, offset: int = 1) -> str:
    lines = text.splitlines()
    width = len(str(offset + max(len(lines) - 1, 0)))
    return "\n".join(f"{i + offset:>{width}} │ {line}"
                     for i, line in enumerate(lines))


def _closest(path: Path, old: str) -> str:
    """A tiny hint engine for edit misses."""
    best, best_score = "", -1.0
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8",
                                                errors="replace").splitlines()):
            score = _similarity(line, old)
            if score > best_score:
                best, best_score = line, score
    except OSError:
        return ""
    if best_score < 0.4:
        return ""
    return f"closest match (line {i + 1}): {best[:120]!r}"


def _similarity(a: str, b: str) -> float:
    a, b = a.strip(), b.strip()
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(len(sa | sb), 1)


def register_builtins(reg: Registry, sandbox: Sandbox,
                      bash_timeout: int = 120) -> None:
    root = sandbox.root

    def read_file(path: str, offset: int = 1, limit: int = 2000) -> ToolResult:
        try:
            target = sandbox.resolve(path)
        except SandboxError as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)
        if not target.is_file():
            return ToolResult(output=f"Error: not a file: {path}", is_error=True)
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        offset = max(1, int(offset))
        limit = max(1, int(limit))
        chunk = lines[offset - 1:offset - 1 + limit]
        if not chunk:
            return ToolResult(output=f"(no lines at offset {offset})")
        return ToolResult(
            output=_numbered("\n".join(chunk), offset)
            + (f"\n… ({len(lines)} lines total)" if offset + limit - 1 < len(lines)
               else ""))

    def write_file(path: str, content: str) -> ToolResult:
        try:
            target = sandbox.resolve(path)
        except SandboxError as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content, encoding="utf-8")
        verb = "overwrote" if existed else "created"
        return ToolResult(output=f"{verb} {path} ({len(content):,} chars)")

    def edit_file(path: str, old_string: str, new_string: str) -> ToolResult:
        try:
            target = sandbox.resolve(path)
        except SandboxError as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)
        if not target.is_file():
            return ToolResult(output=f"Error: not a file: {path}", is_error=True)
        text = target.read_text(encoding="utf-8", errors="replace")
        if text.count(old_string) == 0:
            hint = _closest(target, old_string)
            return ToolResult(
                output=(f"Error: old_string not found in {path}."
                        + (f" {hint}" if hint else "")), is_error=True)
        if text.count(old_string) > 1:
            return ToolResult(
                output=f"Error: old_string matches {text.count(old_string)} "
                       f"places in {path} — add context to make it unique.",
                is_error=True)
        target.write_text(text.replace(old_string, new_string, 1),
                          encoding="utf-8")
        return ToolResult(output=f"edited {path}")

    def bash(command: str, cwd: str = "", timeout: int = 0) -> ToolResult:
        workdir = root
        if cwd:
            try:
                workdir = sandbox.resolve(cwd)
            except SandboxError as exc:
                return ToolResult(output=f"Error: {exc}", is_error=True)
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(workdir),
                capture_output=True, text=True,
                timeout=max(5, int(timeout or bash_timeout)))
        except subprocess.TimeoutExpired:
            return ToolResult(
                output=f"Error: command timed out after "
                       f"{max(5, int(timeout or bash_timeout))}s: {command}",
                is_error=True)
        out = (proc.stdout + proc.stderr).strip()
        return ToolResult(output=out or f"(exit {proc.returncode}, no output)",
                          is_error=proc.returncode != 0)

    def grep(pattern: str, glob: str = "", limit: int = 200) -> ToolResult:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return ToolResult(output=f"Error: bad regex: {exc}", is_error=True)
        hits: List[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                           and not d.startswith(".")]
            for fname in filenames:
                if glob and not fnmatch.fnmatch(fname, glob):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    if fpath.stat().st_size > 2_000_000:
                        continue
                    for i, line in enumerate(
                            fpath.read_text(encoding="utf-8",
                                            errors="ignore").splitlines(), 1):
                        if rx.search(line):
                            rel = fpath.relative_to(root)
                            hits.append(f"{rel}:{i}: {line.strip()[:160]}")
                            if len(hits) >= int(limit):
                                raise _Stop()
                except _Stop:
                    break
                except OSError:
                    continue
            if len(hits) >= int(limit):
                break
        if not hits:
            return ToolResult(output=f"no matches for /{pattern}/")
        return ToolResult(output="\n".join(hits)
                          + (f"\n… (capped at {limit} matches)"
                             if len(hits) >= int(limit) else ""))

    def glob(pattern: str, limit: int = 500) -> ToolResult:
        matches = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime
                         if p.exists() else 0, reverse=True)
        if not matches:
            return ToolResult(output=f"no files match {pattern}")
        shown = [str(m.relative_to(root)) for m in matches[:int(limit)]]
        return ToolResult(output="\n".join(shown)
                          + (f"\n… ({len(matches)} total)" if len(matches) > int(limit)
                             else ""))

    def ls(path: str = ".") -> ToolResult:
        try:
            target = sandbox.resolve(path)
        except SandboxError as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)
        if not target.is_dir():
            return ToolResult(output=f"Error: not a directory: {path}",
                              is_error=True)
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
        if not entries:
            return ToolResult(output="(empty)")
        rows = [f"{'d' if e.is_dir() else '-'} {e.name}"
                + ("/" if e.is_dir() else "") for e in entries]
        return ToolResult(output="\n".join(rows[:400]))

    todo_state: Dict[str, List[str]] = {"items": []}

    def todo(action: str = "list", item: str = "") -> ToolResult:
        items = todo_state["items"]
        if action == "add" and item:
            items.append(f"[ ] {item}")
        elif action == "done" and item:
            items[:] = [f"[x] {i[3:].strip()}" if i[3:].strip() == item
                        else i for i in items]
        elif action == "clear":
            items.clear()
        return ToolResult(output="\n".join(items) or "(todo list empty)")

    reg.register(ToolSpec(
        "read_file", "Read a file with 1-based line numbers.",
        [ToolParam("path", "string", "file path", True),
         ToolParam("offset", "integer", "first line (default 1)"),
         ToolParam("limit", "integer", "max lines (default 2000)")],
        fn=read_file, readonly=True))
    reg.register(ToolSpec(
        "write_file", "Create or overwrite a file with full content.",
        [ToolParam("path", "string", "file path", True),
         ToolParam("content", "string", "full file content", True)],
        fn=write_file))
    reg.register(ToolSpec(
        "edit_file", "Replace an exact unique string in a file.",
        [ToolParam("path", "string", "file path", True),
         ToolParam("old_string", "string", "text to replace", True),
         ToolParam("new_string", "string", "replacement", True)],
        fn=edit_file))
    reg.register(ToolSpec(
        "bash", "Run a shell command in the project root.",
        [ToolParam("command", "string", "the command to run", True),
         ToolParam("cwd", "string", "working dir inside the root"),
         ToolParam("timeout", "integer", "seconds (default 120)")],
        fn=bash))
    reg.register(ToolSpec(
        "grep", "Regex search across the project.",
        [ToolParam("pattern", "string", "regex", True),
         ToolParam("glob", "string", "filename filter, e.g. *.py"),
         ToolParam("limit", "integer", "max matches (default 200)")],
        fn=grep, readonly=True))
    reg.register(ToolSpec(
        "glob", "Find files by pattern, newest first.",
        [ToolParam("pattern", "string", "glob like **/*.py", True),
         ToolParam("limit", "integer", "max results (default 500)")],
        fn=glob, readonly=True))
    reg.register(ToolSpec(
        "ls", "List a directory, dirs first.",
        [ToolParam("path", "string", "directory (default .)")],
        fn=ls, readonly=True))
    reg.register(ToolSpec(
        "todo", "Track multi-step work.",
        [ToolParam("action", "string", "add | done | list | clear"),
         ToolParam("item", "string", "todo text")],
        fn=todo, readonly=True))
    reg.register(ToolSpec(
        "task", "Spawn a scoped subagent for a sub-job and get its report.",
        [ToolParam("prompt", "string", "what the subagent should do", True),
         ToolParam("profile", "string", "explore (read-only) or general",
                   enum=["explore", "general"])],
        fn=None, readonly=True))


class _Stop(Exception):
    pass
