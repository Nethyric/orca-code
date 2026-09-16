"""Console renderer: a bus subscriber that prints plain lines.

No full-screen TUI, no cursor tricks — output is append-only and renders
the same in a dumb terminal, an IDE panel, or a log file.
"""
import sys
from typing import Optional, TextIO

from ..core.events import Bus, EKind, Event
from .theme import Theme


class Console:
    def __init__(self, bus: Bus, theme: Optional[Theme] = None,
                 stream: Optional[TextIO] = None,
                 mute_text: bool = False):
        self.theme = theme or Theme()
        self.stream = stream or sys.stdout
        self.mute_text = mute_text  # print mode: final answer only, on stdout
        bus.subscribe(self)

    def __call__(self, event: Event) -> None:
        handler = {
            EKind.session_start: self.on_session_start,
            EKind.user: self.on_user,
            EKind.text: self.on_text,
            EKind.thinking: self.on_thinking,
            EKind.tool_start: self.on_tool_start,
            EKind.tool_end: self.on_tool_end,
            EKind.task_start: self.on_task_start,
            EKind.task_end: self.on_task_end,
            EKind.error: self.on_error,
            EKind.notice: self.on_notice,
            EKind.budget: self.on_budget,
        }.get(event.kind)
        if handler:
            handler(**event.data)

    # ------------------------------------------------------------- render
    def out(self, text: str) -> None:
        print(text, file=self.stream)

    def on_session_start(self, version: str = "", **_) -> None:
        self.out(self.theme.banner(version))
        self.out("")

    def on_user(self, text: str = "", **_) -> None:
        self.out(self.theme.paint("◆", self.theme.ACCENT, bold=True) + " "
                 + self.theme.dim(text))

    def on_text(self, text: str = "", depth: int = 0, **_) -> None:
        if self.mute_text:
            return
        self.out(("  " * depth) + text if depth else text)

    def on_thinking(self, text: str = "", depth: int = 0, **_) -> None:
        snippet = text if len(text) <= 300 else text[:300] + "…"
        self.out(self.theme.italic_dim(("  " * depth) + "◦ " + snippet))

    def on_tool_start(self, tool: str = "", summary: str = "",
                      depth: int = 0, **_) -> None:
        self.out(f"{('  ' * depth)}{self.theme.tool('↳')} "
                 f"{self.theme.tool(tool)} "
                 f"{self.theme.file(summary)}")

    def on_tool_end(self, tool: str = "", output: str = "",
                    is_error: bool = False, depth: int = 0, **_) -> None:
        if is_error:
            first = output.splitlines()[0] if output else ""
            self.out(f"{('  ' * depth)}  {self.theme.err('✗ ' + first[:160])}")
        elif tool == "bash":
            first = (output.splitlines()[:1] or [""])[0]
            if first:
                self.out(self.theme.dim(("  " * depth) + "  " + first[:160]))

    def on_task_start(self, profile: str = "", prompt: str = "", **_) -> None:
        self.out(f"  {self.theme.whale('◈ task')} "
                 f"{self.theme.meta(profile)} "
                 f"{self.theme.file(prompt)}")

    def on_task_end(self, profile: str = "", **_) -> None:
        self.out(self.theme.ok("  ◈ task done"))

    def on_error(self, message: str = "", fatal: bool = False, **_) -> None:
        mark = "✗ error:" if fatal else "⚠"
        self.out(self.theme.err(f"{mark} {message}"))

    def on_notice(self, message: str = "", **_) -> None:
        self.out(self.theme.warn(f"ℹ {message}"))

    def on_budget(self, usage=None, model: str = "", **_) -> None:
        if usage is None:
            return
        self.out(self.theme.meta(
            f"  ∿ {model or 'model'} · in {usage.input_tokens:,}"
            f" + out {usage.output_tokens:,} + cache {usage.cache_read:,}"
            f" · ${usage.cost_usd:.4f}"))
