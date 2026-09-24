# Security Policy

Orca Code executes model-chosen actions on your machine, so security is the
core design constraint — not an afterthought.

## The security model

The security boundary is made of four independent layers:

1. **Default-ask permissions.** Nothing that mutates state (file writes,
   shell, web) runs without approval in `default` mode. Auto-approval exists
   only for a small argv-validated allowlist of read-only commands.
2. **Project-root confinement.** Every tool path is resolved symlink-aware
   and must stay inside the project root. Absolute paths, `..` traversal and
   symlink hops are blocked unless `--allow-outside-root` is set.
3. **Metacharacter gate.** A command containing any quote, pipe, redirect,
   substitution, glob or assignment character is never auto-approved.
4. **SSRF guard.** `web_fetch`/`web_search` validate the resolved IP at
   connect time (loopback, RFC1918, link-local/metadata, CGNAT all blocked),
   re-validated on every redirect — immune to DNS rebinding.

Additional boundaries:

- **Trust gate for repos.** `hooks` and `verify_command` from a project's
  `.orca/settings.json` are inert until you run `orca trust` in that project.
  Cloning a malicious repository and running Orca inside it must never
  execute attacker-controlled commands.
- **Key hygiene.** API keys are stored in `~/.orca/keys.json` with `0600`
  permissions, separate from shareable configuration.
- Destructive-pattern blocking (`rm -rf /`, `mkfs`, fork bombs, `dd of=/dev/…`)
  applies in **every** mode, including `yolo` — as a backstop, not the boundary.

## Reporting a vulnerability

Please open a **private security advisory** on GitHub
(Security → Advisories → "Report a vulnerability") rather than a public issue.
You should receive a response within 72 hours. Fixes for confirmed issues in
the latest release are prioritised over all other work.

## Scope

In scope: permission bypasses, sandbox/confinement escapes, SSRF-guard
bypasses, auto-approval of non-read-only commands, key disclosure.
Out of scope: attacks requiring `yolo` mode plus a malicious prompt the user
typed themselves, and third-party model/provider behaviour.
