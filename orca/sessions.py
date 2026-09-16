"""Session persistence — JSONL transcripts in ~/.orca/sessions/."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import sessions_dir

SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, limit: int = 24) -> str:
    slug = SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:limit] or "session"


class Session:
    def __init__(self, name: Optional[str] = None):
        self.path: Optional[Path] = None
        self.name = name
        self._meta_written = False

    def start(self, meta: Dict[str, Any], first_user_text: str = "") -> Path:
        if self.path is not None:      # resumed session: keep the same file
            self.append({"t": "resume", **meta})
            return self.path
        directory = sessions_dir()
        directory.mkdir(parents=True, exist_ok=True)
        if self.name:
            self.path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(self.name)}.jsonl"
        else:
            hint = _slug(first_user_text[:60]) or "session"
            self.path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{hint}.jsonl"
        self.append({"t": "meta", **meta})
        return self.path

    def resume(self, path: Path) -> None:
        """Continue an existing session file instead of forking a new one."""
        self.path = Path(path)
        self.name = self.path.stem.split("-", 2)[-1] if "-" in self.path.stem \
            else self.path.stem

    def append(self, event: Dict[str, Any]) -> None:
        if self.path is None:
            return
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def append_message(self, message: Dict[str, Any]) -> None:
        self.append({"t": "msg", "role": message["role"], "content": message["content"]})


def load_session(path: Path) -> List[Dict[str, Any]]:
    """Replay a session file into messages.

    Structural events are honored so a resumed session matches what the user
    actually saw: `rewind` truncates back to its recorded message count, and
    `compaction` drops everything before it (the summary message follows as a
    normal msg event). Without this, resume would resurrect rewound turns and
    undo compaction.
    """
    messages: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("t")
        if kind == "msg" and event.get("role") in ("user", "assistant"):
            messages.append({"role": event["role"], "content": event["content"]})
        elif kind == "rewind":
            keep = event.get("msg_len")
            if isinstance(keep, int):
                messages = messages[:keep]
        elif kind == "compaction":
            messages = []
    return messages


def list_sessions(limit: int = 15) -> List[Path]:
    directory = sessions_dir()
    if not directory.is_dir():
        return []
    files = sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def latest_session() -> Optional[Path]:
    sessions = list_sessions(limit=1)
    return sessions[0] if sessions else None


def find_session(query: str) -> Optional[Path]:
    for path in list_sessions(limit=100):
        if query in path.stem:
            return path
    return None
