// Package security centralises Orca's safety-critical checks:
// path confinement, shell-command classification and SSRF protection.
//
// Design rule: the DEFAULT is deny/ask. Allowlists here only decide what may
// skip the user prompt — they are never the last line of defence.
package security

import (
	"os"
	"path/filepath"
	"strings"
)

// ResolveInRoot resolves p (absolute, relative or ~-prefixed) against root and
// reports whether the final target stays inside root. Symlinks in every
// existing ancestor are resolved, so a link pointing outside the project
// cannot be used to escape confinement.
func ResolveInRoot(root, p string) (abs string, inside bool) {
	if p == "" {
		p = "."
	}
	// Treat POSIX absolute paths as absolute on every platform. Windows' filepath
	// package considers /etc/passwd drive-relative, which could otherwise turn
	// a Unix-style model argument into root-relative project access.
	if (strings.HasPrefix(p, "/") || strings.HasPrefix(p, `\\`)) && !filepath.IsAbs(p) {
		return filepath.Clean(p), false
	}
	if p == "~" || strings.HasPrefix(p, "~/") || strings.HasPrefix(p, `~\`) {
		if home, err := os.UserHomeDir(); err == nil {
			rest := strings.TrimPrefix(p, "~")
			rest = strings.TrimPrefix(rest, "/")
			rest = strings.TrimPrefix(rest, `\`)
			p = filepath.Join(home, rest)
		}
	}
	if !filepath.IsAbs(p) {
		p = filepath.Join(root, p)
	}
	abs = filepath.Clean(p)

	rootReal := evalExisting(filepath.Clean(root))
	target := evalExisting(abs)
	inside = target == rootReal || strings.HasPrefix(target, rootReal+string(filepath.Separator))
	return abs, inside
}

// evalExisting resolves symlinks of the deepest existing ancestor of p and
// re-joins the not-yet-existing suffix, yielding the real final location even
// for files that are about to be created.
func evalExisting(p string) string {
	var suffix []string
	cur := p
	for {
		if real, err := filepath.EvalSymlinks(cur); err == nil {
			return filepath.Join(append([]string{real}, suffix...)...)
		}
		parent := filepath.Dir(cur)
		if parent == cur {
			return p
		}
		suffix = append([]string{filepath.Base(cur)}, suffix...)
		cur = parent
	}
}
