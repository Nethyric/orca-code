"""The REPL: thin shell over the agent, line in / events out."""
import sys
from pathlib import Path
from typing import Optional

from .core.events import Bus, EKind
from .runtime.sessions import Session, export_markdown

HELP = {
    "/help": "show commands",
    "/exit | /quit": "leave the REPL",
    "/new": "start a fresh session",
    "/model <id>": "switch model (takes effect next run)",
    "/provider <name>": "switch provider",
    "/tools": "list available tools",
    "/context": "context usage estimate",
    "/cost": "session spend so far",
    "/export [file]": "export transcript to markdown",
}


class REPL:
    def __init__(self, agent, session: Session, bus: Bus, cli_args=None):
        self.agent = agent
        self.session = session
        self.bus = bus
        self.args = cli_args
        self._running = True

    def run(self) -> int:
        self.bus.emit(EKind.session_start, version=_version())
        while self._running:
            try:
                line = input("◆ ")
            except (KeyboardInterrupt, EOFError):
                print()
                return 0
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                self.command(line)
                continue
            self.bus.emit(EKind.user, text=line)
            self.session.add_user(line)
            self.agent.run(line)
            for msg in self.agent.messages[len(self.session.messages):]:
                self.session.append(msg)
            # agent.messages now fully mirrored into the session
        return 0

    def command(self, line: str) -> None:
        parts = line.split(maxsplit=1)
        cmd, rest = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        if cmd in ("/exit", "/quit", "/q"):
            self._running = False
        elif cmd == "/help":
            for name, desc in HELP.items():
                print(f"  {name:22} {desc}")
        elif cmd == "/new":
            self.session = Session(directory=self.session.directory)
            self.agent.messages = []
            print("  ◆ new session")
        elif cmd == "/model" and rest:
            self.agent.provider.model = rest
            print(f"  ◆ model → {rest}")
        elif cmd == "/provider" and rest:
            print(f"  ⚠ switching provider needs a restart in this build "
                  f"(planned: {rest})")
        elif cmd == "/tools":
            for name in self.agent.tools.names():
                spec = self.agent.tools.get(name)
                tag = " · read-only" if spec and spec.readonly else ""
                print(f"  {name}{tag}")
        elif cmd == "/context":
            chars = sum(len(str(m)) for m in self.agent.messages)
            print(f"  ~{chars // 4:,} tokens in "
                  f"{len(self.agent.messages)} messages")
        elif cmd == "/cost":
            u = self.agent.budget.usage
            print(f"  in {u.input_tokens:,} · out {u.output_tokens:,} · "
                  f"cache {u.cache_read:,} · ${u.cost_usd:.4f}")
        elif cmd == "/export":
            target = Path(rest) if rest else Path(
                f"orca-session-{self.session.sid}.md")
            export_markdown(self.session.messages, target)
            print(f"  ◆ exported → {target}")
        else:
            print(f"  ⚠ unknown command: {cmd} — try /help")


def _version() -> str:
    from . import __version__
    return __version__
