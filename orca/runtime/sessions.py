"""Crash-safe sessions: one append-only JSONL file per session.

Isolation is structural — a session can only read its own file, so context
from one conversation can never leak into another. Each message is one
line, flushed on append: a kill -9 loses nothing that was acknowledged.
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.messages import assistant_msg, user_msg


def new_sid() -> str:
    import uuid
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


class Session:
    def __init__(self, sid: Optional[str] = None,
                 directory: Optional[Path] = None):
        self.sid = sid or new_sid()
        self.directory = Path(directory) if directory else None
        self.messages: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ io
    def append(self, message: Dict[str, Any]) -> Dict[str, Any]:
        self.messages.append(message)
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{self.sid}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"sid": self.sid, "msg": message},
                                    ensure_ascii=False) + "\n")
        return message

    def add_user(self, text: str) -> Dict[str, Any]:
        return self.append(user_msg(text))

    def add_assistant(self, text: str, thinking: str = "",
                      tool_calls: Optional[List[Dict[str, Any]]] = None
                      ) -> Dict[str, Any]:
        return self.append(assistant_msg(text, thinking, tool_calls))

    # -------------------------------------------------------------- load
    @classmethod
    def load(cls, sid: str, directory: Path) -> "Session":
        path = Path(directory) / f"{sid}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"no such session: {sid}")
        session = cls(sid=sid, directory=Path(directory))
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # torn tail line from a crash mid-write
                if record.get("sid") == sid:  # belt and braces
                    session.messages.append(record["msg"])
        return session

    @staticmethod
    def list(directory: Path) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not Path(directory).is_dir():
            return out
        for path in sorted(Path(directory).glob("*.jsonl"),
                           key=lambda p: p.stat().st_mtime, reverse=True):
            first_user = ""
            try:
                with path.open(encoding="utf-8") as fh:
                    for line in fh:
                        record = json.loads(line)
                        msg = record.get("msg", {})
                        if msg.get("role") == "user":
                            blocks = msg.get("content") or []
                            first_user = " ".join(
                                b.get("text", "") for b in blocks
                                if b.get("type") == "text")[:70]
                            break
            except (OSError, ValueError):
                continue
            out.append({"sid": path.stem, "mtime": path.stat().st_mtime,
                        "preview": first_user})
        return out


def export_markdown(messages: List[Dict[str, Any]], path: Path) -> Path:
    """Render a transcript as readable Markdown (◆ user, ↳ tool, whale reply)."""
    lines: List[str] = ["# Orca session transcript", ""]
    for msg in messages:
        role = msg.get("role")
        for block in msg.get("content") or []:
            kind = block.get("type")
            if kind == "text" and block.get("text"):
                lines.append(f"## {'🧑 You' if role == 'user' else '🐋 Orca'}")
                lines.append("")
                lines.append(block["text"])
                lines.append("")
            elif kind == "tool_use":
                lines.append(f"`↳ {block.get('name')}("
                             f"{json.dumps(block.get('input') or {}, ensure_ascii=False)[:120]})`")
                lines.append("")
            elif kind == "tool_result":
                content = str(block.get("content", "")).strip()
                if content:
                    lines.append(f"> ↳ {content[:400]}")
                    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return Path(path)
