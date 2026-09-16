<div align="center">

# 🐋 Orca Code — v2

**The zero-dependency AI coding agent.**
Your keys, your providers, your budget — in any terminal.

`2.0.0a1` · pure Python 3.9+ stdlib · MIT

</div>

> **Status: v2 alpha.** This branch is a ground-up rewrite of the Orca
> kernel. The stable line lives on `main` (v0.0.3, with prebuilt binaries).

## Why a rewrite

v1 grew by accretion; v2 is designed. The architecture is built around
five guarantees, each earned the hard way:

| Guarantee | How |
| --- | --- |
| **Nothing fails silently** | Every decision — tool runs, hooks, subagents, budget stops, compaction — is an event on a bus. If it happened, you can see it. |
| **Nothing hangs** | Every tool, hook, and socket carries a hard timeout. |
| **Streams don't lose work** | Dead streams retry when empty; when content already flowed, partial output is preserved and the model is nudged to continue. |
| **Sessions can't cross-contaminate** | One append-only JSONL file per session; a session can only ever read its own file. |
| **Tokens are counted once** | Cache-read tokens live in their own column, never folded into input. |

## Architecture

```
orca/
  core/       events (bus), budget (usage/caps), loop (agent kernel)
  providers/  catalog (data), transport (SSE + retry), provider (adapters)
  tools/      sandbox (central path guard), registry, builtins
  policy/     permission modes + destructive-command guard
  runtime/    config (layered, versioned), sessions (JSONL), hooks
  ui/         theme (Deep Ocean v2), console (line renderer — no TUI)
```

The kernel is pure orchestration: providers, tools, policy, hooks, budget,
and UI are all plugs. The UI is just a bus subscriber — which is also why
the whole agent is testable headlessly.

## Install & run

```bash
python3 -m pip install .        # or: pipx install .
orca                            # REPL
orca -p "explain this project"  # one-shot
```

Needs an API key for cloud providers (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`,
…) or nothing at all for local models via
[Ollama](https://ollama.com) / LM Studio.

## License

MIT — see [LICENSE](LICENSE).
