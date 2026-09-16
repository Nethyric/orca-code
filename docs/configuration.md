# Configuration

Orca Code is configured by one JSON file — no YAML, no profiles, no plugins.

- [Where settings live](#where-settings-live)
- [Full config reference](#full-config-reference)
- [Environment variables](#environment-variables)
- [Permissions](#permissions)
- [Themes](#themes)
- [Fallback chains](#fallback-chains)
- [Verification gates](#verification-gates)
- [Budgets & compaction](#budgets--compaction)
- [Project memory: ORCA.md](#project-memory-orcamd)

## Where settings live

| | |
| --- | --- |
| Config file | `~/.config/orca/config.json` (or `$ORCA_HOME/config.json`) |
| Sessions | `~/.config/orca/sessions/` |
| Keys added by `orca auth login` | the `api_keys` section of the same file |

Change anything with the wizard (`orca config`) or by editing the file —
Orca reads it at startup. Run `orca doctor` to sanity-check the result.

## Full config reference

```jsonc
{
  "provider": "deepseek",            // any of the 31 presets, or "custom"
  "model": "deepseek-chat",          // model id for your provider
  "fast_model": null,                // cheaper model used for compaction summaries

  "fallbacks": [],                   // e.g. ["groq:llama-3.3-70b-versatile"]
                                     // tried in order when the provider fails

  "verify_command": null,            // e.g. "python3 -m pytest -x -q"
                                     // runs after every file edit; failures go
                                     // straight back to the model to fix

  "max_session_tokens": null,        // hard token budget per session (runaway guard)
  "max_cost_usd": null,              // hard cost cap in USD — mid-run safety stop
  "max_tokens": null,                // per-response token limit (provider default)

  "auto_compact": true,              // compact context near the window limit
  "compact_threshold": 0.82,         // fraction of the window that triggers it
  "keep_recent": 0.30,               // fraction of newest messages kept intact

  "prompt_caching": true,            // Anthropic cache_control on system+tools

  "permissions": {
    "mode": "default",               // "default" | "acceptEdits" | "yolo"
    "allow": [],                     // e.g. ["bash(git *)", "read_file"] — skip prompts
    "deny":  []                      // e.g. ["bash(rm *)"] — always refuse
  },

  "api_keys": { "deepseek": "sk-..." },   // set by `orca auth login`
  "base_urls": { "custom": "https://your-gateway/v1" }
}
```

## Environment variables

Every setting has an env override — env always wins:

| Variable | Overrides |
| --- | --- |
| `ORCA_HOME` | settings directory (default `~/.config/orca`) |
| `ORCA_PROVIDER` / `ORCA_MODEL` | provider / model |
| `ORCA_FAST_MODEL` | compaction model |
| `ORCA_BASE_URL` | endpoint for any provider (custom gateways) |
| `ORCA_API_KEY` | key for any provider — brand-neutral generic |
| `ORCA_MAX_COST` | `max_cost_usd` |
| `<PROVIDER>_API_KEY` | e.g. `DEEPSEEK_API_KEY`, `GROQ_API_KEY`, `HF_TOKEN` — beats stored keys and `ORCA_API_KEY` |

## Permissions

Prompt fatigue is how accidents happen. Tune it once:

```json
"permissions": {
  "mode": "default",
  "allow": ["bash(git diff*)", "bash(python3 -m pytest*)", "read_file"],
  "deny":  ["bash(rm -rf *)", "bash(git push --force*)"]
}
```

- `allow` rules match tool calls by prefix/glob and skip the prompt.
- `deny` rules always refuse, even in `--yolo`.
- Modes: `default` (ask), `acceptEdits` (= `--accept-edits`), `yolo` (= `--yolo`).

## Themes

Five themes, all tuned for legibility (WCAG-checked pairs):

`dark` (Deep Ocean, default) · `light` · `coral` · `ansi` · `mono` (ASCII-safe)

Switch live with `/theme`, or set `"theme"` in the config. The `mono` theme
replaces box-drawing glyphs with pure ASCII for odd terminals.

## Fallback chains

Providers fail — rate limits, outages, expired keys. A fallback chain keeps
the session alive by retrying the same request on the next provider in order:

```bash
orca --fallback groq:llama-3.3-70b-versatile --fallback deepseek:deepseek-chat
```

or persist it: `"fallbacks": ["groq:llama-3.3-70b-versatile", "deepseek:deepseek-chat"]`.

## Verification gates

The single highest-leverage quality setting. A `verify_command` turns "the
model *thinks* it's fixed" into "the tests pass":

```json
"verify_command": "python3 -m pytest -x -q"
```

After every file edit, Orca runs the command; on failure, the output is fed
back to the model automatically until green or `MAX_TURNS` is hit. Works with
any deterministic command: `make test`, `npm test -- --watchAll=false`,
`cargo test`, `.orca/verify.sh`.

## Budgets & compaction

Two hard caps, enforced mid-run — not on next month's invoice:

- `max_cost_usd` — the agent stops itself when session spend crosses the line.
- `max_session_tokens` — the runaway guard.

Compaction is visible, never silent: when context reaches `compact_threshold`
of the window, older messages are summarized (by `fast_model` if set), the
newest `keep_recent` fraction is kept verbatim, and the UI says exactly what
happened. Disable with `--no-auto-compact` or `"auto_compact": false`.

## Project memory: ORCA.md

`orca init` creates an `ORCA.md` at the project root — conventions, commands,
gotchas — which is injected into every session in that project. Fully
provider-neutral. `/memory` shows what's loaded.
