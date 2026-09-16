"""Orca Code CLI — argument parsing, onboarding wizard, doctor, wiring."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import (Config, ConfigError, PROVIDER_PRESETS, SUGGESTED_MODELS,
                     VERSION, config_path, model_info, orca_home)
from .providers import ProviderError, make_provider, require_key
from .usage import TokenBudgetExceeded
from .sessions import Session, latest_session, load_session, find_session
from .ui import UI, fmt_tokens


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-m", "--model", help="model id (overrides config)")
    common.add_argument("--provider", help="provider name (overrides config)")
    common.add_argument("--root", help="project root (default: cwd)")

    parser = argparse.ArgumentParser(
        prog="orca",
        description="🐋 Orca Code — the apex predator of terminal coding agents",
        parents=[common],
    )
    parser.add_argument("-p", "--print", metavar="PROMPT", dest="print_prompt",
                        help="non-interactive: run one prompt and print the result")
    parser.add_argument("-c", "--continue", dest="cont", action="store_true",
                        help="continue the most recent session")
    parser.add_argument("-r", "--resume", metavar="ID", nargs="?", const="",
                        help="resume a session (interactive picker when ID omitted)")
    parser.add_argument("--base-url", help="custom API base URL (OpenAI-compatible)")
    parser.add_argument("--api-key", help="API key for --provider")
    parser.add_argument("--max-cost", type=float, help="hard session cost cap in USD")
    parser.add_argument("--max-tokens", type=int, dest="max_tokens_budget",
                        help="hard token budget for this session (runaway guard)")
    parser.add_argument("--fallback", action="append", default=[], metavar="PROVIDER:MODEL",
                        help="fallback to try when the provider fails "
                             "(repeatable, tried in order)")
    parser.add_argument("--plan", action="store_true", help="start in plan (read-only) mode")
    parser.add_argument("--accept-edits", action="store_true", help="auto-approve file edits")
    parser.add_argument("--yolo", action="store_true",
                        help="skip all permission prompts (catastrophic commands still blocked)")
    parser.add_argument("--no-auto-compact", action="store_true",
                        help="disable automatic context compaction")
    parser.add_argument("--version", action="version", version=f"orca-code {VERSION}")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("config", help="interactive configuration wizard")
    auth = sub.add_parser("auth", help="manage provider API keys")
    auth_sub = auth.add_subparsers(dest="auth_cmd", required=True)
    auth_login = auth_sub.add_parser("login", help="add an API key (validated live)")
    auth_login.add_argument("provider", nargs="?", help="provider (picker if omitted)")
    auth_login.add_argument("-t", "--token", help="API key (non-interactive mode)")
    auth_login.add_argument("--no-default", action="store_true",
                            help="don't offer to make it the default provider")
    auth_logout = auth_sub.add_parser("logout", help="remove a stored API key")
    auth_logout.add_argument("provider", help="provider name")
    auth_ls = auth_sub.add_parser("list", aliases=["ls"], help="show key status")
    sub.add_parser("init", help="create an ORCA.md memory template", parents=[common])
    sub.add_parser("doctor", help="diagnose setup & connectivity", parents=[common])
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    # Windows consoles default to legacy code pages (cp1252) that can't encode
    # the UI's glyphs (←, ✓, ⌁, ⋯). Switch to UTF-8 with replacement so output
    # degrades gracefully instead of crashing with UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # non-tty/captured stream without reconfigure()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd == "auth":
            return run_auth(args)
        if args.cmd == "config":
            return run_wizard()
        if args.cmd == "init":
            return run_init(args.root)
        if args.cmd == "doctor":
            return run_doctor(args)
        return run_session(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print()
        return 130


# --------------------------------------------------------------------------
# main paths
# --------------------------------------------------------------------------

def run_session(args: argparse.Namespace) -> int:
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
    cfg = Config(root=root)
    ui = UI(interactive=interactive, theme=cfg.get("theme"))

    if args.provider:
        os.environ["ORCA_PROVIDER"] = args.provider
        cfg.set("provider", args.provider)
    if args.model:
        from .config import expand_model_alias
        cfg.set("model", expand_model_alias(args.model))
    elif args.provider:
        # switching providers without an explicit model: don't reuse a model
        # id that belongs to a different provider
        cfg.set("model", None)
    if args.base_url:
        os.environ["ORCA_BASE_URL"] = args.base_url
    if args.api_key:
        keys = dict(cfg.get("api_keys", {}) or {})
        keys[args.provider or cfg.detect_provider()] = args.api_key
        cfg.set("api_keys", keys)
    if args.max_cost is not None:
        cfg.set("max_cost_usd", args.max_cost)
    if getattr(args, "max_tokens_budget", None):
        cfg.set("max_session_tokens", args.max_tokens_budget)
    if getattr(args, "fallback", None):
        chain = [f for f in (cfg.get("fallbacks") or []) if f]
        for item in args.fallback:
            if item not in chain:
                chain.append(item)
        cfg.set("fallbacks", chain)
    if args.no_auto_compact:
        cfg.set("auto_compact", False)

    mode = "yolo" if args.yolo else ("plan" if args.plan else
                                     ("acceptEdits" if args.accept_edits else None))
    if mode:
        perms = cfg.get("permissions", {})
        perms["mode"] = mode
        cfg.set("permissions", perms)

    # provider (mock lets people try the UI offline: --provider mock)
    try:
        provider = make_provider(cfg, name=args.provider, model=args.model)
    except ConfigError as exc:
        ui.error(str(exc))
        return 2

    if not provider.model:
        ui.error(f"No model configured for provider '{provider.name}'. "
                 f"Run `orca config` or use --model.")
        return 2

    # session / resume
    session = Session()
    resumed_messages: List[Dict[str, Any]] = []
    if args.resume is not None:
        target = _pick_session(args.resume, ui, interactive)
        if target is None:
            ui.error("No matching session.")
            return 1
        resumed_messages = load_session(target)
        session.resume(target)
        session.append({"t": "resume", "messages": len(resumed_messages)})
    elif args.cont:
        target = latest_session()
        if target is None:
            ui.error("No previous session to continue.")
            return 1
        resumed_messages = load_session(target)
        session.resume(target)
        session.append({"t": "resume", "messages": len(resumed_messages)})

    from .agent import Agent
    from .permissions import Permissions
    from .repl import Repl

    permissions = Permissions(
        mode=cfg.permissions.get("mode", "default"),
        allow=cfg.permissions.get("allow", []),
        deny=cfg.permissions.get("deny", []),
    )
    auto_approve = None
    if not interactive or args.print_prompt:
        # non-interactive permission policy: reads flow through the engine;
        # everything that would ask gets auto-answered by mode (never blocks).
        # Same policy for every provider — no special cases to surprise you.
        mode = permissions.mode

        def auto_approve(name, a, _mode=mode):
            from .tools import TOOL_BY_NAME
            perm = TOOL_BY_NAME.get(name, {}).get("perm", "none")
            if perm in ("read", "none"):
                return "y"
            if _mode == "yolo":
                return "y"
            if perm == "write" and _mode == "acceptEdits":
                return "y"
            return "n"
    agent = Agent(provider, cfg, ui, permissions=permissions, session=session,
                  root=root, auto_approve_callback=auto_approve)
    agent.messages = resumed_messages

    if args.print_prompt:
        return run_print(args, agent, ui)

    if not interactive:
        ui.error("stdin/stdout are not a TTY — use `orca -p \"prompt\"` for "
                 "non-interactive use, or `orca --provider mock` offline demo.")
        return 2

    ui.banner(VERSION, provider.name, provider.model, str(root), permissions.mode)
    if resumed_messages:
        from .context import estimate_messages
        replayed = estimate_messages(resumed_messages)
        ui.notice(f"Resumed session: {session.name} ({len(resumed_messages)} messages, "
                  f"~{replayed // 1000}k tokens of context replayed)")
    if not cfg.model and not os.environ.get("ORCA_MODEL") and provider.name != "mock":
        ui.notice(f"Tip: set your default model with /model or `orca config`.")

    repl = Repl(agent, ui, cfg)
    try:
        repl.run()
    finally:
        _flush_history(agent)
    return 0


class PrintUI(UI):
    """For `orca -p`: final text on stdout, everything else on stderr."""

    def __init__(self, theme: Optional[str] = None) -> None:
        super().__init__(interactive=False, theme=theme)
        self.err = UI(interactive=False, stderr=True, theme=theme)

    def tool_start(self, name, detail):
        self.end_stream()          # flush stdout text before tool banner
        self.err.tool_start(name, detail)

    def reasoning(self, delta):
        self.err.reasoning(delta)

    def tool_done(self, summary, is_error=False):
        self.err.tool_done(summary, is_error)

    def file_preview(self, path, output, max_lines=8):
        self.err.file_preview(path, output, max_lines)

    def turn_footer(self, used, window, cost_text):
        self.end_stream()
        self.err.turn_footer(used, window, cost_text)

    def todos(self, items):
        self.end_stream()
        self.err.todos(items)

    def warn(self, msg):
        self.err.warn(msg)

    def error(self, msg):
        self.err.error(msg)

    def notice(self, msg):
        self.err.notice(msg)

    def ok(self, msg):
        self.err.ok(msg)


def run_print(args: argparse.Namespace, agent, ui: UI) -> int:
    """`orca -p` — one prompt, final answer to stdout, tool noise to stderr."""
    if not os.environ.get("ORCA_PRINT_VERBOSE"):
        _cfg = getattr(agent, "cfg", None)
        agent.ui = PrintUI(theme=_cfg.get("theme") if _cfg is not None else None)
    try:
        agent.run(args.print_prompt)
    except ProviderError as exc:
        print(f"orca: provider error: {exc}", file=sys.stderr)
        return 1
    except TokenBudgetExceeded as exc:
        print(f"orca: {exc}", file=sys.stderr)
        return 1
    if getattr(agent, "last_provider_error", None):
        return 1
    return 0


def _pick_session(query: str, ui: UI, interactive: bool):
    from .sessions import list_sessions
    if query:
        return find_session(query)
    sessions = list_sessions()
    if not sessions:
        return None
    if not interactive:
        return sessions[0]
    ui.rule("Sessions")
    for i, path in enumerate(sessions, 1):
        ui.p(f"  {i:>3}  {path.stem}")
    try:
        choice = input("Resume which? [number, Enter=1, q=quit] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if choice.lower() == "q" or not choice:
        return sessions[0] if choice == "" else None
    if choice.isdigit() and 1 <= int(choice) <= len(sessions):
        return sessions[int(choice) - 1]
    return find_session(choice)


def _flush_history(agent) -> None:
    try:
        if agent.session.path is None and agent.messages:
            agent.session.append({"t": "end"})
    except OSError:
        pass


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------

def run_init(root: Optional[str]) -> int:
    from .memory import init_memory
    target = Path(root).resolve() if root else Path.cwd().resolve()
    path = init_memory(target)
    print(("created " if path.stat().st_size else "exists: ") + str(path))
    return 0


def run_auth(args: argparse.Namespace) -> int:
    """`orca auth login|logout|list` — provider key management.

    Like `opencode auth login`, but the key is validated live against the
    provider's own /models endpoint before it's stored, and you're offered
    the provider's real catalog when picking a default model.
    """
    cfg = Config()
    cmd = args.auth_cmd
    if cmd == "logout":
        keys = dict(cfg.get("api_keys", {}) or {})
        if args.provider not in keys:
            print(f"no stored key for '{args.provider}'")
            return 1
        del keys[args.provider]
        cfg.set("api_keys", keys)
        cfg.save()
        print(f"removed stored key for '{args.provider}'")
        return 0

    if cmd in ("list", "ls"):
        keys = cfg.get("api_keys", {}) or {}
        default = cfg.get("provider") or cfg.detect_provider()
        rows = []
        for name in sorted(PROVIDER_PRESETS):
            if name in ("custom", "mock"):
                continue
            preset = PROVIDER_PRESETS[name]
            if name in keys:
                status = "✓ stored"
            elif preset.get("key_env") and os.environ.get(preset["key_env"]):
                status = f"✓ env {preset['key_env']}"
            elif not preset.get("key_env"):
                status = "local (no key)"
            else:
                continue
            mark = " ← default" if name == default else ""
            rows.append(f"  {name:<14} {status}{mark}")
        print("\n".join(rows) or "  (no keys yet — `orca auth login`)")
        return 0

    # -- login ------------------------------------------------------------
    provider = (args.provider or "").lower()
    if provider and provider not in PROVIDER_PRESETS:
        print(f"unknown provider '{provider}'. "
              f"Valid: {', '.join(sorted(PROVIDER_PRESETS))}")
        return 2
    if not provider:
        if not sys.stdin.isatty():
            print("non-interactive shell — use: orca auth login <provider> -t <key>")
            return 2
        names = [n for n in sorted(PROVIDER_PRESETS)
                 if n not in ("custom", "mock")]
        print("Providers:\n")
        for i, n in enumerate(names, 1):
            preset = PROVIDER_PRESETS[n]
            tag = "local, no key" if not preset.get("key_env") \
                else f"key: {preset['key_env']}"
            print(f"  {i:>2}. {n:<14} {tag}")
        try:
            raw = input("\nLogin to which provider? [number] ").strip()
            provider = names[int(raw) - 1]
        except (ValueError, IndexError, EOFError, KeyboardInterrupt):
            print("\naborted")
            return 1
    preset = PROVIDER_PRESETS[provider]
    if not preset.get("key_env"):
        print(f"'{provider}' runs locally — no API key needed.")
        return 0

    token = args.token
    if not token:
        if not sys.stdin.isatty():
            print("non-interactive shell — pass the key with -t/--token")
            return 2
        try:
            import getpass
            token = getpass.getpass(f"API key for {provider} (input hidden): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\naborted")
            return 1
    if not token:
        print("no key given — aborted")
        return 1

    # validate against the provider's live catalog
    models: List[str] = []
    verdict = ""
    try:
        conf = dict(preset)
        conf["name"] = provider
        conf["api_key"] = token
        from .providers import BaseProvider, list_remote_models
        probe = BaseProvider(conf, "")
        models = list_remote_models(probe)
        verdict = f"✓ key works — {len(models)} models available"
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "403" in msg or "invalid" in msg.lower():
            print(f"✗ provider rejected this key: {msg}")
            return 1
        verdict = f"? could not validate ({msg}) — storing anyway"

    keys = dict(cfg.get("api_keys", {}) or {})
    keys[provider] = token
    cfg.set("api_keys", keys)
    try:
        cfg.save()
    except OSError as exc:
        print(f"could not save config: {exc}")
        return 1
    print(verdict)
    print(f"✓ key stored for '{provider}' in {config_path()}")

    # offer to make it the default with a real model id
    if not args.no_default and sys.stdin.isatty() and models:
        suggested = (SUGGESTED_MODELS.get(provider) or [])
        default_model = next((m for m in suggested if m in models),
                             suggested[0] if suggested else
                             (models[0] if models else ""))
        try:
            answer = input(f"Make {provider} your default provider? [Y/n] ").strip().lower()
            if answer in ("", "y", "yes"):
                model = default_model
                pick = input(f"Default model [{model}]: ").strip() or model
                cfg.set("provider", provider)
                cfg.set("model", pick)
                cfg.save()
                print(f"✓ default: {provider} · {pick}")
        except (EOFError, KeyboardInterrupt):
            print()
    print("\nNext: run `orca` in any project, or `orca -p \"...\"` for one-shot tasks.")
    return 0


def run_wizard() -> int:
    interactive = sys.stdin.isatty()
    print(f"🐋 Orca Code setup  (config → {config_path()})\n")
    names = [n for n in PROVIDER_PRESETS if n not in ("custom", "mock")]
    if not interactive:
        print("Non-interactive shell. Configure via environment variables instead:\n"
              "  export ORCA_PROVIDER=openrouter\n"
              "  export ORCA_API_KEY=sk-or-...\n"
              "  export ORCA_MODEL=anthropic/claude-sonnet-4.5\n"
              "or edit the JSON at ~/.orca/config.json")
        return 0

    print("Providers:")
    for i, name in enumerate(names, 1):
        preset = PROVIDER_PRESETS[name]
        tag = "local, no key" if name in ("ollama", "lmstudio") else f"key: {preset['key_env']}"
        print(f"  {i:>2}. {name:<12} {tag}")
    try:
        raw = input(f"Choose provider [1-{len(names)}, default 2 openrouter]: ").strip()
        name = names[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(names) else "openrouter"
    except (ValueError, EOFError, KeyboardInterrupt):
        name = "openrouter"

    api_key = ""
    if name not in ("ollama", "lmstudio"):
        try:
            import getpass
            api_key = getpass.getpass(f"API key for {name} (input hidden): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\naborted")
            return 1

    models = SUGGESTED_MODELS.get(name) or []
    default_model = models[0] if models else ""
    try:
        model = input(f"Model [{default_model}]: ").strip() or default_model
    except (EOFError, KeyboardInterrupt):
        model = default_model
    if not model:
        print("No model given — rerun `orca config` later. Aborting.")
        return 1

    cfg = Config()
    cfg.set("provider", name)
    cfg.set("model", model)
    if api_key:
        keys = dict(cfg.get("api_keys", {}) or {})
        keys[name] = api_key
        cfg.set("api_keys", keys)
    cfg.save()

    print(f"\nsaved → {config_path()}")
    if api_key or name in ("ollama", "lmstudio"):
        print("testing connection…")
        ok, message = _test_provider(cfg, name, model)
        print(("  " + message))
        if ok:
            print(f"\n✓ You're set. Run `orca` in any project directory.")
        else:
            print(f"\n! Saved anyway. Test failed: {message}")
    return 0


def _test_provider(cfg: Config, name: str, model: str) -> tuple[bool, str]:
    try:
        provider = make_provider(cfg, name=name, model=model)
        require_key(provider)
        text = []
        for kind, payload in provider.stream(
            "You are a connection test.",
            [{"role": "user", "content": [{"type": "text", "text": "Say OK"}]}],
            tools=None):
            if kind == "text":
                text.append(payload)
        return True, f"{provider.name}/{provider.model} replied: {''.join(text)[:40] or '(empty)'}"
    except (ProviderError, ConfigError) as exc:
        return False, str(exc)


def run_doctor(args: argparse.Namespace) -> int:
    cfg = Config(root=Path(args.root).resolve() if args.root else None)
    provider_name = args.provider or cfg.detect_provider()
    model = args.model or cfg.model or (SUGGESTED_MODELS.get(provider_name) or ["?"])[0]
    print("🐋 Orca Code doctor\n")
    checks: List[tuple[str, str]] = []

    checks.append(("python", f"{sys.version.split()[0]} "
                  f"({'ok' if sys.version_info >= (3, 9) else 'NEEDS 3.9+'})"))
    checks.append(("config file", str(config_path()) + (" ✓" if config_path().is_file() else " (missing — `orca config`)")))
    checks.append(("provider", provider_name))
    conf = cfg.resolve_provider(provider_name)
    checks.append(("base url", conf["base_url"]))
    has_key = bool(conf.get("api_key")) or provider_name in ("ollama", "lmstudio", "mock")
    checks.append(("api key", "present ✓" if has_key else "MISSING"))
    checks.append(("model", f"{model} · context {fmt_tokens(model_info(model).get('context', 0))}"))

    if provider_name == "mock":
        checks.append(("connectivity", "mock — offline"))
    elif has_key:
        print("running checks…\n")
        ok, message = _test_provider(cfg, provider_name, model)
        checks.append(("connectivity", ("✓ " if ok else "✗ ") + message))
    print()
    width = max(len(k) for k, _ in checks)
    for key, value in checks:
        print(f"  {key:<{width}}  {value}")
    print("\n  home dir:", orca_home())
    return 0


if __name__ == "__main__":
    sys.exit(main())
