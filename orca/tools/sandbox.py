"""Central filesystem sandbox: every path a tool touches goes through here.

The root is the only world. Escapes via `..`, absolute paths outside the
root, or symlinks that point outside are rejected before any I/O happens.
"""
from pathlib import Path
from typing import Union


class SandboxError(Exception):
    """A path tried to leave the sandbox."""


class Sandbox:
    def __init__(self, root: Union[str, Path]):
        self.root = Path(root).resolve()

    def resolve(self, path: Union[str, Path]) -> Path:
        p = Path(path)
        candidate = p if p.is_absolute() else (self.root / p)
        target = candidate.resolve()
        if target != self.root and self.root not in target.parents:
            raise SandboxError(
                f"path escapes the project root: {path}")
        return target

    def inside(self, path: Union[str, Path]) -> bool:
        try:
            self.resolve(path)
            return True
        except SandboxError:
            return False
