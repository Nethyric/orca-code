"""Lifecycle hooks: small shell commands that observe or veto.

`before_bash` returning non-zero blocks the command; `after_edit` and
`after_bash` outputs are appended to the tool result so the model sees
them. Failures are always reported, never swallowed.
"""
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class HookResult:
    ok: bool
    output: str
    blocked: bool = False


class HookRunner:
    TIMEOUT = 30
    MAX_OUTPUT = 2000

    def __init__(self, hooks: Optional[Dict[str, str]] = None,
                 root: Optional[Path] = None):
        self.hooks = {k: v for k, v in (hooks or {}).items() if v}
        self.root = Path(root) if root else Path.cwd()

    def has(self, name: str) -> bool:
        return name in self.hooks

    def run(self, name: str, **subs: str) -> HookResult:
        command = self.hooks.get(name)
        if not command:
            return HookResult(True, "")
        for key, value in subs.items():
            command = command.replace(f"%{key}", str(value or ""))
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(self.root),
                capture_output=True, text=True, timeout=self.TIMEOUT)
        except subprocess.TimeoutExpired:
            return HookResult(False,
                              f"hook '{name}' timed out after {self.TIMEOUT}s",
                              blocked=(name == "before_bash"))
        output = (proc.stdout + proc.stderr).strip()[:self.MAX_OUTPUT]
        return HookResult(proc.returncode == 0, output,
                          blocked=(name == "before_bash"
                                   and proc.returncode != 0))
