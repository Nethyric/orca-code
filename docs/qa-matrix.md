# ORCA QA Matrix

## Current verified checks

| Check | Linux | macOS | Windows |
|---|---:|---:|---:|
| `gofmt` | yes | yes | yes |
| `go vet ./...` | yes | yes | yes (CI) |
| `go test ./...` | yes | yes | yes (CI) |
| `go test -race ./...` | yes | yes | yes (CI) |
| static cross-build | yes | yes | yes |
| `orca version` smoke test | yes | yes | yes in CI |
| live provider SSE fixtures | yes | yes | yes |
| path traversal/confinement | yes | yes | yes |
| SSRF IP policy | yes | yes | yes |

## Gaps that must not be hidden

- There is no automated graphical UI test because no desktop UI ships yet.
- There is no OS-level sandbox runner yet; root confinement and command policy
  are not a substitute for a kernel-enforced sandbox.
- `bash` is the Unix shell adapter; Windows requires Bash/WSL for that tool
  until the PowerShell/cmd adapter lands.
- LSP, MCP, semantic indexing, inline completion, subagents and Git review UI
  are roadmap items, not current features.

## Required acceptance criteria for the desktop client

- Launch and crash recovery on Linux, macOS and Windows.
- Keyboard-only navigation of Explorer, Agent, Diff and Terminal.
- Resize from 800×600 through 4K without clipped critical controls.
- Dark/light contrast audit and Persian/RTL text rendering.
- Agent cancellation during provider stream, tool process and approval prompt.
- Diff accept/reject, checkpoint restore and session resume.
- No secret/API key in events, logs, screenshots or crash reports.
- 10-minute idle memory/CPU baseline and 100k-line output stress test.
