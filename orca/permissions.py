"""Permission engine — friction scaled to how dangerous an action is.

Modes:
  * default      — reads always allowed; edits ask once per session; bash asks
                   unless clearly read-only AND metacharacter-free, or allowlisted
  * acceptEdits  — file edits auto-approved; bash and web still gated
  * plan         — read-only exploration; writes, bash and web fetches are denied
  * yolo         — everything allowed except catastrophic commands

Rules look like "Bash(git *)" (fnmatch on the command), "Edit", "Write",
"read_file", "web_search" etc. Deny beats allow. Rules persist in
.orca/settings*.json.
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any, Dict, List, Optional, Tuple

from .tools import CATASTROPHIC_BASH

MODES = ("default", "acceptEdits", "plan", "yolo")

# Commands auto-allowed in every mode *only when they contain no shell
# metacharacters* — `ls; rm -rf ~` must never slip through the prefix check.
SAFE_BASH_PREFIXES = (
    "ls", "pwd", "echo", "cat ", "head ", "tail ", "wc ", "file ",
    "git status", "git diff", "git log", "git show", "git branch", "git stash list",
    "grep ", "rg ", "which ", "whoami", "date", "uname",
    "python --version", "python3 --version", "node --version", "npm --version",
    "pip list", "pip freeze", "git --version", "docker ps", "docker images",
)

# Anything that can chain, redirect, substitute or execute another command.
_SHELL_META = re.compile(r"[;&|<>`\n\r]|\$\(|\|\||&&|\bexec\b|\bxargs\b")

PLAN_MODE_NOTICE = (
    "Plan mode is active: file modifications, command execution and web access "
    "are disabled. Explore the codebase (read_file/grep/glob/ls) and present a "
    "concrete implementation plan. The user will switch to execution mode after review."
)


class PermissionDenied(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def is_readonly_bash(command: str) -> bool:
    """True only for simple, metacharacter-free, known-read-only commands."""
    command = (command or "").strip()
    if not command or _SHELL_META.search(command):
        return False
    return any(command == p.rstrip() or command.startswith(p) for p in SAFE_BASH_PREFIXES)


class Permissions:
    def __init__(self, mode: str = "default", allow: Optional[List[str]] = None,
                 deny: Optional[List[str]] = None):
        if mode not in MODES:
            raise ValueError(f"Unknown permission mode '{mode}' (use {'/'.join(MODES)})")
        self.mode = mode
        self.allow: List[str] = list(allow or [])
        self.deny: List[str] = list(deny or [])

    # -- evaluation ----------------------------------------------------------

    def check(self, tool: str, args: Dict[str, Any], root=None) -> str:
        """Return 'allow', 'ask' or a denial reason string prefixed with 'deny:'."""
        perm = _perm_category(tool)

        if self._matches(self.deny, tool, args):
            return f"deny:Blocked by a deny rule for {tool}."

        if perm == "bash" and any(p.search(args.get("command", "")) for p in CATASTROPHIC_BASH):
            return "deny:Refused — this command looks catastrophic and is blocked in every mode."

        if self.mode == "yolo":
            return "allow"
        if self.mode == "plan":
            if perm in ("write", "bash", "web"):
                return f"deny:{PLAN_MODE_NOTICE}"
            return "allow"  # reads
        if self._matches(self.allow, tool, args):
            return "allow"
        if self.mode == "acceptEdits" and perm == "write":
            return "allow"

        if perm in ("read", "none"):
            return "allow"
        if perm == "bash":
            if is_readonly_bash(args.get("command", "")):
                return "allow"
            return "ask"
        if perm == "web":
            return "ask"
        # write in default mode: ask
        return "ask"

    # -- rules ---------------------------------------------------------------

    def allow_session(self, rule: str) -> None:
        if rule not in self.allow:
            self.allow.append(rule)

    # short names are accepted as aliases
    _ALIASES = {"edit": "edit_file", "write": "write_file", "read": "read_file",
                "webfetch": "web_fetch", "websearch": "web_search", "glob": "glob",
                "grep": "grep", "ls": "ls", "todo": "todo"}

    def _matches(self, rules: List[str], tool: str, args: Dict[str, Any]) -> bool:
        for rule in rules:
            if "(" in rule and rule.endswith(")"):
                name, _, pattern = rule[:-1].partition("(")
                if self._ALIASES.get(name.lower(), name.lower()) != tool:
                    continue
                if tool == "bash":
                    if fnmatch.fnmatch((args.get("command") or "").strip(), pattern):
                        return True
                elif tool in ("write_file", "edit_file"):
                    if fnmatch.fnmatch(args.get("path", ""), pattern):
                        return True
                else:
                    return True
            elif self._ALIASES.get(rule.lower(), rule.lower()) == tool:
                return True
        return False


def _perm_category(tool: str) -> str:
    from .tools import TOOL_BY_NAME
    spec = TOOL_BY_NAME.get(tool)
    return spec["perm"] if spec else "none"


def describe_tool_use(tool: str, args: Dict[str, Any], root=None) -> Tuple[str, str]:
    """(one-line label, multi-line detail) used in permission prompts & banners."""
    if tool == "bash":
        return "bash", args.get("command", "")
    if tool in ("write_file", "edit_file"):
        path = args.get("path", "")
        if tool == "write_file":
            return "write_file", f"path: {path}\n({len(args.get('content', ''))} chars of content)"
        return "edit_file", (f"path: {path}\nold: {args.get('old_string', '')[:200]!r}\n"
                             f"new: {args.get('new_string', '')[:200]!r}")
    if tool == "grep":
        return "grep", args.get("pattern", "")
    if tool in ("read_file", "glob", "ls"):
        primary = args.get("path") or args.get("pattern") or "."
        return tool, str(primary)
    if tool == "todo":
        items = args.get("todos") or []
        return "todo", f"{len(items)} items"
    if tool == "web_search":
        return "web_search", args.get("query", "")
    if tool == "web_fetch":
        return "web_fetch", args.get("url", "")
    return tool, str(args)[:400]
