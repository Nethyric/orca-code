"""The agent kernel: pure orchestration, no I/O of its own.

Everything else plugs in — providers, tools, policy, hooks, budget, UI —
and every decision is announced on the event bus. The loop cannot hang on
a tool (each carries a timeout), cannot overrun (turn + token + cost caps),
and cannot fail silently (errors become events and tool results).
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..core.budget import Budget
from ..core.events import Bus, EKind
from ..core.messages import assistant_msg, tool_msg, user_msg
from ..providers.provider import BaseProvider, ProviderError
from ..runtime.hooks import HookRunner
from ..tools.registry import Registry, ToolResult

READONLY_TOOLS = frozenset({
    "read_file", "grep", "glob", "ls", "web_search", "web_fetch", "todo",
})


@dataclass
class AgentConfig:
    max_turns: int = 40
    max_task_turns: int = 12
    subagent_depth: int = 1
    continue_limit: int = 2
    system_prompt: str = ""
    style: Optional[str] = None


class Agent:
    """Runs one conversation against one provider."""

    def __init__(self, provider: BaseProvider, tools: Registry,
                 policy, bus: Bus, *,
                 budget: Optional[Budget] = None,
                 hooks: Optional[HookRunner] = None,
                 cfg: Optional[AgentConfig] = None,
                 depth: int = 0,
                 subagent_factory: Optional[Callable[[str], "Agent"]] = None,
                 messages: Optional[List[Dict[str, Any]]] = None) -> None:
        self.provider = provider
        self.tools = tools
        self.policy = policy
        self.bus = bus
        self.budget = budget or Budget()
        self.hooks = hooks
        self.cfg = cfg or AgentConfig()
        self.depth = depth
        self.subagent_factory = subagent_factory
        self.allowed_names: Optional[frozenset] = None
        self.messages: List[Dict[str, Any]] = list(messages or [])
        self.stopped: Optional[str] = None
        self.outcome: Optional[str] = None

    # ------------------------------------------------------------------ api
    def run(self, prompt: str) -> Optional[str]:
        self.bus.emit(EKind.turn_start, depth=self.depth)
        self.messages.append(user_msg(prompt))
        self.outcome = self._loop()
        self.bus.emit(EKind.turn_end, depth=self.depth, outcome=self.outcome)
        return self.last_text()

    def last_text(self) -> Optional[str]:
        for msg in reversed(self.messages):
            if msg["role"] != "assistant":
                continue
            for block in msg["content"]:
                if block.get("type") == "text" and block.get("text", "").strip():
                    return block["text"]
        return None

    # ----------------------------------------------------------------- loop
    def _loop(self) -> str:
        nudges_left = self.cfg.continue_limit
        for _turn in range(self.cfg.max_turns):
            exceeded = self.budget.exceeded()
            if exceeded:
                self.stopped = exceeded
                self.bus.emit(EKind.error, message=exceeded, fatal=True)
                return "budget"

            try:
                reply = self.provider.reply(
                    self.messages,
                    self.tools.specs(self._allowed_names()),
                    system=self._system_prompt())
            except ProviderError as exc:
                self.stopped = str(exc)
                self.bus.emit(EKind.error, message=str(exc), fatal=True)
                return "provider-error"

            self.budget.record(reply.usage, getattr(self.provider, "model", ""))
            self.bus.emit(EKind.budget, usage=self.budget.usage,
                          model=getattr(self.provider, "model", ""))
            if reply.thinking:
                self.bus.emit(EKind.thinking, text=reply.thinking, depth=self.depth)
            if reply.text:
                self.bus.emit(EKind.text, text=reply.text, depth=self.depth)
            self.messages.append(
                assistant_msg(reply.text, reply.thinking, reply.tool_calls))

            if not reply.tool_calls:
                # empty reply or truncated output: nudge instead of stopping
                if nudges_left > 0 and (not reply.text.strip()
                                        or reply.stop_reason == "length"):
                    nudges_left -= 1
                    self.bus.emit(EKind.notice,
                                  message="model stopped early — nudging to continue")
                    self.messages.append(user_msg(
                        "Continue exactly where you left off."))
                    continue
                return "done"

            stop = self._dispatch_all(reply.tool_calls)
            if stop is not None:
                self.stopped = stop
                return "stopped"
        self.stopped = "turn limit reached"
        self.bus.emit(EKind.error, message=self.stopped, fatal=True)
        return "turn-limit"

    def _allowed_names(self) -> Optional[frozenset]:
        return self.allowed_names

    def _system_prompt(self) -> str:
        return self.cfg.system_prompt

    # ------------------------------------------------------------- dispatch
    def _dispatch_all(self, calls: List[Dict[str, Any]]) -> Optional[str]:
        results: List[Dict[str, Any]] = []
        for call in calls:
            result = self._dispatch(call)
            results.append({
                "type": "tool_result",
                "tool_use_id": call.get("id", ""),
                "content": result.output,
                "is_error": result.is_error,
            })
        self.messages.append(tool_msg(results))
        return None

    def _dispatch(self, call: Dict[str, Any]) -> ToolResult:
        name = call.get("name", "")
        args = call.get("input") or {}
        summary = self._summarize(name, args)
        self.bus.emit(EKind.tool_start, tool=name, summary=summary,
                      depth=self.depth)

        if name == "task":
            result = self._run_task(args)
        else:
            spec = self.tools.get(name)
            if spec is None:
                result = ToolResult(
                    output=f"Error: unknown tool '{name}'.", is_error=True)
                self.bus.emit(EKind.tool_end, tool=name,
                              output=result.output, is_error=True,
                              depth=self.depth)
                return result
            decision = self.policy.check(
                name, args, readonly=bool(spec.readonly))
            if not decision.allowed:
                result = ToolResult(
                    output=f"blocked by permissions: {decision.reason}",
                    is_error=True)
            else:
                result = self._execute_checked(name, args)
        self.bus.emit(EKind.tool_end, tool=name, output=result.output[:400],
                      is_error=result.is_error, depth=self.depth)
        return result

    def _execute_checked(self, name: str, args: Dict[str, Any]) -> ToolResult:
        if name == "bash" and self.hooks:
            hook = self.hooks.run("before_bash", command=args.get("command", ""))
            if hook.blocked:
                return ToolResult(
                    output=(f"blocked by before_bash hook"
                            + (f": {hook.output}" if hook.output else "")),
                    is_error=True)
        result = self.tools.dispatch(name, args)
        if result.is_error:
            return result
        if self.hooks:
            if name in ("write_file", "edit_file"):
                hook = self.hooks.run("after_edit", file=args.get("path", ""))
                if hook.output:
                    result = ToolResult(result.output + f"\n[hook] {hook.output}")
            elif name == "bash":
                hook = self.hooks.run("after_bash", command=args.get("command", ""))
                if hook.output:
                    result = ToolResult(result.output + f"\n[hook] {hook.output}")
        return result

    # -------------------------------------------------------------- subagent
    def _run_task(self, args: Dict[str, Any]) -> ToolResult:
        prompt = (args.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(output="Error: task requires 'prompt'.",
                              is_error=True)
        profile = args.get("profile", "explore")
        if profile not in ("explore", "general"):
            profile = "explore"
        if self.depth >= self.cfg.subagent_depth:
            return ToolResult(
                output=("Error: subagents cannot spawn further subagents. "
                        "Do the work yourself with the tools you have."),
                is_error=True)
        if self.subagent_factory is None:
            return ToolResult(
                output="Error: subagents are not available in this session.",
                is_error=True)

        self.bus.emit(EKind.task_start, profile=profile, prompt=prompt[:80])
        try:
            sub = self.subagent_factory(profile)
        except Exception as exc:  # never leak a crash to the main loop
            return ToolResult(output=f"Error: could not start subagent: {exc}",
                              is_error=True)
        sub.budget = self.budget  # shared: caps still bind
        try:
            report = sub.run(prompt)
        except ProviderError as exc:  # defensive: run() normally contains it
            return ToolResult(output=f"Error: subagent failed: {exc}",
                              is_error=True)
        if sub.outcome in ("provider-error", "budget"):
            return ToolResult(
                output=f"Error: subagent failed: {sub.stopped}",
                is_error=True)
        text = (report or "(subagent returned no text)").strip()
        self.bus.emit(EKind.task_end, profile=profile)
        return ToolResult(output=text)

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _summarize(name: str, args: Dict[str, Any]) -> str:
        for key in ("path", "command", "pattern", "prompt"):
            if args.get(key):
                return str(args[key])[:72]
        return ", ".join(f"{k}={v}" for k, v in list(args.items())[:2])[:72]
