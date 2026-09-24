# ORCA Design System

This is the design contract for the future desktop client and the existing
terminal UI. It is intentionally small, high-contrast and developer-focused.

## Brand

- Name: ORCA Code
- Tone: precise, calm, capable, transparent
- Motif: a geometric orca arc and a terminal chevron
- Accent: cyan is a signal, not a wallpaper
- Avoid: purple AI gradients, decorative glass panels, fake activity meters

## Tokens

```css
:root {
  --orca-bg: #0B0F14;
  --orca-surface: #111820;
  --orca-surface-elevated: #18212B;
  --orca-border: #263340;
  --orca-text: #E8EEF5;
  --orca-text-secondary: #8E9BAA;
  --orca-accent: #25C2D9;
  --orca-accent-hover: #45D9ED;
  --orca-success: #42D392;
  --orca-warning: #F2B84B;
  --orca-error: #F06C78;
  --orca-focus: #7CEAF5;
  --orca-radius-sm: 6px;
  --orca-radius-md: 10px;
  --orca-radius-lg: 14px;
  --orca-space-1: 4px;
  --orca-space-2: 8px;
  --orca-space-3: 12px;
  --orca-space-4: 16px;
  --orca-space-6: 24px;
  --orca-space-8: 32px;
}
```

The accent must not be used for body text. Every interactive control needs a
visible focus state. Normal text must meet WCAG AA contrast against its
surface; status colors must also have a text/icon label, never color alone.

## Typography

- UI: Inter or IBM Plex Sans, bundled or system fallback; do not depend on a
  remote font at runtime.
- Code/terminal: JetBrains Mono or a platform monospace fallback.
- Persian: Vazirmatn or Estedad, bundled only after license and packaging
  review.
- UI scale: 12 / 13 / 14 / 16 / 20 / 28 px.
- Code scale: 12–16 px, user adjustable.
- Body line-height: 1.45; code line-height: 1.55.

The current Go terminal build intentionally uses terminal-safe output and does
not claim to render these fonts. They apply to the desktop client when it is
implemented.

## Layout contract

```text
┌───────────────────────────────────────────────────────────┐
│ brand | workspace | model/status | command palette | gear │
├──┬───────────────────────┬────────────────────────────────┤
│  │ Explorer / Search /   │                                │
│A │ Source / Run / Agents │ Editor, Diff, Preview           │
│c │                       │                                │
│t ├───────────────────────┤                                │
│i │                       │                                │
│v │                       │ Agent timeline / chat           │
│i │                       │ tools, approvals, changed files│
│t ├───────────────────────┴────────────────────────────────┤
│y │ Problems | Tests | Terminal | Output | Git | Security  │
└──┴────────────────────────────────────────────────────────┘
```

The Agent timeline is an operational log: user prompt, model response,
selected context, tool call, approval, result, diff and verification. It never
renders hidden chain-of-thought. Each operation can be cancelled, inspected or
replayed only when safe.

## Interaction rules

- Destructive actions use a labeled button and a confirmation containing the
  exact target, not an unlabeled icon.
- Every icon-only control has a tooltip and keyboard equivalent.
- Diffs are reviewable per hunk; accept/reject is explicit.
- Loading indicators reflect real state from the agent event stream.
- Empty states explain the next useful action.
- Error states include cause, safe remediation and a copyable diagnostic.
- Keyboard navigation is first-class; no critical action requires a pointer.

## Icon system

Use one outlined icon family with a consistent 1.75px stroke. Lucide is the
preferred future client library because it is open-source, compact and has
coverage for files, terminal, Git, security and agent states. Until a desktop
client exists, the Go UI uses Unicode/ANSI symbols and does not import an icon
library.

## Logo assets

`docs/logo.png` is the current visual reference. A production desktop client
should add hand-reviewed SVG variants:

- `logo-mark.svg` on dark and light backgrounds
- `logo-mono.svg`
- `favicon.svg`
- `wordmark.svg`

Generated raster art must not be the only source asset for a scalable UI.
