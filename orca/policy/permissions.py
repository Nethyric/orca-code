"""Permission policy: modes, an ask-hook, and a destructive-command guard."""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class Mode(str, Enum):
    PLAN = "plan"
    DEFAULT = "default"
    ACCEPT_EDITS = "accept-edits"
    YOLO = "yolo"


DESTRUCTIVE = [
    re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b"),
    re.compile(r"\brm\s+-rf\s+/(?:\s|$)"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\b[^|]*of=/dev/"),
    re.compile(r":\(\)\s*\{.*\};\s*:"),
    re.compile(r">\s*/dev/sd[a-z]"),
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"),
    re.compile(r"\bgit\s+push\s+.*--force\b"),
    re.compile(r"\bchmod\s+-R\s+777\s+/"),
]


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    asked: bool = False


AskFn = Callable[[str, str], bool]


class Policy:
    """check(tool, args, readonly) -> Decision. Never raises."""

    def __init__(self, mode: Mode = Mode.DEFAULT, ask: Optional[AskFn] = None):
        self.mode = mode
        self.ask = ask

    def check(self, tool: str, args: dict, readonly: bool = False) -> Decision:
        if readonly:
            return Decision(True)
        if self.mode == Mode.PLAN:
            return Decision(False, "plan mode is read-only")
        if tool == "bash" and _is_destructive(args.get("command", "")):
            return Decision(False, "destructive command blocked "
                            "(override by editing policy allowlist)")
        if self.mode == Mode.YOLO:
            return Decision(True)
        if self.mode == Mode.ACCEPT_EDITS and tool != "bash":
            return Decision(True)
        # default: ask a human, if anyone is listening
        if self.ask is not None:
            allowed = bool(self.ask(tool, _summarize_args(args)))
            return Decision(allowed, "" if allowed else "denied by user",
                            asked=True)
        return Decision(False, "no interactive prompt available — "
                        "run with --accept-edits or --yolo to allow this")


def _is_destructive(command: str) -> bool:
    return any(rx.search(command) for rx in DESTRUCTIVE)


def _summarize_args(args: dict) -> str:
    for key in ("path", "command", "pattern", "prompt"):
        if args.get(key):
            return str(args[key])[:80]
    return ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])[:80]
