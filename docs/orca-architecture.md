# ORCA Architecture Contract

## Current implementation

ORCA is currently a Go 1.23, standard-library-only terminal agent. Its actual
layers are:

```text
cmd/orca
  CLI flags, REPL, one-shot mode, trust/key/help/version
internal/agent
  provider → streamed response → permission decision → tool → feedback loop
internal/provider
  Anthropic Messages and OpenAI Chat Completions SSE adapters
internal/tools
  file/search/shell/web/todo tools and byte-safe turn undo
internal/security
  root resolution, symlink-aware confinement, command classification, SSRF
internal/permissions
  default / acceptEdits / plan / yolo plus allow/deny rules
internal/config
  layered config, provider presets, trust gate and 0600 key store
internal/session
  append-only JSONL session records
internal/ui
  ANSI terminal presentation and non-interactive behavior
```

This is what ships today. There is currently no desktop window, editor buffer,
LSP, MCP, semantic index or OS-level sandbox.

## Target architecture

The desktop client must not duplicate the agent's security logic. It should
connect to a local ORCA daemon over a versioned local protocol:

```text
Desktop client / CLI / ACP adapter
              │ local authenticated IPC
              ▼
        ORCA session daemon
              │
  ┌───────────┼───────────┐
  │           │           │
Context     Agent       Event log
engine      runtime     + audit
  │           │           │
repo map   policy      provider
LSP/MCP    sandbox     adapters
              │
        OS isolation runner
```

## Non-negotiable boundaries

1. The UI can request an action; only the policy/runtime can authorize it.
2. The provider receives a context manifest, not an untraceable blob.
3. Every tool event has an ID, start time, end time, status, redacted input and
   redacted output.
4. A cancellation signal reaches the provider, tool process and sandbox.
5. A checkpoint is created before the first mutating operation in a turn.
6. Unsupported sandbox capabilities are reported explicitly, never implied.
7. Project configuration is data until trust is granted; hooks/MCP servers are
   never silently executable.

## Event protocol draft

The stable protocol should use JSON Lines initially because it is debuggable and
works well for a CLI, daemon and test fixtures:

```json
{"type":"session.started","id":"s1","workspace":"/repo"}
{"type":"context.selected","paths":["cmd/main.go"],"reason":"imports"}
{"type":"tool.requested","id":"t1","tool":"bash","permission":"ask"}
{"type":"permission.requested","id":"p1","summary":"go test ./..."}
{"type":"permission.resolved","id":"p1","decision":"allow"}
{"type":"tool.finished","id":"t1","exit_code":0,"duration_ms":482}
{"type":"checkpoint.created","id":"c1","files":3}
{"type":"session.finished","status":"success"}
```

The protocol is not implemented yet; this document prevents the future UI
from coupling to terminal strings.

## Delivery sequence

1. Extract an internal event bus without changing tool behavior.
2. Add JSON event output and session resume/list commands.
3. Add context manifest and deterministic structural project map.
4. Add LSP diagnostics as read-only context.
5. Add MCP with per-server trust and process/network limits.
6. Add daemon/IPC and a minimal desktop shell.
7. Add OS-native sandbox runners and capability reporting.
8. Add parallel agents only after worktree isolation and cancellation are
   reliable.
