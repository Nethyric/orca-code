# Why Orca

Every feature in Orca Code exists because someone using the existing terminal
agents complained about its absence — on Reddit, Hacker News, and GitHub
issues. This page is the map from complaint to feature. It's also the honest
answer to "why another agent?".

| The complaint | What Orca does |
| --- | --- |
| "My agent ran for an hour and burned $40 before I noticed." | Live cost on every response, `max_cost_usd` hard stop enforced **mid-run**, `max_session_tokens` runaway guard. |
| "I can't tell how much context is left." | A context meter in the status line (`/context`), and compaction that announces itself — threshold, what was summarized, what was kept. |
| "It edited the wrong file and I had to `git checkout` by hand." | `/undo` rewinds files **and** conversation state to the previous checkpoint; `/rewind` picks any earlier one. Every edit shows a diff before it lands. |
| "The model says tests pass but they don't." | `verify_command` gates every file edit on a deterministic command (pytest, make test, …) and feeds failures straight back to the model. |
| "I'm locked into one vendor's API and pricing." | 31 providers, one binary. `--fallback` chains. Any OpenAI-compatible endpoint via `custom`. Keys validated live by `orca auth login`. |
| "I don't want to babysit `y/n` prompts all day." | Scoped `allow`/`deny` permission rules that persist, `--accept-edits`, `--yolo` with a hard blocklist that still refuses catastrophic commands. |
| "Upgrades keep breaking my setup." | Zero dependencies, stdlib-only Python 3.9–3.13. There is nothing to break. |
| "I don't know what it's actually sending to the API." | `/system` prints the exact system prompt, provider, and model. `/cost` prints per-provider spend. No telemetry — Orca talks to your provider and nothing else. |
| "The model's 'thinking' eats my context window." | Reasoning streams are shown live in a dim `⌁ thinking` lane but never stored — later turns never pay for them. |
| "It stops halfway through building my app." | Builds run to completion: plan with `todo`, write files one by one, run the result, fix what breaks. 80-turn budget by default (`--max-tokens` for more). |
| "Local models are second-class citizens." | Ollama and LM Studio are presets like any other — no key, no account, no network. |

## Not for everyone (honestly)

- **No TUI framework** — the UI is ANSI prints, not a full-screen app like some
  agents. Deliberate: it works over plain SSH, in CI logs, and in pipes.
- **No team/enterprise features** — no SSO, no admin console, no usage
  dashboards for your org. Your terminal, your keys.
- **0.0.1** — young software. The trade: when something's wrong, the whole
  implementation is ~7k lines of readable, dependency-free Python you can
  debug yourself.

## Design rules

1. **Zero dependencies is a feature, not a stunt.** `pip install` can't break
   what doesn't exist.
2. **Nothing silent.** Cost, compaction, permissions, system prompt — all
   visible on request, most visible by default.
3. **Hard caps beat warnings.** Budgets stop the run; they don't email you
   later.
4. **Provider-neutral by construction.** No vendor gets a default advantage;
   `mock` is a first-class provider so the suite runs offline.
5. **Verification over vibes.** A build is done when the verify command is
   green, not when the model sounds confident.
