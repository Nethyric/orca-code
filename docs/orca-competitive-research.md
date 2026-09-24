# ORCA Competitive Research

> Research snapshot: 2026-09-24. This document separates **verified existing
> ORCA behavior**, competitor capabilities, and proposed work. It intentionally
> does not describe roadmap items as shipped features.

## Executive summary

ORCA currently has a strong terminal-first foundation: a pure-stdlib Go binary,
streaming Anthropic/OpenAI-compatible providers, a tool loop, project-root
confinement, SSRF defenses, permission modes, binary-safe undo, cost tracking,
JSONL sessions, and tests for the security boundary. It is **not yet a desktop
IDE**: there is no editor, language-server client, graphical shell, inline
completion, semantic index, MCP client, or OS-level sandbox. Those are product
opportunities, not claims.

The market is converging on a two-layer product:

1. A fast editor/workspace surface with files, diffs, terminal and diagnostics.
2. An agent runtime with explicit context, tool permissions, checkpoints,
   resumable sessions and an extensible tool protocol.

ORCA's differentiator should be **local-first, provider-neutral, auditable
agent execution**: a small native core that can power a CLI first and a real
IDE client later, without hiding what the model read or did.

## Sources

Primary documentation and official product pages reviewed:

- Cursor Search / Instant Grep: <https://cursor.com/docs/agent/tools/search>
- Claude Code VS Code integration and settings:
  <https://code.claude.com/docs/en/vs-code>
- Claude Code permissions: <https://code.claude.com/docs/en/permissions>
- Claude Code sandboxing: <https://code.claude.com/docs/en/sandboxing>
- Claude Code sandbox environments:
  <https://code.claude.com/docs/en/sandbox-environments>
- GitHub Copilot Agent Mode: <https://github.blog/ai-and-ml/github-copilot/agent-mode-101-all-about-github-copilots-powerful-mode/>
- VS Code Agent Mode and MCP:
  <https://code.visualstudio.com/blogs/2025/04/07/agentMode>
- VS Code Chat overview: <https://code.visualstudio.com/docs/chat/chat-overview>
- Cline approval controls: <https://docs.cline.bot/features/auto-approve>
- Aider documentation: <https://aider.chat/docs/>
- Aider Git integration: <https://aider.chat/docs/git.html>
- Zed Agent Panel: <https://zedhub.dev/ai/agent-panel>
- Zed AI quick start: <https://zed.dev/docs/ai/quick-start>
- Continue configuration reference: <https://docs.continue.dev/reference>
- OpenAI Codex approvals and security:
  <https://developers.openai.com/codex/agent-approvals-security>
- Anthropic Claude Code product overview:
  <https://claude.com/product/claude-code>

Secondary user/community signals reviewed:

- Cursor feature trade-offs and background agents:
  <https://www.altexsoft.com/blog/cursor-pros-and-cons/>
- Roo Code mode/checkpoint discussion:
  <https://www.datacamp.com/tutorial/roo-code>
- Zed external-agent and collaboration analysis:
  <https://codingagenttools.com/en/tools/zed/>
- Continue local-model and context-provider discussion:
  <https://www.sitepoint.com/continuedev-for-developers-the-complete-local-ai-coding-assistant-setup>

Third-party sources are treated as user sentiment and discovery material, not
as authoritative product specifications.

## Competitor review

### Cursor

**Experience.** AI-native VS Code-derived editor with Agent, inline edits,
completion and a codebase-oriented search/indexing experience. Agent tools are
visible and multi-file changes are central to the workflow.

**Loved.** Fast inline completion, strong codebase context, convenient
multi-file agent edits, model choice, rules and background work.

**Pain points.** Privacy trade-offs can vary by feature; autonomous/background
work increases the data and review surface. Large generated diffs still require
human review, and editor/server behavior can feel opaque.

**Lesson for ORCA.** Make context provenance visible: every included path,
ignore decision, and tool result should be inspectable. Separate local indexing
from provider-bound content.

### Windsurf / Cascade

**Experience.** Agentic editor workflow built around continuous context,
workspace awareness, rules/memories, terminal use and multi-step execution.

**Loved.** The feeling of flow: the agent sees the active workspace, remembers
useful project facts, edits several files and reacts to command output.

**Pain points.** Persistent context can become stale or surprising; autonomous
terminal actions need a clear boundary and easy recovery.

**Lesson for ORCA.** Add explicit workspace facts with source and timestamp,
never silent memory. Add a visible run timeline and checkpoints around turns.

### Claude Code

**Experience.** Terminal-first agent with IDE integrations, explicit permission
rules, hooks, MCP and sandbox options. Its docs distinguish permission policy
from OS-enforced sandbox boundaries.

**Loved.** High-quality multi-step coding, transparent tool calls, hooks,
project instructions and provider-native capability.

**Pain points.** CLI-centric workflow is less approachable for users wanting a
full editor; sandbox setup varies by operating system; permissions and hooks
require careful configuration.

**Lesson for ORCA.** Keep the terminal core, but make permission decisions and
sandbox status first-class UI data. Never imply a command-text classifier is an
OS sandbox.

### GitHub Copilot / VS Code

**Experience.** A mature editor shell: Explorer, tabs, diagnostics, integrated
terminal, source control and extensions, with Agent mode orchestrating edits,
commands, MCP and error feedback.

**Loved.** Familiar IDE, language tooling, diagnostics, extensions, working-set
context and a polished review loop.

**Pain points.** Settings and extensions create complexity; capabilities depend
on account, model and host version; terminal permissions can be confusing.

**Lesson for ORCA.** Use a narrow, coherent design system rather than copying
all of VS Code. Add LSP diagnostics and a diff review surface before adding
visual novelty.

### Cline

**Experience.** Open-source IDE/CLI agent with Plan/Act-style workflow,
per-tool auto-approval controls, browser/MCP options and checkpoints.

**Loved.** User-controlled permissions, inspectable actions, local/BYOK model
support, checkpoints and extensibility.

**Pain points.** Fine-grained settings can overwhelm new users; YOLO modes are
powerful but unsafe; extension/runtime integrations multiply attack surface.

**Lesson for ORCA.** Keep safe presets simple, expose advanced rules as an
expert view, and make dangerous modes visibly hard to enable.

### Roo Code

**Experience.** Mode-oriented agent design (Ask/Code/Architect/Debug), custom
modes, memory/context workflows and checkpoint-style recovery.

**Loved.** Specialization: read-only planning and implementation modes make
intent clear. Custom agent profiles suit teams.

**Pain points.** More modes and configuration increase cognitive load and can
fragment the user experience.

**Lesson for ORCA.** Prefer four predictable permission modes plus named agent
profiles, rather than a large mode list.

### Aider

**Experience.** Terminal pair programmer with repository map, chat modes,
strong Git integration, commits, diff and undo commands.

**Loved.** Git-native recovery, repo map efficiency, scripting and simple CLI
workflow.

**Pain points.** Terminal UX is less discoverable than an IDE; context selection
and edit formats can require user knowledge.

**Lesson for ORCA.** Add a structural project map and Git-aware checkpoints,
while preserving ORCA's byte-level undo for non-Git directories and binaries.

### Zed

**Experience.** Native high-performance editor with Agent Panel, threads,
checkpoints, reviewable hunks, profiles, MCP and external agents via ACP.

**Loved.** Speed, focused UI, reviewable changes, parallel threads and the
ability to host external agents.

**Pain points.** External agents do not all support identical history,
checkpoint or usage features; provider/privacy boundaries can be confusing.

**Lesson for ORCA.** Design a stable agent protocol and capability handshake;
clients must show what each provider/runtime actually supports.

### VS Code

**Experience.** The broadest editor platform: files, terminals, source control,
LSP-backed diagnostics, extensions, tasks and debug tooling.

**Loved.** Ecosystem, language support, shortcuts, accessibility and
customizability.

**Pain points.** Extension quality and configuration sprawl; a new user can
lose the product's mental model among panels and settings.

**Lesson for ORCA.** Build a small native client with a deliberately limited
surface, then expose extensions through a documented protocol rather than
requiring an extension for every core feature.

### Continue

**Experience.** Open and configurable assistant with model roles (chat/edit/
autocomplete/embed), context providers, rules, slash commands and local or
OpenAI-compatible backends.

**Loved.** BYO model, local inference, configuration-as-code and context
provider flexibility.

**Pain points.** Configuration can be complex; quality depends heavily on
choosing and hosting compatible models.

**Lesson for ORCA.** Preserve provider freedom, but offer validated presets and
capability detection so users do not hand-author fragile model configuration.

### OpenAI Codex

**Experience.** Agent/IDE/CLI surfaces with explicit approval policy and
OS-level sandbox modes such as read-only and workspace-write.

**Loved.** Clear separation between what an action is allowed to do and whether
it needs approval; strong autonomous iteration and isolation story.

**Pain points.** Sandbox features and policies vary by platform; full access is
necessarily risky; users need to understand network behavior.

**Lesson for ORCA.** Implement an explicit `sandbox status` and capability
matrix. A permission prompt alone is not a sandbox.

## Capability matrix

Legend: **Yes** means a user-facing capability is established in the cited
material; **ORCA now** means implemented in this repository; **planned** means
not implemented and must not be advertised as shipped.

| Capability | ORCA now | Strong examples | ORCA decision |
|---|---:|---|---|
| Terminal-first agent loop | Yes | Claude Code, Aider, Codex | Keep as core |
| Streaming provider adapters | Yes | Most agents | Keep and test |
| Root confinement + SSRF guard | Yes | Varies | ORCA security differentiator |
| Permission modes and session rules | Yes | Claude/Cline/Codex | Keep; add audit explanation |
| Byte-safe undo | Yes | Aider/Zed checkpoints | Keep; add UI/diff view |
| Persistent JSONL sessions | Yes | Claude/Codex/Cline | Add resume/list commands |
| Auto context compaction | Yes | Agent products | Add provenance and budget view |
| Semantic codebase index | No | Cursor/Windsurf | Planned, local-first |
| Structural repo map | No | Aider | Planned, high priority |
| LSP diagnostics | No | VS Code/Zed | Planned, high priority |
| MCP client | No | VS Code/Cline/Continue | Planned, protocol boundary first |
| OS-level sandbox | No | Codex/Claude sandbox | Planned per OS; do not claim now |
| Desktop editor | No | Cursor/Zed/VS Code | Planned client; CLI remains supported |
| Inline completion | No | Cursor/Copilot/Continue | Later, requires low-latency service |
| Git diff/checkpoint UI | Partial (undo only) | Aider/Zed/Cline | Planned |
| Subagents/parallel worktrees | No | Cursor/Zed/Copilot | Planned after isolation |
| ACP external-agent protocol | No | Zed | Planned after agent API stabilizes |

## ORCA product thesis

ORCA should not try to clone every editor. The strongest positioning is:

> **A local-first, auditable AI development environment: the same safe Go
> agent core in a fast terminal, a lightweight desktop client, and future
> protocol integrations.**

Three principles make it distinct:

1. **Evidence over theatre.** Show exact paths, commands, approvals, outputs,
   diffs and verification status. Do not show fake progress or private chain of
   thought. Show concise operational events instead.
2. **Policy plus enforcement.** Permission rules explain intent; OS sandboxing
   enforces boundaries. If a platform has no sandbox, show that limitation.
3. **Provider independence.** Cloud, gateway and local providers share one
   capability-aware interface; keys and context remain user-controlled.

## Prioritized roadmap

### P0 — reliability and trust (next)

- Add `orca doctor` with provider, workspace, shell and security diagnostics.
- Add `orca sessions list/resume/export`.
- Add structured JSON event output for automation and UI clients.
- Add audit records for permission decisions and tool outcomes with secret
  redaction.
- Add a cross-platform shell adapter (PowerShell/cmd on Windows, sh/bash on
  Unix) instead of assuming `bash`.
- Add property/fuzz tests for paths, command parsing, config and SSE.

### P1 — context and review

- Structural repo map from standard-library parsing and deterministic symbol
  extraction.
- Context manifest showing why every file entered a request.
- Git status/diff/checkpoint tools with explicit review and restore.
- LSP bridge with diagnostics surfaced as read-only agent context.

### P2 — extensibility and desktop client

- MCP stdio/HTTP client with per-server trust, capability declarations and
  process limits.
- Stable local daemon/API for a desktop client; CLI remains the reference UI.
- Desktop shell with Explorer, diff review, Agent timeline, terminal and
  Problems/Tests panels.
- Design-token system, accessible keyboard navigation, light theme and
  localized typography.

### P3 — isolation and scale

- Linux Landlock/seccomp runner, macOS Seatbelt runner, Windows restricted
  token/job-object runner; capability detection and explicit fallback.
- Worktree-isolated parallel agents.
- ACP adapter and plugin SDK after the security contract is stable.

## Current truth checklist

As of this research snapshot, ORCA is a tested secure terminal coding agent,
not a completed desktop IDE. The README and release materials should preserve
that distinction until the corresponding components land and have tests.
