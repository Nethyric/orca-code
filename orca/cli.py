"""Command line entry point."""
import argparse
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .core.budget import Budget
from .core.events import Bus, EKind
from .core.loop import Agent, AgentConfig
from .policy.permissions import Mode, Policy
from .providers.catalog import CATALOG
from .providers.provider import ProviderError, make_provider
from .runtime.config import Config, ConfigError
from .runtime.hooks import HookRunner
from .runtime.sessions import Session
from .tools.builtin import register_builtins
from .tools.registry import Registry
from .tools.sandbox import Sandbox
from .ui.console import Console
from .ui.theme import Theme

STYLES = ("concise", "verbose", "code")

STYLE_HINTS = {
    "concise": "Answer in the fewest words that fully solve the task.",
    "verbose": "Explain your reasoning as you work.",
    "code": "Lead with code; keep prose minimal.",
}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="orca", description="Orca Code — the zero-dependency AI coding agent")
    ap.add_argument("--version", action="version",
                    version=f"orca-code {__version__}")
    ap.add_argument("--root", help="project root (default: cwd)")
    ap.add_argument("-p", "--print", dest="prompt",
                    help="one-shot: run a prompt and print the answer")
    ap.add_argument("--provider", help="provider name")
    ap.add_argument("--model", help="model id")
    ap.add_argument("--base-url", help="custom endpoint (any provider)")
    ap.add_argument("--api-key", help="API key for the chosen provider")
    ap.add_argument("--plan", action="store_true", help="read-only mode")
    ap.add_argument("--accept-edits", action="store_true",
                    help="auto-approve file edits (bash still asks)")
    ap.add_argument("--yolo", action="store_true",
                    help="skip prompts (destructive commands still blocked)")
    ap.add_argument("--max-cost", type=float, help="hard cost cap in USD")
    ap.add_argument("--max-tokens", type=int, dest="max_tokens_budget",
                    help="hard token budget for the session")
    ap.add_argument("--style", choices=STYLES, help="output style")
    ap.add_argument("--providers", action="store_true",
                    help="list known providers and exit")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.providers:
        for name, spec in CATALOG.items():
            tag = " · local, no key" if spec.local else ""
            print(f"  {name:14} {spec.base_url}{tag}")
        return 0

    try:
        return _run(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


def _run(args) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
    cfg = Config(root=root)

    if args.provider:
        cfg.set("provider", args.provider)
    if args.model:
        cfg.set("model", args.model)
    if args.base_url:
        urls = dict(cfg.get("base_urls") or {})
        urls[args.provider or cfg.detect_provider()] = args.base_url
        cfg.set("base_urls", urls)
    if args.api_key:
        keys = dict(cfg.get("api_keys") or {})
        keys[args.provider or cfg.detect_provider()] = args.api_key
        cfg.set("api_keys", keys)
    if args.style:
        cfg.set("output_style", args.style)

    provider = make_provider(cfg, args.provider, args.model)

    sandbox = Sandbox(root)
    registry = Registry()
    register_builtins(registry, sandbox,
                      bash_timeout=int(cfg.get("bash_timeout") or 120))

    mode = (Mode.PLAN if args.plan
            else Mode.YOLO if args.yolo
            else Mode.ACCEPT_EDITS if args.accept_edits
            else _mode_from(cfg))
    policy = Policy(mode)

    budget = Budget(max_cost_usd=args.max_cost
                    or cfg.get("max_cost_usd"),
                    max_tokens=args.max_tokens_budget
                    or cfg.get("max_session_tokens"))

    bus = Bus()
    theme = Theme()
    console = Console(bus, theme,
                      stream=sys.stderr if args.prompt is not None else None,
                      mute_text=args.prompt is not None)

    style = cfg.get("output_style")
    system = _system_prompt(root, style)
    agent_cfg = AgentConfig(
        max_turns=int(cfg.get("max_turns") or 40),
        max_task_turns=int(cfg.get("max_task_turns") or 12),
        system_prompt=system)

    def factory(profile: str) -> Agent:
        sub_provider = make_provider(cfg)
        sub = Agent(sub_provider, registry, policy, bus, budget=budget,
                    hooks=HookRunner(cfg.get("hooks"), root),
                    cfg=AgentConfig(
                        max_turns=agent_cfg.max_task_turns,
                        system_prompt=_system_prompt(root, style, subagent=True)),
                    depth=1)
        if profile == "explore":
            sub.allowed_names = frozenset(
                {"read_file", "grep", "glob", "ls", "todo"})
        return sub

    hooks = HookRunner(cfg.get("hooks"), root)
    agent = Agent(provider, registry, policy, bus, budget=budget, hooks=hooks,
                  cfg=agent_cfg, subagent_factory=factory)

    if args.prompt is not None:
        bus.emit(EKind.session_start, version=__version__)
        answer = agent.run(args.prompt)
        if answer:
            print(answer)
        return 0 if agent.stopped is None else 1

    from .repl import REPL
    session = Session(directory=root / ".orca" / "sessions")
    repl = REPL(agent, session, bus, args)
    return repl.run()


def _mode_from(cfg: Config) -> Mode:
    try:
        return Mode(str(cfg.permission_mode()))
    except ValueError:
        return Mode.DEFAULT


def _system_prompt(root: Path, style: Optional[str],
                   subagent: bool = False) -> str:
    from . import __version__
    parts = [
        f"You are Orca Code v{__version__}, a terminal coding agent.",
        f"Project root: {root}.",
        "Prefer the smallest change that works. Verify with tools "
        "(read files back, run commands) before claiming success.",
        "Never fabricate file contents — read them.",
    ]
    if subagent:
        parts.append("You are a scoped subagent: do exactly what was asked, "
                     "then report the result concisely.")
    if style and style in STYLE_HINTS:
        parts.append(f"Style: {STYLE_HINTS[style]}")
    return "\n".join(parts)


if __name__ == "__main__":
    sys.exit(main())
