# CLI & Tools

Everything Orca Code can do, on one page.

- [Starting Orca](#starting-orca)
- [Global flags](#global-flags)
- [Subcommands](#subcommands)
- [Slash commands (REPL)](#slash-commands-repl)
- [Agent tools](#agent-tools)
- [Permissions](#permissions)
- [One-shot scripting](#one-shot-scripting)

## Starting Orca

```bash
orca                 # REPL in the current directory
orca -c              # continue the most recent session
orca -r              # pick a past session to resume
orca -p "fix the flaky test"    # one-shot, print result, exit
```

## Global flags

| Flag | Effect |
| --- | --- |
| `-m, --model <id>` | model id (overrides config) |
| `--provider <name>` | provider (overrides config; see [providers](providers.md)) |
| `--root <dir>` | project root (default: cwd) |
| `-p, --print <prompt>` | non-interactive one-shot mode |
| `-c, --continue` | continue the most recent session |
| `-r, --resume [id]` | resume a session (picker when id omitted) |
| `--base-url <url>` | custom OpenAI-compatible endpoint |
| `--api-key <key>` | key for the chosen provider |
| `--max-cost <usd>` | **hard** session cost cap — mid-run stop |
| `--max-tokens <n>` | hard token budget (runaway guard) |
| `--fallback P:M` | fallback chain, repeatable: `--fallback openai:gpt-5.1 --fallback groq:llama-3.3-70b-versatile` |
| `--plan` | start read-only: agent can look but not touch |
| `--accept-edits` | auto-approve file edits (bash still asks) |
| `--yolo` | skip all prompts (destructive commands still blocked) |
| `--no-auto-compact` | disable automatic context compaction |

## Subcommands

| Command | Effect |
| --- | --- |
| `orca auth login [provider] [-t key] [--no-default]` | add an API key — **validated live** against the provider's model list; hidden input; offers to set provider+model default |
| `orca auth list` / `ls` | which providers have keys, and whether from config or env |
| `orca auth logout <provider>` | remove a stored key |
| `orca config` | interactive setup wizard (provider, model, theme, budgets) |
| `orca init` | create an `ORCA.md` project-memory template |
| `orca doctor` | diagnose config, auth, and connectivity |
| `orca --version` | print version |

## Slash commands (REPL)

| Command | Effect |
| --- | --- |
| `/help` | list commands |
| `/model <id>` | switch model |
| `/models` | **live** model list from the provider's API (then static suggestions) |
| `/provider <name>` | switch provider |
| `/context` | context-window meter (tokens used / limit) |
| `/compact` | compact the conversation now |
| `/cost` | session cost breakdown per provider |
| `/undo` | rewind files **and** conversation to the last checkpoint |
| `/rewind` | pick any earlier checkpoint to rewind to |
| `/diff` | show uncommitted changes the agent made |
| `/todo` | show the agent's task list |
| `/plan` | toggle plan (read-only) mode |
| `/yolo` | toggle permission-free mode |
| `/theme` | switch UI theme (5 themes) |
| `/system` | transparency: exact system prompt + provider + model |
| `/tools` | list the agent's tools and which are enabled |
| `/memory` | show loaded project memory (ORCA.md) |
| `/init` | create ORCA.md template |
| `/sessions` | list past sessions |
| `/save` | save the session now |
| `/clear` | clear conversation and context |

## Agent tools

The tools the model can call, and what they can do:

| Tool | What it does |
| --- | --- |
| `read_file` | read a file with 1-based line numbers; `offset`/`limit` for ranges |
| `write_file` | create or overwrite a file with full content |
| `edit_file` | exact-string replacement (`old_string` → `new_string`), with closest-match hints on mismatch |
| `bash` | run a shell command in the project root; combined stdout+stderr, 120s default timeout |
| `grep` | regex content search, respects `.gitignore`, glob filter |
| `glob` | find files by pattern (`**/*.py`), sorted by mtime |
| `ls` | list a directory, dirs first |
| `todo` | multi-step task tracking shown in the UI |
| `web_search` | DuckDuckGo search, no API key needed |
| `web_fetch` | fetch a URL as readable text (HTML stripped) |

Tool availability adapts: in plan mode, mutating tools are disabled; permission
levels are visible in `/tools`.

## Permissions

Three levels, per tool:

1. **Ask** (default for edits and bash) — a prompt with the exact command/diff
   before anything runs; answers: once / this session / always (saved) / no.
2. **Auto** via `--accept-edits` — file edits proceed, bash still asks.
3. **YOLO** via `--yolo` or `/yolo` — everything proceeds; a built-in blocklist
   still refuses catastrophic commands (`rm -rf /`, disk-wipe, force-push to
   shared refs, credential exfiltration).

## One-shot scripting

`-p` mode is pipe-friendly — exit code and stdout are clean for scripts:

```bash
orca -p "summarize the diff in src/auth" > notes.md
orca -p "run the test suite and fix what fails" --accept-edits
echo "review $(git diff --name-only)" | orca -p -
```

The agent plans with `todo`, writes files one by one, then **runs the result**
to verify — a build is done when it works, not when the files exist.
