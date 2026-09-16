"""The Orca agent loop — the heartbeat of the system.

Receives a user prompt → streams a model response → collects tool calls →
asks permissions → executes tools → appends results → loops until the model
stops calling tools (or hits the turn guard / cost cap / an interrupt).

Beyond the basic loop: live context metering, calibrated auto-compaction,
an undo-safety net and a hard cost cap.
"""
from __future__ import annotations

import json
import time
import platform
import subprocess
import difflib
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import tools as toolmod
from .config import Config, VERSION
from .context import ContextManager
from .permissions import Permissions, describe_tool_use
from .providers import (BaseProvider, ProviderError, make_provider, require_key,
                       text_block, tool_result_block)
from .sessions import Session
from .ui import UI
from .usage import UsageTracker, CostLimitExceeded, TokenBudgetExceeded

MAX_TURNS = 80   # long-haul builds (websites, games) need room to finish

BUILD_GUIDELINE = """\
# Completing large builds
- For multi-file projects (websites, games, apps): plan first with the todo tool,
  then create files one by one, then run the project with bash and fix what breaks.
- Do not stop at a skeleton. A build is done when it runs and every todo is ☒.
- If a file needs to be large, write it in full with write_file rather than
  fragmenting it across many partial edits."""

TOOL_GUIDELINES = """\
# Tool notes
- read_file, write_file, edit_file, bash, grep, glob, ls take paths relative to the project root.
- edit_file: `old_string` must match EXACTLY (whitespace/indentation included) and be unique;
  on mismatch you get a closest-match hint. Use write_file only for new files or full rewrites.
- Prefer grep/glob to find things, then read_file only the relevant ranges.
- Run builds/tests/linters with bash after changes; iterate until green.
- Use todo to track multi-step work and keep exactly one task in_progress.
- Tool outputs are truncated (⋯ markers) — narrow your reads instead of asking for more.
"""

OPERATING_PRINCIPLES = """\
# Operating principles
- You are proactive and finish the job: explore, implement, verify. Do not stop halfway
  to ask the user things you can determine yourself from the codebase.
- Before editing a file you haven't seen this session, read the relevant part first.
- After finishing code changes, run the relevant tests/build/linter when present.
- Keep responses concise and technical. Short answers for simple questions; no filler.
- Use markdown. Never claim you did something you didn't actually do via tools.
- When the user asks for explanations, be precise and reference real code you read.
"""

SAFETY = """\
# Safety
- Never run destructive commands (wiping disks, force-pushing to shared branches,
  credential exfiltration), even when asked; suggest safer alternatives.
- Stay inside the working directory unless the user explicitly requests otherwise.
- Do not commit or push unless the user asks.
"""

CONTEXT_NOTICE = """\
# Context
- Older conversation may have been compacted into a summary message; treat it as
  authoritative history and keep file paths/identifiers it mentions.
- A context usage meter is shown to the user after each turn; be economical with
  huge outputs (pipe through head/tail, narrow greps).
"""


class Interrupted(Exception):
    pass


_FALLBACK = object()   # sentinel: provider failed, retry on the next fallback


class Agent:
    def __init__(self, provider: BaseProvider, cfg: Config, ui: UI,
                 permissions: Optional[Permissions] = None,
                 session: Optional[Session] = None,
                 root: Optional[Path] = None,
                 auto_approve_callback: Optional[Callable[[str, Dict[str, Any]], str]] = None):
        self.provider = provider
        self.cfg = cfg
        self.ui = ui
        self.root = Path(root) if root else cfg.root
        self.permissions = permissions or Permissions(
            mode=cfg.permissions.get("mode", "default"),
            allow=cfg.permissions.get("allow", []),
            deny=cfg.permissions.get("deny", []),
        )
        self.session = session or Session()
        self.usage = UsageTracker(max_cost_usd=cfg.get("max_cost_usd"))
        self.ctx = toolmod.ToolContext(self.root)
        self.context = ContextManager(cfg, provider.model)
        self.messages: List[Dict[str, Any]] = []
        self.auto_approve_callback = auto_approve_callback  # used in -p mode
        self.checkpoints: List[Dict[str, int]] = []
        self._last_call_signature = None
        self._repeat_count = 0
        self._system_cache: Optional[str] = None
        self._memory_text = ""
        # reliability chain: tried in order when the active provider errors out
        self._fallback_queue = self._build_fallbacks(cfg.get("fallbacks"))
        self._fast_provider: Optional[BaseProvider] = None
        self._max_session_tokens = cfg.get("max_session_tokens")

    # ------------------------------------------------------------------ prompt

    def system_prompt(self) -> str:
        if self._system_cache:
            return self._system_cache
        from .memory import load_memory
        self._memory_text, _ = load_memory(self.root)
        parts = [
            f"You are Orca, an expert agentic coding assistant running as the CLI "
            f"'orca-code' v{VERSION} in the user's terminal.",
            self._environment_block(),
            self._memory_block(),
            OPERATING_PRINCIPLES,
            TOOL_GUIDELINES,
            BUILD_GUIDELINE,
            CONTEXT_NOTICE,
            SAFETY,
        ]
        self._system_cache = "\n\n".join(p for p in parts if p)
        return self._system_cache

    def _environment_block(self) -> str:
        branch, dirty = _git_state(self.root)
        lines = [
            "# Environment",
            f"- Working directory: {self.root}",
            f"- Platform: {platform.system()} {platform.release()}",
            f"- Date: {date.today().isoformat()}",
            f"- Model: {self.provider.label}",
        ]
        if branch:
            lines.append(f"- Git repo: yes (branch: {branch}, dirty files: {dirty})")
        else:
            lines.append("- Git repo: no")
        return "\n".join(lines)

    def _memory_block(self) -> str:
        if not self._memory_text:
            return ("# Project memory (ORCA.md)\n(none found — you may suggest the user "
                    "run /init to create one)")
        return f"# Project memory (ORCA.md)\n{self._memory_text}"

    # ------------------------------------------------------------------ loop

    def run(self, user_text: str, on_finished: Optional[Callable[[], None]] = None) -> None:
        if self.session.path is None:
            self.session.start(
                {"provider": self.provider.name, "model": self.provider.model,
                 "mode": self.permissions.mode, "root": str(self.root)},
                first_user_text=user_text,
            )
        # checkpoint: rewind target for /rewind (message length + undo state)
        self.checkpoints.append({
            "msg_len": len(self.messages),
            "undo_len": len(self.ctx.undo.entries),
        })
        self.messages.append({"role": "user", "content": [text_block(user_text)]})
        self.session.append_message(self.messages[-1])
        self.last_provider_error: Optional[str] = None
        try:
            self._loop()
        finally:
            self._print_footer()
            if on_finished:
                on_finished()

    def rewind(self, turns: int = 1) -> str:
        """Rewind the conversation AND the agent's file changes by N user turns.

        Checkpoint semantics: checkpoints[k] is the state recorded right before
        user turn k ran. Rewinding N turns restores checkpoints[len - N].
        """
        turns = max(1, turns)
        if not self.checkpoints:
            return "Nothing to rewind yet."
        turns = min(turns, len(self.checkpoints))
        idx = len(self.checkpoints) - turns
        checkpoint = self.checkpoints[idx]
        restored_files = self.ctx.undo.rewind_to(checkpoint["undo_len"])
        self.messages = self.messages[:checkpoint["msg_len"]]
        self.session.append({"t": "rewind", "turns": turns,
                             "msg_len": len(self.messages)})
        self.checkpoints = self.checkpoints[:idx]
        summary = (f"Rewound {turns} turn(s): conversation back to "
                   f"{len(self.messages)} messages")
        if restored_files:
            summary += f", {len(restored_files)} file change(s) reverted"
        return summary

    def _print_footer(self) -> None:
        report = self.context_report()
        self.ui.turn_footer(report["used"], report["window"], self.usage.cost_text())

    def _loop(self) -> None:
        specs = toolmod.tool_specs()
        tools_json = json.dumps(specs)
        for _turn in range(MAX_TURNS):
            self.usage.guard()
            system = self.system_prompt()
            assistant_msg = self._stream_assistant(system, specs)
            if assistant_msg is None:
                return
            self.messages.append(assistant_msg)
            self.session.append_message(assistant_msg)

            tool_calls = [b for b in assistant_msg["content"] if b.get("type") == "tool_use"]
            if not tool_calls:
                break

            self.ctx.undo.begin_turn()
            results: List[Dict[str, Any]] = []
            for i, call in enumerate(tool_calls):
                try:
                    results.append(self._execute(call))
                except KeyboardInterrupt:
                    self.ui.end_stream()
                    self.ui.warn("Interrupted mid-tool.")
                    results.append(tool_result_block(
                        call.get("id", ""), "Interrupted by the user.", is_error=True))
                    for remaining in tool_calls[i + 1:]:
                        results.append(tool_result_block(
                            remaining.get("id", ""), "Skipped — the user interrupted.", is_error=True))
                    self.messages.append({"role": "user", "content": results})
                    self.session.append_message(self.messages[-1])
                    return
            self.messages.append({"role": "user", "content": results})
            self.session.append_message(self.messages[-1])

            todos_text = _render_todos(self.ctx.todos)
            compacted = self.context.maybe_compact(
                system, self.messages, tools_json, self._summarize,
                extra_context=todos_text,
            )
            if compacted is not None:
                self.messages = compacted
                self.session.append({"t": "compaction"})
        else:
            self.ui.warn(f"Turn limit ({MAX_TURNS}) reached — stopping for a check-in.")

    # ------------------------------------------------------------------ streaming

    # ------------------------------------------------------------------ reliability

    def _build_fallbacks(self, entries) -> List[BaseProvider]:
        """Parse ['groq:llama-3.3-70b-versatile', 'deepseek-chat', ...] into
        providers. A bare entry that names a known provider uses that provider
        with its suggested model; otherwise it is a model id on the active
        provider. 'provider:model' picks both explicitly."""
        from .config import PROVIDER_PRESETS
        out: List[BaseProvider] = []
        for raw in entries or []:
            raw = str(raw).strip()
            if not raw:
                continue
            try:
                prov_name, _, model = raw.partition(":")
                if not model:
                    if prov_name in PROVIDER_PRESETS:      # e.g. "mock", "groq"
                        out.append(make_provider(self.cfg, name=prov_name))
                    else:                                  # e.g. "deepseek-chat"
                        out.append(make_provider(self.cfg, name=self.provider.name,
                                                 model=prov_name))
                else:
                    out.append(make_provider(self.cfg, name=prov_name, model=model))
            except Exception:
                continue  # a broken fallback entry must never crash the agent
        return out

    def _switch_provider(self, provider: BaseProvider) -> None:
        self.provider = provider
        self.context = ContextManager(self.cfg, provider.model or "")
        self._system_cache = None
        self.session.append({"t": "fallback", "to": provider.label})

    def _verify_command(self) -> Optional[str]:
        """Deterministic gate: config `verify_command`, else .orca/verify.sh."""
        cmd = self.cfg.get("verify_command")
        if cmd:
            return str(cmd)
        script = self.root / ".orca" / "verify.sh"
        if script.is_file():
            return "sh .orca/verify.sh"   # run with cwd = project root
        return None

    def _run_verify(self, cmd: str) -> str:
        import subprocess
        started = time.time()
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(self.root), timeout=120,
                capture_output=True, text=True)
            elapsed = time.time() - started
            if proc.returncode == 0:
                self.ui.ok(f"verify: passed ({elapsed:.1f}s)")
                return f"\n\n[orca] verification passed: `{cmd}` ({elapsed:.1f}s)."
            tail = (proc.stdout + "\n" + proc.stderr).strip()
            tail = "\n".join(tail.splitlines()[:20])[:1500]
            self.ui.warn(f"verify: FAILED ({elapsed:.1f}s) — feeding it back to the model")
            return (f"\n\n[orca] verification FAILED (`{cmd}`, exit "
                    f"{proc.returncode}):\n{tail}\n"
                    "Fix the failures above before claiming the task is done.")
        except subprocess.TimeoutExpired:
            self.ui.warn("verify: timed out after 120s")
            return f"\n\n[orca] verification TIMED OUT after 120s: `{cmd}`."
        except OSError as exc:
            return f"\n\n[orca] verification could not run: {exc}"

    # ------------------------------------------------------------------ streaming

    def _stream_assistant(self, system: str, specs: List[Dict[str, Any]]
                          ) -> Optional[Dict[str, Any]]:
        while True:
            assistant = self._stream_once(system, specs)
            if assistant is not _FALLBACK:
                return assistant

    def _stream_once(self, system: str, specs: List[Dict[str, Any]]
                     ) -> Optional[Dict[str, Any]]:
        require_key(self.provider)
        collected: List[Dict[str, Any]] = []
        usage: Dict[str, int] = {}
        assistant: Optional[Dict[str, Any]] = None
        streamed_text = {"any": False}
        try:
            with self.ui.thinking("Thinking"):
                for kind, payload in self.provider.stream(system, self.messages, specs):
                    if kind == "reasoning":
                        # thinking models: shown live, never stored — reasoning
                        # tokens already burned as output; keeping them in the
                        # transcript would burn them again as input every turn
                        reason_fn = getattr(self.ui, "reasoning", None)
                        if reason_fn:
                            reason_fn(payload)
                    elif kind == "text":
                        streamed_text["any"] = True
                        self.ui.stream_text(payload)
                    elif kind == "tool_use":
                        collected.append(payload)
                    elif kind == "usage":
                        usage = payload
                    elif kind == "message":
                        assistant = payload
        except KeyboardInterrupt:
            self.ui.end_stream()
            self.ui.warn("Interrupted.")
            self._patch_interrupted()
            return None
        except ProviderError as exc:
            self.ui.end_stream()
            nxt = self._fallback_queue.pop(0) if self._fallback_queue else None
            if nxt is not None and not streamed_text["any"]:
                self.ui.warn(f"Provider error — switching to fallback "
                             f"{nxt.label} ({exc})")
                self._switch_provider(nxt)
                return _FALLBACK
            self.ui.error(f"Provider error: {exc}")
            self.last_provider_error = str(exc)
            self._patch_interrupted()
            return None
        except CostLimitExceeded as exc:
            self.ui.error(str(exc))
            return None

        self.ui.end_stream()
        if usage:
            self.usage.record(self.provider.name, self.provider.model, usage)
            self.context.calibrate(
                usage.get("input"), system, self.messages, json.dumps(specs)
            )
            budget = self._max_session_tokens
            if budget and self.usage.total_tokens >= int(budget):
                raise TokenBudgetExceeded(
                    f"Token budget reached: {self.usage.total_tokens:,} / "
                    f"{int(budget):,} tokens this session. Raise "
                    f"max_session_tokens or start a new session.")
        if assistant is None:
            return None
        return assistant

    def _patch_interrupted(self) -> None:
        """Make the transcript valid again after Ctrl+C mid-turn."""
        if self.messages and self.messages[-1]["role"] == "assistant":
            calls = [b for b in self.messages[-1]["content"] if b.get("type") == "tool_use"]
            if calls:
                results = [
                    tool_result_block(b["id"], "Interrupted by the user.", is_error=True)
                    for b in calls
                ]
                self.messages.append({"role": "user", "content": results})

    # ------------------------------------------------------------------ tools

    def _execute(self, call: Dict[str, Any]) -> Dict[str, Any]:
        name = call.get("name", "")
        args = call.get("input") or {}
        label, detail = describe_tool_use(name, args, self.root)

        decision = self.permissions.check(name, args, self.root)
        if decision.startswith("deny:"):
            message = decision[5:]
            self.ui.tool_start(name, detail)
            self.ui.tool_done(message, is_error=True)
            return tool_result_block(call.get("id", ""), f"Error: {message}", is_error=True)

        if decision == "ask":
            answer = self._ask_permission(name, args, label)
            if answer == "n":
                message = "User denied this tool call. Ask what to do differently."
                self.ui.tool_start(name, detail)
                self.ui.tool_done("denied by user", is_error=True)
                return tool_result_block(call.get("id", ""), f"Error: {message}", is_error=True)

        self.ui.tool_start(name, detail)
        try:
            output = toolmod.run_tool(name, args, self.ctx)
            is_error = False
        except toolmod.ToolError as exc:
            output, is_error = f"Error: {exc}", True
        except Exception as exc:  # defensive: never crash the loop on a tool bug
            output, is_error = f"Error: tool crashed: {exc!r}", True

        # loop detection: the exact same call 3+ times in a row means stuck
        signature = (name, json.dumps(args, sort_keys=True, default=str)[:500])
        if signature == self._last_call_signature:
            self._repeat_count += 1
        else:
            self._repeat_count = 0
            self._last_call_signature = signature
        if self._repeat_count >= 2:
            output += ("\n\n[orca] Notice: you have made this exact same call "
                       f"{self._repeat_count + 1} times in a row with no progress. "
                       "If you are stuck, stop repeating and change your approach.")
            self.ui.warn("Loop detected: identical tool call repeated "
                         f"{self._repeat_count + 1}×")

        # deterministic gate: run the project's verify command after every edit
        if name in ("write_file", "edit_file") and not is_error:
            verify_cmd = self._verify_command()
            if verify_cmd:
                output += self._run_verify(verify_cmd)

        if name == "todo" and self.ctx.todos:
            self.ui.todos(self.ctx.todos)
        elif name == "read_file" and not is_error and \
                getattr(self.ui, "file_preview", None) is not None:
            self.ui.file_preview(str(args.get("path", "")), output)
        else:
            self.ui.tool_done(_result_summary(output), is_error=is_error)
        return tool_result_block(call.get("id", ""), output, is_error=is_error)

    def _ask_permission(self, name: str, args: Dict[str, Any], label: str) -> str:
        if self.auto_approve_callback is not None:
            return self.auto_approve_callback(name, args)
        if not self.ui.interactive:
            return "n"
        _, detail = describe_tool_use(name, args, self.root)
        pattern = None
        diff = None
        if name in ("write_file", "edit_file"):
            pattern = name
            diff = build_change_diff(self.ctx, name, args)
        elif name == "bash":
            pattern = "bash command"
        answer = self.ui.ask_permission(name, detail or label, pattern, diff=diff)
        if answer == "a":
            self.permissions.allow_session(name if name != "bash" else _bash_rule(args))
        elif answer == "A":
            rule = name if name != "bash" else _bash_rule(args)
            self.permissions.allow_session(rule)
            try:
                self.cfg.add_permission_rule(rule, allow=True, local=True)
                self.ui.notice(f"Saved rule: {rule} → .orca/settings.local.json")
            except OSError as exc:
                self.ui.warn(f"Could not save rule: {exc}")
        return answer if answer in ("y", "a", "A") else "n"

    # ------------------------------------------------------------------ helpers

    def _summarize(self, prompt_system: str, prompt_text: str) -> str:
        """Provider call used by the context manager for compaction summaries.

        Uses the cheaper `fast_model` when one is configured — compaction is
        bookkeeping, not craftsmanship, so it shouldn't burn premium tokens.
        """
        provider = self._fast_provider or self.provider
        if self._fast_provider is None:
            fast = self.cfg.get("fast_model")
            if fast:
                prov_name, _, model = str(fast).partition(":")
                if not model:
                    model, prov_name = fast, self.provider.name
                try:
                    self._fast_provider = make_provider(
                        self.cfg, name=prov_name, model=model)
                    provider = self._fast_provider
                except Exception:
                    provider = self.provider
        chunks: List[str] = []
        for kind, payload in provider.stream(
            prompt_system,
            [{"role": "user", "content": [text_block(prompt_text)]}],
            tools=None,
        ):
            if kind == "text":
                chunks.append(payload)
        return "".join(chunks)

    def context_report(self) -> Dict[str, Any]:
        specs_json = json.dumps(toolmod.tool_specs())
        system = self.system_prompt()
        return {
            "used": self.context.used(system, self.messages, specs_json),
            "window": self.context.window,
            "breakdown": self.context.breakdown(system, self.messages, specs_json),
            "compactions": self.context.compactions,
            "calibration": round(self.context.calibration, 2),
        }


def _bash_rule(args: Dict[str, Any]) -> str:
    command = (args.get("command") or "").strip()
    first = command.split()[0] if command.split() else "*"
    return f"Bash({first} *)"


def build_change_diff(ctx: "toolmod.ToolContext", name: str, args: Dict[str, Any],
                      max_lines: int = 40) -> Optional[str]:
    """Predict the unified diff a write_file/edit_file call will produce,
    so the user can review the change *before* approving it."""
    try:
        path = ctx.resolve(args.get("path", ""))
        if not path.is_file():
            current = None
        else:
            if not toolmod._readable(path) or path.stat().st_size > toolmod.MAX_READ_BYTES:
                return None  # binary/oversized: skip diff, keep the prompt short
            current = path.read_text(encoding="utf-8", errors="replace")
        if name == "write_file":
            new_content = args.get("content")
            if not isinstance(new_content, str):
                return None
            old_lines = (current or "").splitlines()
            header_from = f"a/{ctx.rel(path)}" if current is not None else "/dev/null"
        else:
            old_string = args.get("old_string")
            new_string = args.get("new_string", "")
            if current is None or not isinstance(old_string, str) or not old_string:
                return None
            if current.count(old_string) != 1:
                return None  # ambiguous — execution will report it precisely
            new_content = current.replace(old_string, new_string, 1)
            old_lines = current.splitlines()
            header_from = f"a/{ctx.rel(path)}"
        new_lines = new_content.splitlines()
        diff = list(difflib.unified_diff(
            old_lines, new_lines, fromfile=header_from, tofile=f"b/{ctx.rel(path)}", lineterm=""))
        if not diff:
            return "(no changes)"
        if len(diff) > max_lines:
            diff = diff[:max_lines] + [f"⋯ (+{len(diff) - max_lines} more diff lines)"]
        return "\n".join(diff)
    except Exception:
        return None  # diff preview must never block the actual permission flow


def _render_todos(todos: List[Dict[str, str]]) -> str:
    if not todos:
        return ""
    marks = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}
    lines = ["Current task list (live state, preserved across compaction):"]
    for item in todos:
        lines.append(f"- {marks.get(item.get('status'), '[ ]')} {item.get('content', '')}")
    return "\n".join(lines)


def _result_summary(output: str) -> str:
    lines = output.splitlines()
    if not lines:
        return "(no output)"
    preview = lines[0][:160]
    if len(lines) == 1:
        return preview
    return f"{preview}  (+{len(lines) - 1} lines)"


def _git_state(root: Path) -> tuple[Optional[str], int]:
    try:
        branch = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if not branch:
            return None, 0
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return branch, len([ln for ln in status.splitlines() if ln.strip()])
    except (OSError, subprocess.SubprocessError):
        return None, 0
