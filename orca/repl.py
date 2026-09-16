"""The Orca REPL — slash commands, readline niceties, status prompt."""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import List

from .agent import Agent
from .config import (Config, PROVIDER_PRESETS, SUGGESTED_MODELS,
                     expand_model_alias)
from .context import ContextManager
from .memory import load_memory, init_memory
from .providers import make_provider
from .sessions import list_sessions
from .ui import UI, fmt_tokens

COMMANDS = {
    "/help": "show commands",
    "/model [id]": "show or switch model",
    "/provider [name]": "show or switch provider",
    "/models": "suggested models for this provider",
    "/context": "context window breakdown",
    "/compact": "compact the conversation now",
    "/cost": "session tokens & cost",
    "/undo": "revert the last file changes Orca made",
    "/rewind [n]": "rewind conversation AND files by n user turns",
    "/diff": "diff of files changed this session",
    "/todo": "show the current task list",
    "/permissions [mode]": "show or set: default | acceptEdits | plan | yolo",
    "/theme [name]": "colors: dark | light | coral | ansi | mono",
    "/plan": "toggle plan mode (read-only exploration)",
    "/system": "show the exact system prompt (full transparency)",
    "/tools": "list available tools",
    "/memory": "show loaded ORCA.md memory",
    "/init": "create an ORCA.md template here",
    "/sessions": "list saved sessions",
    "/save [name]": "name this session",
    "/clear": "clear the conversation",
    "/exit": "quit (also Ctrl+D)",
}

MODES = ("default", "acceptEdits", "plan", "yolo")


class Repl:
    def __init__(self, agent: Agent, ui: UI, cfg: Config):
        self.agent = agent
        self.ui = ui
        self.cfg = cfg
        self._setup_readline()

    # ------------------------------------------------------------------ setup

    def _setup_readline(self) -> None:
        try:
            import readline  # noqa: F401  (POSIX only)
            self._readline = True
            readline.set_completer(self._completer)
            readline.parse_and_bind("tab: complete")
            histfile = self.cfg.root / ".orca" / "history"
            histfile.parent.mkdir(parents=True, exist_ok=True)
            try:
                readline.read_history_file(histfile)
            except OSError:
                pass
            import atexit
            atexit.register(lambda: self._safe_write_history(histfile))
        except ImportError:
            self._readline = False

    def _safe_write_history(self, histfile: Path) -> None:
        try:
            import readline
            readline.write_history_file(histfile)
        except Exception:
            pass

    def _completer(self, text: str, state: int):
        import readline
        try:
            line = readline.get_line_buffer()
            options: List[str] = []
            if line.startswith("/") and " " not in line:
                options = [c for c in list(COMMANDS) + list(self.custom_commands())
                           if c.startswith(text)]
            else:
                options = [p.name + ("/" if p.is_dir() else "")
                           for p in (self.agent.root / text).parent.glob("*")]
            matches = [o for o in options if o.startswith(text)]
        except (ValueError, OSError):
            matches = []
        return matches[state] if state < len(matches) else None

    # ------------------------------------------------------------------ loop

    def prompt_line(self) -> str:
        model = self.agent.provider.model.split("/")[-1][:18]
        report = self.agent.context_report()
        pct = int(100 * min(1.0, report["used"] / max(1, report["window"])))
        style = "green" if pct < 60 else ("yellow" if pct < 85 else "red")
        badge = self.ui.paint(f"{model} {pct}%", style)
        mode = self.agent.permissions.mode
        if mode == "acceptEdits":
            badge += self.ui.paint(f" {self.ui.sym('⏵⏵')} edits", "yellow")
        elif mode == "plan":
            badge += self.ui.paint(f" {self.ui.sym('⏸')} plan", "cyan")
        elif mode == "yolo":
            badge += self.ui.paint(f" {self.ui.sym('⏵⏵')} yolo", "red")
        brand = self.ui.paint("orca", "bold", "brand")
        arrow = self.ui.paint(self.ui.sym("❯"), "brand", "bold")
        return f"{self.ui.paint('[', 'gray')}{badge}{self.ui.paint(']', 'gray')} {brand}{arrow} "

    def run(self) -> None:
        while True:
            try:
                line = input(self.prompt_line()).rstrip()
            except EOFError:
                self.ui.p()
                break
            except KeyboardInterrupt:
                self.ui.p()
                self.ui.notice("(Ctrl+C — /exit or Ctrl+D to quit)")
                continue

            if line.strip() == "?":
                self._hints()
                continue

            text = self._multiline(line)
            if not text.strip():
                continue
            if text.startswith("/"):
                if self._command(text):
                    break
                continue
            try:
                self.agent.run(text)
            except KeyboardInterrupt:
                self.ui.warn("Turn interrupted.")
            except Exception as exc:  # keep the REPL alive
                self.ui.error(f"{type(exc).__name__}: {exc}")
        self.ui.notice("Goodbye. " + self.ui.sym(chr(128056)))

    def _multiline(self, first: str) -> str:
        """\\ at end-of-line continues; \"\"\" opens/closes a block."""
        if first.strip() == '"""':
            lines: List[str] = []
            while True:
                try:
                    nxt = input("... ").rstrip("\n")
                except (EOFError, KeyboardInterrupt):
                    return "\n".join(lines)
                if nxt.strip() == '"""':
                    return "\n".join(lines)
                lines.append(nxt)
            # unreachable
        if first.endswith("\\"):
            buf = [first[:-1]]
            while True:
                try:
                    nxt = input("... ").rstrip("\n")
                except (EOFError, KeyboardInterrupt):
                    break
                if nxt.endswith("\\"):
                    buf.append(nxt[:-1])
                else:
                    buf.append(nxt)
                    break
            return "\n".join(buf)
        return first

    # ------------------------------------------------------------------ commands

    def custom_commands(self) -> dict:
        """.orca/commands/*.md (project) + ~/.orca/commands/*.md (global).
        Project files win on name clashes. /name [args] sends the file body
        as the user message, with $ARGUMENTS substituted."""
        out = {}
        home = Path.home() / ".orca" / "commands"
        project = self.cfg.root / ".orca" / "commands"
        for base in (home, project):
            try:
                if base.is_dir():
                    for f in sorted(base.glob("*.md")):
                        out["/" + f.stem] = f
            except OSError:
                pass
        return out

    def _command(self, text: str) -> bool:
        """Returns True when the REPL should exit."""
        parts = text.split()
        cmd = parts[0].lower()
        rest = text[len(parts[0]):].strip()

        custom = self.custom_commands()
        if cmd in custom:
            body = custom[cmd].read_text(encoding="utf-8", errors="replace")
            self.agent.run(body.replace("$ARGUMENTS", rest))
            return False

        if cmd in ("/exit", "/quit", "/q"):
            return True
        if cmd == "/help":
            self._help()
        elif cmd == "/model":
            self._model(rest)
        elif cmd == "/provider":
            self._provider(rest)
        elif cmd == "/models":
            self._models()
        elif cmd == "/context":
            self._context()
        elif cmd == "/compact":
            self._compact()
        elif cmd == "/cost":
            self._cost()
        elif cmd == "/undo":
            self._undo()
        elif cmd == "/rewind":
            self._rewind(rest)
        elif cmd == "/diff":
            self._diff()
        elif cmd == "/todo":
            if self.agent.ctx.todos:
                self.ui.todos(self.agent.ctx.todos)
            else:
                self.ui.notice("No todos yet.")
        elif cmd in ("/permissions", "/plan", "/yolo"):
            self._permissions(cmd, rest)
        elif cmd == "/theme":
            self._theme(rest)
        elif cmd == "/system":
            self.ui.p(self.agent.system_prompt())
        elif cmd == "/tools":
            from .tools import TOOLS
            for t in TOOLS:
                self.ui.p(f"  {self.ui.paint(t['name'], 'bold', 'cyan')}  [{t['perm']}]  {t['description'].split('. ')[0]}")
        elif cmd == "/memory":
            self._memory()
        elif cmd == "/init":
            path = init_memory(self.agent.root)
            self.ui.ok(f"Created {path}")
            self.agent._system_cache = None  # reload prompt
        elif cmd == "/sessions":
            self._sessions()
        elif cmd == "/save":
            if rest:
                self.agent.session.name = rest
                self.ui.ok(f"Session name → {rest} (saved on your next message)")
            elif self.agent.session.path is not None:
                self.ui.ok(f"Session file: {self.agent.session.path}")
            else:
                self.ui.notice("Session will save on your next message.")
        elif cmd == "/clear":
            self.agent.messages = []
            self.agent.checkpoints = []
            self.agent._system_cache = None
            self.ui.ok("Conversation cleared. (/rewind history reset — file "
                       "changes stay; use /undo or /rewind before clearing.)")
        else:
            pool = list(COMMANDS) + list(self.custom_commands())
            suggestion = difflib.get_close_matches(cmd, pool, n=1)
            hint = f" (did you mean {suggestion[0]}?)" if suggestion else ""
            self.ui.error(f"Unknown command {cmd}{hint} — /help lists everything.")
        return False

    def _help(self) -> None:
        self.ui.rule("Orca Code commands")
        width = max(len(k) for k in COMMANDS)
        for name, desc in COMMANDS.items():
            self.ui.p(f"  {self.ui.paint(name.ljust(width), 'bold', 'brand')}  "
                      f"{self.ui.paint(desc, 'gray')}")
        custom = self.custom_commands()
        if custom:
            self.ui.rule("Custom commands (.orca/commands/*.md)")
            for name, path in custom.items():
                try:
                    first = path.read_text(encoding="utf-8", errors="replace") \
                        .strip().splitlines()[0][:52]
                except (OSError, IndexError):
                    first = ""
                self.ui.p(f"  {self.ui.paint(name.ljust(width), 'bold', 'teal')}  {first}")
        cont = self.ui.paint("\\", "bold")
        block = self.ui.paint('"""', "bold")
        self.ui.p(f"\n  {cont} at end of line = multiline · {block} block = paste-safe multiline")

    def _model(self, rest: str) -> None:
        if not rest:
            info = self.agent.context.info
            self.ui.p(f"  provider  {self.agent.provider.name}")
            self.ui.p(f"  model     {self.agent.provider.model}")
            self.ui.p(f"  context   {fmt_tokens(info.get('context', 0))} tokens")
            pricing = info.get("in")
            if pricing is not None:
                self.ui.p(f"  pricing   ~${pricing}/${info.get('out')}/M tokens")
            return
        rest = expand_model_alias(rest)
        self.agent.provider.model = rest
        self.agent.context = ContextManager(self.cfg, rest)
        self.agent._system_cache = None
        self.cfg.set("model", rest)
        try:
            self.cfg.save()
        except OSError:
            pass
        self.ui.ok(f"Model → {rest}")

    def _provider(self, rest: str) -> None:
        if not rest:
            self.ui.p(f"  active  {self.agent.provider.name}")
            self.ui.p(f"  known   {', '.join(sorted(PROVIDER_PRESETS))}")
            return
        if rest not in PROVIDER_PRESETS:
            self.ui.error(f"Unknown provider '{rest}'. Known: {', '.join(sorted(PROVIDER_PRESETS))}")
            return
        try:
            provider = make_provider(self.cfg, name=rest)
            provider.model = provider.model or (SUGGESTED_MODELS.get(rest) or [""])[0]
        except Exception as exc:
            self.ui.error(str(exc))
            return
        self.agent.provider = provider
        self.agent.context = ContextManager(self.cfg, provider.model or "")
        self.agent._system_cache = None
        self.cfg.set("provider", rest)
        self.cfg.set("model", provider.model)
        try:
            self.cfg.save()
        except OSError:
            pass
        self.ui.ok(f"Provider → {rest} ({provider.model})")

    def _models(self) -> None:
        # live list first — your key, your catalog, no guessing
        live = None
        try:
            from .providers import list_remote_models
            live = list_remote_models(self.agent.provider)
        except Exception:
            live = None
        if live:
            self.ui.p(f"  {len(live)} models available:", style=["dim"])
            for m in live[:40]:
                mark = self.ui.paint(" ← active", "green") \
                    if m == self.agent.provider.model else ""
                self.ui.p(f"    {m}{mark}")
            if len(live) > 40:
                self.ui.p(f"    ⋯ +{len(live) - 40} more", style=["dim"])
        suggested = SUGGESTED_MODELS.get(self.agent.provider.name) or []
        if suggested:
            self.ui.p("  suggested:", style=["dim"])
            for m in suggested:
                mark = " ← active" if m == self.agent.provider.model else ""
                self.ui.p(f"    {m}{mark}")
        self.ui.p("  (any model id works: /model <id>)", style=["dim"])

    def _context(self) -> None:
        report = self.agent.context_report()
        self.ui.rule("Context window")
        self.ui.context_meter(report["used"], report["window"])
        for key, value in report["breakdown"].items():
            bar_len = int(30 * value / max(1, report["used"]))
            bar = self.ui.paint(self.ui.sym("█") * bar_len, "cyan")
            self.ui.p(f"  {key:<12} {bar} {fmt_tokens(value)}")
        self.ui.p(f"  compactions: {report['compactions']} · "
                  f"estimator calibration: ×{report['calibration']}", style=["dim"])

    def _compact(self) -> None:
        import json as _json
        from .tools import tool_specs
        specs_json = _json.dumps(tool_specs())
        self.ui.notice("Compacting…")
        before = self.agent.context.used(self.agent.system_prompt(), self.agent.messages, specs_json)
        try:
            from orca.agent import _render_todos
            compacted = self.agent.context.compact(
                self.agent.system_prompt(), self.agent.messages, specs_json,
                self.agent._summarize,
                extra_context=_render_todos(self.agent.ctx.todos))
        except Exception as exc:
            self.ui.error(f"Compaction failed: {exc}")
            return
        if self.agent.context.compactions == 0 or len(compacted) >= len(self.agent.messages):
            self.ui.notice("Nothing worth compacting yet (history too short or already dense).")
            return
        self.agent.messages = compacted
        after = self.agent.context.used(self.agent.system_prompt(), self.agent.messages, specs_json)
        self.ui.ok(f"Compacted: {fmt_tokens(before)} → {fmt_tokens(after)} tokens")

    def _cost(self) -> None:
        u = self.agent.usage
        self.ui.rule("Session usage")
        for key, tin, tout, tread, cost in u.summary_rows():
            cache = f" {tread:>8,} cached" if tread else " " * 17
            self.ui.p(f"  {key:<40} {tin:>8,} in {tout:>8,} out{cache}  {cost}")
        self.ui.p(f"  total  {u.cost_text()}")
        if u.max_cost_usd is not None:
            self.ui.p(f"  cap    ${u.total_cost:.4f} / ${u.max_cost_usd:.2f}")

    def _undo(self) -> None:
        restored = self.agent.ctx.undo.undo()
        if not restored:
            self.ui.notice("Nothing to undo.")
            return
        for entry in restored:
            self.ui.ok(f"Reverted: {entry}")

    def _rewind(self, rest: str) -> None:
        try:
            turns = max(1, int(rest)) if rest else 1
        except ValueError:
            turns = 1
        if not self.agent.checkpoints:
            self.ui.notice("Nothing to rewind yet.")
            return
        self.ui.ok(self.agent.rewind(turns))

    def _diff(self) -> None:
        originals = self.agent.ctx.undo.originals
        if not originals:
            self.ui.notice("No files changed this session.")
            return
        for rel, before in originals.items():
            path = self.agent.root / rel
            after = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            if before == after:
                continue
            self.ui.rule(rel)
            diff = difflib.unified_diff(
                (before or "").splitlines(), after.splitlines(),
                fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="")
            for line in list(diff)[:200]:
                if line.startswith("+"):
                    self.ui.p(self.ui.paint(line, "green"))
                elif line.startswith("-"):
                    self.ui.p(self.ui.paint(line, "red"))
                elif line.startswith("@"):
                    self.ui.p(self.ui.paint(line, "cyan"))
                else:
                    self.ui.p(line, style=["dim"])

    def _permissions(self, cmd: str, rest: str) -> None:
        perms = self.agent.permissions
        if cmd == "/plan":
            rest = "plan" if perms.mode != "plan" else "default"
        elif cmd == "/yolo":
            rest = "yolo"
        if not rest:
            self.ui.p(f"  mode    {perms.mode}")
            self.ui.p(f"  allow   {', '.join(perms.allow) or '(none)'}")
            self.ui.p(f"  deny    {', '.join(perms.deny) or '(none)'}")
            self.ui.p("  modes: " + ", ".join(MODES), style=["dim"])
            return
        if rest not in MODES:
            self.ui.error(f"Unknown mode '{rest}'. Use: {', '.join(MODES)}")
            return
        perms.mode = rest
        self.ui.ok(f"Permission mode → {rest}")

    def _theme(self, rest: str) -> None:
        from .ui import THEMES
        if not rest:
            current = getattr(self.ui, "theme", "dark")
            self.ui.rule("Theme")
            for name in THEMES:
                mark = self.ui.paint(" ← active", "green") if name == current else ""
                self.ui.set_theme(name)   # borrow this theme's palette for the swatch
                sample = self.ui.paint("⏺ sample text", "brand") + "  " + \
                    self.ui.paint("⎿ result", "gray") + "  " + \
                    self.ui.paint("+ diff", "green")
                self.ui.set_theme(current)  # restore
                self.ui.p(f"  {name:<8} {sample}{mark}")
            self.ui.p("  /theme <name> switches · dark = Deep Ocean (default) · "
                      "ansi uses only your terminal's 16 colors", style=["gray"])
            return
        if rest not in THEMES:
            self.ui.error(f"Unknown theme '{rest}'. Use: {', '.join(THEMES)}")
            return
        self.ui.set_theme(rest)
        self.cfg.set("theme", rest)
        try:
            self.cfg.save()
        except OSError:
            pass
        self.ui.ok(f"Theme → {rest}")

    def _hints(self) -> None:
        ui = self.ui
        ui.rule("Hints")
        rows = [
            ("esc… nothing to escape", "Ctrl+C interrupts a turn, Ctrl+D exits"),
            ("/model kimi", "short names work: kimi · minimax · deepseek-flash · glm"),
            (ui.sym("⏵⏵") + " edits", "acceptEdits mode — edits stop asking, bash still does"),
            (ui.sym("⏵⏵") + " yolo", "everything auto-approved (still no rm -rf /)"),
            ("/rewind 2", "rewind 2 user turns — chat AND files"),
            ("/diff", "everything Orca changed this session, unified diff"),
            ("/theme ansi", "use your terminal's own palette instead of ours"),
            (r'\ or """', 'multiline input'),
        ]
        for left, right in rows:
            ui.p(f"  {ui.paint(left.ljust(28), 'teal')} {right}", style=["gray"])

    def _memory(self) -> None:
        text, paths = load_memory(self.agent.root)
        if not paths:
            self.ui.notice("No ORCA.md found. /init creates one in this project.")
            return
        for path in paths:
            self.ui.p(f"  {path}", style=["dim"])
        self.ui.p()
        self.ui.markdown(text)

    def _sessions(self) -> None:
        sessions = list_sessions()
        if not sessions:
            self.ui.notice("No saved sessions yet.")
            return
        for path in sessions:
            self.ui.p(f"  {path.stem}")
        self.ui.p("  resume with: orca --resume <id>", style=["dim"])
